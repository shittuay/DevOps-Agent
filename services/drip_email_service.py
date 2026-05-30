"""
Onboarding Drip Email Service

Sends a 5-email sequence (Day 0/2/5/14/25) to new users after signup.
Called hourly by the scheduler. Supports opt-out and smart skip for upgraded users.
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DRIP_SEQUENCE: List[Dict[str, Any]] = [
    {
        'key': 'day_2_credits',
        'delay_days': 2,
        'subject': '3 things you can do with your 20 free credits',
        'skip_if_upgraded': False,
        'requires_low_credits': False,
    },
    {
        'key': 'day_5_persona',
        'delay_days': 5,
        'subject': 'How a platform engineer saves 2 hours/day',
        'skip_if_upgraded': False,
        'requires_low_credits': False,
    },
    {
        'key': 'day_14_power',
        'delay_days': 14,
        'subject': 'Credits halfway — here\'s what power users do',
        'skip_if_upgraded': True,
        'requires_low_credits': False,
    },
    {
        'key': 'day_25_upgrade',
        'delay_days': 25,
        'subject': '5 credits left — upgrade now',
        'skip_if_upgraded': True,
        'requires_low_credits': True,
    },
]

MAX_AGE_DAYS = 35


def _get_secret_key() -> str:
    """Get secret key from env or the persisted instance key (never fall back to a hardcoded value)."""
    key = os.environ.get('SECRET_KEY', '')
    if not key:
        key_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance', 'secret_key')
        if os.path.exists(key_file):
            with open(key_file) as f:
                key = f.read().strip()
    if not key:
        raise RuntimeError('SECRET_KEY is not set and instance/secret_key does not exist')
    return key


def generate_unsubscribe_token(user_id: int) -> str:
    secret = _get_secret_key()
    return hmac.new(
        secret.encode(), f'unsub-{user_id}'.encode(), hashlib.sha256
    ).hexdigest()[:32]


def verify_unsubscribe_token(user_id: int, token: str) -> bool:
    expected = generate_unsubscribe_token(user_id)
    return hmac.compare_digest(expected, token)


def process_drip_emails(db):
    """Process pending drip emails for all eligible users. Called hourly."""
    from models import User, DripEmailLog, UserSubscription, SubscriptionTier
    from services.email_service import EmailService

    email_svc = EmailService()
    now = datetime.utcnow()

    users = (
        User.query
        .filter(User.email_verified == True)
        .filter((User.email_opt_out == False) | (User.email_opt_out == None))
        .filter(User.email != None)
        .all()
    )

    sent_count = 0
    skipped_count = 0

    for user in users:
        try:
            if not user.created_at:
                continue

            days_since_signup = (now - user.created_at).days

            # Skip users older than MAX_AGE_DAYS — record unsent steps as skipped
            if days_since_signup > MAX_AGE_DAYS:
                _backfill_old_user(db, user)
                continue

            # Get already-sent drip keys
            sent_keys = {
                log.drip_key for log in
                DripEmailLog.query.filter_by(user_id=user.id).all()
            }

            # Check if user is on a paid tier
            from services.credit_service import CreditService
            is_paid = False
            credits_remaining = CreditService.balance(user.id)
            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            if sub and sub.tier:
                is_paid = sub.tier.name in ('starter', 'professional', 'business')

            # Process at most 1 drip per user per run
            for step in DRIP_SEQUENCE:
                if step['key'] in sent_keys:
                    continue

                if days_since_signup < step['delay_days']:
                    break  # Not time yet; later steps are also not ready

                # Skip (record) if user already upgraded
                if step['skip_if_upgraded'] and is_paid:
                    log = DripEmailLog(
                        user_id=user.id,
                        drip_key=step['key'],
                        success=True,
                    )
                    db.session.add(log)
                    db.session.commit()
                    skipped_count += 1
                    continue

                # Defer if requires low credits but user still has plenty
                if step['requires_low_credits'] and credits_remaining > 5:
                    continue

                # Build and send
                html = _build_drip_html(step['key'], user, email_svc.base_url)
                ok = email_svc.send_email(user.email, step['subject'], html)

                log = DripEmailLog(
                    user_id=user.id,
                    drip_key=step['key'],
                    success=ok,
                )
                db.session.add(log)
                db.session.commit()

                if ok:
                    sent_count += 1
                    logger.info(f"Drip email '{step['key']}' sent to user {user.id}")
                else:
                    logger.warning(f"Drip email '{step['key']}' failed for user {user.id}")

                break  # Max 1 drip per user per run

        except Exception as e:
            logger.warning(f"Drip processing failed for user {user.id}: {e}")

    if sent_count or skipped_count:
        logger.info(f"Drip emails: sent={sent_count}, skipped={skipped_count}")


def _backfill_old_user(db, user):
    """Record all drip steps as skipped for users older than MAX_AGE_DAYS."""
    from models import DripEmailLog

    sent_keys = {
        log.drip_key for log in
        DripEmailLog.query.filter_by(user_id=user.id).all()
    }

    added = False
    for step in DRIP_SEQUENCE:
        if step['key'] not in sent_keys:
            log = DripEmailLog(
                user_id=user.id,
                drip_key=step['key'],
                success=False,
            )
            db.session.add(log)
            added = True

    if added:
        db.session.commit()


def _build_drip_html(drip_key: str, user, base_url: str) -> str:
    """Route to the correct HTML builder."""
    username = user.username or user.email.split('@')[0]
    unsub_token = generate_unsubscribe_token(user.id)
    unsub_url = f"{base_url}/email/unsubscribe?user_id={user.id}&token={unsub_token}"

    builders = {
        'day_2_credits': _html_day2,
        'day_5_persona': _html_day5,
        'day_14_power': _html_day14,
        'day_25_upgrade': _html_day25,
    }

    builder = builders.get(drip_key)
    if not builder:
        return ''
    return builder(username, base_url, unsub_url)


def _email_wrapper(content: str, unsub_url: str) -> str:
    """Wrap email content in the dark-theme branded shell matching digest emails."""
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
          </tr></table>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:linear-gradient(135deg,#1a1d2e,#161925);padding:0 40px 32px;border:1px solid rgba(255,255,255,0.08);border-top:none;border-radius:0 0 16px 16px">
          {content}
          <p style="text-align:center;margin:24px 0 0;font-size:12px;color:#475569">
            You're receiving this because you signed up for DevOps Agent.<br>
            <a href="{unsub_url}" style="color:#64748b">Unsubscribe from onboarding emails</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _html_day2(username: str, base_url: str, unsub_url: str) -> str:
    content = f"""
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">3 things you can do with your 20 free credits</h1>
          <p style="margin:0 0 24px;color:#94a3b8;font-size:14px">Hi {username} — here are the quickest wins to try.</p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;margin-bottom:12px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">1. Scan your AWS account</div>
              <div style="font-size:13px;color:#94a3b8">"Show me all EC2 instances running in us-east-1" — instant inventory, zero setup.</div>
            </td></tr>
            <tr><td style="height:8px"></td></tr>
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">2. Find cost savings</div>
              <div style="font-size:13px;color:#94a3b8">"Are there any unused EBS volumes?" — most teams find $50-200/mo in waste.</div>
            </td></tr>
            <tr><td style="height:8px"></td></tr>
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">3. Check security posture</div>
              <div style="font-size:13px;color:#94a3b8">"List IAM users without MFA" — know your exposure in one message.</div>
            </td></tr>
          </table>

          <div style="text-align:center;margin:28px 0 0">
            <a href="{base_url}/chat" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">Try it now</a>
          </div>"""
    return _email_wrapper(content, unsub_url)


def _html_day5(username: str, base_url: str, unsub_url: str) -> str:
    content = f"""
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">How a platform engineer saves 2 hours/day</h1>
          <p style="margin:0 0 20px;color:#94a3b8;font-size:14px">Hi {username} — here's a real workflow from one of our early users.</p>

          <div style="padding:20px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px;margin-bottom:20px">
            <p style="color:#e2e8f0;font-size:14px;line-height:1.7;margin:0 0 12px">
              <strong style="color:#ff6b35">8:30 AM</strong> — "Show me any pods in CrashLoopBackOff across all namespaces"<br>
              <strong style="color:#ff6b35">8:31 AM</strong> — "What are the logs for that failing pod?"<br>
              <strong style="color:#ff6b35">8:32 AM</strong> — "Restart the deployment with the updated image tag"
            </p>
            <p style="color:#94a3b8;font-size:13px;margin:0">
              What used to take 20 minutes of kubectl + context switching now takes 3 chat messages.
            </p>
          </div>

          <p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 4px">
            DevOps Agent handles <strong style="color:#e2e8f0">726 operations</strong> across AWS, Azure, GCP, Kubernetes, Terraform, Docker, and CI/CD — all through natural language.
          </p>

          <div style="text-align:center;margin:28px 0 0">
            <a href="{base_url}/chat" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">Start a conversation</a>
          </div>"""
    return _email_wrapper(content, unsub_url)


def _html_day14(username: str, base_url: str, unsub_url: str) -> str:
    content = f"""
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">You're halfway through your credits</h1>
          <p style="margin:0 0 20px;color:#94a3b8;font-size:14px">Hi {username} — here's how power users get the most out of every credit.</p>

          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">Connect your cloud credentials</div>
              <div style="font-size:13px;color:#94a3b8">Settings &gt; Cloud Credentials — enables real-time infra sync, proactive alerts, and the weekly health digest.</div>
            </td></tr>
            <tr><td style="height:8px"></td></tr>
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">Enable Skills</div>
              <div style="font-size:13px;color:#94a3b8">Settings &gt; Skills — activate Kubernetes Troubleshooting, Cost Optimization, or Security Hardening for deeper, context-aware answers.</div>
            </td></tr>
            <tr><td style="height:8px"></td></tr>
            <tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">
              <div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">Use multi-step commands</div>
              <div style="font-size:13px;color:#94a3b8">"Find all untagged resources, then create a Terraform import plan" — chain complex tasks into a single conversation.</div>
            </td></tr>
          </table>

          <div style="text-align:center;margin:28px 0 0">
            <a href="{base_url}/settings" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">Open Settings</a>
          </div>"""
    return _email_wrapper(content, unsub_url)


def _html_day25(username: str, base_url: str, unsub_url: str) -> str:
    content = f"""
          <h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">Your free credits are almost gone</h1>
          <p style="margin:0 0 20px;color:#94a3b8;font-size:14px">Hi {username} — upgrade to keep your infrastructure automation running.</p>

          <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid rgba(255,255,255,0.08);border-radius:10px;overflow:hidden">
            <!-- Header row -->
            <tr style="background:rgba(255,255,255,0.05)">
              <td style="padding:12px 16px;font-size:13px;font-weight:700;color:#64748b"></td>
              <td style="padding:12px 16px;font-size:13px;font-weight:700;color:#94a3b8;text-align:center">Free</td>
              <td style="padding:12px 16px;font-size:13px;font-weight:700;color:#ff6b35;text-align:center">Starter</td>
              <td style="padding:12px 16px;font-size:13px;font-weight:700;color:#ff6b35;text-align:center">Pro</td>
            </tr>
            <!-- Credits -->
            <tr>
              <td style="padding:10px 16px;font-size:13px;color:#94a3b8;border-top:1px solid rgba(255,255,255,0.06)">Monthly credits</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">20</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">200</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">1,000</td>
            </tr>
            <!-- Model -->
            <tr>
              <td style="padding:10px 16px;font-size:13px;color:#94a3b8;border-top:1px solid rgba(255,255,255,0.06)">AI model</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">Kimi K2.5</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">Kimi K2.5</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">Claude Sonnet</td>
            </tr>
            <!-- Price -->
            <tr>
              <td style="padding:10px 16px;font-size:13px;color:#94a3b8;border-top:1px solid rgba(255,255,255,0.06)">Price</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">$0</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">$29/mo</td>
              <td style="padding:10px 16px;font-size:13px;color:#e2e8f0;text-align:center;border-top:1px solid rgba(255,255,255,0.06)">$99/mo</td>
            </tr>
          </table>

          <div style="text-align:center;margin:28px 0 0">
            <a href="{base_url}/billing" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">Upgrade now</a>
          </div>"""
    return _email_wrapper(content, unsub_url)
