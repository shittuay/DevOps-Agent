"""
API Keys Management Endpoints

Provides API key CRUD operations.
"""

from flask import jsonify, request, g
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key, api_key_service


@api_v1_bp.route('/api-keys', methods=['GET'])
@require_api_key(scope='read')
def list_api_keys():
    """
    List user's API keys.

    Requires: API key with 'read' scope

    Query Parameters:
        include_revoked (bool): Include revoked keys (default: false)
    """
    include_revoked = request.args.get('include_revoked', 'false').lower() == 'true'

    keys = api_key_service.list_user_keys(
        user_id=g.api_user.id,
        include_revoked=include_revoked
    )

    return jsonify({
        'api_keys': [k.to_dict() for k in keys]
    })


@api_v1_bp.route('/api-keys', methods=['POST'])
@require_api_key(scope='admin')
def create_api_key():
    """
    Create a new API key.

    Requires: API key with 'admin' scope

    Body:
        name (string, required): Friendly name for the key
        scopes (array, optional): Permission scopes (default: ['read'])
        expires_days (int, optional): Days until expiration
        allowed_ips (array, optional): IP whitelist
        rate_limit (int, optional): Requests per hour (default: 1000)

    Note: The plain text key is only returned once upon creation.
    """
    data = request.get_json() or {}

    if not data.get('name'):
        return jsonify({
            'error': 'Bad request',
            'message': 'Key name is required'
        }), 400

    # Validate scopes
    allowed_scopes = ['read', 'write', 'admin']
    scopes = data.get('scopes', ['read'])
    if not all(s in allowed_scopes for s in scopes):
        return jsonify({
            'error': 'Bad request',
            'message': f'Invalid scopes. Allowed: {allowed_scopes}'
        }), 400

    api_key, plain_key = api_key_service.create_key(
        user_id=g.api_user.id,
        name=data['name'],
        scopes=scopes,
        expires_days=data.get('expires_days'),
        allowed_ips=data.get('allowed_ips'),
        rate_limit=data.get('rate_limit', 1000)
    )

    return jsonify({
        'message': 'API key created',
        'api_key': api_key.to_dict(),
        'key': plain_key,
        'warning': 'Save this key now. It will not be shown again.'
    }), 201


@api_v1_bp.route('/api-keys/<int:key_id>', methods=['GET'])
@require_api_key(scope='read')
def get_api_key(key_id):
    """
    Get a specific API key.

    Requires: API key with 'read' scope
    """
    from models import APIKey

    api_key = APIKey.query.filter_by(
        id=key_id,
        user_id=g.api_user.id
    ).first()

    if not api_key:
        return jsonify({
            'error': 'Not found',
            'message': 'API key not found'
        }), 404

    return jsonify(api_key.to_dict())


@api_v1_bp.route('/api-keys/<int:key_id>', methods=['PATCH'])
@require_api_key(scope='admin')
def update_api_key(key_id):
    """
    Update an API key.

    Requires: API key with 'admin' scope

    Body:
        name (string, optional): New name
        scopes (array, optional): New scopes
        allowed_ips (array, optional): New IP whitelist
        rate_limit (int, optional): New rate limit
    """
    from models import APIKey, db

    api_key = APIKey.query.filter_by(
        id=key_id,
        user_id=g.api_user.id,
        is_active=True
    ).first()

    if not api_key:
        return jsonify({
            'error': 'Not found',
            'message': 'API key not found'
        }), 404

    data = request.get_json() or {}

    if 'name' in data:
        api_key.name = data['name']

    if 'scopes' in data:
        allowed_scopes = ['read', 'write', 'admin']
        if not all(s in allowed_scopes for s in data['scopes']):
            return jsonify({
                'error': 'Bad request',
                'message': f'Invalid scopes. Allowed: {allowed_scopes}'
            }), 400
        api_key.scopes = data['scopes']

    if 'allowed_ips' in data:
        api_key.allowed_ips = data['allowed_ips']

    if 'rate_limit' in data:
        api_key.rate_limit = data['rate_limit']

    db.session.commit()

    return jsonify({
        'message': 'API key updated',
        'api_key': api_key.to_dict()
    })


@api_v1_bp.route('/api-keys/<int:key_id>', methods=['DELETE'])
@require_api_key(scope='admin')
def revoke_api_key(key_id):
    """
    Revoke an API key.

    Requires: API key with 'admin' scope
    """
    success = api_key_service.revoke_key(
        key_id=key_id,
        user_id=g.api_user.id
    )

    if not success:
        return jsonify({
            'error': 'Not found',
            'message': 'API key not found'
        }), 404

    return jsonify({
        'message': 'API key revoked'
    })


@api_v1_bp.route('/api-keys/<int:key_id>/rotate', methods=['POST'])
@require_api_key(scope='admin')
def rotate_api_key(key_id):
    """
    Rotate an API key (create new, revoke old).

    Requires: API key with 'admin' scope

    Note: The new plain text key is only returned once.
    """
    new_api_key, result = api_key_service.rotate_key(
        key_id=key_id,
        user_id=g.api_user.id
    )

    if not new_api_key:
        return jsonify({
            'error': 'Not found',
            'message': result
        }), 404

    return jsonify({
        'message': 'API key rotated',
        'api_key': new_api_key.to_dict(),
        'key': result,
        'warning': 'Save this key now. It will not be shown again.'
    }), 201
