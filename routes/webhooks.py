"""
Webhook Integration Routes for DevOps Agent.

Provides endpoints for receiving webhooks from GitHub, GitLab, and Bitbucket,
as well as a dashboard for viewing webhook events.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
import logging

from services.webhook_integrations import get_webhook_service, WebhookSource
from services.rbac import admin_required

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__, url_prefix='/webhooks')


# ==================== WEB ROUTES ====================


@webhooks_bp.route('/')
@login_required
@admin_required
def webhooks_dashboard():
    """Webhook events dashboard."""
    service = get_webhook_service()
    events = service.get_events(limit=100)
    stats = service.get_stats()

    return render_template('webhooks/dashboard.html',
        events=events,
        stats=stats
    )


# ==================== WEBHOOK RECEIVERS ====================


@webhooks_bp.route('/github', methods=['POST'])
def receive_github():
    """
    Receive webhooks from GitHub.

    Headers:
    - X-GitHub-Event: Event type (push, pull_request, etc.)
    - X-Hub-Signature-256: HMAC signature for validation
    """
    service = get_webhook_service()

    event_type = request.headers.get('X-GitHub-Event')
    signature = request.headers.get('X-Hub-Signature-256') or request.headers.get('X-Hub-Signature')

    if not event_type:
        return jsonify({'error': 'Missing X-GitHub-Event header'}), 400

    # Validate signature if secret is configured
    secret = service.secrets.get('github')
    if secret:
        if not signature:
            return jsonify({'error': 'Missing signature'}), 401
        if not service.validate_github_signature(request.get_data(), signature, secret):
            logger.warning("Invalid GitHub webhook signature")
            return jsonify({'error': 'Invalid signature'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    # Handle ping event
    if event_type == 'ping':
        logger.info(f"GitHub webhook ping received: {data.get('zen', '')}")
        return jsonify({'status': 'pong'})

    event = service.process_webhook('github', event_type, data)

    if event:
        return jsonify({
            'status': 'ok',
            'event_id': event.id,
            'event_type': event.event_type.value
        })

    return jsonify({'status': 'ignored', 'event_type': event_type})


@webhooks_bp.route('/gitlab', methods=['POST'])
def receive_gitlab():
    """
    Receive webhooks from GitLab.

    Headers:
    - X-Gitlab-Event: Event type (Push Hook, Merge Request Hook, etc.)
    - X-Gitlab-Token: Secret token for validation
    """
    service = get_webhook_service()

    event_type = request.headers.get('X-Gitlab-Event')
    token = request.headers.get('X-Gitlab-Token')

    if not event_type:
        return jsonify({'error': 'Missing X-Gitlab-Event header'}), 400

    # Validate token if secret is configured
    secret = service.secrets.get('gitlab')
    if secret:
        if not service.validate_gitlab_token(token, secret):
            logger.warning("Invalid GitLab webhook token")
            return jsonify({'error': 'Invalid token'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    event = service.process_webhook('gitlab', event_type, data)

    if event:
        return jsonify({
            'status': 'ok',
            'event_id': event.id,
            'event_type': event.event_type.value
        })

    return jsonify({'status': 'ignored', 'event_type': event_type})


@webhooks_bp.route('/bitbucket', methods=['POST'])
def receive_bitbucket():
    """
    Receive webhooks from Bitbucket.

    Headers:
    - X-Event-Key: Event type (repo:push, pullrequest:created, etc.)
    """
    service = get_webhook_service()

    event_type = request.headers.get('X-Event-Key')

    if not event_type:
        return jsonify({'error': 'Missing X-Event-Key header'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    event = service.process_webhook('bitbucket', event_type, data)

    if event:
        return jsonify({
            'status': 'ok',
            'event_id': event.id,
            'event_type': event.event_type.value
        })

    return jsonify({'status': 'ignored', 'event_type': event_type})


# ==================== API ROUTES ====================


@webhooks_bp.route('/api/events')
@login_required
@admin_required
def api_list_events():
    """API: List webhook events."""
    service = get_webhook_service()

    source = request.args.get('source')
    event_type = request.args.get('type')
    limit = request.args.get('limit', 50, type=int)

    events = service.get_events(source=source, event_type=event_type, limit=limit)

    return jsonify({
        'success': True,
        'count': len(events),
        'events': [{
            'id': e.id,
            'source': e.source.value,
            'event_type': e.event_type.value,
            'repository': e.repository,
            'branch': e.branch,
            'commit_sha': e.commit_sha,
            'actor': e.actor,
            'title': e.title,
            'description': e.description[:200] if e.description else '',
            'url': e.url,
            'status': e.status,
            'received_at': e.received_at.isoformat()
        } for e in events]
    })


@webhooks_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """API: Get webhook statistics."""
    service = get_webhook_service()
    return jsonify({
        'success': True,
        'stats': service.get_stats()
    })


@webhooks_bp.route('/api/configure', methods=['POST'])
@login_required
def api_configure():
    """API: Configure webhook secrets."""
    from services.rbac import user_is_admin

    if not user_is_admin(current_user):
        return jsonify({'success': False, 'error': 'Admin access required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    service = get_webhook_service()

    if 'github_secret' in data:
        service.set_secret('github', data['github_secret'])

    if 'gitlab_token' in data:
        service.set_secret('gitlab', data['gitlab_token'])

    logger.info(f"Webhook secrets configured by {current_user.email}")

    return jsonify({
        'success': True,
        'message': 'Webhook configuration updated'
    })


@webhooks_bp.route('/api/test', methods=['POST'])
@login_required
def api_test_webhook():
    """API: Send a test webhook event."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    source = data.get('source', 'github')
    service = get_webhook_service()

    # Create a test event
    test_data = {
        'repository': {'full_name': 'test/repo'},
        'ref': 'refs/heads/main',
        'after': 'abc123def456',
        'pusher': {'name': current_user.email},
        'commits': [{'id': 'abc123def456', 'message': 'Test commit'}],
        'compare': 'https://example.com/compare'
    }

    event = service.process_webhook(source, 'push', test_data)

    if event:
        return jsonify({
            'success': True,
            'event_id': event.id,
            'message': 'Test event created'
        })

    return jsonify({'success': False, 'error': 'Failed to create test event'}), 500
