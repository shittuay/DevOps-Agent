"""Register the signed-in user's iPhone for push notifications (called by the iOS app)."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import limiter, security_logger
from src.utils.timeutils import utcnow

push_bp = Blueprint('push', __name__)


@push_bp.route('/api/push/devices', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def register_device():
    """Body: {"token": "<APNs device token, hex>", "environment": "production"|"sandbox"}.

    A token belongs to one phone; if it was registered to another account (someone signed out
    and a different person signed in), it moves to this one.

    Only the iPhone app registers tokens, so other callers are refused: a token copied off a
    phone can't be moved to another account from a script or a browser. The marker is the
    app's user agent, which a determined caller can fake (App Attest would close that), so
    every move between accounts is also logged.
    """
    from models import PushDevice, db
    from services.app_client import is_ios_app
    from services.push_service import valid_token

    if not is_ios_app():
        return jsonify({'error': 'app_only'}), 403

    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    environment = data.get('environment') or 'production'
    if not valid_token(token):
        return jsonify({'error': 'invalid_token'}), 400
    if environment not in ('production', 'sandbox'):
        return jsonify({'error': 'invalid_environment'}), 400

    device = PushDevice.query.filter_by(token=token).first()
    if device is None:
        device = PushDevice(token=token)
        db.session.add(device)
    elif device.user_id != current_user.id:
        security_logger.warning(
            f"Push token moved from user {device.user_id} to user {current_user.id} "
            f"(ip {request.remote_addr}, token ...{token[-6:]})")
    device.user_id = current_user.id
    device.environment = environment
    device.platform = 'ios'
    device.last_seen_at = utcnow()
    db.session.commit()
    return jsonify({'success': True})


@push_bp.route('/api/push/devices', methods=['DELETE'])
@login_required
def unregister_device():
    """Body: {"token": "..."}. Called by the app when the user signs out or turns alerts off."""
    from models import PushDevice, db

    token = ((request.get_json(silent=True) or {}).get('token') or '').strip()
    PushDevice.query.filter_by(token=token, user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'success': True})
