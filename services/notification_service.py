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
class NotificationConfig:
    """Configuration for a notification channel."""
    channel: NotificationChannel
    enabled: bool = True
    webhook_url: Optional[str] = None
    api_token: Optional[str] = None
    default_channel: Optional[str] = None
    metadata: dict = field(default_factory=dict)


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


class NotificationService:
    """
    Central notification service for managing and sending notifications
    across multiple channels.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        # Per-user channel configs, keyed by user_id
        self._user_channels: dict[int, dict[str, NotificationConfig]] = {}
        self._user_slack_clients: dict[int, SlackClient] = {}
        self._user_teams_clients: dict[int, TeamsClient] = {}

    def _get_user_channels(self, user_id: int) -> dict[str, NotificationConfig]:
        """Get or initialize per-user channel configs."""
        if user_id not in self._user_channels:
            self._user_channels[user_id] = {}
        return self._user_channels[user_id]

    def configure_slack(self, user_id: int, webhook_url: str = None, api_token: str = None,
                        default_channel: str = "#alerts") -> None:
        """Configure Slack integration for a user."""
        user_channels = self._get_user_channels(user_id)
        user_channels["slack"] = NotificationConfig(
            channel=NotificationChannel.SLACK,
            enabled=True,
            webhook_url=webhook_url,
            api_token=api_token,
            default_channel=default_channel
        )
        self._user_slack_clients[user_id] = SlackClient(webhook_url=webhook_url, api_token=api_token)
        logger.info("Slack notification channel configured")

    def configure_teams(self, user_id: int, webhook_url: str) -> None:
        """Configure Microsoft Teams integration for a user."""
        user_channels = self._get_user_channels(user_id)
        user_channels["teams"] = NotificationConfig(
            channel=NotificationChannel.TEAMS,
            enabled=True,
            webhook_url=webhook_url
        )
        self._user_teams_clients[user_id] = TeamsClient(webhook_url=webhook_url)
        logger.info("Teams notification channel configured")

    def send(self, user_id: int, notification: Notification, channels: list[str] = None) -> dict[str, bool]:
        """
        Send notification to specified channels for a user.

        Args:
            user_id: The user ID
            notification: The notification to send
            channels: List of channel names to send to (defaults to all enabled)

        Returns:
            Dict mapping channel names to success status
        """
        user_channels = self._get_user_channels(user_id)
        results = {}
        target_channels = channels or list(user_channels.keys())

        for channel_name in target_channels:
            if channel_name not in user_channels:
                logger.warning(f"Unknown channel: {channel_name}")
                results[channel_name] = False
                continue

            config = user_channels[channel_name]
            if not config.enabled:
                logger.debug(f"Channel {channel_name} is disabled")
                results[channel_name] = False
                continue

            slack_client = self._user_slack_clients.get(user_id)
            teams_client = self._user_teams_clients.get(user_id)

            if config.channel == NotificationChannel.SLACK and slack_client:
                if config.webhook_url:
                    results[channel_name] = slack_client.send_webhook(
                        notification,
                        config.default_channel
                    )
                elif config.api_token:
                    results[channel_name] = slack_client.send_api(
                        notification,
                        config.default_channel
                    )
                else:
                    results[channel_name] = False

            elif config.channel == NotificationChannel.TEAMS and teams_client:
                results[channel_name] = teams_client.send(notification)
            else:
                results[channel_name] = False

        return results

    def send_alert(self, user_id: int, alert_data: dict, channels: list[str] = None) -> dict[str, bool]:
        """Send an alert notification."""
        severity = alert_data.get("severity", "medium")
        priority_map = {
            "low": NotificationPriority.LOW,
            "medium": NotificationPriority.NORMAL,
            "high": NotificationPriority.HIGH,
            "critical": NotificationPriority.CRITICAL,
        }

        notification = Notification(
            title=f"Alert: {alert_data.get('rule_name', 'Unknown')}",
            message=alert_data.get("message", "Alert triggered"),
            priority=priority_map.get(severity, NotificationPriority.NORMAL),
            fields={
                "Severity": severity.upper(),
                "Value": str(alert_data.get("value", "N/A")),
                "Threshold": str(alert_data.get("threshold", "N/A")),
                "Time": utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )

        return self.send(user_id, notification, channels)

    def send_deployment_notification(self, user_id: int, deployment_data: dict,
                                     status: str = "started",
                                     channels: list[str] = None) -> dict[str, bool]:
        """Send a deployment notification."""
        status_priorities = {
            "started": NotificationPriority.NORMAL,
            "completed": NotificationPriority.LOW,
            "failed": NotificationPriority.CRITICAL,
            "rolled_back": NotificationPriority.HIGH,
        }

        notification = Notification(
            title=f"Deployment {status.title()}: {deployment_data.get('name', 'Unknown')}",
            message=deployment_data.get("message", f"Deployment {status}"),
            priority=status_priorities.get(status, NotificationPriority.NORMAL),
            fields={
                "Environment": deployment_data.get("environment", "N/A"),
                "Version": deployment_data.get("version", "N/A"),
                "Deployed By": deployment_data.get("deployed_by", "N/A"),
            }
        )

        if deployment_data.get("url"):
            notification.actions.append({
                "text": "View Deployment",
                "url": deployment_data["url"],
                "primary": True
            })

        return self.send(user_id, notification, channels)

    def send_change_notification(self, user_id: int, change_data: dict,
                                    event: str = "created",
                                    channels: list[str] = None) -> dict[str, bool]:
        """Send a change governance notification."""
        event_config = {
            "created": ("Change Request Created", NotificationPriority.NORMAL),
            "approved": ("Change Request Approved", NotificationPriority.NORMAL),
            "rejected": ("Change Request Rejected", NotificationPriority.HIGH),
            "executed": ("Change Executed", NotificationPriority.NORMAL),
            "failed": ("Change Execution Failed", NotificationPriority.CRITICAL),
            "rollback": ("Change Rolled Back", NotificationPriority.HIGH),
        }

        title, priority = event_config.get(event, ("Change Update", NotificationPriority.NORMAL))
        risk = change_data.get("risk_level", "unknown")
        if risk == "high":
            priority = NotificationPriority.HIGH

        notification = Notification(
            title=f"{title}: #{change_data.get('id', 'N/A')}",
            message=change_data.get("title", "Infrastructure change"),
            priority=priority,
            fields={
                "Action": change_data.get("action_type", "N/A"),
                "Resource": f"{change_data.get('resource_type', '')} {change_data.get('resource_name', '')}".strip(),
                "Risk": risk.upper(),
                "Status": event.upper(),
            }
        )

        if change_data.get("approval_comment"):
            notification.fields["Comment"] = change_data["approval_comment"]

        return self.send(user_id, notification, channels)

    def send_security_notification(self, user_id: int, findings_data: dict,
                                    channels: list[str] = None) -> dict[str, bool]:
        """Send security scan results notification."""
        critical = findings_data.get("critical", 0)
        high = findings_data.get("high", 0)
        total = findings_data.get("total", 0)

        if critical > 0:
            priority = NotificationPriority.CRITICAL
        elif high > 0:
            priority = NotificationPriority.HIGH
        else:
            priority = NotificationPriority.NORMAL

        notification = Notification(
            title=f"Security Scan: {total} findings",
            message=f"Security scan completed with {critical} critical, {high} high severity findings",
            priority=priority,
            fields={
                "Critical": str(critical),
                "High": str(high),
                "Medium": str(findings_data.get("medium", 0)),
                "Low": str(findings_data.get("low", 0)),
                "Total": str(total),
            }
        )

        return self.send(user_id, notification, channels)

    def send_cost_alert(self, user_id: int, cost_data: dict,
                        channels: list[str] = None) -> dict[str, bool]:
        """Send cost threshold alert."""
        notification = Notification(
            title=f"Cost Alert: ${cost_data.get('amount', 0):.2f}",
            message=cost_data.get("message", "Cost threshold exceeded"),
            priority=NotificationPriority.HIGH,
            fields={
                "Current Spend": f"${cost_data.get('amount', 0):.2f}",
                "Threshold": f"${cost_data.get('threshold', 0):.2f}",
                "Period": cost_data.get("period", "Monthly"),
                "Top Service": cost_data.get("top_service", "N/A"),
            }
        )

        return self.send(user_id, notification, channels)

    def get_status(self, user_id: int) -> dict:
        """Get the status of all notification channels for a user."""
        user_channels = self._get_user_channels(user_id)
        return {
            "channels": {
                name: {
                    "type": config.channel.value,
                    "enabled": config.enabled,
                    "configured": bool(config.webhook_url or config.api_token)
                }
                for name, config in user_channels.items()
            },
            "total_configured": sum(
                1 for c in user_channels.values()
                if c.webhook_url or c.api_token
            )
        }


# Global notification service instance
_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get or create the global notification service instance."""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


def configure_notifications(config: dict) -> NotificationService:
    """Configure and return the notification service."""
    global _notification_service
    _notification_service = NotificationService(config)
    return _notification_service


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

