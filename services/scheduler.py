"""
Scheduled Infrastructure Checks Service

Runs periodic background tasks: infrastructure sync, security scans,
cost anomaly detection, and health checks.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

_scheduler_thread = None
_stop_event = threading.Event()


def start_scheduler(app, db):
    """Start the background scheduler in a daemon thread."""
    global _scheduler_thread, _stop_event

    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info("Scheduler already running")
        return

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
    global _stop_event
    _stop_event.set()
    logger.info("Scheduler stop requested")


def _scheduler_loop(app, db):
    """Main scheduler loop. Runs checks on intervals."""
    intervals = {
        'health_check': timedelta(minutes=5),
        'cost_check': timedelta(hours=6),
        'security_scan': timedelta(hours=12),
        'infra_sync': timedelta(hours=1),
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
                    logger.error(f"Scheduler task '{task_name}' failed: {e}")

        _stop_event.wait(timeout=30)


def _run_task(task_name: str, app, db):
    """Execute a scheduled task."""
    logger.info(f"Running scheduled task: {task_name}")

    if task_name == 'health_check':
        _run_health_check(app, db)
    elif task_name == 'cost_check':
        _run_cost_anomaly_check(db)
    elif task_name == 'security_scan':
        _run_security_scan(db)
    elif task_name == 'infra_sync':
        _run_infra_sync(db)


def _run_health_check(app, db):
    """Run system health diagnostics."""
    from services.doctor import run_diagnostics
    results = run_diagnostics(app=app, db=db)

    if results['overall'] == 'unhealthy':
        logger.error(f"HEALTH CHECK FAILED: {results['summary']}")
        _store_alert(db, 'health_check', 'critical',
                     f"System unhealthy: {results['summary']['error']} errors detected")
    elif results['overall'] == 'degraded':
        logger.warning(f"HEALTH CHECK DEGRADED: {results['summary']}")
        _store_alert(db, 'health_check', 'warning',
                     f"System degraded: {results['summary']['warning']} warnings")
    else:
        logger.info("Health check passed")


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
    recent = CostOptimization.query.filter_by(
        user_id=user.id
    ).order_by(CostOptimization.detected_at.desc()).limit(10).all()

    if len(recent) >= 2:
        latest_savings = sum(r.estimated_savings or 0 for r in recent[:5])
        if latest_savings > 100:
            logger.info(f"User {user.id}: ${latest_savings:.0f} potential savings detected")


def _run_security_scan(db):
    """Run security scan for all active users."""
    from models import User, SecurityFinding
    users = User.query.filter(User.is_active == True).all()

    for user in users:
        try:
            open_findings = SecurityFinding.query.filter_by(
                user_id=user.id,
                status='open'
            ).count()

            if open_findings > 0:
                critical = SecurityFinding.query.filter_by(
                    user_id=user.id,
                    status='open',
                    severity='critical'
                ).count()
                if critical > 0:
                    logger.warning(f"User {user.id}: {critical} critical security findings open")
        except Exception as e:
            logger.debug(f"Security scan skipped for user {user.id}: {e}")


def _run_infra_sync(db):
    """Trigger infrastructure sync for users with stale data."""
    from models import User, InfrastructureResource

    users = User.query.filter(User.is_active == True).all()
    stale_threshold = datetime.utcnow() - timedelta(hours=2)

    for user in users:
        try:
            latest = InfrastructureResource.query.filter_by(
                user_id=user.id
            ).order_by(InfrastructureResource.last_synced.desc()).first()

            if latest and latest.last_synced and latest.last_synced < stale_threshold:
                logger.info(f"User {user.id}: infrastructure data is stale, needs sync")
        except Exception as e:
            logger.debug(f"Infra sync check skipped for user {user.id}: {e}")


def _store_alert(db, source: str, severity: str, message: str):
    """Log a system-level alert. Alerts are logged (not stored in DB since they require a user_id)."""
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
    }
