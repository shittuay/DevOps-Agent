"""Push notifications to the DevOps Agent iPhone app through Apple Push Notification service.

Used for approval requests: when the agent files one, the person who has to confirm or approve
it gets a notification on their phone instead of finding it later on /approvals.

Configuration (all four required, else sending is a silent no-op):
  APNS_KEY_ID     the 10-character key id of an APNs auth key (.p8) from the Apple Developer site
  APNS_TEAM_ID    the 10-character Apple Developer team id
  APNS_KEY        the .p8 file's contents (PEM). APNS_KEY_PATH may point at the file instead.
  APNS_BUNDLE_ID  the app's bundle id, sent as apns-topic (e.g. io.devopsagent.app)

APNs only speaks HTTP/2, hence httpx with ``http2=True`` (needs the ``h2`` package). The hosts
are Apple's fixed endpoints, never caller-supplied, so this is not an SSRF surface.

What goes in a notification passes through Apple's servers and shows on a lock screen, so it
carries the tool name and risk level only, never tool arguments or results.
"""
import logging
import os
import re
import threading
import time
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

APNS_HOSTS = {
    'production': 'https://api.push.apple.com',
    'sandbox': 'https://api.sandbox.push.apple.com',
}
TOKEN_RE = re.compile(r'^[0-9a-fA-F]{64,200}$')
JWT_TTL_SECONDS = 50 * 60  # Apple rejects tokens older than an hour and throttles refreshes
GONE_REASONS = {'BadDeviceToken', 'Unregistered', 'DeviceTokenNotForTopic'}

_jwt_lock = threading.Lock()
_jwt_cache: dict = {}


def _config() -> Optional[dict]:
    key = os.environ.get('APNS_KEY', '').strip()
    path = os.environ.get('APNS_KEY_PATH', '').strip()
    if not key and path:
        try:
            with open(path, encoding='utf-8') as fh:
                key = fh.read().strip()
        except OSError:
            logger.error('APNS_KEY_PATH is set but unreadable')
            return None
    cfg = {
        'key': key.replace('\\n', '\n'),
        'key_id': os.environ.get('APNS_KEY_ID', '').strip(),
        'team_id': os.environ.get('APNS_TEAM_ID', '').strip(),
        'bundle_id': os.environ.get('APNS_BUNDLE_ID', '').strip(),
    }
    return cfg if all(cfg.values()) else None


def is_configured() -> bool:
    return _config() is not None


def valid_token(token: str) -> bool:
    return bool(token) and bool(TOKEN_RE.match(token))


def _provider_token(cfg: dict) -> str:
    from joserfc import jwt
    from joserfc.jwk import ECKey

    now = int(time.time())
    cache_key = (cfg['key_id'], cfg['team_id'])
    with _jwt_lock:
        cached = _jwt_cache.get(cache_key)
        if cached and now - cached[1] < JWT_TTL_SECONDS:
            return cached[0]
        token = jwt.encode({'alg': 'ES256', 'kid': cfg['key_id']},
                           {'iss': cfg['team_id'], 'iat': now},
                           ECKey.import_key(cfg['key']))
        _jwt_cache[cache_key] = (token, now)
        return token


def build_payload(title: str, body: str, data: Optional[dict] = None,
                  category: Optional[str] = None) -> dict:
    aps = {'alert': {'title': title[:120], 'body': body[:300]}, 'sound': 'default'}
    if category:
        aps['category'] = category
    return {'aps': aps, **(data or {})}


def _send(client, cfg: dict, device_token: str, environment: str, payload: dict) -> Optional[str]:
    """POST one notification. Returns the APNs failure reason, or None on success."""
    url = f"{APNS_HOSTS.get(environment, APNS_HOSTS['production'])}/3/device/{device_token}"
    resp = client.post(url, json=payload, headers={
        'authorization': f"bearer {_provider_token(cfg)}",
        'apns-topic': cfg['bundle_id'],
        'apns-push-type': 'alert',
        'apns-priority': '10',
    })
    if resp.status_code == 200:
        return None
    try:
        reason = resp.json().get('reason') or str(resp.status_code)
    except ValueError:
        reason = str(resp.status_code)
    return reason


def send_now(user_ids: Iterable[int], payload: dict) -> int:
    """Send to every registered device of these users. Returns how many were delivered.

    Needs an app context. Devices Apple says are gone are removed.
    """
    cfg = _config()
    if not cfg:
        return 0
    from models import PushDevice, db

    devices = PushDevice.query.filter(PushDevice.user_id.in_(list(user_ids))).all()
    if not devices:
        return 0
    import httpx

    delivered = 0
    with httpx.Client(http2=True, timeout=10.0) as client:
        for device in devices:
            try:
                reason = _send(client, cfg, device.token, device.environment, payload)
            except Exception as exc:  # network trouble must never break the caller
                logger.warning('APNs send failed for device %s: %s', device.id, type(exc).__name__)
                continue
            if reason is None:
                delivered += 1
            elif reason in GONE_REASONS:
                db.session.delete(device)
            else:
                logger.warning('APNs refused notification for device %s: %s', device.id, reason)
    db.session.commit()
    return delivered


def send_async(user_ids: Iterable[int], payload: dict) -> None:
    """send_now on a daemon thread with its own app context (never blocks a request)."""
    ids = [int(u) for u in user_ids if u]
    if not ids or not is_configured():
        return
    from flask import current_app
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                send_now(ids, payload)
            except Exception:
                logger.exception('Push notification dispatch failed')

    threading.Thread(target=run, daemon=True, name='apns-push').start()


def notify_approval(req, recipient_ids: Iterable[int], self_confirm: bool) -> None:
    """Tell the people who must act on an ApprovalRequest. Only tool name and risk are sent."""
    risk = (req.risk_level or '').lower()
    if self_confirm:
        title = 'Confirm an action'
        body = f'DevOps Agent wants to run {req.tool_name} ({risk} risk). Tap to review.'
        link = '/approvals/mine'
    else:
        who = req.requester.username if getattr(req, 'requester', None) else 'A teammate'
        title = 'Approval needed'
        body = f'{who} asked to run {req.tool_name} ({risk} risk). Tap to review.'
        link = '/approvals'
    send_async(recipient_ids, build_payload(
        title, body, data={'approval_id': req.id, 'link': link}, category='APPROVAL_REQUEST'))
