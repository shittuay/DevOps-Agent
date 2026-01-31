"""
Automated Incident Response Service for DevOps Agent.

This service provides automated remediation capabilities:
- Define response playbooks for different incident types
- Automatically match incidents to playbooks
- Execute remediation actions (with approval for dangerous ops)
- Track incident lifecycle and actions taken
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass, field
import threading
import queue

logger = logging.getLogger(__name__)


class IncidentSeverity(Enum):
    """Incident severity levels."""
    CRITICAL = 'critical'  # P1 - Immediate action required
    HIGH = 'high'          # P2 - Urgent, within 1 hour
    MEDIUM = 'medium'      # P3 - Important, within 4 hours
    LOW = 'low'            # P4 - Minor, within 24 hours
    INFO = 'info'          # P5 - Informational


class IncidentStatus(Enum):
    """Incident lifecycle status."""
    DETECTED = 'detected'
    ACKNOWLEDGED = 'acknowledged'
    INVESTIGATING = 'investigating'
    REMEDIATING = 'remediating'
    AWAITING_APPROVAL = 'awaiting_approval'
    RESOLVED = 'resolved'
    CLOSED = 'closed'
    ESCALATED = 'escalated'


class ActionType(Enum):
    """Types of remediation actions."""
    RESTART_SERVICE = 'restart_service'
    SCALE_UP = 'scale_up'
    SCALE_DOWN = 'scale_down'
    FAILOVER = 'failover'
    ROLLBACK = 'rollback'
    CLEAR_CACHE = 'clear_cache'
    ROTATE_CREDENTIALS = 'rotate_credentials'
    BLOCK_IP = 'block_ip'
    NOTIFY = 'notify'
    RUN_SCRIPT = 'run_script'
    ANSIBLE_PLAYBOOK = 'ansible_playbook'
    KUBERNETES_ACTION = 'kubernetes_action'
    AWS_ACTION = 'aws_action'
    CUSTOM = 'custom'


@dataclass
class RemediationAction:
    """A single remediation action."""
    action_type: ActionType
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    timeout_seconds: int = 300
    retry_count: int = 0
    retry_delay_seconds: int = 30
    rollback_action: Optional['RemediationAction'] = None


@dataclass
class ResponsePlaybook:
    """A playbook defining how to respond to an incident type."""
    id: str
    name: str
    description: str
    trigger_conditions: Dict[str, Any]  # Conditions to match
    severity: IncidentSeverity
    actions: List[RemediationAction]
    enabled: bool = True
    auto_execute: bool = False  # Auto-execute without approval
    notification_channels: List[str] = field(default_factory=list)
    escalation_policy: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Incident:
    """An active incident."""
    id: str
    title: str
    description: str
    severity: IncidentSeverity
    status: IncidentStatus
    source: str  # Where the incident originated (prometheus, datadog, etc.)
    source_id: Optional[str] = None  # ID in source system
    playbook_id: Optional[str] = None
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)


class IncidentResponseEngine:
    """Engine for automated incident response."""

    def __init__(self):
        self.playbooks: Dict[str, ResponsePlaybook] = {}
        self.incidents: Dict[str, Incident] = {}
        self.action_handlers: Dict[ActionType, Callable] = {}
        self.action_queue = queue.Queue()
        self.running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Register default action handlers
        self._register_default_handlers()

        # Load built-in playbooks
        self._load_builtin_playbooks()

    def _register_default_handlers(self):
        """Register default action handlers."""
        self.action_handlers[ActionType.NOTIFY] = self._handle_notify
        self.action_handlers[ActionType.RESTART_SERVICE] = self._handle_restart_service
        self.action_handlers[ActionType.SCALE_UP] = self._handle_scale_up
        self.action_handlers[ActionType.SCALE_DOWN] = self._handle_scale_down
        self.action_handlers[ActionType.KUBERNETES_ACTION] = self._handle_kubernetes_action
        self.action_handlers[ActionType.AWS_ACTION] = self._handle_aws_action
        self.action_handlers[ActionType.RUN_SCRIPT] = self._handle_run_script
        self.action_handlers[ActionType.CLEAR_CACHE] = self._handle_clear_cache
        self.action_handlers[ActionType.BLOCK_IP] = self._handle_block_ip

    def _load_builtin_playbooks(self):
        """Load built-in response playbooks."""

        # High CPU Usage Playbook
        self.register_playbook(ResponsePlaybook(
            id='high-cpu-usage',
            name='High CPU Usage Response',
            description='Responds to high CPU usage alerts by scaling or restarting services',
            trigger_conditions={
                'alert_name': ['HighCPUUsage', 'CPUThrottling', 'InstanceCPUHigh'],
                'metric': 'cpu_usage',
                'threshold': 90
            },
            severity=IncidentSeverity.HIGH,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Notify Team',
                    description='Send notification to ops team',
                    parameters={'channel': 'ops', 'message': 'High CPU detected'}
                ),
                RemediationAction(
                    action_type=ActionType.SCALE_UP,
                    name='Scale Up',
                    description='Add additional instances',
                    parameters={'increment': 1},
                    requires_approval=False
                )
            ],
            auto_execute=True,
            notification_channels=['slack', 'pagerduty'],
            tags=['performance', 'cpu', 'auto-scaling']
        ))

        # Memory Pressure Playbook
        self.register_playbook(ResponsePlaybook(
            id='memory-pressure',
            name='Memory Pressure Response',
            description='Responds to memory pressure by restarting services or scaling',
            trigger_conditions={
                'alert_name': ['HighMemoryUsage', 'MemoryPressure', 'OOMKiller'],
                'metric': 'memory_usage',
                'threshold': 85
            },
            severity=IncidentSeverity.HIGH,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Alert Team',
                    description='Notify team of memory issues',
                    parameters={'channel': 'ops'}
                ),
                RemediationAction(
                    action_type=ActionType.CLEAR_CACHE,
                    name='Clear Application Cache',
                    description='Clear application caches to free memory',
                    parameters={}
                ),
                RemediationAction(
                    action_type=ActionType.RESTART_SERVICE,
                    name='Restart Service',
                    description='Restart the affected service',
                    parameters={'graceful': True},
                    requires_approval=True
                )
            ],
            auto_execute=False,
            tags=['performance', 'memory']
        ))

        # Disk Space Low Playbook
        self.register_playbook(ResponsePlaybook(
            id='disk-space-low',
            name='Low Disk Space Response',
            description='Responds to low disk space by cleaning up old files',
            trigger_conditions={
                'alert_name': ['DiskSpaceLow', 'DiskFull', 'LowDiskSpace'],
                'metric': 'disk_usage',
                'threshold': 90
            },
            severity=IncidentSeverity.MEDIUM,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Alert Team',
                    description='Notify about disk space',
                    parameters={'channel': 'ops'}
                ),
                RemediationAction(
                    action_type=ActionType.RUN_SCRIPT,
                    name='Cleanup Old Logs',
                    description='Remove old log files',
                    parameters={
                        'script': 'cleanup_logs.sh',
                        'args': ['--older-than', '7d']
                    }
                )
            ],
            auto_execute=True,
            tags=['disk', 'cleanup']
        ))

        # Service Down Playbook
        self.register_playbook(ResponsePlaybook(
            id='service-down',
            name='Service Down Response',
            description='Responds to service health check failures',
            trigger_conditions={
                'alert_name': ['ServiceDown', 'HealthCheckFailed', 'EndpointDown'],
                'type': 'health_check'
            },
            severity=IncidentSeverity.CRITICAL,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Page On-Call',
                    description='Page the on-call engineer',
                    parameters={'channel': 'pagerduty', 'priority': 'high'}
                ),
                RemediationAction(
                    action_type=ActionType.RESTART_SERVICE,
                    name='Restart Service',
                    description='Attempt to restart the failed service',
                    parameters={'graceful': False, 'force': True},
                    requires_approval=False,
                    retry_count=2,
                    retry_delay_seconds=30
                )
            ],
            auto_execute=True,
            escalation_policy='critical-incidents',
            tags=['availability', 'health']
        ))

        # Security Alert Playbook
        self.register_playbook(ResponsePlaybook(
            id='security-alert',
            name='Security Alert Response',
            description='Responds to security-related alerts',
            trigger_conditions={
                'alert_name': ['SecurityAlert', 'SuspiciousActivity', 'BruteForce', 'UnauthorizedAccess'],
                'type': 'security'
            },
            severity=IncidentSeverity.CRITICAL,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Alert Security Team',
                    description='Immediately notify security team',
                    parameters={'channel': 'security', 'priority': 'critical'}
                ),
                RemediationAction(
                    action_type=ActionType.BLOCK_IP,
                    name='Block Suspicious IP',
                    description='Block the source IP if identified',
                    parameters={},
                    requires_approval=True
                )
            ],
            auto_execute=False,  # Security actions need human review
            escalation_policy='security-incidents',
            tags=['security', 'threat']
        ))

        # Pod Crash Loop Playbook
        self.register_playbook(ResponsePlaybook(
            id='pod-crashloop',
            name='Kubernetes Pod CrashLoop Response',
            description='Responds to pods stuck in CrashLoopBackOff',
            trigger_conditions={
                'alert_name': ['PodCrashLooping', 'CrashLoopBackOff', 'PodNotReady'],
                'type': 'kubernetes'
            },
            severity=IncidentSeverity.HIGH,
            actions=[
                RemediationAction(
                    action_type=ActionType.NOTIFY,
                    name='Alert Team',
                    description='Notify about pod issues',
                    parameters={'channel': 'ops'}
                ),
                RemediationAction(
                    action_type=ActionType.KUBERNETES_ACTION,
                    name='Collect Pod Logs',
                    description='Gather logs from the failing pod',
                    parameters={'action': 'get_logs', 'previous': True}
                ),
                RemediationAction(
                    action_type=ActionType.KUBERNETES_ACTION,
                    name='Rollback Deployment',
                    description='Rollback to previous stable version',
                    parameters={'action': 'rollback'},
                    requires_approval=True
                )
            ],
            auto_execute=False,
            tags=['kubernetes', 'availability']
        ))

    def register_playbook(self, playbook: ResponsePlaybook) -> None:
        """Register a response playbook."""
        self.playbooks[playbook.id] = playbook
        logger.info(f"Registered playbook: {playbook.name} ({playbook.id})")

    def unregister_playbook(self, playbook_id: str) -> bool:
        """Unregister a playbook."""
        if playbook_id in self.playbooks:
            del self.playbooks[playbook_id]
            return True
        return False

    def get_playbook(self, playbook_id: str) -> Optional[ResponsePlaybook]:
        """Get a playbook by ID."""
        return self.playbooks.get(playbook_id)

    def list_playbooks(self) -> List[ResponsePlaybook]:
        """List all registered playbooks."""
        return list(self.playbooks.values())

    def match_playbook(self, alert_data: Dict[str, Any]) -> Optional[ResponsePlaybook]:
        """Match an alert to an appropriate playbook."""
        alert_name = alert_data.get('alert_name', alert_data.get('name', ''))
        alert_type = alert_data.get('type', '')

        for playbook in self.playbooks.values():
            if not playbook.enabled:
                continue

            conditions = playbook.trigger_conditions

            # Check alert name match
            if 'alert_name' in conditions:
                names = conditions['alert_name']
                if isinstance(names, str):
                    names = [names]
                if alert_name in names or any(n.lower() in alert_name.lower() for n in names):
                    return playbook

            # Check type match
            if 'type' in conditions and conditions['type'] == alert_type:
                return playbook

            # Check metric threshold
            if 'metric' in conditions and 'threshold' in conditions:
                metric = conditions['metric']
                if metric in alert_data:
                    value = alert_data[metric]
                    if isinstance(value, (int, float)) and value >= conditions['threshold']:
                        return playbook

        return None

    def create_incident(
        self,
        title: str,
        description: str,
        severity: IncidentSeverity,
        source: str,
        source_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Incident:
        """Create a new incident."""
        import uuid

        incident_id = str(uuid.uuid4())[:8]
        incident = Incident(
            id=incident_id,
            title=title,
            description=description,
            severity=severity,
            status=IncidentStatus.DETECTED,
            source=source,
            source_id=source_id,
            metadata=metadata or {}
        )

        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'incident_created',
            'details': f'Incident created from {source}'
        })

        self.incidents[incident_id] = incident
        logger.info(f"Created incident {incident_id}: {title}")

        return incident

    def process_alert(self, alert_data: Dict[str, Any]) -> Optional[Incident]:
        """Process an incoming alert and create incident if needed."""
        # Match to playbook
        playbook = self.match_playbook(alert_data)

        # Create incident
        title = alert_data.get('title', alert_data.get('alert_name', 'Unknown Alert'))
        description = alert_data.get('description', alert_data.get('message', ''))
        source = alert_data.get('source', 'unknown')

        severity = IncidentSeverity.MEDIUM
        if playbook:
            severity = playbook.severity
        elif 'severity' in alert_data:
            try:
                severity = IncidentSeverity(alert_data['severity'].lower())
            except ValueError:
                pass

        incident = self.create_incident(
            title=title,
            description=description,
            severity=severity,
            source=source,
            source_id=alert_data.get('alert_id'),
            metadata=alert_data
        )

        if playbook:
            incident.playbook_id = playbook.id
            incident.timeline.append({
                'timestamp': datetime.utcnow().isoformat(),
                'event': 'playbook_matched',
                'details': f'Matched playbook: {playbook.name}'
            })

            # Auto-execute if configured
            if playbook.auto_execute:
                self.execute_playbook(incident, playbook)

        return incident

    def execute_playbook(
        self,
        incident: Incident,
        playbook: Optional[ResponsePlaybook] = None,
        skip_approval: bool = False
    ) -> Dict[str, Any]:
        """Execute a playbook for an incident."""
        if playbook is None:
            if incident.playbook_id:
                playbook = self.playbooks.get(incident.playbook_id)
            if playbook is None:
                return {'success': False, 'error': 'No playbook found'}

        incident.status = IncidentStatus.REMEDIATING
        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'playbook_execution_started',
            'details': f'Executing playbook: {playbook.name}'
        })

        results = []

        for action in playbook.actions:
            # Check if approval is required
            if action.requires_approval and not skip_approval:
                incident.status = IncidentStatus.AWAITING_APPROVAL
                incident.timeline.append({
                    'timestamp': datetime.utcnow().isoformat(),
                    'event': 'awaiting_approval',
                    'details': f'Action requires approval: {action.name}'
                })
                results.append({
                    'action': action.name,
                    'status': 'awaiting_approval',
                    'requires_approval': True
                })
                continue

            # Execute action
            result = self._execute_action(incident, action)
            results.append(result)

            incident.actions_taken.append({
                'action': action.name,
                'type': action.action_type.value,
                'result': result,
                'timestamp': datetime.utcnow().isoformat()
            })

            # Stop on failure unless configured otherwise
            if not result.get('success', False):
                incident.timeline.append({
                    'timestamp': datetime.utcnow().isoformat(),
                    'event': 'action_failed',
                    'details': f'Action failed: {action.name} - {result.get("error", "Unknown error")}'
                })
                break

        # Check if all actions completed successfully
        all_success = all(r.get('success', False) or r.get('status') == 'awaiting_approval' for r in results)

        if all_success and incident.status != IncidentStatus.AWAITING_APPROVAL:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = datetime.utcnow()
            incident.timeline.append({
                'timestamp': datetime.utcnow().isoformat(),
                'event': 'incident_resolved',
                'details': 'All remediation actions completed successfully'
            })

        return {
            'success': all_success,
            'incident_id': incident.id,
            'playbook': playbook.name,
            'actions': results
        }

    def _execute_action(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Execute a single remediation action."""
        handler = self.action_handlers.get(action.action_type)

        if handler is None:
            return {
                'success': False,
                'action': action.name,
                'error': f'No handler for action type: {action.action_type.value}'
            }

        try:
            result = handler(incident, action)
            result['action'] = action.name

            incident.timeline.append({
                'timestamp': datetime.utcnow().isoformat(),
                'event': 'action_executed',
                'details': f'Executed: {action.name}',
                'result': 'success' if result.get('success') else 'failed'
            })

            return result

        except Exception as e:
            logger.error(f"Error executing action {action.name}: {str(e)}")
            return {
                'success': False,
                'action': action.name,
                'error': str(e)
            }

    # Action Handlers
    def _handle_notify(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle notification action."""
        channel = action.parameters.get('channel', 'default')
        message = action.parameters.get('message', f'Incident: {incident.title}')
        priority = action.parameters.get('priority', 'normal')

        # Log the notification (actual implementation would send to Slack/PagerDuty/etc.)
        logger.info(f"NOTIFY [{channel}] ({priority}): {message}")

        return {
            'success': True,
            'channel': channel,
            'message': f'Notification sent to {channel}'
        }

    def _handle_restart_service(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle service restart action."""
        service = incident.metadata.get('service', action.parameters.get('service'))
        graceful = action.parameters.get('graceful', True)

        if not service:
            return {'success': False, 'error': 'No service specified'}

        logger.info(f"RESTART SERVICE: {service} (graceful={graceful})")

        # Actual implementation would call systemctl, docker, or k8s
        return {
            'success': True,
            'service': service,
            'message': f'Service {service} restart initiated'
        }

    def _handle_scale_up(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle scale up action."""
        increment = action.parameters.get('increment', 1)
        target = incident.metadata.get('service', action.parameters.get('target'))

        logger.info(f"SCALE UP: {target} by {increment}")

        return {
            'success': True,
            'target': target,
            'increment': increment,
            'message': f'Scaled up {target} by {increment} instance(s)'
        }

    def _handle_scale_down(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle scale down action."""
        decrement = action.parameters.get('decrement', 1)
        target = incident.metadata.get('service', action.parameters.get('target'))

        logger.info(f"SCALE DOWN: {target} by {decrement}")

        return {
            'success': True,
            'target': target,
            'decrement': decrement,
            'message': f'Scaled down {target} by {decrement} instance(s)'
        }

    def _handle_kubernetes_action(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle Kubernetes-related actions."""
        k8s_action = action.parameters.get('action')
        namespace = incident.metadata.get('namespace', 'default')
        resource = incident.metadata.get('resource', incident.metadata.get('pod'))

        logger.info(f"K8S ACTION: {k8s_action} on {resource} in {namespace}")

        return {
            'success': True,
            'action': k8s_action,
            'resource': resource,
            'namespace': namespace,
            'message': f'Kubernetes {k8s_action} completed'
        }

    def _handle_aws_action(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle AWS-related actions."""
        aws_action = action.parameters.get('action')
        resource = action.parameters.get('resource')

        logger.info(f"AWS ACTION: {aws_action} on {resource}")

        return {
            'success': True,
            'action': aws_action,
            'resource': resource,
            'message': f'AWS {aws_action} completed'
        }

    def _handle_run_script(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle script execution action."""
        script = action.parameters.get('script')
        args = action.parameters.get('args', [])

        if not script:
            return {'success': False, 'error': 'No script specified'}

        logger.info(f"RUN SCRIPT: {script} {' '.join(args)}")

        # Actual implementation would execute the script
        return {
            'success': True,
            'script': script,
            'message': f'Script {script} executed'
        }

    def _handle_clear_cache(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle cache clearing action."""
        target = action.parameters.get('target', 'all')

        logger.info(f"CLEAR CACHE: {target}")

        return {
            'success': True,
            'target': target,
            'message': f'Cache cleared for {target}'
        }

    def _handle_block_ip(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Handle IP blocking action."""
        ip = incident.metadata.get('source_ip', action.parameters.get('ip'))

        if not ip:
            return {'success': False, 'error': 'No IP address specified'}

        logger.info(f"BLOCK IP: {ip}")

        return {
            'success': True,
            'ip': ip,
            'message': f'IP {ip} blocked'
        }

    # Incident Management
    def acknowledge_incident(self, incident_id: str, user: str) -> Dict[str, Any]:
        """Acknowledge an incident."""
        incident = self.incidents.get(incident_id)
        if not incident:
            return {'success': False, 'error': 'Incident not found'}

        incident.status = IncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = datetime.utcnow()
        incident.assigned_to = user
        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'incident_acknowledged',
            'details': f'Acknowledged by {user}'
        })

        return {'success': True, 'incident_id': incident_id}

    def resolve_incident(self, incident_id: str, resolution: str = None) -> Dict[str, Any]:
        """Resolve an incident."""
        incident = self.incidents.get(incident_id)
        if not incident:
            return {'success': False, 'error': 'Incident not found'}

        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.utcnow()
        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'incident_resolved',
            'details': resolution or 'Incident resolved'
        })

        return {'success': True, 'incident_id': incident_id}

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get an incident by ID."""
        return self.incidents.get(incident_id)

    def list_incidents(
        self,
        status: Optional[IncidentStatus] = None,
        severity: Optional[IncidentSeverity] = None,
        limit: int = 50
    ) -> List[Incident]:
        """List incidents with optional filters."""
        incidents = list(self.incidents.values())

        if status:
            incidents = [i for i in incidents if i.status == status]

        if severity:
            incidents = [i for i in incidents if i.severity == severity]

        # Sort by triggered_at descending
        incidents.sort(key=lambda x: x.triggered_at, reverse=True)

        return incidents[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get incident statistics."""
        incidents = list(self.incidents.values())

        return {
            'total': len(incidents),
            'by_status': {
                status.value: len([i for i in incidents if i.status == status])
                for status in IncidentStatus
            },
            'by_severity': {
                sev.value: len([i for i in incidents if i.severity == sev])
                for sev in IncidentSeverity
            },
            'playbooks_registered': len(self.playbooks),
            'auto_execute_enabled': len([p for p in self.playbooks.values() if p.auto_execute])
        }


# Global instance
incident_engine = IncidentResponseEngine()


def get_incident_engine() -> IncidentResponseEngine:
    """Get the global incident response engine."""
    return incident_engine
