"""
ChatOps Service for DevOps Agent.

Provides interactive bot commands for Slack and Microsoft Teams,
allowing users to query incidents, trigger actions, and get status updates.
"""

import logging
import os
import re
from datetime import datetime
from typing import Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


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

        self.register_command(ChatCommand(
            name="link",
            description="Link this Slack/Teams account to your DevOps Agent account",
            usage="/link <code>",
            handler=self._cmd_link,
            requires_auth=False
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
                        app_user_id: Optional[int] = None) -> ChatResponse:
        """Process an incoming message and return response.

        `user_id` is the platform-native id (Slack/Teams user id) carried on
        every inbound event — it has no relation to an app account. Incident
        and monitoring data in this app is strictly per-user (see
        IncidentResponseEngine/ProactiveMonitoringService), so any command
        that touches it needs a real app `User.id`, resolved via a linked
        ChatOpsIdentity. `app_user_id` lets a caller that already knows the
        app user (e.g. the logged-in dashboard's test-command panel) skip
        that lookup.
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

        resolved_app_user_id = app_user_id
        if command.requires_auth and resolved_app_user_id is None:
            resolved_app_user_id = self._resolve_app_user_id(platform, user_id)
            if resolved_app_user_id is None:
                return ChatResponse(text=self._not_linked_message())

        try:
            response = command.handler(args, user_id=user_id, channel_id=channel_id,
                                        platform=platform, app_user_id=resolved_app_user_id)
            return response
        except Exception as e:
            logger.error(f"Command error: {e}", exc_info=True)
            return ChatResponse(
                text=f"Error executing command: {str(e)}"
            )

    def _resolve_app_user_id(self, platform: ChatPlatform, platform_user_id: Optional[str]) -> Optional[int]:
        """Look up the app user linked to this Slack/Teams identity, if any."""
        if not platform_user_id:
            return None

        from models import ChatOpsIdentity

        identity = ChatOpsIdentity.query.filter_by(
            platform=platform.value, platform_user_id=str(platform_user_id)
        ).first()
        return identity.user_id if identity else None

    def _not_linked_message(self) -> str:
        return (
            "Your Slack/Teams account isn't linked to a DevOps Agent account yet. "
            "Log in to DevOps Agent, open the ChatOps page, generate a link code, "
            "then run `/link <code>` here to connect this account."
        )

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

    def _cmd_status(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Get system status."""
        from services.incident_response import get_incident_engine, IncidentStatus
        from services.proactive_monitoring import get_monitoring_service

        engine = get_incident_engine()
        monitoring = get_monitoring_service()

        stats = engine.get_stats(app_user_id)
        mon_status = monitoring.get_status(app_user_id)

        by_status = stats.get('by_status', {})
        resolved = by_status.get(IncidentStatus.RESOLVED.value, 0)
        closed = by_status.get(IncidentStatus.CLOSED.value, 0)
        active_incidents = stats.get('total', 0) - resolved - closed
        critical = stats.get('by_severity', {}).get('critical', 0)

        resolved_24h = sum(
            1 for inc in engine.list_incidents(app_user_id, status=IncidentStatus.RESOLVED, limit=1000)
            if inc.resolved_at and (datetime.utcnow() - inc.resolved_at).total_seconds() <= 86400
        )

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
• Resolved (24h): {resolved_24h}

📡 *Monitoring*
• Status: {'Running' if mon_status.get('running') else 'Stopped'}
• Active Rules: {mon_status.get('rules_enabled', 0)}
• Active Alerts: {mon_status.get('alerts_active', 0)}
"""
        return ChatResponse(text=text)

    def _cmd_incidents(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """List incidents."""
        from services.incident_response import get_incident_engine, IncidentStatus, IncidentSeverity

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

    def _cmd_incident_detail(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Get incident details."""
        if not args:
            return ChatResponse(text="Usage: `/incident <id>`")

        from services.incident_response import get_incident_engine

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

    def _cmd_acknowledge(self, args: list, user_id: str = None, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Acknowledge an incident."""
        if not args:
            return ChatResponse(text="Usage: `/ack <incident_id>`")

        from services.incident_response import get_incident_engine

        engine = get_incident_engine()
        result = engine.acknowledge_incident(
            app_user_id, args[0], user=self._display_name(app_user_id, user_id)
        )

        if result.get('success'):
            return ChatResponse(text=f"✅ Incident `{args[0]}` acknowledged.")
        return ChatResponse(text=f"❌ Failed to acknowledge: {result.get('error')}")

    def _cmd_resolve(self, args: list, user_id: str = None, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Resolve an incident."""
        if not args:
            return ChatResponse(text="Usage: `/resolve <incident_id> [resolution note]`")

        from services.incident_response import get_incident_engine

        incident_id = args[0]
        display_name = self._display_name(app_user_id, user_id)
        resolution = " ".join(args[1:]) if len(args) > 1 else f"Resolved via ChatOps by {display_name}"

        engine = get_incident_engine()
        result = engine.resolve_incident(app_user_id, incident_id, resolution)

        if result.get('success'):
            return ChatResponse(text=f"✅ Incident `{incident_id}` resolved.")
        return ChatResponse(text=f"❌ Failed to resolve: {result.get('error')}")

    def _display_name(self, app_user_id: Optional[int], platform_user_id: Optional[str]) -> str:
        """Best-effort human-readable identifier for audit/timeline text."""
        if app_user_id:
            from models import User
            user = User.query.get(app_user_id)
            if user and user.email:
                return user.email
        return f"chatops:{platform_user_id}" if platform_user_id else "chatops"

    def _cmd_alerts(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """List active alerts."""
        from services.proactive_monitoring import get_monitoring_service

        service = get_monitoring_service()
        alerts = service.get_active_alerts(app_user_id)

        if not alerts:
            return ChatResponse(text="✅ No active alerts.")

        severity_filter = args[0].lower() if args else None

        lines = ["*Active Alerts:*\n"]
        for alert in alerts[:10]:
            if severity_filter and alert.get('severity') != severity_filter:
                continue
            lines.append(f"• [{alert.get('severity', '').upper()}] {alert.get('rule_name')}\n  {(alert.get('message') or '')[:100]}")

        if len(lines) == 1:
            return ChatResponse(text=f"No active alerts match severity `{severity_filter}`.")

        return ChatResponse(text="\n".join(lines))

    def _cmd_playbooks(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """List playbooks."""
        from services.incident_response import get_incident_engine

        engine = get_incident_engine()
        playbooks = engine.list_playbooks(app_user_id)

        lines = ["*Available Playbooks:*\n"]
        for pb in playbooks:
            status = "✅" if pb.enabled else "⏸️"
            lines.append(f"{status} `{pb.id}` - {pb.name}")

        return ChatResponse(text="\n".join(lines))

    def _cmd_execute(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Execute playbook for incident."""
        if not args:
            return ChatResponse(text="Usage: `/execute <incident_id> [playbook_id]`")

        from services.incident_response import get_incident_engine

        incident_id = args[0]
        engine = get_incident_engine()

        incident = engine.get_incident(app_user_id, incident_id)
        if not incident:
            return ChatResponse(text=f"Incident `{incident_id}` not found.")

        playbook = None
        if len(args) > 1:
            playbook = engine.get_playbook(app_user_id, args[1])
            if not playbook:
                return ChatResponse(text=f"Playbook `{args[1]}` not found.")

        result = engine.execute_playbook(app_user_id, incident, playbook=playbook, skip_approval=False)

        if result.get('success'):
            return ChatResponse(text=f"✅ Playbook execution started for incident `{incident_id}`.")
        return ChatResponse(text=f"❌ Execution failed: {result.get('error')}")

    def _cmd_analyze(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Run root cause analysis."""
        if not args:
            return ChatResponse(text="Usage: `/analyze <incident_id>`")

        from services.incident_response import get_incident_engine
        from services.root_cause_analyzer import get_root_cause_analyzer

        incident_id = args[0]
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

    def _cmd_metrics(self, args: list, app_user_id: int = None, **kwargs) -> ChatResponse:
        """Get a live metrics summary from the user's configured monitoring rules.

        No fabricated numbers: this reads real, just-collected values via
        ProactiveMonitoringService.check_now(), which evaluates each rule's
        actual Prometheus/CloudWatch/Datadog query. A user with no monitoring
        rules configured gets told that, not a plausible-looking placeholder.
        """
        service_filter = args[0].lower() if args else None

        from services.proactive_monitoring import get_monitoring_service

        monitoring = get_monitoring_service()
        results = monitoring.check_now(app_user_id)

        if not results:
            return ChatResponse(text=(
                "No monitoring rules are configured yet. Set some up on the "
                "Monitoring dashboard to see live metrics here."
            ))

        state_emoji = {'firing': '🔴', 'pending': '🟡', 'ok': '🟢'}

        lines = ["*Metrics Summary* (live, from your monitoring rules)\n"]
        matched = False
        for rule_id, r in results.items():
            name = r.get('name', rule_id)
            if service_filter and service_filter not in rule_id.lower() and service_filter not in name.lower():
                continue
            matched = True
            if 'error' in r:
                lines.append(f"⚠️ {name}: error collecting metric ({r['error']})")
                continue
            value = r.get('last_value')
            value_text = f"{value:.2f}" if isinstance(value, (int, float)) else "no data yet"
            emoji = state_emoji.get(r.get('state'), '⚪')
            lines.append(f"{emoji} {name}: {value_text} (threshold {r.get('threshold')})")

        if not matched:
            return ChatResponse(text=f"No monitoring rules match `{service_filter}`.")

        return ChatResponse(text="\n".join(lines))

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
        """Show on-call information from the configured PagerDuty/OpsGenie integration.

        No fabricated roster: fails closed with a clear "not configured"
        message when neither PAGERDUTY_API_KEY nor OPSGENIE_API_KEY is set,
        instead of returning a plausible-looking placeholder schedule.
        """
        if os.environ.get('PAGERDUTY_API_KEY'):
            from src.tools.alerting_tools import pagerduty_list_oncalls

            result = pagerduty_list_oncalls()
            if not result.get('success'):
                return ChatResponse(text=f"Could not fetch the on-call schedule from PagerDuty: {result.get('error')}")

            oncalls = result.get('oncalls', [])
            if not oncalls:
                return ChatResponse(text="No on-call schedules found in PagerDuty.")

            lines = ["*On-Call Schedule* (from PagerDuty)\n"]
            for oc in oncalls[:10]:
                lines.append(
                    f"• {oc.get('user') or 'Unknown'} — {oc.get('schedule') or 'n/a'} "
                    f"(escalation level {oc.get('escalation_level')})"
                )
            return ChatResponse(text="\n".join(lines))

        if os.environ.get('OPSGENIE_API_KEY'):
            from src.tools.alerting_tools import opsgenie_list_schedules, opsgenie_get_oncall

            schedules_result = opsgenie_list_schedules()
            if not schedules_result.get('success'):
                return ChatResponse(text=f"Could not fetch schedules from OpsGenie: {schedules_result.get('error')}")

            schedules = schedules_result.get('schedules', [])
            if not schedules:
                return ChatResponse(text="No on-call schedules found in OpsGenie.")

            lines = ["*On-Call Schedule* (from OpsGenie)\n"]
            for sched in schedules[:5]:
                oncall_result = opsgenie_get_oncall(sched['id'])
                participants = oncall_result.get('oncall_participants', []) if oncall_result.get('success') else []
                names = ", ".join(p.get('name', '?') for p in participants) or "nobody currently on call"
                lines.append(f"• *{sched.get('name')}*: {names}")
            return ChatResponse(text="\n".join(lines))

        return ChatResponse(text=(
            "No on-call integration is configured. Set `PAGERDUTY_API_KEY` or "
            "`OPSGENIE_API_KEY` to enable `/oncall`."
        ))

    def _cmd_link(self, args: list, user_id: str = None,
                  platform: ChatPlatform = ChatPlatform.SLACK, **kwargs) -> ChatResponse:
        """Redeem a link code generated on the ChatOps settings page, binding
        this Slack/Teams identity to the app user who generated it."""
        if not args:
            return ChatResponse(text=(
                "Usage: `/link <code>` — generate a code from the ChatOps page "
                "in DevOps Agent while logged in."
            ))
        if not user_id:
            return ChatResponse(text="Could not determine your platform user id.")

        from models import db, ChatOpsIdentity, ChatOpsLinkCode

        code = args[0].strip().upper()
        link_code = ChatOpsLinkCode.query.filter_by(code=code).first()

        if not link_code or link_code.used_at is not None or link_code.expires_at < datetime.utcnow():
            return ChatResponse(text=(
                "That code is invalid or has expired. Generate a new one from "
                "the ChatOps page in DevOps Agent."
            ))

        existing = ChatOpsIdentity.query.filter_by(
            platform=platform.value, platform_user_id=str(user_id)
        ).first()
        if existing:
            existing.user_id = link_code.user_id
            existing.linked_at = datetime.utcnow()
        else:
            db.session.add(ChatOpsIdentity(
                platform=platform.value,
                platform_user_id=str(user_id),
                user_id=link_code.user_id,
            ))

        link_code.used_at = datetime.utcnow()
        db.session.commit()

        return ChatResponse(text="✅ Account linked! You can now use incident and monitoring commands here.")

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
