"""
Email Service

Supports Brevo, SMTP, and SendGrid for transactional email delivery.
Configure via environment variables:
  EMAIL_PROVIDER=brevo|smtp|sendgrid   (default: brevo if BREVO_API_KEY set, else smtp)
  BREVO_API_KEY   — Brevo API key (also used by SMS service)
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
  SENDGRID_API_KEY
  EMAIL_FROM, EMAIL_FROM_NAME
"""
import os
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

BREVO_EMAIL_URL = "https://api.brevo.com/v3/smtp/email"


class EmailService:
    def __init__(self):
        self.brevo_key = os.getenv('BREVO_API_KEY', '')
        # Default to brevo if API key present, otherwise smtp
        default_provider = 'brevo' if self.brevo_key else 'smtp'
        self.provider = os.getenv('EMAIL_PROVIDER', default_provider)
        self.from_email = os.getenv('EMAIL_FROM', 'noreply@devopsagent.io')
        self.from_name = os.getenv('EMAIL_FROM_NAME', 'DevOps Agent')
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp-relay.brevo.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER')
        self.smtp_pass = os.getenv('SMTP_PASS')
        self.sendgrid_key = os.getenv('SENDGRID_API_KEY')
        self.base_url = os.getenv('BASE_URL', 'https://devopsagent.io')

    def send_email(self, to_email, subject, html_content, text_content=None):
        """Send email via configured provider. Returns bool."""
        if self.provider == 'brevo' and self.brevo_key:
            return self._send_brevo(to_email, subject, html_content, text_content)
        if self.provider == 'sendgrid' and self.sendgrid_key:
            return self._send_sendgrid(to_email, subject, html_content, text_content)
        return self._send_smtp(to_email, subject, html_content, text_content)

    def _send_brevo(self, to_email, subject, html_content, text_content=None):
        """Send via Brevo transactional email API."""
        try:
            import requests

            payload = {
                "sender": {"name": self.from_name, "email": self.from_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content,
            }
            if text_content:
                payload["textContent"] = text_content

            resp = requests.post(
                BREVO_EMAIL_URL,
                json=payload,
                headers={
                    "api-key": self.brevo_key,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            if resp.status_code in (200, 201):
                logger.info(f"Brevo email sent to {to_email}: {subject}")
                return True
            else:
                logger.error(f"Brevo email error {resp.status_code}: {resp.text}")
                return False

        except Exception as e:
            logger.error(f"Brevo email send failed: {e}")
            return False

    def _send_smtp(self, to_email, subject, html_content, text_content=None):
        """Send via SMTP."""
        if not self.smtp_user or not self.smtp_pass:
            logger.warning("SMTP credentials not configured, skipping email send")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email

            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.sendmail(self.from_email, to_email, msg.as_string())

            logger.info(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False

    def _send_sendgrid(self, to_email, subject, html_content, text_content=None):
        """Send via SendGrid HTTP API."""
        try:
            import requests

            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": self.from_email, "name": self.from_name},
                "subject": subject,
                "content": []
            }

            if text_content:
                payload["content"].append({"type": "text/plain", "value": text_content})
            payload["content"].append({"type": "text/html", "value": html_content})

            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.sendgrid_key}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )

            if resp.status_code in (200, 201, 202):
                logger.info(f"SendGrid email sent to {to_email}: {subject}")
                return True
            else:
                logger.error(f"SendGrid error {resp.status_code}: {resp.text}")
                return False

        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            return False

    def _wrap_html(self, body_content):
        """Wrap email body in a branded HTML template."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; padding: 20px;">
            <div style="max-width: 560px; margin: 0 auto; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <span style="font-size: 20px; font-weight: 700; color: #ff6b35;">DevOps Agent</span>
                </div>
                {body_content}
                <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;">
                <p style="font-size: 12px; color: #999; text-align: center;">
                    DevOps Agent | AI-Powered Cloud Management
                </p>
            </div>
        </body>
        </html>
        """

    def send_verification_email(self, user, token=None):
        """Send account verification email. If token is not provided, one will be generated."""
        if token is None:
            import secrets as _secrets
            token = _secrets.token_urlsafe(32)
        link = f"{self.base_url}/verify-email?token={token}&user_id={user.id}"

        html = self._wrap_html(f"""
            <h2 style="color: #333; margin-bottom: 12px;">Verify Your Email</h2>
            <p>Hi {user.username},</p>
            <p>Please verify your email address to complete your account setup.</p>
            <p style="font-size: 13px; color: #666;">This link expires in 24 hours.</p>
            <div style="text-align: center; margin: 24px 0;">
                <a href="{link}" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">
                    Verify Email
                </a>
            </div>
            <p style="font-size: 13px; color: #666;">If you didn't create this account, you can ignore this email.</p>
        """)

        return self.send_email(user.email, "Verify Your Email - DevOps Agent", html)

    def send_password_reset_email(self, user, token):
        """Send password reset email with a tokenized link. Link expires in 1 hour."""
        link = f"{self.base_url}/reset-password?token={token}&user_id={user.id}"

        html = self._wrap_html(f"""
            <h2 style="color: #333; margin-bottom: 12px;">Reset Your Password</h2>
            <p>Hi {user.username},</p>
            <p>We received a request to reset your password. Click the button below to choose a new one.</p>
            <div style="text-align: center; margin: 24px 0;">
                <a href="{link}" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">
                    Reset Password
                </a>
            </div>
            <p style="font-size: 13px; color: #666;">This link expires in 1 hour. If you didn't request a password reset, you can safely ignore this email.</p>
        """)

        return self.send_email(user.email, "Reset Your Password - DevOps Agent", html)

    def send_payment_failed_warning(self, user):
        """Warn user about failed payment."""
        html = self._wrap_html(f"""
            <h2 style="color: #ef4444; margin-bottom: 12px;">Payment Failed</h2>
            <p>Hi {user.username},</p>
            <p>We were unable to process your subscription payment. Please update your payment method within 3 days to avoid a service downgrade.</p>
            <div style="text-align: center; margin: 24px 0;">
                <a href="{self.base_url}/billing" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">
                    Update Payment
                </a>
            </div>
        """)

        return self.send_email(user.email, "Payment Failed - Action Required", html)

    def send_subscription_confirmation(self, user, tier_name):
        """Confirm subscription purchase/upgrade."""
        html = self._wrap_html(f"""
            <h2 style="color: #10b981; margin-bottom: 12px;">Subscription Confirmed</h2>
            <p>Hi {user.username},</p>
            <p>Your <strong>{tier_name}</strong> subscription is now active. You have access to all features included in your plan.</p>
            <div style="text-align: center; margin: 24px 0;">
                <a href="{self.base_url}/dashboard" style="display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">
                    Go to Dashboard
                </a>
            </div>
        """)

        return self.send_email(user.email, f"Welcome to {tier_name} - DevOps Agent", html)


    def send_otp_email(self, user, code):
        """Send a 6-digit MFA verification code via email."""
        html = self._wrap_html(f"""
            <h2 style="color: #333; margin-bottom: 12px;">Your Verification Code</h2>
            <p>Hi {user.username},</p>
            <p>Use the code below to complete your login:</p>
            <div style="text-align: center; margin: 28px 0;">
                <span style="display: inline-block; font-family: 'Courier New', monospace; font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #ff6b35; background: #fff5f0; padding: 16px 32px; border-radius: 12px; border: 2px dashed #ff6b35;">
                    {code}
                </span>
            </div>
            <p style="font-size: 13px; color: #666;">This code expires in 10 minutes. If you did not request this code, please change your password immediately.</p>
        """)
        return self.send_email(user.email, "Your Verification Code - DevOps Agent", html)


email_service = EmailService()
