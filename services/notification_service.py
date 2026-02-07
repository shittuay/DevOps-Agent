"""
Notification Service for DevOps Agent.

Provides integrations for Slack and Microsoft Teams to send alerts,
incident notifications, and status updates.
"""

import json
import logging
import requests
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field

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
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_slack_blocks(self) -> list:
        """Convert notification to Slack Block Kit format."""
        color_map = {
            NotificationPriority.LOW: "#36a64f",
            NotificationPriority.NORMAL: "#2196f3",
            NotificationPriority.HIGH: "#ff9800",
            NotificationPriority.CRITICAL: "#f44336",
        }

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
                action_elements.append({
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": action.get("text", "Action")
                    },
                    "url": action.get("url", "#"),
                    "style": "primary" if action.get("primary") else None
                })
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
        color_map = {
            NotificationPriority.LOW: "good",
            NotificationPriority.NORMAL: "default",
            NotificationPriority.HIGH: "warning",
            NotificationPriority.CRITICAL: "attention",
        }

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

        payload = {
            "blocks": notification.to_slack_blocks(),
            "attachments": [notification.to_slack_attachment()]
        }

        if channel:
            payload["channel"] = channel

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Slack notification sent: {notification.title}")
            return True
        except requests.RequestException as e:
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

        payload = notification.to_teams_card()

        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            logger.info(f"Teams notification sent: {notification.title}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to send Teams notification: {e}")
            return False


class NotificationService:
    """
    Central notification service for managing and sending notifications
    across multiple channels.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.channels: dict[str, NotificationConfig] = {}
        self._slack_client: Optional[SlackClient] = None
        self._teams_client: Optional[TeamsClient] = None

        self._load_config()

    def _load_config(self):
        """Load channel configurations."""
        if "slack" in self.config:
            slack_config = self.config["slack"]
            self.channels["slack"] = NotificationConfig(
                channel=NotificationChannel.SLACK,
                enabled=slack_config.get("enabled", True),
                webhook_url=slack_config.get("webhook_url"),
                api_token=slack_config.get("api_token"),
                default_channel=slack_config.get("default_channel", "#alerts")
            )
            self._slack_client = SlackClient(
                webhook_url=slack_config.get("webhook_url"),
                api_token=slack_config.get("api_token")
            )

        if "teams" in self.config:
            teams_config = self.config["teams"]
            self.channels["teams"] = NotificationConfig(
                channel=NotificationChannel.TEAMS,
                enabled=teams_config.get("enabled", True),
                webhook_url=teams_config.get("webhook_url")
            )
            self._teams_client = TeamsClient(
                webhook_url=teams_config.get("webhook_url")
            )

    def configure_slack(self, webhook_url: str = None, api_token: str = None,
                        default_channel: str = "#alerts") -> None:
        """Configure Slack integration."""
        self.channels["slack"] = NotificationConfig(
            channel=NotificationChannel.SLACK,
            enabled=True,
            webhook_url=webhook_url,
            api_token=api_token,
            default_channel=default_channel
        )
        self._slack_client = SlackClient(webhook_url=webhook_url, api_token=api_token)
        logger.info("Slack notification channel configured")

    def configure_teams(self, webhook_url: str) -> None:
        """Configure Microsoft Teams integration."""
        self.channels["teams"] = NotificationConfig(
            channel=NotificationChannel.TEAMS,
            enabled=True,
            webhook_url=webhook_url
        )
        self._teams_client = TeamsClient(webhook_url=webhook_url)
        logger.info("Teams notification channel configured")

    def send(self, notification: Notification, channels: list[str] = None) -> dict[str, bool]:
        """
        Send notification to specified channels.

        Args:
            notification: The notification to send
            channels: List of channel names to send to (defaults to all enabled)

        Returns:
            Dict mapping channel names to success status
        """
        results = {}
        target_channels = channels or list(self.channels.keys())

        for channel_name in target_channels:
            if channel_name not in self.channels:
                logger.warning(f"Unknown channel: {channel_name}")
                results[channel_name] = False
                continue

            config = self.channels[channel_name]
            if not config.enabled:
                logger.debug(f"Channel {channel_name} is disabled")
                results[channel_name] = False
                continue

            if config.channel == NotificationChannel.SLACK and self._slack_client:
                if config.webhook_url:
                    results[channel_name] = self._slack_client.send_webhook(
                        notification,
                        config.default_channel
                    )
                elif config.api_token:
                    results[channel_name] = self._slack_client.send_api(
                        notification,
                        config.default_channel
                    )
                else:
                    results[channel_name] = False

            elif config.channel == NotificationChannel.TEAMS and self._teams_client:
                results[channel_name] = self._teams_client.send(notification)
            else:
                results[channel_name] = False

        return results

    def send_alert(self, alert_data: dict, channels: list[str] = None) -> dict[str, bool]:
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
                "Time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            }
        )

        if alert_data.get("incident_id"):
            notification.fields["Incident"] = f"#{alert_data['incident_id']}"

        return self.send(notification, channels)

    def send_incident_notification(self, incident_data: dict,
                                   event: str = "created",
                                   channels: list[str] = None) -> dict[str, bool]:
        """Send an incident lifecycle notification."""
        event_titles = {
            "created": "New Incident Created",
            "acknowledged": "Incident Acknowledged",
            "resolved": "Incident Resolved",
            "escalated": "Incident Escalated",
        }

        severity = incident_data.get("severity", "medium")
        priority_map = {
            "low": NotificationPriority.LOW,
            "medium": NotificationPriority.NORMAL,
            "high": NotificationPriority.HIGH,
            "critical": NotificationPriority.CRITICAL,
        }

        notification = Notification(
            title=f"{event_titles.get(event, 'Incident Update')}: #{incident_data.get('id', 'N/A')}",
            message=incident_data.get("title", "Incident notification"),
            priority=priority_map.get(severity, NotificationPriority.NORMAL),
            fields={
                "Status": incident_data.get("status", "unknown").upper(),
                "Severity": severity.upper(),
                "Source": incident_data.get("source", "N/A"),
            }
        )

        if incident_data.get("assigned_to"):
            notification.fields["Assigned To"] = incident_data["assigned_to"]

        if incident_data.get("playbook"):
            notification.fields["Playbook"] = incident_data["playbook"]

        return self.send(notification, channels)

    def send_deployment_notification(self, deployment_data: dict,
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

        return self.send(notification, channels)

    def send_change_notification(self, change_data: dict,
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

        return self.send(notification, channels)

    def send_security_notification(self, findings_data: dict,
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

        return self.send(notification, channels)

    def send_cost_alert(self, cost_data: dict,
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

        return self.send(notification, channels)

    def get_status(self) -> dict:
        """Get the status of all notification channels."""
        return {
            "channels": {
                name: {
                    "type": config.channel.value,
                    "enabled": config.enabled,
                    "configured": bool(config.webhook_url or config.api_token)
                }
                for name, config in self.channels.items()
            },
            "total_configured": sum(
                1 for c in self.channels.values()
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
