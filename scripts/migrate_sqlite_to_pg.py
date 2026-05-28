"""
Migrate users + related data from local SQLite (instance/devops_agent.db)
into the production PostgreSQL database.

Run on the server after copying devops_agent.db to /tmp/:
  python3 scripts/migrate_sqlite_to_pg.py

Skips users already present in PG (matched by email).
Remaps user_id / conversation_id across all related tables.
"""
import sqlite3
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SQLITE_PATH = os.environ.get('SQLITE_PATH', '/tmp/devops_agent.db')
BATCH_SIZE = 500


def _parse_dt(value):
    """Parse a SQLite ISO datetime string into a Python datetime, or return None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _safe(row, col, default=None):
    """Return row[col] if the column exists, else default."""
    return row[col] if col in row.keys() else default


def _parse_learning_level(raw):
    """Normalise learning_level to a dict regardless of stored type."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def migrate():
    from app import app, db
    from models import (
        User, UserSubscription, UserPreferences,
        Conversation, ChatMessage, SubscriptionTier,
        UserCloudCredential,
    )

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite file not found at {SQLITE_PATH}")
        sys.exit(1)

    sqlite = sqlite3.connect(SQLITE_PATH)
    try:
        sqlite.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        sqlite.row_factory = sqlite3.Row
        cur = sqlite.cursor()

        with app.app_context():
            # ── 1. Get subscription tier IDs from PG ──────────────────────────
            tiers = {t.name: t.id for t in SubscriptionTier.query.all()}
            if not tiers:
                print("ERROR: No subscription tiers found in PG — seed the tiers table first.")
                sys.exit(1)
            print(f"PG tiers: {tiers}")

            free_tier_id = tiers.get('free')
            if free_tier_id is None:
                print("ERROR: 'free' tier missing from PG subscription_tiers.")
                sys.exit(1)

            # ── 2. Read SQLite subscription tiers for ID mapping ──────────────
            cur.execute("SELECT id, name FROM subscription_tiers")
            sqlite_tier_map = {r['id']: r['name'] for r in cur.fetchall()}
            print(f"SQLite tiers: {sqlite_tier_map}")

            # ── 3. Migrate users ───────────────────────────────────────────────
            cur.execute("SELECT * FROM users ORDER BY id")
            sqlite_users = cur.fetchall()
            user_id_map = {}   # sqlite_id -> pg_id

            # Build existing-email set and id map from PG in one query
            existing_pg_users = User.query.all()
            existing_emails = {u.email for u in existing_pg_users}
            for pg_user in existing_pg_users:
                for su in sqlite_users:
                    if su['email'] == pg_user.email:
                        user_id_map[su['id']] = pg_user.id
                        break

            print(f"\nMigrating {len(sqlite_users)} users...")
            migrated_users = 0

            for su in sqlite_users:
                if su['email'] in existing_emails:
                    print(f"  SKIP {su['email']} (already exists in PG)")
                    continue

                u = User(
                    email=su['email'],
                    username=su['username'],
                    password_hash=su['password_hash'],
                    full_name=su['full_name'] if su['full_name'] else None,
                    created_at=_parse_dt(su['created_at']),
                    avatar_color=su['avatar_color'] if su['avatar_color'] else '#ff6b35',
                    role=su['role'] if su['role'] else 'user',
                    two_factor_enabled=bool(su['two_factor_enabled']),
                    two_factor_secret=su['two_factor_secret'],
                    onboarding_completed=bool(su['onboarding_completed']),
                    # Default False — safer than silently granting verified status to
                    # users from a schema that predated the email_verified column.
                    email_verified=bool(su['email_verified']) if 'email_verified' in su.keys() else False,
                    mfa_method=_safe(su, 'mfa_method') or 'totp',
                )
                db.session.add(u)
                db.session.flush()   # get new PG id
                user_id_map[su['id']] = u.id
                existing_emails.add(su['email'])
                print(f"  ADDED {su['email']} -> PG id={u.id}")
                migrated_users += 1

            db.session.commit()
            print(f"Users migrated: {migrated_users}")

            # ── 4. Migrate subscriptions ───────────────────────────────────────
            print("\nMigrating subscriptions...")
            cur.execute("SELECT * FROM user_subscriptions")
            for s in cur.fetchall():
                sqlite_uid = s['user_id']
                if sqlite_uid not in user_id_map:
                    continue
                pg_uid = user_id_map[sqlite_uid]
                if UserSubscription.query.filter_by(user_id=pg_uid).first():
                    print(f"  SKIP sub for user {pg_uid} (exists)")
                    continue

                tier_name = sqlite_tier_map.get(s['tier_id'], 'free')
                pg_tier_id = tiers.get(tier_name, free_tier_id)

                raw_credits = s['credits_remaining']
                credits = 20 if raw_credits is None else int(raw_credits)

                sub = UserSubscription(
                    user_id=pg_uid,
                    tier_id=pg_tier_id,
                    credits_remaining=credits,
                    current_period_start=_parse_dt(s['current_period_start']),
                    current_period_end=_parse_dt(s['current_period_end']),
                    last_reset_date=_parse_dt(_safe(s, 'last_reset_date')),
                    stripe_customer_id=_safe(s, 'stripe_customer_id'),
                    stripe_subscription_id=_safe(s, 'stripe_subscription_id'),
                )
                db.session.add(sub)
                print(f"  Added sub for user {pg_uid} tier={tier_name} credits={credits}")

            db.session.commit()

            # ── 5. Migrate user preferences ───────────────────────────────────
            print("\nMigrating preferences...")
            try:
                cur.execute("SELECT * FROM user_preferences")
                for p in cur.fetchall():
                    if p['user_id'] not in user_id_map:
                        continue
                    pg_uid = user_id_map[p['user_id']]
                    if UserPreferences.query.filter_by(user_id=pg_uid).first():
                        continue
                    pref = UserPreferences(
                        user_id=pg_uid,
                        learning_mode=bool(_safe(p, 'learning_mode', False)),
                        sandbox_mode=bool(_safe(p, 'sandbox_mode', False)),
                        # Normalise to dict — old schema stored plain strings like 'beginner'
                        learning_level=_parse_learning_level(_safe(p, 'learning_level')),
                    )
                    db.session.add(pref)
                db.session.commit()
                print("  Preferences migrated")
            except Exception as e:
                db.session.rollback()
                print(f"  Preferences skipped: {e}")

            # ── 6. Migrate cloud credentials ──────────────────────────────────
            print("\nMigrating cloud credentials...")
            try:
                cur.execute("SELECT * FROM user_cloud_credentials ORDER BY id")
                cred_count = 0
                for c in cur.fetchall():
                    if c['user_id'] not in user_id_map:
                        continue
                    pg_uid = user_id_map[c['user_id']]
                    if UserCloudCredential.query.filter_by(
                        user_id=pg_uid, cloud_provider=c['cloud_provider']
                    ).first():
                        continue
                    cred = UserCloudCredential(
                        user_id=pg_uid,
                        cloud_provider=c['cloud_provider'],
                        credentials_encrypted=c['credentials_encrypted'],
                        default_region=_safe(c, 'default_region'),
                        default_zone=_safe(c, 'default_zone'),
                        is_active=bool(_safe(c, 'is_active', True)),
                        last_verified=_parse_dt(_safe(c, 'last_verified')),
                        verification_status=_safe(c, 'verification_status', 'pending'),
                        created_at=_parse_dt(_safe(c, 'created_at')),
                        updated_at=_parse_dt(_safe(c, 'updated_at')),
                    )
                    db.session.add(cred)
                    cred_count += 1
                db.session.commit()
                print(f"  Cloud credentials migrated: {cred_count}")
            except Exception as e:
                db.session.rollback()
                print(f"  Cloud credentials skipped: {e}")

            # ── 7. Migrate conversations ───────────────────────────────────────
            print("\nMigrating conversations...")
            conv_id_map = {}  # sqlite conv_id -> pg conv_id
            try:
                cur.execute("SELECT * FROM conversations ORDER BY id")
                for c in cur.fetchall():
                    if c['user_id'] not in user_id_map:
                        continue
                    pg_uid = user_id_map[c['user_id']]
                    # Dedup: skip if this sqlite conv_id was already migrated
                    if Conversation.query.filter_by(
                        user_id=pg_uid, created_at=_parse_dt(c['created_at'])
                    ).first():
                        continue
                    conv = Conversation(
                        id=os.urandom(8).hex(),
                        user_id=pg_uid,
                        title=c['title'] if c['title'] else 'Imported conversation',
                        created_at=_parse_dt(c['created_at']),
                    )
                    updated = _parse_dt(_safe(c, 'updated_at'))
                    if updated:
                        conv.updated_at = updated
                    db.session.add(conv)
                    db.session.flush()
                    conv_id_map[c['id']] = conv.id

                db.session.commit()
                print(f"  Conversations: {len(conv_id_map)} migrated")
            except Exception as e:
                db.session.rollback()
                print(f"  Conversations skipped: {e}")

            # ── 8. Migrate messages (batched to avoid OOM) ────────────────────
            print("\nMigrating messages...")
            msg_count = 0
            try:
                cur.execute("SELECT * FROM chat_messages ORDER BY id")
                while True:
                    batch = cur.fetchmany(BATCH_SIZE)
                    if not batch:
                        break
                    for m in batch:
                        if m['conversation_id'] not in conv_id_map:
                            continue
                        pg_conv_id = conv_id_map[m['conversation_id']]
                        pg_uid = user_id_map.get(m['user_id']) if m['user_id'] else None
                        msg = ChatMessage(
                            conversation_id=pg_conv_id,
                            user_id=pg_uid,
                            role=m['role'],
                            content=m['content'],
                            timestamp=_parse_dt(_safe(m, 'timestamp') or _safe(m, 'created_at')),
                        )
                        db.session.add(msg)
                        msg_count += 1
                    db.session.commit()

                print(f"  Messages: {msg_count} migrated")
            except Exception as e:
                db.session.rollback()
                print(f"  Messages skipped: {e}")

            # ── 9. Summary ─────────────────────────────────────────────────────
            print("\n=== Migration Complete ===")
            for pg_user in User.query.order_by(User.id).all():
                sub = UserSubscription.query.filter_by(user_id=pg_user.id).first()
                tier = sub.tier.name if sub and sub.tier else 'none'
                convs = Conversation.query.filter_by(user_id=pg_user.id).count()
                print(f"  id={pg_user.id} | {pg_user.email} | tier={tier} | convs={convs}")

    finally:
        sqlite.close()


if __name__ == '__main__':
    migrate()
