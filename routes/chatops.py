"""
ChatOps Routes for DevOps Agent.

Provides endpoints for Slack and Microsoft Teams bot integrations.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required
import logging
import hmac
import hashlib
import json
import os

from services.chatops_service import get_chatops_service, ChatPlatform

logger = logging.getLogger(__name__)

chatops_bp = Blueprint('chatops', __name__, url_prefix='/chatops')


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
    # Verify request signature
    slack_signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
    if slack_signing_secret:
        timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
        signature = request.headers.get('X-Slack-Signature', '')

        if not _verify_slack_signature(slack_signing_secret, timestamp, signature, request.get_data()):
            return jsonify({'error': 'Invalid signature'}), 401

    data = request.get_json()

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
    # Verify request signature
    slack_signing_secret = os.environ.get('SLACK_SIGNING_SECRET')
    if slack_signing_secret:
        timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
        signature = request.headers.get('X-Slack-Signature', '')

        if not _verify_slack_signature(slack_signing_secret, timestamp, signature, request.get_data()):
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


@chatops_bp.route('/teams/messages', methods=['POST'])
def teams_messages():
    """
    Microsoft Teams Bot Framework endpoint.

    Handles incoming messages from Teams.
    """
    data = request.get_json()

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
    data = request.get_json()

    command_id = data.get('name')
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
    response = service.process_message(
        data.get('command'),
        user_id=data.get('user_id', 'test-user'),
        platform=ChatPlatform.SLACK
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
