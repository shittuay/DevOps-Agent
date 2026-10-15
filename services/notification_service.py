"""
Notification Service for DevOps Agent.

Provides integrations for Slack and Microsoft Teams to send cost, security
and change notifications.
"""

import json
import logging
import os
import threading
import requests
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field

from src.utils.network_safety import assert_safe_external_webhook_url, safe_request, UnsafeUrlError
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Supported notification channels."""
    SLACK = "slack"
    TEAMS = "teams"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Notification:
    """A notification to be sent."""
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    fields: dict = field(default_factory=dict)
    actions: list = field(default_factory=list)
    color: Optional[str] = None
    timestamp: datetime = field(default_factory=utcnow)

    def to_slack_blocks(self) -> list:
        """Convert notification to Slack Block Kit format."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": self.title,
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": self.message
                }
            }
        ]

        if self.fields:
            field_blocks = []
            for key, value in self.fields.items():
                field_blocks.append({
                    "type": "mrkdwn",
                    "text": f"*{key}:*\n{value}"
                })

            for i in range(0, len(field_blocks), 2):
                blocks.append({
                    "type": "section",
                    "fields": field_blocks[i:i+2]
                })

        if self.actions:
            action_elements = []
            for action in self.actions:
                btn = {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": action.get("text", "Action")
                    },
                    "url": action.get("url", "#"),
                }
                if action.get("primary"):
                    btn["style"] = "primary"
                action_elements.append(btn)
            blocks.append({
                "type": "actions",
                "elements": action_elements
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Sent at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                }
            ]
        })

        return blocks

    def to_slack_attachment(self) -> dict:
        """Convert notification to Slack attachment format."""
        color_map = {
            NotificationPriority.LOW: "good",
            NotificationPriority.NORMAL: "#2196f3",
            NotificationPriority.HIGH: "warning",
            NotificationPriority.CRITICAL: "danger",
        }

        attachment = {
            "color": self.color or color_map.get(self.priority, "#2196f3"),
            "title": self.title,
            "text": self.message,
            "ts": int(self.timestamp.timestamp()),
            "mrkdwn_in": ["text", "fields"]
        }

        if self.fields:
            attachment["fields"] = [
                {"title": k, "value": str(v), "short": True}
                for k, v in self.fields.items()
            ]

        if self.actions:
            attachment["actions"] = [
                {
                    "type": "button",
                    "text": action.get("text", "Action"),
                    "url": action.get("url", "#")
                }
                for action in self.actions
            ]

        return attachment

    def to_teams_card(self) -> dict:
        """Convert notification to Microsoft Teams Adaptive Card format."""
        card = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": self._get_teams_color(),
            "summary": self.title,
            "sections": [
                {
                    "activityTitle": self.title,
                    "text": self.message,
                    "markdown": True
                }
            ]
        }

        if self.fields:
            facts = [{"name": k, "value": str(v)} for k, v in self.fields.items()]
            card["sections"][0]["facts"] = facts

        if self.actions:
            card["potentialAction"] = [
                {
                    "@type": "OpenUri",
                    "name": action.get("text", "Action"),
                    "targets": [{"os": "default", "uri": action.get("url", "#")}]
                }
                for action in self.actions
            ]

        return card

    def _get_teams_color(self) -> str:
        """Get Teams theme color based on priority."""
        color_map = {
            NotificationPriority.LOW: "00FF00",
            NotificationPriority.NORMAL: "0078D7",
            NotificationPriority.HIGH: "FFA500",
            NotificationPriority.CRITICAL: "FF0000",
        }
        return self.color.lstrip("#") if self.color else color_map.get(self.priority, "0078D7")


class SlackClient:
    """Slack notification client."""

    def __init__(self, webhook_url: str = None, api_token: str = None):
        self.webhook_url = webhook_url
        self.api_token = api_token

    def send_webhook(self, notification: Notification, channel: str = None) -> bool:
        """Send notification via webhook."""
        if not self.webhook_url:
            logger.error("Slack webhook URL not configured")
            return False

        try:
            assert_safe_external_webhook_url(self.webhook_url)
        except UnsafeUrlError as e:
            logger.error(f"Blocked Slack webhook to unsafe URL: {e}")
            return False

        # Use blocks-only payload. Slack requires a top-level `text` as a
        # notification fallback when blocks are present. Sending `attachments`
        # alongside `blocks` can cause silent delivery failures.
        payload = {
            "text": notification.title,
            "blocks": notification.to_slack_blocks(),
        }

        if channel:
            payload["channel"] = channel

        try:
            response = safe_request(
                'POST',
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
                validator=assert_safe_external_webhook_url,
            )
            response.raise_for_status()
            # Slack returns HTTP 200 for both success ("ok") and some payload
            # errors ("invalid_payload", "no_text", etc.). Always check the body.
            if response.text != 'ok':
                logger.error(f"Slack webhook error: {response.text}")
                return False
            logger.info(f"Slack notification sent: {notification.title}")
            return True
        except (requests.RequestException, UnsafeUrlError) as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    def send_api(self, notification: Notification, channel: str) -> bool:
        """Send notification via Slack API."""
        if not self.api_token:
            logger.error("Slack API token not configured")
            return False

        payload = {
            "channel": channel,
            "blocks": notification.to_slack_blocks(),
            "attachments": [notification.to_slack_attachment()]
        }

        try:
            # ssrf-safe: hardcoded slack.com/api (Slack API token path, distinct from the user-configured webhook_url path above)
            response = requests.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json"
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                logger.info(f"Slack notification sent via API: {notification.title}")
                return True
            else:
                logger.error(f"Slack API error: {data.get('error')}")
                return False
        except requests.RequestException as e:
            logger.error(f"Failed to send Slack notification via API: {e}")
            return False


class TeamsClient:
    """Microsoft Teams notification client."""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url

    def send(self, notification: Notification) -> bool:
        """Send notification to Teams."""
        if not self.webhook_url:
            logger.error("Teams webhook URL not configured")
            return False

        try:
            assert_safe_external_webhook_url(self.webhook_url)
        except UnsafeUrlError as e:
            logger.error(f"Blocked Teams webhook to unsafe URL: {e}")
            return False

        payload = notification.to_teams_card()

        try:
            response = safe_request(
                'POST',
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
                validator=assert_safe_external_webhook_url,
            )
            response.raise_for_status()
            logger.info(f"Teams notification sent: {notification.title}")
            return True
        except (requests.RequestException, UnsafeUrlError) as e:
            logger.error(f"Failed to send Teams notification: {e}")
            return False


_BASE_URL = os.environ.get('BASE_URL', 'https://devopsagent.io')


class _Proxy:
    """Lazy wrapper — defers flask.current_app resolution to call time so
    unittest.mock.patch can replace the module-level `current_app` name safely."""

    def _get_current_object(self):
        import flask as _flask
        return _flask.current_app._get_current_object()

    def app_context(self):
        import flask as _flask
        return _flask.current_app.app_context()


# Module-level references replaced by tests via patch().
# These are plain Python objects (not Werkzeug LocalProxy instances) so that
# unittest.mock.patch can inspect them safely outside an app context.
current_app = _Proxy()

try:
    from models import UserNotificationChannel  # noqa: E402
except ImportError:
    UserNotificationChannel = None  # type: ignore


def _send_async(user_id: int, event_type: str, notification: 'Notification') -> None:
    """Load matching channels from DB and send notification in a daemon thread.

    event_type must be one of: 'cost', 'security', 'changes', 'alerts'.
    Requires Flask app context at call site. Silently no-ops if no app context.
    """
    import services.notification_service as _self
    _current_app = _self.current_app
    _UserNotificationChannel = _self.UserNotificationChannel
    if _UserNotificationChannel is None:
        logger.debug("UserNotificationChannel not available — skipping notification")
        return

    try:
        flask_app = _current_app._get_current_object()
    except RuntimeError:
        logger.debug("_send_async called outside app context — skipping")
        return

    flag_map = {
        'cost':      _UserNotificationChannel.notify_cost,
        'security':  _UserNotificationChannel.notify_security,
        'changes':   _UserNotificationChannel.notify_changes,
        'alerts':    _UserNotificationChannel.notify_alerts,
    }
    flag_col = flag_map.get(event_type)
    if flag_col is None:
        logger.warning(f"_send_async: unknown event_type '{event_type}'")
        return

    def _run():
        with flask_app.app_context():
            try:
                channels = (
                    _UserNotificationChannel.query
                    .filter_by(user_id=user_id, is_active=True)
                    .filter(flag_col == True)
                    .all()
                )
                for ch in channels:
                    if ch.channel_type == 'slack':
                        SlackClient(webhook_url=ch.webhook_url).send_webhook(notification)
                    elif ch.channel_type == 'teams':
                        TeamsClient(webhook_url=ch.webhook_url).send(notification)
            except Exception:
                logger.exception(f"Error sending {event_type} notification for user {user_id}")

    threading.Thread(target=_run, daemon=True).start()


def notify_security(user_id: int, results: dict, base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for security scan results. Skips if no critical/high findings."""
    if results.get('critical', 0) == 0 and results.get('high', 0) == 0:
        return
    critical = results.get('critical', 0)
    high = results.get('high', 0)
    priority = NotificationPriority.CRITICAL if critical > 0 else NotificationPriority.HIGH
    notification = Notification(
        title=f"Security Scan: {results.get('total', 0)} findings",
        message=f"Security scan found {critical} critical and {high} high severity issues that need attention.",
        priority=priority,
        fields={
            'Critical': str(critical),
            'High':     str(high),
            'Medium':   str(results.get('medium', 0)),
            'Low':      str(results.get('low', 0)),
        },
        actions=[{
            'text': 'View Findings',
            'url':  f"{base_url}/dashboard",
            'primary': True,
        }],
    )
    _send_async(user_id, 'security', notification)


def notify_cost(user_id: int, new_count: int, total_savings: float,
                base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for new cost recommendations. Skips when new_count == 0."""
    if new_count == 0:
        return
    notification = Notification(
        title=f"Cost Alert: {new_count} new recommendation{'s' if new_count > 1 else ''}",
        message=f"DevOps Agent found {new_count} new cost optimization opportunities totalling ${total_savings:.2f}/month in potential savings.",
        priority=NotificationPriority.NORMAL,
        fields={
            'New Recommendations': str(new_count),
            'Potential Savings':   f"${total_savings:.2f}/mo",
        },
        actions=[{
            'text': 'View Recommendations',
            'url':  f"{base_url}/dashboard",
            'primary': True,
        }],
    )
    _send_async(user_id, 'cost', notification)


def notify_changes(user_id: int, rec_count: int, base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for new proactive recommendations. Skips when rec_count == 0."""
    if rec_count == 0:
        return
    notification = Notification(
        title=f"Infrastructure Analysis: {rec_count} new finding{'s' if rec_count > 1 else ''}",
        message=f"Proactive analysis found {rec_count} new infrastructure recommendation{'s' if rec_count > 1 else ''} across observability, governance, and optimization.",
        priority=NotificationPriority.NORMAL,
        fields={'New Findings': str(rec_count)},
        actions=[{
            'text': 'View Analysis',
            'url':  f"{base_url}/dashboard",
            'primary': True,
        }],
    )
    _send_async(user_id, 'changes', notification)



_CHANGE_EVENTS = {
    'created': ('Change request created', NotificationPriority.NORMAL),
    'approved': ('Change request approved', NotificationPriority.NORMAL),
    'rejected': ('Change request rejected', NotificationPriority.HIGH),
    'executed': ('Change executed', NotificationPriority.NORMAL),
    'failed': ('Change failed', NotificationPriority.CRITICAL),
    'rollback': ('Change rolled back', NotificationPriority.HIGH),
}


def notify_change_event(user_id: int, change: dict, event: str, base_url: str = _BASE_URL) -> None:
    """Tell the user's saved channels about a change request moving (Settings > Notifications).

    Used to go through an in-memory per-process store that only the removed
    /notifications page wrote to, so these were never delivered.
    """
    title, priority = _CHANGE_EVENTS.get(event, ('Change updated', NotificationPriority.NORMAL))
    risk = str(change.get('risk_level') or 'unknown')
    if risk == 'high' and priority == NotificationPriority.NORMAL:
        priority = NotificationPriority.HIGH
    fields = {
        'Action': str(change.get('action_type') or 'N/A'),
        'Resource': f"{change.get('resource_type') or ''} {change.get('resource_name') or ''}".strip() or 'N/A',
        'Risk': risk.upper(),
    }
    if change.get('approval_comment'):
        fields['Comment'] = str(change['approval_comment'])[:300]
    notification = Notification(
        title=f"{title}: #{change.get('id', '')}",
        message=str(change.get('title') or 'Infrastructure change'),
        priority=priority,
        fields=fields,
        actions=[{'text': 'View change history', 'url': f'{base_url}/changes', 'primary': True}],
    )
    _send_async(user_id, 'changes', notification)
