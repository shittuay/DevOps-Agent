"""
Scheduled Infrastructure Checks Service

Runs periodic background tasks: infrastructure sync, budget alerts, the weekly
digest email, onboarding emails, backups and health checks.

Multi-worker safety: uses a PID file lock so only one gunicorn worker
starts the scheduler thread. Other workers skip silently.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Any
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()
_LOCK_FILE = os.path.join(os.path.dirname(__file__), '..', '.scheduler.lock')


def _acquire_scheduler_lock() -> bool:
    """
    Try to acquire the scheduler PID lock.

    Returns True if this process owns the lock (should start the scheduler).
    Returns False if another process already holds it.

    The lock file stores the owning PID. On startup, if the PID in the file
    is no longer alive, we steal the lock (handles crashes / ungraceful restarts).
    """
    lock_path = os.path.abspath(_LOCK_FILE)
    my_pid = os.getpid()

    try:
        if os.path.exists(lock_path):
            try:
                with open(lock_path) as f:
                    existing_pid = int(f.read().strip())
                # Check if that process is still alive
                os.kill(existing_pid, 0)  # signal 0 = existence check only
                if existing_pid == my_pid:
                    return True  # we already own it
                logger.debug(f"Scheduler lock held by PID {existing_pid} — skipping")
                return False
            except (ValueError, ProcessLookupError, PermissionError):
                # PID file corrupt or process is dead — steal the lock
                pass

        with open(lock_path, 'w') as f:
            f.write(str(my_pid))
        logger.info(f"Scheduler lock acquired by PID {my_pid}")
        return True

    except Exception as e:
        # If we can't manage the lock file at all, fail open (start the scheduler)
        # so autonomous ops still run. Log a warning so ops can investigate.
        logger.warning(f"Could not manage scheduler lock file: {e} — starting anyway")
        return True


def _release_scheduler_lock():
    """Release the PID lock if this process owns it."""
    lock_path = os.path.abspath(_LOCK_FILE)
    try:
        if os.path.exists(lock_path):
            with open(lock_path) as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(lock_path)
                logger.debug("Scheduler lock released")
    except Exception:
        pass


def start_scheduler(app, db):
    """Start the background scheduler in a daemon thread (one worker only)."""
    global _scheduler_thread

    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info("Scheduler already running in this worker")
        return

    if not _acquire_scheduler_lock():
        return  # another gunicorn worker owns the scheduler

    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(app, db),
        daemon=True,
        name='infra-scheduler'
    )
    _scheduler_thread.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    """Stop the background scheduler."""
    _stop_event.set()
    _release_scheduler_lock()
    logger.info("Scheduler stop requested")


def _scheduler_loop(app, db):
    """Main scheduler loop. Runs checks on intervals."""
    intervals = {
        'health_check':      timedelta(minutes=5),
        'infra_sync':        timedelta(hours=1),
        'budget_check':      timedelta(hours=1),     # each alert at most daily
        'drip_email':        timedelta(hours=1),
        'weekly_digest':     timedelta(hours=1),     # sends on Sundays, once per user per week
        'db_backup':         timedelta(hours=24),
    }

    last_run = {k: datetime.min for k in intervals}

    while not _stop_event.is_set():
        now = utcnow()

        for task_name, interval in intervals.items():
            if now - last_run[task_name] >= interval:
                # Record the attempt BEFORE running so a task that raises backs
                # off to its full interval instead of retrying every loop (30s).
                # Previously last_run was only set on success, so a persistently
                # failing task (e.g. db_backup hitting a bad BACKUP_DIR) spammed
                # an error every 30s indefinitely.
                last_run[task_name] = now
                try:
                    with app.app_context():
                        _run_task(task_name, app, db)
                except Exception as e:
                    logger.error(f"Scheduler task '{task_name}' failed: {e}", exc_info=True)

        _stop_event.wait(timeout=30)

    _release_scheduler_lock()


def _run_task(task_name: str, app, db):
    """Execute a scheduled task."""
    logger.debug(f"Running scheduled task: {task_name}")

    if task_name == 'health_check':
        _run_health_check(app, db)
    elif task_name == 'infra_sync':
        _run_infra_sync(app, db)
    elif task_name == 'budget_check':
        _run_budget_checks(db)
    elif task_name == 'drip_email':
        _run_drip_emails(db)
    elif task_name == 'weekly_digest':
        _run_weekly_digest(db)
    elif task_name == 'db_backup':
        _run_db_backup()


def _run_health_check(app, db):
    """Run system health diagnostics."""
    from services.doctor import run_diagnostics
    results = run_diagnostics(app=app, db=db)

    if results['overall'] == 'unhealthy':
        error_count = results['summary'].get('error', 0)
        is_prod = os.environ.get('FLASK_ENV') == 'production'
        if is_prod:
            logger.error(f"HEALTH CHECK FAILED: {results['summary']}")
            _store_alert(db, 'health_check', 'critical',
                         f"System unhealthy: {error_count} errors detected")
        else:
            logger.warning(f"Health check: {error_count} errors (non-production, suppressing CRITICAL)")
    elif results['overall'] == 'degraded':
        logger.info(f"Health check: {results['summary'].get('warning', 0)} warnings")
    else:
        logger.debug("Health check passed")


def _users_with_credentials_query(db):
    """Active users who have at least one cloud credential.

    Uses a DISTINCT subquery on user_id rather than `SELECT DISTINCT users.*` —
    Postgres can't apply DISTINCT to a row containing a `json` column (e.g.
    users.backup_codes), which raised
    `could not identify an equality operator for type json` and failed the
    infra-sync/digest tasks every tick. Returns a query so callers
    can chain extra filters. Portable across Postgres and SQLite.
    """
    from sqlalchemy import select
    from models import User, UserCloudCredential
    # NB: User has NO is_active COLUMN — it's UserMixin's property, so the old
    # `.filter(User.is_active == True)` evaluated to Python False and rendered
    # `WHERE false`, matching nobody. Scope to users with an ACTIVE credential
    # (UserCloudCredential does have that column) via an IN subquery — never
    # `SELECT DISTINCT users.*`, which chokes on Postgres json columns.
    cred_user_ids = (
        select(UserCloudCredential.user_id)
        .where(UserCloudCredential.is_active == True)  # noqa: E712
        .distinct()
    )
    return db.session.query(User).filter(User.id.in_(cred_user_ids))


def _run_infra_sync(app, db):
    """
    Trigger infrastructure sync for users with stale data.

    A user's data is considered stale if their most recent InfrastructureResource
    hasn't been synced in the past 2 hours. We sync in a background thread per
    user so one slow AWS call doesn't block the entire scheduler tick.
    """
    from models import User, InfrastructureResource, UserCloudCredential
    from services.infrastructure_sync import sync_user_infrastructure

    stale_threshold = utcnow() - timedelta(hours=2)

    # Only users with at least one credential
    users_with_creds = _users_with_credentials_query(db).all()

    for user in users_with_creds:
        try:
            latest = (
                InfrastructureResource.query
                .filter_by(user_id=user.id)
                .order_by(InfrastructureResource.last_synced.desc())
                .first()
            )

            needs_sync = (
                latest is None or
                latest.last_synced is None or
                latest.last_synced < stale_threshold
            )

            if needs_sync:
                logger.info(f"User {user.id}: infrastructure data stale — triggering sync")
                # Run sync in a separate thread so slow cloud calls don't block the scheduler.
                # The thread gets its own app context — it does NOT inherit the
                # `with app.app_context()` the scheduler loop is holding, since that's
                # thread-local to the scheduler thread, not this new one.
                t = threading.Thread(
                    target=_sync_user_safe,
                    args=(app, user.id),
                    daemon=True,
                    name=f'infra-sync-{user.id}'
                )
                t.start()

        except Exception as e:
            logger.debug(f"Infra sync check skipped for user {user.id}: {e}")


def _sync_user_safe(app, user_id: int):
    """Run sync_user_infrastructure in a try/except so one failure doesn't kill the thread."""
    from services.infrastructure_sync import sync_user_infrastructure
    try:
        with app.app_context():
            sync_user_infrastructure(user_id)
        logger.info(f"Infra sync complete for user {user_id}")
    except Exception as e:
        logger.warning(f"Infra sync failed for user {user_id}: {e}")


def _run_budget_checks(db):
    """Compare billed AWS spend with each user's budget alerts (Settings > Budgets)."""
    from models import BudgetAlert
    from services.budget_alerts import check_user_budgets
    user_ids = [uid for (uid,) in db.session.query(BudgetAlert.user_id)
                .filter(BudgetAlert.is_active == True).distinct()]  # noqa: E712
    for uid in user_ids:
        try:
            check_user_budgets(uid)
        except Exception as e:
            logger.warning(f"Budget check failed for user {uid}: {e}")


def _run_drip_emails(db):
    """Send pending onboarding drip emails."""
    from services.drip_email_service import process_drip_emails
    try:
        process_drip_emails(db)
    except Exception as e:
        logger.error(f"Drip email processing failed: {e}", exc_info=True)


def _run_weekly_digest(db):
    """
    Send the weekly infrastructure digest email to every active user.

    Runs hourly and sends on Sundays (UTC), once per user per week, tracked by
    `User.last_digest_sent_at`. It used to run every 168h from process start and
    send only if that moment fell on a Sunday, so it almost never went out.
    Skips users with no cloud credentials or no email address.
    """
    now = utcnow()
    if now.weekday() != 6:   # 0=Mon … 6=Sun
        logger.debug("Weekly digest: not Sunday, skipping")
        return
    week_start = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

    from models import User, UserCloudCredential, CostOptimization, SecurityFinding, ApprovalRequest
    from services.email_service import EmailService

    email_svc = EmailService()
    week_ago = utcnow() - timedelta(days=7)
    base_url = __import__('os').environ.get('BASE_URL', 'https://devopsagent.io')

    users = (_users_with_credentials_query(db)
             .filter(User.email != None)  # noqa: E711
             .filter(db.or_(User.email_opt_out == False, User.email_opt_out == None))  # noqa: E711,E712
             .filter(db.or_(User.last_digest_sent_at == None,  # noqa: E711
                            User.last_digest_sent_at < week_start))
             .all())

    sent = skipped = 0
    for user in users:
        try:
            has_aws = UserCloudCredential.query.filter_by(
                user_id=user.id, cloud_provider='aws', is_active=True).first() is not None
            checked = user.security_checked_at is not None and user.security_checked_at >= week_ago
            serious = SecurityFinding.query.filter(
                SecurityFinding.user_id == user.id, SecurityFinding.status == 'open',
                SecurityFinding.severity.in_(('critical', 'high')),
            ).count() if checked else None

            new_recs = CostOptimization.query.filter(
                CostOptimization.user_id == user.id, CostOptimization.status == 'pending',
                CostOptimization.created_at >= week_ago,
            )
            rec_count = new_recs.count()
            rec_savings = db.session.query(
                db.func.sum(CostOptimization.potential_monthly_savings)
            ).filter(
                CostOptimization.user_id == user.id, CostOptimization.status == 'pending',
                CostOptimization.created_at >= week_ago,
            ).scalar() or 0.0

            waiting = ApprovalRequest.query.filter_by(requester_id=user.id, status='pending').count()

            from services.drip_email_service import generate_unsubscribe_token
            html = _build_digest_html(
                unsubscribe_url=(f"{base_url}/email/unsubscribe?user_id={user.id}"
                                 f"&token={generate_unsubscribe_token(user.id)}"),
                username=user.username or user.email.split('@')[0],
                serious_findings=serious,
                rec_count=rec_count,
                rec_savings=rec_savings,
                waiting_approvals=waiting,
                security_available=has_aws,
            )

            ok = email_svc.send_email(user.email, "Your DevOps Agent weekly summary", html)
            if ok:
                user.last_digest_sent_at = now
                db.session.commit()
                sent += 1
            else:
                skipped += 1

        except Exception as e:
            logger.warning(f"Weekly digest failed for user {user.id}: {e}")
            skipped += 1

    logger.info(f"Weekly digest: sent={sent}, skipped={skipped}")


def _build_digest_html(username, serious_findings, rec_count, rec_savings,
                       waiting_approvals, unsubscribe_url='', security_available=True) -> str:
    """Build the weekly summary email.

    Only facts the app has: findings from a security check run in the last 7 days
    (None = no check, which is said plainly rather than shown as zero), cost
    recommendations found this week with their estimated savings, and the user's
    requests still waiting for confirmation. There is no overall grade: a score
    computed from whatever happens to be stored read as an assessment of the account.
    """
    base_url = __import__('os').environ.get('BASE_URL', 'https://devopsagent.io')

    if not security_available:
        sec_text, sec_color = 'Available for AWS accounts only', '#94a3b8'
    elif serious_findings is None:
        sec_text, sec_color = 'Not run this week. Run the security checks on your Dashboard.', '#fbbf24'
    elif serious_findings:
        sec_text = f"{serious_findings} critical or high finding{'s' if serious_findings != 1 else ''} open"
        sec_color = '#f87171'
    else:
        sec_text, sec_color = 'No critical or high findings open', '#4ade80'

    if rec_count:
        cost_text = f"{rec_count} new recommendation{'s' if rec_count != 1 else ''}"
        if rec_savings >= 1:
            cost_text += f", about ${rec_savings:,.0f}/mo (estimate)"
    else:
        cost_text = 'No new recommendations'

    if waiting_approvals:
        appr_text = f"{waiting_approvals} waiting for your confirmation"
        appr_color = '#fbbf24'
    else:
        appr_text, appr_color = 'Nothing waiting', '#94a3b8'

    def row(label, value, color):
        return (
            '<tr><td style="padding:14px 0;border-top:1px solid rgba(255,255,255,0.06)">'
            f'<div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">{label}</div>'
            f'<div style="font-size:15px;font-weight:600;color:{color};margin-top:4px">{value}</div>'
            '</td></tr>'
        )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f1117;font-family:'Segoe UI',Arial,sans-serif;color:#e2e8f0">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:40px 16px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:linear-gradient(135deg,#1a1d2e,#161925);border:1px solid rgba(255,255,255,0.08);border-radius:16px">
        <tr><td style="padding:32px 40px 8px">
          <div style="background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-family:'Courier New',monospace;font-weight:700;font-size:14px;padding:6px 12px;border-radius:8px;display:inline-block">&gt;_</div>
          <span style="font-size:18px;font-weight:800;color:#f1f5f9;margin-left:12px;vertical-align:middle">DevOps Agent</span>
          <h1 style="margin:24px 0 4px;font-size:22px;font-weight:800;color:#f1f5f9">Your weekly summary</h1>
          <p style="margin:0;color:#94a3b8;font-size:14px">Hi {username}, here is your account over the last 7 days.</p>
        </td></tr>
        <tr><td style="padding:8px 40px 0">
          <table width="100%" cellpadding="0" cellspacing="0">
            {row('Security checks', sec_text, sec_color)}
            {row('Cost recommendations', cost_text, '#e2e8f0')}
            {row('Your requests', appr_text, appr_color)}
          </table>
        </td></tr>
        <tr><td style="padding:24px 40px 32px">
          <div style="text-align:center">
            <a href="{base_url}/dashboard" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">Open Dashboard</a>
          </div>
          <p style="text-align:center;margin:24px 0 0;font-size:12px;color:#475569">
            You're receiving this because your DevOps Agent account has a cloud account connected.<br>
            <a href="{unsubscribe_url or base_url + '/settings'}" style="color:#64748b">Unsubscribe from tips and weekly summary emails</a>
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _run_db_backup():
    """
    Run a PostgreSQL or SQLite backup in-process (no Celery broker required).

    PostgreSQL: pg_dump -F c + gzip.  SQLite: copy + gzip.
    Uploads to S3 if BACKUP_S3_BUCKET env var is set (non-fatal on failure).
    Enforces BACKUP_RETENTION_DAYS (default 30) by deleting old .gz files.
    """
    import gzip
    import shutil
    import subprocess

    backup_dir = os.environ.get('BACKUP_DIR', '/backups')
    timestamp = utcnow().strftime('%Y%m%d_%H%M%S')
    db_url = os.environ.get('DATABASE_URL', '')
    backup_file = None
    s3_key = None

    try:
        # Inside the try so a non-writable BACKUP_DIR is handled here (logged)
        # rather than propagating out and tripping the scheduler retry loop.
        os.makedirs(backup_dir, exist_ok=True)

        if 'postgresql' in db_url or 'postgres' in db_url:
            raw_file = os.path.join(backup_dir, f"devops_agent_full_{timestamp}.dump")
            backup_file = raw_file + '.gz'
            result = subprocess.run(
                ['pg_dump', '--format=custom', db_url, '--file', raw_file],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"pg_dump failed: {result.stderr.strip()}")
            with open(raw_file, 'rb') as f_in, gzip.open(backup_file, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.remove(raw_file)
            logger.info(f"Scheduled PostgreSQL backup created: {backup_file}")

        elif 'sqlite' in db_url:
            db_path = db_url.replace('sqlite:///', '').replace('sqlite://', '')
            raw_file = os.path.join(backup_dir, f"devops_agent_full_{timestamp}.db")
            backup_file = raw_file + '.gz'
            shutil.copy2(db_path, raw_file)
            with open(raw_file, 'rb') as f_in, gzip.open(backup_file, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.remove(raw_file)
            logger.info(f"Scheduled SQLite backup created: {backup_file}")

        else:
            logger.warning(f"db_backup: unsupported DB type, skipping ({db_url[:40]})")
            return

        # S3 upload (non-fatal)
        s3_bucket = os.environ.get('BACKUP_S3_BUCKET', '')
        if s3_bucket:
            try:
                from services.backup_upload import upload_backup_to_s3
                s3_key = f"database-backups/{os.path.basename(backup_file)}"
                upload_backup_to_s3(backup_file, s3_bucket, s3_key)
                logger.info(f"Backup uploaded to s3://{s3_bucket}/{s3_key}")
            except Exception as s3_err:
                logger.warning(f"S3 upload failed (non-fatal): {s3_err}")

        # Retention cleanup
        retention_days = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))
        cutoff = utcnow().timestamp() - retention_days * 86400
        deleted = 0
        for fname in os.listdir(backup_dir):
            if fname.endswith('.gz') and fname.startswith('devops_agent_'):
                fpath = os.path.join(backup_dir, fname)
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    deleted += 1
        if deleted:
            logger.info(f"Deleted {deleted} backup(s) older than {retention_days} days")

        size_mb = round(os.path.getsize(backup_file) / (1024 * 1024), 2)
        logger.info(f"Backup complete: {backup_file} ({size_mb} MB)")

    except Exception as e:
        logger.error(f"Scheduled backup failed: {e}", exc_info=True)


def _store_alert(db, source: str, severity: str, message: str):
    """Log a system-level alert."""
    if severity == 'critical':
        logger.critical(f"[ALERT:{source}] {message}")
    elif severity == 'warning':
        logger.warning(f"[ALERT:{source}] {message}")
    else:
        logger.info(f"[ALERT:{source}] {message}")


def get_scheduler_status() -> Dict[str, Any]:
    """Get the current scheduler status."""
    return {
        'running': _scheduler_thread is not None and _scheduler_thread.is_alive(),
        'thread_name': _scheduler_thread.name if _scheduler_thread else None,
        'lock_file': os.path.abspath(_LOCK_FILE),
    }
