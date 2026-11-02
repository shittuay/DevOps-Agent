"""Allow or withdraw sending your messages to the AI providers (see services/ai_consent.py)."""
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from extensions import limiter
from src.utils.timeutils import utcnow

ai_consent_bp = Blueprint('ai_consent', __name__)


def _state():
    at = current_user.ai_consent_at
    return {'allowed': at is not None, 'allowed_at': at.isoformat() + 'Z' if at else None}


@ai_consent_bp.route('/api/ai-consent', methods=['GET'])
@login_required
def get_consent():
    return jsonify(_state())


@ai_consent_bp.route('/api/ai-consent', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def allow():
    from models import db
    if current_user.ai_consent_at is None:
        current_user.ai_consent_at = utcnow()
        db.session.commit()
    return jsonify(_state())


@ai_consent_bp.route('/api/ai-consent', methods=['DELETE'])
@login_required
@limiter.limit("30 per hour")
def withdraw():
    from models import db
    current_user.ai_consent_at = None
    db.session.commit()
    return jsonify(_state())
