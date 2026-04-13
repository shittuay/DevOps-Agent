"""
Scheduled Infrastructure Checks Service

Runs periodic background tasks: infrastructure sync, security scans,
cost anomaly detection, health checks, and proactive monitoring ticks.

Multi-worker safety: uses a PID file lock so only one gunicorn worker
starts the scheduler thread. Other workers skip silently.
"""

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Any

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
        'monitoring_tick':   timedelta(seconds=60),
        'infra_sync':        timedelta(hours=1),
        'cost_check':        timedelta(hours=6),
        'security_scan':     timedelta(hours=12),
        'drip_email':        timedelta(hours=1),
        'weekly_digest':     timedelta(hours=168),   # 7 days
        'db_backup':         timedelta(hours=24),
    }

    last_run = {k: datetime.min for k in intervals}

    while not _stop_event.is_set():
        now = datetime.utcnow()

        for task_name, interval in intervals.items():
            if now - last_run[task_name] >= interval:
                try:
                    with app.app_context():
                        _run_task(task_name, app, db)
                    last_run[task_name] = now
                except Exception as e:
                    logger.error(f"Scheduler task '{task_name}' failed: {e}", exc_info=True)

        _stop_event.wait(timeout=30)

    _release_scheduler_lock()


def _run_task(task_name: str, app, db):
    """Execute a scheduled task."""
    logger.debug(f"Running scheduled task: {task_name}")

    if task_name == 'health_check':
        _run_health_check(app, db)
    elif task_name == 'monitoring_tick':
        _run_monitoring_tick(db)
    elif task_name == 'infra_sync':
        _run_infra_sync(db)
    elif task_name == 'cost_check':
        _run_cost_anomaly_check(db)
    elif task_name == 'security_scan':
        _run_security_scan(db)
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


def _run_monitoring_tick(db):
    """
    Fire a proactive monitoring evaluation for every active user.

    ProactiveMonitoringService has its own internal loop, but that loop only
    fires for users whose rules are already loaded in memory. This tick
    ensures every active user with cloud credentials gets evaluated at least
    once per minute, even if they haven't sent a chat message recently.

    Alert → incident wiring happens inside ProactiveMonitoringService via
    set_incident_engine(), which is called during app startup in app.py.
    """
    from models import User, UserCloudCredential
    from services.proactive_monitoring import get_monitoring_service
    monitoring_service = get_monitoring_service()

    # Only process users who have at least one cloud credential configured
    users_with_creds = (
        db.session.query(User)
        .join(UserCloudCredential, UserCloudCredential.user_id == User.id)
        .filter(User.is_active == True)
        .distinct()
        .all()
    )

    if not users_with_creds:
        return

    logger.debug(f"Monitoring tick: evaluating {len(users_with_creds)} users")

    for user in users_with_creds:
        try:
            monitoring_service.check_now(user.id)
        except Exception as e:
            logger.debug(f"Monitoring tick skipped for user {user.id}: {e}")


def _run_infra_sync(db):
    """
    Trigger infrastructure sync for users with stale data.

    A user's data is considered stale if their most recent InfrastructureResource
    hasn't been synced in the past 2 hours. We sync in a background thread per
    user so one slow AWS call doesn't block the entire scheduler tick.
    """
    from models import User, InfrastructureResource, UserCloudCredential
    from services.infrastructure_sync import sync_user_infrastructure

    stale_threshold = datetime.utcnow() - timedelta(hours=2)

    # Only users with at least one credential
    users_with_creds = (
        db.session.query(User)
        .join(UserCloudCredential, UserCloudCredential.user_id == User.id)
        .filter(User.is_active == True)
        .distinct()
        .all()
    )

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
                # Run sync in a separate thread so slow cloud calls don't block the scheduler
                t = threading.Thread(
                    target=_sync_user_safe,
                    args=(user.id,),
                    daemon=True,
                    name=f'infra-sync-{user.id}'
                )
                t.start()

        except Exception as e:
            logger.debug(f"Infra sync check skipped for user {user.id}: {e}")


def _sync_user_safe(user_id: int):
    """Run sync_user_infrastructure in a try/except so one failure doesn't kill the thread."""
    from services.infrastructure_sync import sync_user_infrastructure
    try:
        sync_user_infrastructure(user_id)
        logger.info(f"Infra sync complete for user {user_id}")
    except Exception as e:
        logger.warning(f"Infra sync failed for user {user_id}: {e}")


def _run_cost_anomaly_check(db):
    """Check for cost anomalies across all users with AWS credentials."""
    from models import User
    users = User.query.filter(User.is_active == True).all()

    for user in users:
        try:
            _check_user_costs(db, user)
        except Exception as e:
            logger.debug(f"Cost check skipped for user {user.id}: {e}")


def _check_user_costs(db, user):
    """Check a single user's cost trends for anomalies."""
    from models import CostOptimization
    recent = (
        CostOptimization.query
        .filter_by(user_id=user.id)
        .order_by(CostOptimization.detected_at.desc())
        .limit(10)
        .all()
    )

    if len(recent) >= 2:
        latest_savings = sum(r.estimated_savings or 0 for r in recent[:5])
        if latest_savings > 100:
            logger.info(f"User {user.id}: ${latest_savings:.0f} potential savings detected")


def _run_security_scan(db):
    """Log open security findings for active users."""
    from models import User, SecurityFinding
    users = User.query.filter(User.is_active == True).all()

    for user in users:
        try:
            critical = SecurityFinding.query.filter_by(
                user_id=user.id,
                status='open',
                severity='critical'
            ).count()
            if critical > 0:
                logger.warning(f"User {user.id}: {critical} critical security findings open")
        except Exception as e:
            logger.debug(f"Security scan skipped for user {user.id}: {e}")


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

    Fires on Sundays (checked here so the 168h interval doesn't drift to
    wrong days). Only sends if today is Sunday (UTC weekday == 6).
    Skips users with no cloud credentials or no email address.
    """
    from datetime import datetime as _dt
    if _dt.utcnow().weekday() != 6:   # 0=Mon … 6=Sun
        logger.debug("Weekly digest: not Sunday, skipping")
        return

    from models import User, UserCloudCredential, IncidentModel, CostOptimization, SecurityFinding, Alert
    from services.email_service import EmailService
    from services.health_score import calculate_health_score, get_grade_label

    email_svc = EmailService()
    week_ago = _dt.utcnow() - timedelta(days=7)

    users = (
        db.session.query(User)
        .join(UserCloudCredential, UserCloudCredential.user_id == User.id)
        .filter(User.is_active == True, User.email != None)
        .distinct()
        .all()
    )

    sent = skipped = 0
    for user in users:
        try:
            # ── Per-user 7-day stats ───────────────────────────────────
            incidents_total = IncidentModel.query.filter(
                IncidentModel.user_id == user.id,
                IncidentModel.triggered_at >= week_ago
            ).count()

            incidents_resolved = IncidentModel.query.filter(
                IncidentModel.user_id == user.id,
                IncidentModel.triggered_at >= week_ago,
                IncidentModel.status == 'resolved'
            ).count()

            savings_identified = db.session.query(
                db.func.sum(CostOptimization.estimated_savings)
            ).filter(
                CostOptimization.user_id == user.id,
                CostOptimization.detected_at >= week_ago
            ).scalar() or 0.0

            critical_sec = SecurityFinding.query.filter_by(
                user_id=user.id, status='open', severity='critical'
            ).count()

            health = calculate_health_score(user.id)
            grade_label = get_grade_label(health['grade'])

            html = _build_digest_html(
                username=user.username or user.email.split('@')[0],
                grade=health['grade'],
                grade_label=grade_label,
                score=health['score'],
                incidents_total=incidents_total,
                incidents_resolved=incidents_resolved,
                savings_identified=savings_identified,
                critical_sec=critical_sec,
            )

            subject = f"Your DevOps Agent weekly digest — Infrastructure health: {health['grade']} ({grade_label})"
            ok = email_svc.send_email(user.email, subject, html)
            if ok:
                sent += 1
            else:
                skipped += 1

        except Exception as e:
            logger.warning(f"Weekly digest failed for user {user.id}: {e}")
            skipped += 1

    logger.info(f"Weekly digest: sent={sent}, skipped={skipped}")


def _build_digest_html(username, grade, grade_label, score,
                       incidents_total, incidents_resolved,
                       savings_identified, critical_sec) -> str:
    """Build the weekly digest HTML email body."""
    grade_color = {
        'A': '#4ade80', 'B': '#60a5fa',
        'C': '#fbbf24', 'D': '#fb923c', 'F': '#f87171'
    }.get(grade, '#60a5fa')

    savings_text = f"${savings_identified:.0f}" if savings_identified >= 1 else "$0"
    sec_text = f"{critical_sec} critical finding{'s' if critical_sec != 1 else ''}" if critical_sec > 0 else "No critical findings"
    sec_color = '#f87171' if critical_sec > 0 else '#4ade80'

    base_url = __import__('os').environ.get('BASE_URL', 'https://devopsagent.io')

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f1117;font-family:'Segoe UI',Arial,sans-serif;color:#e2e8f0">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f1117;padding:40px 16px">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">

        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#1a1d2e,#161925);border-radius:16px 16px 0 0;padding:32px 40px;border:1px solid rgba(255,255,255,0.08);border-bottom:none">
          <table width="100%"><tr>
            <td>
              <div style="background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-family:'Courier New',monospace;font-weight:700;font-size:14px;padding:6px 12px;border-radius:8px;display:inline-block">&gt;_</div>
              <span style="font-size:18px;font-weight:800;color:#f1f5f9;margin-left:12px;vertical-align:middle">DevOps Agent</span>
            </td>
            <td align="right" style="color:#64748b;font-size:12px;font-family:'Courier New',monospace">WEEKLY DIGEST</td>
          </tr></table>
          <h1 style="margin:24px 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">Your infrastructure this week</h1>
          <p style="margin:0;color:#94a3b8;font-size:14px">Hi {username} — here's what your DevOps Agent found and fixed.</p>
        </td></tr>

        <!-- Health score banner -->
        <tr><td style="background:linear-gradient(135deg,#1a1d2e,#161925);padding:0 40px 32px;border:1px solid rgba(255,255,255,0.08);border-top:none;border-bottom:none">
          <table width="100%" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:24px" cellpadding="0" cellspacing="0">
            <tr>
              <td style="text-align:center;padding:0 16px 0 0;border-right:1px solid rgba(255,255,255,0.08)">
                <div style="font-size:64px;font-weight:800;color:{grade_color};line-height:1">{grade}</div>
                <div style="font-size:13px;color:#94a3b8;margin-top:4px">Infrastructure Health</div>
                <div style="font-size:11px;color:#64748b;font-family:'Courier New',monospace;margin-top:2px">{score}/100 — {grade_label}</div>
              </td>
              <td style="padding:0 0 0 24px">
                <table cellpadding="0" cellspacing="0" width="100%">
                  <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                    <span style="color:#94a3b8;font-size:13px">Incidents this week</span>
                    <span style="float:right;font-weight:700;color:#f1f5f9;font-size:13px">{incidents_total}</span>
                  </td></tr>
                  <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                    <span style="color:#94a3b8;font-size:13px">Auto-resolved</span>
                    <span style="float:right;font-weight:700;color:#4ade80;font-size:13px">{incidents_resolved}</span>
                  </td></tr>
                  <tr><td style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.06)">
                    <span style="color:#94a3b8;font-size:13px">Savings identified</span>
                    <span style="float:right;font-weight:700;color:#fbbf24;font-size:13px">{savings_text}/mo</span>
                  </td></tr>
                  <tr><td style="padding:8px 0">
                    <span style="color:#94a3b8;font-size:13px">Security status</span>
                    <span style="float:right;font-weight:700;color:{sec_color};font-size:13px">{sec_text}</span>
                  </td></tr>
                </table>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- CTA -->
        <tr><td style="background:linear-gradient(135deg,#1a1d2e,#161925);padding:0 40px 32px;border:1px solid rgba(255,255,255,0.08);border-top:none;border-radius:0 0 16px 16px">
          <table width="100%"><tr><td align="center">
            <a href="{base_url}/dashboard" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">View Dashboard</a>
          </td></tr></table>
          <p style="text-align:center;margin:16px 0 0;font-size:12px;color:#475569">
            You're receiving this because you have an active DevOps Agent account.<br>
            <a href="{base_url}/settings" style="color:#64748b">Manage email preferences</a>
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
    from datetime import datetime as _dt

    backup_dir = os.environ.get('BACKUP_DIR', '/backups')
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = _dt.utcnow().strftime('%Y%m%d_%H%M%S')
    db_url = os.environ.get('DATABASE_URL', '')
    backup_file = None
    s3_key = None

    try:
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
                import boto3
                s3_key = f"database-backups/{os.path.basename(backup_file)}"
                boto3.client('s3').upload_file(backup_file, s3_bucket, s3_key)
                logger.info(f"Backup uploaded to s3://{s3_bucket}/{s3_key}")
            except Exception as s3_err:
                logger.warning(f"S3 upload failed (non-fatal): {s3_err}")

        # Retention cleanup
        retention_days = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))
        cutoff = _dt.utcnow().timestamp() - retention_days * 86400
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
