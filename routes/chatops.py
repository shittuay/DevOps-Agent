"""
ChatOps Routes for DevOps Agent.

Provides endpoints for Slack and Microsoft Teams bot integrations.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
import logging
import hmac
import hashlib
import json
import os
import time

from services.chatops_service import get_chatops_service, ChatPlatform
from src.utils.network_safety import safe_request

logger = logging.getLogger(__name__)

chatops_bp = Blueprint('chatops', __name__, url_prefix='/chatops')

# Bot Framework auth for the Teams endpoints below (see _verify_teams_request).
_BOTFRAMEWORK_OPENID_CONFIG = 'https://login.botframework.com/v1/.well-known/openidconfiguration'
_BOTFRAMEWORK_ISSUER = 'https://api.botframework.com'
_TEAMS_JWKS_CACHE: dict = {}
_TEAMS_JWKS_TTL = 3600  # seconds


# ==================== WEB ROUTES ====================


@chatops_bp.route('/')
@login_required
def chatops_dashboard():
    """ChatOps configuration dashboard."""
    service = get_chatops_service()

    # Get unique commands
    unique_commands = {}
    for cmd in service.commands.values():
        unique_commands[cmd.name] = cmd

    return render_template('chatops/dashboard.html',
        commands=sorted(unique_commands.values(), key=lambda c: c.name)
    )


# ==================== SLACK INTEGRATION ====================


@chatops_bp.route('/slack/events', methods=['POST'])
def slack_events():
    """
    Slack Events API endpoint.

    Handles:
    - url_verification challenge
    - app_mention events
    - message events (DMs)
    """
    if not _verify_slack_request():
        return jsonify({'error': 'Invalid signature'}), 401

    data = request.get_json(silent=True) or {}

    # Handle URL verification challenge
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data.get('challenge')})

    # Handle events
    event = data.get('event', {})
    event_type = event.get('type')

    if event_type in ['app_mention', 'message']:
        # Don't respond to bot messages
        if event.get('bot_id') or event.get('subtype') == 'bot_message':
            return jsonify({'ok': True})

        text = event.get('text', '')
        user_id = event.get('user')
        channel_id = event.get('channel')

        service = get_chatops_service()
        response = service.process_message(
            text,
            user_id=user_id,
            channel_id=channel_id,
            platform=ChatPlatform.SLACK
        )

        # Post response back to Slack
        _post_slack_message(channel_id, response, ephemeral=response.ephemeral, user_id=user_id)

    return jsonify({'ok': True})


@chatops_bp.route('/slack/commands', methods=['POST'])
def slack_commands():
    """
    Slack Slash Commands endpoint.

    Handles slash commands like /devops status
    """
    if not _verify_slack_request():
        return jsonify({'error': 'Invalid signature'}), 401

    # Parse form data
    command = request.form.get('command', '')
    text = request.form.get('text', '')
    user_id = request.form.get('user_id')
    channel_id = request.form.get('channel_id')

    # Combine command and text
    full_text = f"{command.replace('/devops', '')} {text}".strip()
    if not full_text:
        full_text = "help"

    service = get_chatops_service()
    response = service.process_message(
        full_text,
        user_id=user_id,
        channel_id=channel_id,
        platform=ChatPlatform.SLACK
    )

    # Return immediate response
    slack_response = {
        'response_type': 'ephemeral' if response.ephemeral else 'in_channel',
        'text': response.text
    }

    if response.blocks:
        slack_response['blocks'] = response.blocks

    return jsonify(slack_response)


@chatops_bp.route('/slack/interactive', methods=['POST'])
def slack_interactive():
    """
    Slack Interactive Components endpoint.

    Handles button clicks, menu selections, etc.
    """
    if not _verify_slack_request():
        return jsonify({'error': 'Invalid signature'}), 401

    payload = json.loads(request.form.get('payload', '{}'))

    action_type = payload.get('type')
    user_id = payload.get('user', {}).get('id')
    channel_id = payload.get('channel', {}).get('id')

    if action_type == 'block_actions':
        actions = payload.get('actions', [])
        for action in actions:
            action_id = action.get('action_id')
            value = action.get('value')

            # Process action
            service = get_chatops_service()
            response = service.process_message(
                value or action_id,
                user_id=user_id,
                channel_id=channel_id,
                platform=ChatPlatform.SLACK
            )

            return jsonify({
                'response_type': 'ephemeral',
                'text': response.text
            })

    return jsonify({'ok': True})


# ==================== MICROSOFT TEAMS INTEGRATION ====================


def _get_botframework_jwks() -> dict:
    """Fetch (and cache) Bot Framework's JWKS used to verify inbound bot tokens."""
    cached = _TEAMS_JWKS_CACHE.get('jwks')
    if cached and time.time() - cached[0] < _TEAMS_JWKS_TTL:
        return cached[1]

    # Both URLs are hardcoded to Microsoft's Bot Framework endpoint, never
    # caller-influenced — still routed through safe_request for defense in depth.
    doc = safe_request('GET', _BOTFRAMEWORK_OPENID_CONFIG, timeout=10).json()
    jwks = safe_request('GET', doc['jwks_uri'], timeout=10).json()
    _TEAMS_JWKS_CACHE['jwks'] = (time.time(), jwks)
    return jwks


def _verify_teams_request() -> bool:
    """Validate the Bot Framework JWT bearer token on an inbound Teams request.

    Unlike the Slack routes (HMAC signature over the raw body), Teams/Bot
    Framework authenticates via a JWT in the Authorization header, signed by
    Microsoft and audienced to this bot's app ID (TEAMS_APP_ID). Without this
    check, these routes accepted any anonymous POST as a legitimate Teams
    message — dispatched straight into ChatOpsService.process_message().
    """
    app_id = os.environ.get('TEAMS_APP_ID')
    if not app_id:
        # Teams integration isn't configured — never accept unauthenticated bot traffic.
        return False

    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return False
    token = auth_header[len('Bearer '):]

    try:
        from joserfc import jwt
        from joserfc.jwk import KeySet

        jwks = _get_botframework_jwks()
        key_set = KeySet.import_key_set(jwks)
        decoded = jwt.decode(token, key_set)

        registry = jwt.JWTClaimsRegistry(
            iss={'essential': True, 'value': _BOTFRAMEWORK_ISSUER},
            aud={'essential': True, 'value': app_id},
            exp={'essential': True},
        )
        registry.validate(decoded.claims)
        return True
    except Exception as e:
        logger.warning(f"Rejected Teams request with invalid bot token: {e}")
        return False


@chatops_bp.route('/teams/messages', methods=['POST'])
def teams_messages():
    """
    Microsoft Teams Bot Framework endpoint.

    Handles incoming messages from Teams.
    """
    if not _verify_teams_request():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}

    activity_type = data.get('type')

    if activity_type == 'message':
        text = data.get('text', '')
        # Remove bot mention
        text = _remove_teams_mention(text)

        user_id = data.get('from', {}).get('id')
        conversation_id = data.get('conversation', {}).get('id')

        service = get_chatops_service()
        response = service.process_message(
            text,
            user_id=user_id,
            channel_id=conversation_id,
            platform=ChatPlatform.TEAMS
        )

        # Format as Teams response
        teams_response = {
            'type': 'message',
            'text': response.text
        }

        # Add adaptive card if available
        if response.blocks:
            teams_response['attachments'] = [{
                'contentType': 'application/vnd.microsoft.card.adaptive',
                'content': service.format_teams_card(response)
            }]

        return jsonify(teams_response)

    return jsonify({'type': 'message', 'text': 'OK'})


@chatops_bp.route('/teams/commands', methods=['POST'])
def teams_commands():
    """
    Microsoft Teams messaging extension commands.
    """
    if not _verify_teams_request():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}

    command_id = data.get('name')
    if not command_id:
        return jsonify({'error': 'Missing command name'}), 400
    parameters = data.get('parameters', [])

    # Build command text from parameters
    text = command_id
    for param in parameters:
        text += f" {param.get('value', '')}"

    user_id = data.get('from', {}).get('id')

    service = get_chatops_service()
    response = service.process_message(
        text,
        user_id=user_id,
        platform=ChatPlatform.TEAMS
    )

    return jsonify({
        'composeExtension': {
            'type': 'message',
            'text': response.text
        }
    })


# ==================== API ROUTES ====================


@chatops_bp.route('/api/test', methods=['POST'])
@login_required
def api_test_command():
    """API: Test a ChatOps command."""
    data = request.get_json()

    if not data or not data.get('command'):
        return jsonify({'success': False, 'error': 'Command required'}), 400

    service = get_chatops_service()
    # This route is @login_required, so the app identity is known here even
    # though the Slack/Teams webhooks above only carry a platform id.
    response = service.process_message(
        data.get('command'),
        user_id=data.get('user_id', 'test-user'),
        platform=ChatPlatform.SLACK,
        app_user_id=current_user.id
    )

    return jsonify({
        'success': True,
        'response': {
            'text': response.text,
            'ephemeral': response.ephemeral
        }
    })


@chatops_bp.route('/api/commands')
@login_required
def api_list_commands():
    """API: List available commands."""
    service = get_chatops_service()

    unique_commands = {}
    for cmd in service.commands.values():
        unique_commands[cmd.name] = cmd

    return jsonify({
        'success': True,
        'commands': [{
            'name': cmd.name,
            'description': cmd.description,
            'usage': cmd.usage,
            'aliases': cmd.aliases
        } for cmd in sorted(unique_commands.values(), key=lambda c: c.name)]
    })


# ==================== HELPER FUNCTIONS ====================


def _verify_slack_request() -> bool:
    """Validate the HMAC signature Slack signs into every inbound request.

    Fails closed if SLACK_SIGNING_SECRET isn't configured, mirroring
    _verify_teams_request()'s Bot Framework convention: never accept
    unauthenticated bot traffic just because the operator hasn't wired up
    the integration yet.
    """
    slack_signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
    if not slack_signing_secret:
        return False

    timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    signature = request.headers.get('X-Slack-Signature', '')
    return _verify_slack_signature(slack_signing_secret, timestamp, signature, request.get_data())


def _verify_slack_signature(signing_secret: str, timestamp: str, signature: str, body: bytes) -> bool:
    """Verify Slack request signature."""
    if not timestamp or not signature:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def _post_slack_message(channel_id: str, response, ephemeral: bool = False, user_id: str = None):
    """Post a message to Slack."""
    slack_token = os.environ.get('SLACK_BOT_TOKEN')
    if not slack_token:
        return

    import requests

    service = get_chatops_service()

    url = 'https://slack.com/api/chat.postEphemeral' if ephemeral else 'https://slack.com/api/chat.postMessage'

    payload = {
        'channel': channel_id,
        'text': response.text,
        'blocks': service.format_slack_blocks(response)
    }

    if ephemeral and user_id:
        payload['user'] = user_id

    try:
        # ssrf-safe: hardcoded slack.com/api (ChatOps reply path, distinct from any user-configured webhook)
        requests.post(
            url,
            headers={
                'Authorization': f'Bearer {slack_token}',
                'Content-Type': 'application/json'
            },
            json=payload
        )
    except Exception as e:
        logger.error(f"Failed to post Slack message: {e}")


def _remove_teams_mention(text: str) -> str:
    """Remove @mention from Teams message."""
    import re
    # Remove <at>BotName</at> pattern
    return re.sub(r'<at>[^<]+</at>', '', text).strip()
