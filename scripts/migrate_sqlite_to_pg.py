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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SQLITE_PATH = os.environ.get('SQLITE_PATH', '/tmp/devops_agent.db')


def migrate():
    from app import app, db
    from models import (
        User, UserSubscription, UserPreferences,
        Conversation, ChatMessage, SubscriptionTier,
        UserCloudCredential,
    )
    from sqlalchemy import text

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite file not found at {SQLITE_PATH}")
        sys.exit(1)

    sqlite = sqlite3.connect(SQLITE_PATH)
    sqlite.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    sqlite.row_factory = sqlite3.Row
    cur = sqlite.cursor()

    with app.app_context():
        # ── 1. Get subscription tier IDs from PG ──────────────────────────
        tiers = {t.name: t.id for t in SubscriptionTier.query.all()}
        print(f"PG tiers: {tiers}")

        # ── 2. Read SQLite subscription tiers for ID mapping ──────────────
        cur.execute("SELECT id, name FROM subscription_tiers")
        sqlite_tier_map = {r['id']: r['name'] for r in cur.fetchall()}
        print(f"SQLite tiers: {sqlite_tier_map}")

        # ── 3. Migrate users ───────────────────────────────────────────────
        cur.execute("SELECT * FROM users ORDER BY id")
        sqlite_users = cur.fetchall()
        user_id_map = {}   # sqlite_id -> pg_id

        # Preserve existing PG users in the map
        for pg_user in User.query.all():
            # Find matching sqlite user by email
            for su in sqlite_users:
                if su['email'] == pg_user.email:
                    user_id_map[su['id']] = pg_user.id
                    break

        print(f"\nMigrating {len(sqlite_users)} users...")
        migrated_users = 0

        for su in sqlite_users:
            if su['email'] in [u.email for u in User.query.all()]:
                print(f"  SKIP {su['email']} (already exists in PG)")
                continue

            u = User(
                email=su['email'],
                username=su['username'],
                password_hash=su['password_hash'],
                full_name=su['full_name'] if su['full_name'] else None,
                created_at=su['created_at'],
                avatar_color=su['avatar_color'] if su['avatar_color'] else '#ff6b35',
                role=su['role'] if su['role'] else 'user',
                two_factor_enabled=bool(su['two_factor_enabled']),
                two_factor_secret=su['two_factor_secret'],
                onboarding_completed=bool(su['onboarding_completed']),
                email_verified=bool(su['email_verified']) if 'email_verified' in su.keys() else True,
                mfa_method=su['mfa_method'] if 'mfa_method' in su.keys() and su['mfa_method'] else 'totp',
            )
            db.session.add(u)
            db.session.flush()   # get new PG id
            user_id_map[su['id']] = u.id
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
            pg_tier_id = tiers.get(tier_name, tiers.get('free'))

            sub = UserSubscription(
                user_id=pg_uid,
                tier_id=pg_tier_id,
                credits_remaining=s['credits_remaining'] or 20,
                current_period_start=s['current_period_start'],
                current_period_end=s['current_period_end'],
                last_reset_date=s['last_reset_date'] if 'last_reset_date' in s.keys() else None,
                stripe_customer_id=s['stripe_customer_id'] if 'stripe_customer_id' in s.keys() else None,
                stripe_subscription_id=s['stripe_subscription_id'] if 'stripe_subscription_id' in s.keys() else None,
            )
            db.session.add(sub)
            print(f"  Added sub for user {pg_uid} tier={tier_name} credits={s['credits_remaining']}")

        db.session.commit()

        # ── 5. Migrate user preferences ───────────────────────────────────
        print("\nMigrating preferences...")
        try:
            cur.execute("SELECT * FROM user_preferences")
            for p in cur.fetchall():
                if p['user_id'] not in user_id_map:
                    continue
                pg_uid = user_id_map[p['user_id']]
                from models import UserPreferences
                if UserPreferences.query.filter_by(user_id=pg_uid).first():
                    continue
                pref = UserPreferences(
                    user_id=pg_uid,
                    learning_mode=bool(p['learning_mode']) if 'learning_mode' in p.keys() else False,
                    sandbox_mode=bool(p['sandbox_mode']) if 'sandbox_mode' in p.keys() else False,
                    learning_level=p['learning_level'] if 'learning_level' in p.keys() else 'beginner',
                )
                db.session.add(pref)
            db.session.commit()
            print("  Preferences migrated")
        except Exception as e:
            db.session.rollback()
            print(f"  Preferences skipped: {e}")

        # ── 6. Migrate conversations + messages ───────────────────────────
        print("\nMigrating conversations...")
        conv_id_map = {}  # sqlite conv_id -> pg conv_id
        try:
            cur.execute("SELECT * FROM conversations ORDER BY id")
            for c in cur.fetchall():
                if c['user_id'] not in user_id_map:
                    continue
                pg_uid = user_id_map[c['user_id']]
                conv = Conversation(
                    user_id=pg_uid,
                    title=c['title'] if c['title'] else 'Imported conversation',
                    created_at=c['created_at'],
                )
                if 'updated_at' in c.keys() and c['updated_at']:
                    conv.updated_at = c['updated_at']
                db.session.add(conv)
                db.session.flush()
                conv_id_map[c['id']] = conv.id

            db.session.commit()
            print(f"  Conversations: {len(conv_id_map)} migrated")
        except Exception as e:
            db.session.rollback()
            print(f"  Conversations skipped: {e}")

        print("\nMigrating messages...")
        msg_count = 0
        try:
            cur.execute("SELECT * FROM chat_messages ORDER BY id")
            for m in cur.fetchall():
                if m['conversation_id'] not in conv_id_map:
                    continue
                pg_conv_id = conv_id_map[m['conversation_id']]
                pg_uid = user_id_map.get(m['user_id']) if m['user_id'] else None
                msg = ChatMessage(
                    conversation_id=pg_conv_id,
                    user_id=pg_uid,
                    role=m['role'],
                    content=m['content'],
                    created_at=m['created_at'],
                )
                db.session.add(msg)
                msg_count += 1

            db.session.commit()
            print(f"  Messages: {msg_count} migrated")
        except Exception as e:
            db.session.rollback()
            print(f"  Messages skipped: {e}")

        # ── 7. Summary ─────────────────────────────────────────────────────
        print("\n=== Migration Complete ===")
        for pg_user in User.query.order_by(User.id).all():
            sub = UserSubscription.query.filter_by(user_id=pg_user.id).first()
            tier = sub.tier.name if sub and sub.tier else 'none'
            convs = Conversation.query.filter_by(user_id=pg_user.id).count()
            print(f"  id={pg_user.id} | {pg_user.email} | tier={tier} | convs={convs}")

    sqlite.close()


if __name__ == '__main__':
    migrate()
