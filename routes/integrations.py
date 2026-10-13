"""Settings API for per-user integration credentials (GitHub, GitLab, Jenkins, PagerDuty, ...).

JSON only, so the form-CSRF hook does not apply. Secret values are write-only: they are
never returned, and a blank secret on update keeps the saved one.
"""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from services import integration_credentials as ic

integrations_bp = Blueprint('integrations', __name__, url_prefix='/api/integrations')


@integrations_bp.route('', methods=['GET'])
@login_required
def list_integrations():
    return jsonify({'integrations': ic.status(current_user.id)})


@integrations_bp.route('/<provider>', methods=['PUT'])
@login_required
def save_integration(provider):
    if provider not in ic.INTEGRATIONS:
        return jsonify({'error': 'Unknown integration.'}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Send a JSON object of field values.'}), 400
    errors = ic.save(current_user.id, provider, {k: v for k, v in data.items() if isinstance(v, str)})
    if errors:
        return jsonify({'error': 'Please fix the highlighted fields.', 'fields': errors}), 400
    return jsonify({'success': True, 'message': f'{ic.INTEGRATIONS[provider].label} connected.'})


@integrations_bp.route('/<provider>', methods=['DELETE'])
@login_required
def delete_integration(provider):
    if provider not in ic.INTEGRATIONS:
        return jsonify({'error': 'Unknown integration.'}), 404
    if not ic.delete(current_user.id, provider):
        return jsonify({'error': 'Not connected.'}), 404
    return jsonify({'success': True, 'message': f'{ic.INTEGRATIONS[provider].label} disconnected.'})
