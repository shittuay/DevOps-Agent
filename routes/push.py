"""Register the signed-in user's iPhone for push notifications (called by the iOS app)."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from extensions import limiter
from src.utils.timeutils import utcnow

push_bp = Blueprint('push', __name__)


@push_bp.route('/api/push/devices', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def register_device():
    """Body: {"token": "<APNs device token, hex>", "environment": "production"|"sandbox"}.

    A token belongs to one phone; if it was registered to another account (someone signed out
    and a different person signed in), it moves to this one.
    """
    from models import PushDevice, db
    from services.push_service import valid_token

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
