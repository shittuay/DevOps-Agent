"""
ChatOps Service for DevOps Agent.

Provides interactive bot commands for Slack and Microsoft Teams,
allowing users to query incidents, trigger actions, and get status updates.
"""

import logging
import re
from datetime import datetime
from typing import Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


_UNLINKED_ACCOUNT_MESSAGE = (
    "This command needs to know which DevOps Agent account you are, and this "
    "chat identity is not linked to one yet. Slack/Teams user ids are not "
    "application user ids, so there is nothing safe to look up. Run the command "
    "from the web UI, or link your chat account from Settings."
)


class _UnresolvedAppUser(Exception):
    """Raised when a per-user command cannot determine the app `User.id`.

    Deliberately not a fallback to the chat platform id: per-user state in the
    incident engine is keyed on `User.id`, so guessing would either read an
    empty namespace or, worse, somebody else's.
    """


class ChatPlatform(Enum):
    """Supported chat platforms."""
    SLACK = "slack"
    TEAMS = "teams"


@dataclass
class ChatCommand:
    """A registered chat command."""
    name: str
    description: str
    usage: str
    handler: Callable
    aliases: list[str] = field(default_factory=list)
    requires_auth: bool = True


@dataclass
class ChatResponse:
    """Response to send back to chat platform."""
    text: str
    blocks: Optional[list] = None  # Slack blocks or Teams cards
    attachments: Optional[list] = None
    ephemeral: bool = False  # Only visible to command issuer


class ChatOpsService:
    """
    Interactive ChatOps service for Slack and Teams.

    Features:
    - Natural language command parsing
    - Incident queries and management
    - Status checks and health monitoring
    - Deployment and action triggers
    """

    def __init__(self):
        self.commands: dict[str, ChatCommand] = {}
        self.command_prefix = "/"
        self._register_default_commands()

    def _register_default_commands(self):
        """Register built-in commands."""

        self.register_command(ChatCommand(
            name="help",
            description="Show available commands",
            usage="/help [command]",
            handler=self._cmd_help,
            aliases=["h", "?"],
            requires_auth=False
        ))

        self.register_command(ChatCommand(
            name="status",
            description="Get system status overview",
            usage="/status",
            handler=self._cmd_status,
            aliases=["s"]
        ))

        self.register_command(ChatCommand(
            name="incidents",
            description="List recent incidents",
            usage="/incidents [status] [limit]",
            handler=self._cmd_incidents,
            aliases=["inc", "i"]
        ))

        self.register_command(ChatCommand(
            name="incident",
            description="Get incident details",
            usage="/incident <id>",
            handler=self._cmd_incident_detail,
            aliases=["id"]
        ))

        self.register_command(ChatCommand(
            name="ack",
            description="Acknowledge an incident",
            usage="/ack <incident_id>",
            handler=self._cmd_acknowledge,
            aliases=["acknowledge"]
        ))

        self.register_command(ChatCommand(
            name="resolve",
            description="Resolve an incident",
            usage="/resolve <incident_id> [resolution note]",
            handler=self._cmd_resolve,
            aliases=["res"]
        ))

        self.register_command(ChatCommand(
            name="alerts",
            description="List active alerts",
            usage="/alerts [severity]",
            handler=self._cmd_alerts,
            aliases=["a"]
        ))

        self.register_command(ChatCommand(
            name="playbooks",
            description="List available playbooks",
            usage="/playbooks",
            handler=self._cmd_playbooks,
            aliases=["pb"]
        ))

        self.register_command(ChatCommand(
            name="execute",
            description="Execute a playbook for an incident",
            usage="/execute <incident_id> [playbook_id]",
            handler=self._cmd_execute,
            aliases=["exec", "run"]
        ))

        self.register_command(ChatCommand(
            name="analyze",
            description="Run root cause analysis on an incident",
            usage="/analyze <incident_id>",
            handler=self._cmd_analyze,
            aliases=["rca"]
        ))

        self.register_command(ChatCommand(
            name="metrics",
            description="Get current metrics summary",
            usage="/metrics [service]",
            handler=self._cmd_metrics,
            aliases=["m"]
        ))

        self.register_command(ChatCommand(
            name="deployments",
            description="List recent deployments",
            usage="/deployments [environment]",
            handler=self._cmd_deployments,
            aliases=["deploy", "d"]
        ))

        self.register_command(ChatCommand(
            name="oncall",
            description="Show who's on call",
            usage="/oncall [team]",
            handler=self._cmd_oncall,
            aliases=["oc"]
        ))

    def register_command(self, command: ChatCommand):
        """Register a chat command."""
        self.commands[command.name] = command
        for alias in command.aliases:
            self.commands[alias] = command

    def parse_command(self, text: str) -> tuple[Optional[str], list[str]]:
        """Parse command and arguments from text."""
        text = text.strip()

        # Remove command prefix if present
        if text.startswith(self.command_prefix):
            text = text[len(self.command_prefix):]

        # Handle @ mentions (for Slack)
        text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

        parts = text.split()
        if not parts:
            return None, []

        command = parts[0].lower()
        args = parts[1:]

        return command, args

    def process_message(self, text: str, user_id: str = None, channel_id: str = None,
                        platform: ChatPlatform = ChatPlatform.SLACK,
                        app_user_id: int = None) -> ChatResponse:
        """Process an incoming message and return response.

        `user_id` is the *chat platform* identity (a Slack/Teams id such as
        "U01ABC123"). `app_user_id` is this application's `User.id`. They are
        NOT interchangeable: the incident engine and monitoring service key all
        per-user state on `User.id`, so passing a platform id through would read
        another user's namespace or none at all. Commands that need per-user
        data resolve it through `_require_app_user()` and refuse politely when
        the caller could not supply one.
        """

        command_name, args = self.parse_command(text)

        if not command_name:
            return ChatResponse(
                text="I didn't understand that. Try `/help` for available commands."
            )

        command = self.commands.get(command_name)

        if not command:
            # Try to find similar commands
            similar = [c for c in self.commands.keys() if command_name in c or c in command_name]
            if similar:
                return ChatResponse(
                    text=f"Unknown command `{command_name}`. Did you mean: {', '.join(f'`{s}`' for s in similar[:3])}?"
                )
            return ChatResponse(
                text=f"Unknown command `{command_name}`. Try `/help` for available commands."
            )

        try:
            response = command.handler(args, user_id=user_id, channel_id=channel_id,
                                       platform=platform, app_user_id=app_user_id)
            return response
        except _UnresolvedAppUser:
            return ChatResponse(text=_UNLINKED_ACCOUNT_MESSAGE)
        except Exception as e:
            logger.error(f"Command error: {e}")
            return ChatResponse(
                text=f"Error executing command: {str(e)}"
            )

    @staticmethod
    def _require_app_user(kwargs: dict) -> int:
        """Return the calling app user's id, or refuse.

        Raises `_UnresolvedAppUser` when the request carried no application
        identity. Every caller of a per-user engine method must go through
        this rather than falling back to the chat platform id.
        """
        app_user_id = kwargs.get('app_user_id')
        if isinstance(app_user_id, int):
            return app_user_id
        raise _UnresolvedAppUser()

    # Command Handlers

    def _cmd_help(self, args: list, **kwargs) -> ChatResponse:
        """Show help information."""
        if args:
            cmd_name = args[0].lower()
            command = self.commands.get(cmd_name)
            if command:
                return ChatResponse(
                    text=f"*{command.name}*\n{command.description}\n`{command.usage}`"
                )
            return ChatResponse(text=f"Unknown command: {cmd_name}")

        # List all unique commands
        unique_commands = {}
        for cmd in self.commands.values():
            unique_commands[cmd.name] = cmd

        lines = ["*Available Commands:*\n"]
        for name, cmd in sorted(unique_commands.items()):
            aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"`{cmd.usage}`{aliases}\n  {cmd.description}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_status(self, args: list, **kwargs) -> ChatResponse:
        """Get system status."""
        from services.incident_response import get_incident_engine
        from services.proactive_monitoring import get_monitoring_service

        app_user_id = self._require_app_user(kwargs)
        engine = get_incident_engine()
        monitoring = get_monitoring_service()

        stats = engine.get_stats(app_user_id)
        mon_status = monitoring.get_status(app_user_id)

        active_incidents = stats.get('active', 0)
        critical = stats.get('by_severity', {}).get('critical', 0)

        # Determine overall health
        if critical > 0:
            health = "🔴 Critical"
        elif active_incidents > 0:
            health = "🟡 Warning"
        else:
            health = "🟢 Healthy"

        text = f"""*System Status*

{health}

📊 *Incidents*
• Active: {active_incidents}
• Critical: {critical}
• Resolved (24h): {stats.get('resolved_last_24h', 0)}

📡 *Monitoring*
• Status: {'Running' if mon_status.get('running') else 'Stopped'}
• Active Rules: {mon_status.get('active_rules', 0)}
• Active Alerts: {mon_status.get('alerts_count', 0)}
"""
        return ChatResponse(text=text)

    def _cmd_incidents(self, args: list, **kwargs) -> ChatResponse:
        """List incidents."""
        from services.incident_response import get_incident_engine, IncidentStatus, IncidentSeverity

        app_user_id = self._require_app_user(kwargs)
        engine = get_incident_engine()

        status_filter = None
        limit = 5

        for arg in args:
            if arg.isdigit():
                limit = min(int(arg), 10)
            else:
                try:
                    status_filter = IncidentStatus(arg.lower())
                except ValueError:
                    pass

        incidents = engine.list_incidents(app_user_id, status=status_filter, limit=limit)

        if not incidents:
            return ChatResponse(text="No incidents found.")

        severity_emoji = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🔵',
            'info': '⚪'
        }

        lines = ["*Recent Incidents:*\n"]
        for inc in incidents:
            emoji = severity_emoji.get(inc.severity.value, '⚪')
            lines.append(f"{emoji} `{inc.id}` [{inc.status.value}] {inc.title}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_incident_detail(self, args: list, **kwargs) -> ChatResponse:
        """Get incident details."""
        if not args:
            return ChatResponse(text="Usage: `/incident <id>`")

        from services.incident_response import get_incident_engine

        app_user_id = self._require_app_user(kwargs)
        engine = get_incident_engine()
        incident = engine.get_incident(app_user_id, args[0])

        if not incident:
            return ChatResponse(text=f"Incident `{args[0]}` not found.")

        text = f"""*Incident {incident.id}*

*Title:* {incident.title}
*Severity:* {incident.severity.value.upper()}
*Status:* {incident.status.value}
*Source:* {incident.source}

*Description:*
{incident.description[:500]}{'...' if len(incident.description) > 500 else ''}

*Triggered:* {incident.triggered_at.strftime('%Y-%m-%d %H:%M UTC')}
{'*Assigned:* ' + incident.assigned_to if incident.assigned_to else ''}

*Actions:* `/ack {incident.id}` | `/resolve {incident.id}` | `/analyze {incident.id}`
"""
        return ChatResponse(text=text)

    def _cmd_acknowledge(self, args: list, user_id: str = None, **kwargs) -> ChatResponse:
        """Acknowledge an incident."""
        if not args:
            return ChatResponse(text="Usage: `/ack <incident_id>`")

        from services.incident_response import get_incident_engine

        engine = get_incident_engine()
        app_user_id = self._require_app_user(kwargs)
        result = engine.acknowledge_incident(app_user_id, args[0], user_id or "chatops")

        if result.get('success'):
            return ChatResponse(text=f"✅ Incident `{args[0]}` acknowledged.")
        return ChatResponse(text=f"❌ Failed to acknowledge: {result.get('error')}")

    def _cmd_resolve(self, args: list, user_id: str = None, **kwargs) -> ChatResponse:
        """Resolve an incident."""
        if not args:
            return ChatResponse(text="Usage: `/resolve <incident_id> [resolution note]`")

        from services.incident_response import get_incident_engine

        incident_id = args[0]
        resolution = " ".join(args[1:]) if len(args) > 1 else f"Resolved via ChatOps by {user_id or 'user'}"

        engine = get_incident_engine()
        result = engine.resolve_incident(self._require_app_user(kwargs), incident_id, resolution)

        if result.get('success'):
            return ChatResponse(text=f"✅ Incident `{incident_id}` resolved.")
        return ChatResponse(text=f"❌ Failed to resolve: {result.get('error')}")

    def _cmd_alerts(self, args: list, **kwargs) -> ChatResponse:
        """List active alerts."""
        from services.proactive_monitoring import get_monitoring_service

        service = get_monitoring_service()
        alerts = service.get_active_alerts(self._require_app_user(kwargs))

        if not alerts:
            return ChatResponse(text="✅ No active alerts.")

        severity_filter = args[0].lower() if args else None

        lines = ["*Active Alerts:*\n"]
        # get_active_alerts returns dicts (Alert.to_dict()), not Alert objects.
        for alert in alerts[:10]:
            severity = str(alert.get('severity', '')).lower()
            if severity_filter and severity != severity_filter:
                continue
            lines.append(f"• [{severity.upper()}] {alert.get('name', 'unnamed')}\n  {str(alert.get('message', ''))[:100]}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_playbooks(self, args: list, **kwargs) -> ChatResponse:
        """List playbooks."""
        from services.incident_response import get_incident_engine

        engine = get_incident_engine()
        playbooks = engine.list_playbooks(self._require_app_user(kwargs))

        lines = ["*Available Playbooks:*\n"]
        for pb in playbooks:
            status = "✅" if pb.enabled else "⏸️"
            lines.append(f"{status} `{pb.id}` - {pb.name}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_execute(self, args: list, user_id: str = None, **kwargs) -> ChatResponse:
        """Execute playbook for incident."""
        if not args:
            return ChatResponse(text="Usage: `/execute <incident_id> [playbook_id]`")

        from services.incident_response import get_incident_engine

        incident_id = args[0]
        engine = get_incident_engine()

        app_user_id = self._require_app_user(kwargs)
        incident = engine.get_incident(app_user_id, incident_id)
        if not incident:
            return ChatResponse(text=f"Incident `{incident_id}` not found.")

        result = engine.execute_playbook(app_user_id, incident, skip_approval=False)

        if result.get('success'):
            return ChatResponse(text=f"✅ Playbook execution started for incident `{incident_id}`.")
        return ChatResponse(text=f"❌ Execution failed: {result.get('error')}")

    def _cmd_analyze(self, args: list, **kwargs) -> ChatResponse:
        """Run root cause analysis."""
        if not args:
            return ChatResponse(text="Usage: `/analyze <incident_id>`")

        from services.incident_response import get_incident_engine
        from services.root_cause_analyzer import get_root_cause_analyzer

        incident_id = args[0]
        app_user_id = self._require_app_user(kwargs)
        engine = get_incident_engine()
        analyzer = get_root_cause_analyzer()

        incident = engine.get_incident(app_user_id, incident_id)
        if not incident:
            return ChatResponse(text=f"Incident `{incident_id}` not found.")

        # Build incident data
        incident_data = {
            'id': incident.id,
            'title': incident.title,
            'description': incident.description,
            'severity': incident.severity.value,
            'status': incident.status.value,
            'source': incident.source,
            'triggered_at': incident.triggered_at.isoformat(),
            'timeline': incident.timeline,
            'actions_taken': incident.actions_taken
        }

        result = analyzer.analyze_incident(app_user_id, incident_data)

        if result.root_causes:
            rc = result.root_causes[0]
            text = f"""*Root Cause Analysis for Incident {incident_id}*

*Summary:* {result.summary}

*Primary Root Cause:* {rc.title}
*Confidence:* {rc.confidence.value.upper()}

*Description:*
{rc.description[:300]}{'...' if len(rc.description) > 300 else ''}

*Remediation Steps:*
"""
            for i, step in enumerate(rc.remediation_steps[:3], 1):
                text += f"{i}. {step}\n"

            return ChatResponse(text=text)

        return ChatResponse(text=f"Analysis completed but no root causes identified. See full report: /analysis/{result.id}")

    def _cmd_metrics(self, args: list, **kwargs) -> ChatResponse:
        """Get metrics summary."""
        service_filter = args[0] if args else None

        # In a real implementation, this would fetch from Prometheus/CloudWatch
        text = """*Metrics Summary*

📊 *Infrastructure*
• CPU Utilization: 45% (avg)
• Memory Usage: 62% (avg)
• Disk I/O: Normal

🌐 *Application*
• Request Rate: 1.2k/min
• Error Rate: 0.05%
• P95 Latency: 120ms

🗄️ *Database*
• Connection Pool: 45/100
• Query Time (avg): 15ms
• Replication Lag: 0ms
"""
        return ChatResponse(text=text)

    def _cmd_deployments(self, args: list, **kwargs) -> ChatResponse:
        """List recent deployments."""
        from services.webhook_integrations import get_webhook_service, EventType

        service = get_webhook_service()
        events = service.get_events(event_type='deployment', limit=5)

        if not events:
            return ChatResponse(text="No recent deployments found.")

        env_filter = args[0].lower() if args else None

        lines = ["*Recent Deployments:*\n"]
        for event in events:
            env = event.metadata.get('environment', 'unknown')
            if env_filter and env.lower() != env_filter:
                continue

            status_emoji = "✅" if event.status == 'success' else "❌" if event.status in ['failure', 'failed'] else "⏳"
            lines.append(f"{status_emoji} {event.repository} → {env}\n  {event.received_at.strftime('%Y-%m-%d %H:%M')}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_oncall(self, args: list, **kwargs) -> ChatResponse:
        """Show on-call information."""
        # In a real implementation, this would integrate with PagerDuty/OpsGenie

        text = """*On-Call Schedule*

🔴 *Primary:* @devops-team
🟡 *Secondary:* @sre-team

*Escalation:*
1. Primary (0-15 min)
2. Secondary (15-30 min)
3. Engineering Lead (30+ min)

_To update on-call schedule, visit PagerDuty._
"""
        return ChatResponse(text=text)

    def format_slack_blocks(self, response: ChatResponse) -> list:
        """Format response as Slack blocks."""
        blocks = []

        if response.text:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": response.text
                }
            })

        return blocks

    def format_teams_card(self, response: ChatResponse) -> dict:
        """Format response as Teams Adaptive Card."""
        return {
            "type": "AdaptiveCard",
            "body": [
                {
                    "type": "TextBlock",
                    "text": response.text,
                    "wrap": True
                }
            ],
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4"
        }


# Global instance
_chatops_service: Optional[ChatOpsService] = None


def get_chatops_service() -> ChatOpsService:
    """Get or create the global ChatOps service."""
    global _chatops_service
    if _chatops_service is None:
        _chatops_service = ChatOpsService()
    return _chatops_service
