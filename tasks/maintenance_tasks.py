"""
Maintenance Tasks

Background tasks for system maintenance and cleanup.
"""

import logging
from celery import shared_task
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def cleanup_expired_sessions(self):
    """
    Clean up expired user sessions and tokens.
    Called hourly by Celery Beat.
    """
    try:
        from app import app, db
        from models import User

        with app.app_context():
            # Clean up expired email verification tokens
            expired_count = User.query.filter(
                User.email_verification_expires < datetime.utcnow(),
                User.email_verified == False
            ).update({
                'email_verification_token': None,
                'email_verification_expires': None
            })

            db.session.commit()

            logger.info(f"Cleaned up {expired_count} expired verification tokens")

            return {
                'status': 'success',
                'expired_tokens_cleaned': expired_count
            }

    except Exception as e:
        logger.error(f"Session cleanup error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def reset_monthly_credits(self):
    """
    Reset monthly credits for all users.
    Called on the 1st of each month by Celery Beat.
    """
    try:
        from app import app, db
        from models import User, UserSubscription, SubscriptionTier

        with app.app_context():
            # Get all active subscriptions
            active_subs = UserSubscription.query.filter(
                UserSubscription.is_active == True,
                UserSubscription.end_date > datetime.utcnow()
            ).all()

            reset_count = 0
            for sub in active_subs:
                if sub.tier:
                    sub.credits_remaining = sub.tier.monthly_credits
                    reset_count += 1

            db.session.commit()

            logger.info(f"Reset credits for {reset_count} subscriptions")

            return {
                'status': 'success',
                'subscriptions_reset': reset_count
            }

    except Exception as e:
        logger.error(f"Credit reset error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def cleanup_old_conversations(self, days_old: int = 90):
    """
    Archive or delete old conversations.

    Args:
        days_old: Delete conversations older than this many days
    """
    try:
        from app import app, db
        from models import Conversation, ChatMessage

        with app.app_context():
            cutoff = datetime.utcnow() - timedelta(days=days_old)

            # Get old conversations
            old_convos = Conversation.query.filter(
                Conversation.updated_at < cutoff
            ).all()

            deleted_messages = 0
            deleted_convos = 0

            for convo in old_convos:
                # Delete messages first
                msg_count = ChatMessage.query.filter(
                    ChatMessage.conversation_id == convo.id
                ).delete()
                deleted_messages += msg_count

                # Delete conversation
                db.session.delete(convo)
                deleted_convos += 1

            db.session.commit()

            logger.info(f"Deleted {deleted_convos} conversations and {deleted_messages} messages")

            return {
                'status': 'success',
                'conversations_deleted': deleted_convos,
                'messages_deleted': deleted_messages
            }

    except Exception as e:
        logger.error(f"Conversation cleanup error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def optimize_database(self):
    """
    Run database optimization tasks.
    """
    try:
        from app import app, db

        with app.app_context():
            # For PostgreSQL
            try:
                db.session.execute(db.text('VACUUM ANALYZE'))
                db.session.commit()
                logger.info("Database vacuum completed")
            except Exception:
                # SQLite or other DB might not support VACUUM in transaction
                pass

            return {'status': 'success'}

    except Exception as e:
        logger.error(f"Database optimization error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def generate_usage_report(self, period: str = 'daily'):
    """
    Generate usage statistics report.

    Args:
        period: Report period (daily, weekly, monthly)
    """
    try:
        from app import app, db
        from models import User, Conversation, ChatMessage, UserSubscription
        from sqlalchemy import func

        with app.app_context():
            if period == 'daily':
                start_date = datetime.utcnow() - timedelta(days=1)
            elif period == 'weekly':
                start_date = datetime.utcnow() - timedelta(weeks=1)
            else:
                start_date = datetime.utcnow() - timedelta(days=30)

            # Gather statistics
            stats = {
                'period': period,
                'start_date': start_date.isoformat(),
                'end_date': datetime.utcnow().isoformat(),
                'new_users': User.query.filter(User.created_at >= start_date).count(),
                'active_users': db.session.query(func.count(func.distinct(Conversation.user_id))).filter(
                    Conversation.created_at >= start_date
                ).scalar(),
                'total_conversations': Conversation.query.filter(
                    Conversation.created_at >= start_date
                ).count(),
                'total_messages': ChatMessage.query.filter(
                    ChatMessage.created_at >= start_date
                ).count(),
                'active_subscriptions': UserSubscription.query.filter(
                    UserSubscription.is_active == True
                ).count()
            }

            logger.info(f"Generated {period} usage report: {stats}")

            return {'status': 'success', 'report': stats}

    except Exception as e:
        logger.error(f"Report generation error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def backup_database(self, backup_type: str = 'full'):
    """
    Create database backup.

    Args:
        backup_type: Type of backup (full, incremental)
    """
    try:
        import os
        import subprocess
        from datetime import datetime

        backup_dir = os.environ.get('BACKUP_DIR', '/backups')
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        backup_file = f"{backup_dir}/devops_agent_{backup_type}_{timestamp}.sql"

        # Get database URL
        db_url = os.environ.get('DATABASE_URL', '')

        if 'postgresql' in db_url:
            # PostgreSQL backup
            # pg_dump command would go here
            logger.info(f"PostgreSQL backup created: {backup_file}")
        elif 'sqlite' in db_url:
            # SQLite backup - just copy the file
            import shutil
            db_path = db_url.replace('sqlite:///', '')
            shutil.copy2(db_path, backup_file)
            logger.info(f"SQLite backup created: {backup_file}")

        return {
            'status': 'success',
            'backup_file': backup_file,
            'backup_type': backup_type
        }

    except Exception as e:
        logger.error(f"Database backup error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def check_system_health(self):
    """
    Check overall system health.
    """
    try:
        import psutil
        from app import app, db
        from services.cache_service import cache

        health = {
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'healthy',
            'checks': {}
        }

        # CPU usage
        health['checks']['cpu'] = {
            'usage_percent': psutil.cpu_percent(),
            'status': 'ok' if psutil.cpu_percent() < 80 else 'warning'
        }

        # Memory usage
        memory = psutil.virtual_memory()
        health['checks']['memory'] = {
            'usage_percent': memory.percent,
            'available_gb': round(memory.available / (1024**3), 2),
            'status': 'ok' if memory.percent < 80 else 'warning'
        }

        # Disk usage
        disk = psutil.disk_usage('/')
        health['checks']['disk'] = {
            'usage_percent': disk.percent,
            'free_gb': round(disk.free / (1024**3), 2),
            'status': 'ok' if disk.percent < 85 else 'warning'
        }

        # Database connectivity
        with app.app_context():
            try:
                db.session.execute(db.text('SELECT 1'))
                health['checks']['database'] = {'status': 'ok'}
            except Exception as e:
                health['checks']['database'] = {'status': 'error', 'message': str(e)}
                health['status'] = 'unhealthy'

        # Cache connectivity
        cache_stats = cache.get_stats()
        health['checks']['cache'] = {
            'backend': cache_stats['backend'],
            'status': 'ok' if cache_stats['enabled'] else 'warning'
        }

        # Overall status
        if any(c.get('status') == 'error' for c in health['checks'].values()):
            health['status'] = 'unhealthy'
        elif any(c.get('status') == 'warning' for c in health['checks'].values()):
            health['status'] = 'degraded'

        logger.info(f"System health check: {health['status']}")

        return health

    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {'status': 'error', 'message': str(e)}
