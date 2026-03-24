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
