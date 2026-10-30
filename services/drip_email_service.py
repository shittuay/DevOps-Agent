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
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

# Keys are stored in DripEmailLog, so never rename one: a renamed key would be
# re-sent to everyone who already received it.
DRIP_SEQUENCE: List[Dict[str, Any]] = [
    {
        'key': 'day_2_credits',
        'delay_days': 2,
        'subject': 'Three things to try with your free credits',
        'skip_if_upgraded': False,
        'requires_low_credits': False,
    },
    {
        'key': 'day_5_persona',
        'delay_days': 5,
        'subject': 'Find out why a Kubernetes pod is failing, from chat',
        'skip_if_upgraded': False,
        'requires_low_credits': False,
    },
    {
        'key': 'day_14_power',
        'delay_days': 14,
        'subject': 'Four ways to get more out of DevOps Agent',
        'skip_if_upgraded': True,
        'requires_low_credits': False,
    },
    {
        'key': 'day_25_upgrade',
        'delay_days': 25,
        'subject': "You're almost out of free credits",
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
    now = utcnow()

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
            <a href="{unsub_url}" style="color:#64748b">Unsubscribe from tips and weekly summary emails</a>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _card(title: str, body: str) -> str:
    return (
        '<tr><td style="padding:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:10px">'
        f'<div style="font-size:15px;font-weight:700;color:#ff6b35;margin-bottom:4px">{title}</div>'
        f'<div style="font-size:13px;color:#94a3b8;line-height:1.6">{body}</div>'
        '</td></tr><tr><td style="height:8px"></td></tr>'
    )


def _cards(*cards) -> str:
    return '<table width="100%" cellpadding="0" cellspacing="0">' + ''.join(cards) + '</table>'


def _button(href: str, label: str) -> str:
    return (
        '<div style="text-align:center;margin:28px 0 0">'
        f'<a href="{href}" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#ff6b35,#ff8c5a);'
        f'color:white;font-weight:700;font-size:14px;border-radius:10px;text-decoration:none">{label}</a></div>'
    )


def _intro(title: str, line: str) -> str:
    return (
        f'<h1 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#f1f5f9">{title}</h1>'
        f'<p style="margin:0 0 24px;color:#94a3b8;font-size:14px;line-height:1.6">{line}</p>'
    )


def _note(text: str) -> str:
    return f'<p style="margin:16px 0 0;color:#94a3b8;font-size:13px;line-height:1.6">{text}</p>'


def _q(text: str) -> str:
    return f'<span style="color:#e2e8f0">&ldquo;{text}&rdquo;</span>'


def _html_day2(username: str, base_url: str, unsub_url: str) -> str:
    content = (
        _intro('Three things to try with your free credits',
               f'Hi {username}, here are three good first questions. Type any of them in chat.')
        + _cards(
            _card('1. See what you are running', _q('List my EC2 instances in us-east-1') +
                  ' gives you an inventory with state, type and tags.'),
            _card('2. Look for waste', _q('Find unattached EBS volumes and instances that have been stopped for a while') +
                  ' shows resources you may be paying for without using.'),
            _card('3. Check security basics', _q('Which IAM users have no MFA?') +
                  ' tells you who can sign in with only a password.'),
        )
        + _note('These read your account and change nothing. Anything risky, such as deleting or stopping a '
                'resource, waits for you to confirm. No cloud account connected yet? Turn on '
                '<strong style="color:#e2e8f0">Sandbox (practice)</strong> in the chat sidebar to try it on '
                'simulated resources.')
        + _button(f'{base_url}/chat', 'Open chat')
    )
    return _email_wrapper(content, unsub_url)


def _html_day5(username: str, base_url: str, unsub_url: str) -> str:
    content = (
        _intro('Find out why a Kubernetes pod is failing, from chat',
               f'Hi {username}, if you run an EKS cluster, you can troubleshoot it in a few messages.')
        + _cards(
            _card('1. Find the problem', _q('Show me pods that are not running in my cluster')),
            _card('2. See why', _q('Show the logs and recent events for that pod')),
            _card('3. Fix it', _q('Restart that deployment') +
                  '. You see exactly what will change and confirm it first.'),
        )
        + _note('This works with EKS clusters in your connected AWS account. The cluster needs an access entry for '
                'the DevOps Agent role; if it is missing, the agent tells you how to add it. Prefer a guided version? '
                'Run <strong style="color:#e2e8f0">Troubleshoot Failing Kubernetes Pods</strong> from the Workflows tab.')
        + _button(f'{base_url}/workflows', 'Open Workflows')
    )
    return _email_wrapper(content, unsub_url)


def _html_day14(username: str, base_url: str, unsub_url: str) -> str:
    content = (
        _intro('Four ways to get more out of DevOps Agent', f'Hi {username}, a few features worth knowing about.')
        + _cards(
            _card('Connect your cloud account',
                  'Settings &gt; Cloud Credentials. Connect AWS, Azure or GCP and your resources sync every hour into '
                  'the Dashboard and the infrastructure map. AWS accounts also get security checks and a weekly summary.'),
            _card('Run a workflow',
                  'The Workflows tab has step-by-step tasks such as launching a server, auditing IAM or finding idle '
                  'resources. Fill in a short form and the agent does the rest.'),
            _card('Turn on Skills',
                  'Settings &gt; Skills. Adds expert guidance for Kubernetes troubleshooting, cost optimization, '
                  'security hardening and more.'),
            _card('Stay in control',
                  'Risky actions wait for your confirmation in chat. Your requests and their results are listed on '
                  'the Approvals page.'),
        )
        + _button(f'{base_url}/settings#cloud', 'Open Settings')
    )
    return _email_wrapper(content, unsub_url)


def _plan_rows():
    """Plans as the app defines them, so the email can't drift from what users are charged."""
    from services.subscription_tiers import TIER_DEFINITIONS
    from services.model_router import DEFAULT_TIER_MODELS
    rows = []
    for t in TIER_DEFINITIONS:
        cfg = DEFAULT_TIER_MODELS.get(t['name'])
        model = (cfg.display_name if cfg else '').replace(' (Trial)', '')
        price = '$0' if not t['monthly_price'] else f"${t['monthly_price']:.0f}/mo"
        rows.append((t['display_name'], f"{t['monthly_credits']:,}", model, price))
    return rows


def _html_day25(username: str, base_url: str, unsub_url: str) -> str:
    cell = 'padding:10px 12px;font-size:13px;color:#e2e8f0;border-top:1px solid rgba(255,255,255,0.06)'
    head = 'padding:10px 12px;font-size:12px;font-weight:700;color:#94a3b8'
    body_rows = ''.join(
        f'<tr><td style="{cell};font-weight:700">{n}</td><td style="{cell};text-align:center">{c}</td>'
        f'<td style="{cell};text-align:center">{m}</td><td style="{cell};text-align:center">{p}</td></tr>'
        for n, c, m, p in _plan_rows()
    )
    table = (
        '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid rgba(255,255,255,0.08);border-radius:10px">'
        f'<tr style="background:rgba(255,255,255,0.05)"><td style="{head}">Plan</td>'
        f'<td style="{head};text-align:center">Credits / month</td><td style="{head};text-align:center">AI model</td>'
        f'<td style="{head};text-align:center">Price</td></tr>{body_rows}</table>'
    )
    content = (
        _intro("You're almost out of free credits",
               f'Hi {username}, your free credits refill every month. If you need more before then, '
               'a plan or a one-off credit pack keeps you going.')
        + table
        + _button(f'{base_url}/billing', 'See plans and credit packs')
    )
    return _email_wrapper(content, unsub_url)
