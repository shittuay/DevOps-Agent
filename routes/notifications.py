"""
Notification Routes for DevOps Agent.

Provides API endpoints for managing notification channel configurations
and testing notifications.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import logging

from services.notification_service import (
    get_notification_service,
    Notification,
    NotificationPriority
)

logger = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications', __name__, url_prefix='/notifications')


def json_response(data: dict, status: int = 200):
    """Create a JSON response."""
    return jsonify(data), status


@notifications_bp.route('/')
@login_required
def notifications_settings():
    """Render the notifications settings page."""
    service = get_notification_service()
    return render_template(
        'notifications/settings.html',
        status=service.get_status(current_user.id)
    )


# API Endpoints

@notifications_bp.route('/api/status')
@login_required
def api_status():
    """Get notification service status."""
    service = get_notification_service()
    return json_response(service.get_status(current_user.id))


@notifications_bp.route('/api/configure/slack', methods=['POST'])
@login_required
def api_configure_slack():
    """Configure Slack integration."""
    data = request.get_json()

    if not data:
        return json_response({"error": "No data provided"}, 400)

    webhook_url = data.get("webhook_url")
    api_token = data.get("api_token")
    default_channel = data.get("default_channel", "#alerts")

    if not webhook_url and not api_token:
        return json_response({"error": "Either webhook_url or api_token required"}, 400)

    service = get_notification_service()
    service.configure_slack(
        current_user.id,
        webhook_url=webhook_url,
        api_token=api_token,
        default_channel=default_channel
    )

    return json_response({"success": True, "message": "Slack configured"})


@notifications_bp.route('/api/configure/teams', methods=['POST'])
@login_required
def api_configure_teams():
    """Configure Microsoft Teams integration."""
    data = request.get_json()

    if not data:
        return json_response({"error": "No data provided"}, 400)

    webhook_url = data.get("webhook_url")
    if not webhook_url:
        return json_response({"error": "webhook_url required"}, 400)

    service = get_notification_service()
    service.configure_teams(current_user.id, webhook_url=webhook_url)

    return json_response({"success": True, "message": "Teams configured"})


@notifications_bp.route('/api/test/<channel>', methods=['POST'])
@login_required
def api_test_notification(channel: str):
    """Send a test notification to a channel."""
    service = get_notification_service()

    user_channels = service._get_user_channels(current_user.id)
    if channel not in user_channels:
        return json_response({"error": f"Channel {channel} not configured"}, 404)

    notification = Notification(
        title="Test Notification",
        message=f"This is a test notification from DevOps Agent sent by {current_user.email}",
        priority=NotificationPriority.NORMAL,
        fields={
            "Type": "Test",
            "Sender": current_user.email,
            "Channel": channel.title()
        },
        actions=[
            {"text": "View Dashboard", "url": "/dashboard", "primary": True}
        ]
    )

    results = service.send(current_user.id, notification, channels=[channel])
    success = results.get(channel, False)

    if success:
        return json_response({"success": True, "message": f"Test notification sent to {channel}"})
    else:
        return json_response({"error": f"Failed to send test notification to {channel}"}, 500)


@notifications_bp.route('/api/send', methods=['POST'])
@login_required
def api_send_notification():
    """Send a custom notification."""
    data = request.get_json()

    if not data:
        return json_response({"error": "No data provided"}, 400)

    title = data.get("title")
    message = data.get("message")
    channels = data.get("channels")

    if not title or not message:
        return json_response({"error": "title and message required"}, 400)

    priority_map = {
        "low": NotificationPriority.LOW,
        "normal": NotificationPriority.NORMAL,
        "high": NotificationPriority.HIGH,
        "critical": NotificationPriority.CRITICAL,
    }

    notification = Notification(
        title=title,
        message=message,
        priority=priority_map.get(data.get("priority", "normal"), NotificationPriority.NORMAL),
        fields=data.get("fields", {}),
        actions=data.get("actions", [])
    )

    service = get_notification_service()
    results = service.send(current_user.id, notification, channels=channels)

    return json_response({
        "success": any(results.values()),
        "results": results
    })
