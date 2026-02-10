"""
Celery Configuration for DevOps Agent

Handles background task processing for:
- Long-running cloud operations
- Email sending
- Security scans
- Resource synchronization
- Scheduled maintenance tasks
"""

import os
from celery import Celery
from celery.schedules import crontab

# Load secrets: production from AWS Secrets Manager, development from .env
_flask_env = os.environ.get('FLASK_ENV', 'development')
if _flask_env == 'production' or os.environ.get('USE_AWS_SECRETS', '').lower() == 'true':
    from services.secrets_manager import init_secrets
    init_secrets()
else:
    from dotenv import load_dotenv
    for _env_path in ['config/.env', '.env']:
        if os.path.exists(_env_path):
            load_dotenv(_env_path)
            break


def make_celery(app=None):
    """
    Create and configure Celery instance.

    Can be used standalone or with Flask app context.
    """
    # Get broker URL from environment
    broker_url = os.environ.get('CELERY_BROKER_URL') or \
                 os.environ.get('REDIS_URL') or \
                 'redis://localhost:6379/1'

    result_backend = os.environ.get('CELERY_RESULT_BACKEND') or \
                     os.environ.get('REDIS_URL') or \
                     'redis://localhost:6379/2'

    celery = Celery(
        'devops_agent',
        broker=broker_url,
        backend=result_backend,
        include=[
            'tasks.cloud_tasks',
            'tasks.email_tasks',
            'tasks.security_tasks',
            'tasks.maintenance_tasks'
        ]
    )

    # Celery configuration
    celery.conf.update(
        # Task settings
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,

        # Task execution settings
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_time_limit=1800,  # 30 minutes max
        task_soft_time_limit=1500,  # 25 minutes soft limit

        # Worker settings
        worker_prefetch_multiplier=1,
        worker_concurrency=4,
        worker_max_tasks_per_child=100,

        # Result settings
        result_expires=3600,  # Results expire after 1 hour

        # Rate limiting
        task_default_rate_limit='10/m',

        # Retry settings
        task_default_retry_delay=60,
        task_max_retries=3,

        # Task routes - separate queues for different priorities
        task_routes={
            'tasks.cloud_tasks.*': {'queue': 'cloud'},
            'tasks.email_tasks.*': {'queue': 'email'},
            'tasks.security_tasks.*': {'queue': 'security'},
            'tasks.maintenance_tasks.*': {'queue': 'maintenance'},
        },

        # Beat schedule for periodic tasks
        beat_schedule={
            # Clean up expired sessions every hour
            'cleanup-expired-sessions': {
                'task': 'tasks.maintenance_tasks.cleanup_expired_sessions',
                'schedule': crontab(minute=0),
            },
            # Sync cloud resources every 15 minutes
            'sync-cloud-resources': {
                'task': 'tasks.cloud_tasks.sync_all_user_resources',
                'schedule': crontab(minute='*/15'),
            },
            # Reset monthly credits on the 1st of each month
            'reset-monthly-credits': {
                'task': 'tasks.maintenance_tasks.reset_monthly_credits',
                'schedule': crontab(hour=0, minute=0, day_of_month=1),
            },
            # Send subscription renewal reminders
            'subscription-reminders': {
                'task': 'tasks.email_tasks.send_renewal_reminders',
                'schedule': crontab(hour=9, minute=0),  # 9 AM daily
            },
            # Security scan for suspicious activity
            'security-audit': {
                'task': 'tasks.security_tasks.audit_user_activity',
                'schedule': crontab(minute=0, hour='*/6'),  # Every 6 hours
            },
        }
    )

    if app:
        # Flask integration
        celery.conf.update(app.config)

        class ContextTask(celery.Task):
            """Task that runs within Flask app context."""
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = ContextTask

    return celery


# Create default celery instance
celery = make_celery()


if __name__ == '__main__':
    celery.start()
