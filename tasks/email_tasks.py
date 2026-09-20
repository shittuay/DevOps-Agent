"""
Email Tasks

Background tasks for sending emails.
"""

import logging
from celery import shared_task
from datetime import datetime, timedelta
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_email_async(self, to_email: str, subject: str, html_content: str,
                     text_content: str = None):
    """
    Send email asynchronously.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML email body
        text_content: Plain text email body (optional)
    """
    try:
        logger.info(f"Sending email to {to_email}: {subject}")

        from services.email_service import email_service

        success = email_service.send_email(
            to_email=to_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )

        if success:
            return {'status': 'success', 'to': to_email}
        else:
            raise Exception("Email sending failed")

    except Exception as e:
        logger.error(f"Error sending email: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def send_verification_email_async(self, user_id: int):
    """
    Send verification email to a user.

    Args:
        user_id: User ID
    """
    try:
        from app import app, db
        from models import User
        from services.email_service import email_service

        with app.app_context():
            user = User.query.get(user_id)
            if not user:
                return {'status': 'error', 'message': 'User not found'}

            if user.email_verified:
                return {'status': 'skipped', 'message': 'Already verified'}

            success = email_service.send_verification_email(user)
            return {'status': 'success' if success else 'error', 'user_id': user_id}

    except Exception as e:
        logger.error(f"Error sending verification email: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True)
def send_renewal_reminders(self):
    """
    Send subscription renewal reminder emails.
    Called daily by Celery Beat.
    """
    try:
        from app import app, db
        from models import User, UserSubscription

        with app.app_context():
            # Find subscriptions expiring in 7 days
            reminder_date = utcnow() + timedelta(days=7)

            expiring_subs = UserSubscription.query.filter(
                UserSubscription.end_date <= reminder_date,
                UserSubscription.end_date > utcnow(),
                UserSubscription.is_active == True
            ).all()

            sent = 0
            for sub in expiring_subs:
                user = User.query.get(sub.user_id)
                if user and user.email:
                    send_email_async.delay(
                        to_email=user.email,
                        subject="Your DevOps Agent subscription is expiring soon",
                        html_content=f"""
                        <h2>Subscription Reminder</h2>
                        <p>Hi {user.username},</p>
                        <p>Your {sub.tier.name if sub.tier else 'subscription'} is expiring on
                           {sub.end_date.strftime('%B %d, %Y')}.</p>
                        <p>Renew now to keep your access and credits!</p>
                        <a href="https://yourapp.com/billing">Manage Subscription</a>
                        """
                    )
                    sent += 1

            return {'status': 'success', 'reminders_sent': sent}

    except Exception as e:
        logger.error(f"Error sending renewal reminders: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def send_credit_low_warning(self, user_id: int, remaining_credits: int):
    """
    Send warning when user's credits are running low.

    Args:
        user_id: User ID
        remaining_credits: Number of credits remaining
    """
    try:
        from app import app
        from models import User

        with app.app_context():
            user = User.query.get(user_id)
            if not user or not user.email:
                return {'status': 'error', 'message': 'User not found'}

            send_email_async.delay(
                to_email=user.email,
                subject="Low Credits Warning - DevOps Agent",
                html_content=f"""
                <h2>Low Credits Warning</h2>
                <p>Hi {user.username},</p>
                <p>You have only <strong>{remaining_credits}</strong> credits remaining.</p>
                <p>Purchase more credits or upgrade your plan to continue using DevOps Agent.</p>
                <a href="https://yourapp.com/billing">Get More Credits</a>
                """
            )

            return {'status': 'success', 'user_id': user_id}

    except Exception as e:
        logger.error(f"Error sending credit warning: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True)
def send_security_alert(self, user_id: int, alert_type: str, details: dict):
    """
    Send security alert email to user.

    Args:
        user_id: User ID
        alert_type: Type of security alert
        details: Alert details
    """
    try:
        from app import app
        from models import User

        with app.app_context():
            user = User.query.get(user_id)
            if not user or not user.email:
                return {'status': 'error', 'message': 'User not found'}

            send_email_async.delay(
                to_email=user.email,
                subject=f"Security Alert: {alert_type} - DevOps Agent",
                html_content=f"""
                <h2>Security Alert</h2>
                <p>Hi {user.username},</p>
                <p>We detected a security event on your account:</p>
                <p><strong>{alert_type}</strong></p>
                <ul>
                    {''.join(f'<li>{k}: {v}</li>' for k, v in details.items())}
                </ul>
                <p>If this wasn't you, please secure your account immediately.</p>
                <a href="https://yourapp.com/settings">Review Account Settings</a>
                """
            )

            return {'status': 'success', 'user_id': user_id, 'alert_type': alert_type}

    except Exception as e:
        logger.error(f"Error sending security alert: {e}")
        return {'status': 'error', 'message': str(e)}
