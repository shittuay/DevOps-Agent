"""Where a new user came from (owner request, 2026-10-15).

The first visit's ?utm_source= / ?ref= / ?src= (plus utm_campaign), or else the
referring site, is kept in the session and saved on the account at signup, so the
admin pages can show which ads and posts actually bring people in. First touch
wins: a later visit never overwrites it.
"""
import re
from typing import Optional
from urllib.parse import urlparse

SESSION_KEY = 'signup_source'
_CLEAN = re.compile(r'[^a-z0-9_.-]')
_OWN_HOSTS = ('devopsagent.io', 'localhost', '127.0.0.1')


def _clean(value: Optional[str], limit: int = 40) -> str:
    return _CLEAN.sub('', (value or '').strip().lower())[:limit]


def source_from(args, referrer: Optional[str]) -> Optional[str]:
    """'tiktok', 'tiktok/launch', 'site:google.com', or None."""
    src = _clean(args.get('utm_source') or args.get('ref') or args.get('src'))
    if src:
        campaign = _clean(args.get('utm_campaign'))
        return f'{src}/{campaign}' if campaign else src
    host = _clean(urlparse(referrer or '').hostname or '', 60)
    if host.startswith('www.'):
        host = host[4:]
    if host and not any(host == h or host.endswith('.' + h) for h in _OWN_HOSTS):
        return f'site:{host}'
    return None


def remember(session, args, referrer: Optional[str]) -> None:
    if session.get(SESSION_KEY):
        return
    src = source_from(args, referrer)
    if src:
        session[SESSION_KEY] = src


FUNNEL_STEPS = (
    ('signed_up', 'Signed up'),
    ('verified', 'Verified email'),
    ('onboarded', 'Finished setup'),
    ('connected', 'Connected a cloud account'),
    ('sandbox', 'Turned on sandbox'),
    ('chatted', 'Sent a chat message'),
)


def user_progress(user_ids) -> dict:
    """{user_id: {'verified', 'onboarded', 'connected', 'sandbox', 'messages'}}."""
    from sqlalchemy import func
    from models import ChatMessage, User, UserCloudCredential, UserPreferences
    ids = list(user_ids)
    if not ids:
        return {}
    users = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
    connected = {r[0] for r in UserCloudCredential.query.with_entities(UserCloudCredential.user_id)
                 .filter(UserCloudCredential.user_id.in_(ids), UserCloudCredential.is_active.is_(True)).all()}
    sandbox = {r[0] for r in UserPreferences.query.with_entities(UserPreferences.user_id)
               .filter(UserPreferences.user_id.in_(ids), UserPreferences.sandbox_mode.is_(True)).all()}
    messages = dict(ChatMessage.query.with_entities(ChatMessage.user_id, func.count(ChatMessage.id))
                    .filter(ChatMessage.user_id.in_(ids), ChatMessage.role == 'user')
                    .group_by(ChatMessage.user_id).all())
    return {uid: {
        'verified': bool(getattr(u, 'email_verified', False)),
        'onboarded': bool(getattr(u, 'onboarding_completed', False)),
        'connected': uid in connected,
        'sandbox': uid in sandbox,
        'messages': int(messages.get(uid, 0)),
    } for uid, u in users.items()}


def signup_report(days: int = 30) -> dict:
    """Signups in the last `days`: how far each got, and counts by source.
    Admin accounts are left out so the owner's own testing doesn't count."""
    from datetime import timedelta
    from models import User
    from src.utils.timeutils import utcnow
    since = utcnow() - timedelta(days=days)
    users = (User.query.filter(User.created_at >= since)
             .filter((User.role.is_(None)) | (User.role != 'admin')).all())
    progress = user_progress(u.id for u in users)
    funnel = {key: 0 for key, _ in FUNNEL_STEPS}
    by_source = {}
    for u in users:
        p = progress.get(u.id, {})
        funnel['signed_up'] += 1
        for key in ('verified', 'onboarded', 'connected', 'sandbox'):
            funnel[key] += 1 if p.get(key) else 0
        funnel['chatted'] += 1 if p.get('messages') else 0
        src = u.signup_source or 'unknown'
        row = by_source.setdefault(src, {'signups': 0, 'chatted': 0})
        row['signups'] += 1
        row['chatted'] += 1 if p.get('messages') else 0
    return {
        'days': days,
        'funnel': [(label, funnel[key]) for key, label in FUNNEL_STEPS],
        'by_source': sorted(by_source.items(), key=lambda kv: -kv[1]['signups']),
    }
