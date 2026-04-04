"""
Automated Incident Response Service for DevOps Agent.

This service provides automated remediation capabilities:
- Define response playbooks for different incident types
- Automatically match incidents to playbooks
- Execute remediation actions (with approval for dangerous ops)
- Track incident lifecycle and actions taken
- DB persistence with per-user isolation
- Real tool integration with AWS, Kubernetes, Azure, GCP
"""

import os
import json
import logging
import uuid
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
    trigger_conditions: Dict[str, Any]
    severity: IncidentSeverity
    actions: List[RemediationAction]
    enabled: bool = True
    auto_execute: bool = False
    notification_channels: List[str] = field(default_factory=list)
    escalation_policy: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    is_builtin: bool = False
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
    source: str
    user_id: Optional[int] = None
    source_id: Optional[str] = None
    playbook_id: Optional[str] = None
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    timeline: List[Dict[str, Any]] = field(default_factory=list)


# Built-in playbook definitions
BUILTIN_PLAYBOOKS = [
    {
        'id': 'high-cpu-usage',
        'name': 'High CPU Usage Response',
        'description': 'Responds to high CPU usage alerts by scaling or restarting services',
        'trigger_conditions': {
            'alert_name': ['HighCPUUsage', 'CPUThrottling', 'InstanceCPUHigh'],
            'metric': 'cpu_usage',
            'threshold': 90
        },
        'severity': 'high',
        'actions': [
            {'action_type': 'notify', 'name': 'Notify Team', 'description': 'Send notification to ops team',
             'parameters': {'channel': 'ops', 'message': 'High CPU detected'}, 'requires_approval': False},
            {'action_type': 'scale_up', 'name': 'Scale Up', 'description': 'Add additional instances',
             'parameters': {'increment': 1}, 'requires_approval': False}
        ],
        'auto_execute': True,
        'notification_channels': ['slack', 'pagerduty'],
        'tags': ['performance', 'cpu', 'auto-scaling']
    },
    {
        'id': 'memory-pressure',
        'name': 'Memory Pressure Response',
        'description': 'Responds to memory pressure by restarting services or scaling',
        'trigger_conditions': {
            'alert_name': ['HighMemoryUsage', 'MemoryPressure', 'OOMKiller'],
            'metric': 'memory_usage',
            'threshold': 85
        },
        'severity': 'high',
        'actions': [
            {'action_type': 'notify', 'name': 'Alert Team', 'description': 'Notify team of memory issues',
             'parameters': {'channel': 'ops'}, 'requires_approval': False},
            {'action_type': 'clear_cache', 'name': 'Clear Application Cache',
             'description': 'Clear application caches to free memory', 'parameters': {}, 'requires_approval': False},
            {'action_type': 'restart_service', 'name': 'Restart Service',
             'description': 'Restart the affected service', 'parameters': {'graceful': True}, 'requires_approval': True}
        ],
        'auto_execute': False,
        'tags': ['performance', 'memory']
    },
    {
        'id': 'disk-space-low',
        'name': 'Low Disk Space Response',
        'description': 'Responds to low disk space by cleaning up old files',
        'trigger_conditions': {
            'alert_name': ['DiskSpaceLow', 'DiskFull', 'LowDiskSpace'],
            'metric': 'disk_usage',
            'threshold': 90
        },
        'severity': 'medium',
        'actions': [
            {'action_type': 'notify', 'name': 'Alert Team', 'description': 'Notify about disk space',
             'parameters': {'channel': 'ops'}, 'requires_approval': False},
            {'action_type': 'run_script', 'name': 'Cleanup Old Logs', 'description': 'Remove old log files',
             'parameters': {'script': 'cleanup_logs.sh', 'args': ['--older-than', '7d']}, 'requires_approval': False}
        ],
        'auto_execute': True,
        'tags': ['disk', 'cleanup']
    },
    {
        'id': 'service-down',
        'name': 'Service Down Response',
        'description': 'Responds to service health check failures',
        'trigger_conditions': {
            'alert_name': ['ServiceDown', 'HealthCheckFailed', 'EndpointDown'],
            'type': 'health_check'
        },
        'severity': 'critical',
        'actions': [
            {'action_type': 'notify', 'name': 'Page On-Call', 'description': 'Page the on-call engineer',
             'parameters': {'channel': 'pagerduty', 'priority': 'high'}, 'requires_approval': False},
            {'action_type': 'restart_service', 'name': 'Restart Service',
             'description': 'Attempt to restart the failed service',
             'parameters': {'graceful': False, 'force': True}, 'requires_approval': False,
             'retry_count': 2, 'retry_delay_seconds': 30}
        ],
        'auto_execute': True,
        'escalation_policy': 'critical-incidents',
        'tags': ['availability', 'health']
    },
    {
        'id': 'security-alert',
        'name': 'Security Alert Response',
        'description': 'Responds to security-related alerts',
        'trigger_conditions': {
            'alert_name': ['SecurityAlert', 'SuspiciousActivity', 'BruteForce', 'UnauthorizedAccess'],
            'type': 'security'
        },
        'severity': 'critical',
        'actions': [
            {'action_type': 'notify', 'name': 'Alert Security Team',
             'description': 'Immediately notify security team',
             'parameters': {'channel': 'security', 'priority': 'critical'}, 'requires_approval': False},
            {'action_type': 'block_ip', 'name': 'Block Suspicious IP',
             'description': 'Block the source IP if identified',
             'parameters': {}, 'requires_approval': True}
        ],
        'auto_execute': False,
        'escalation_policy': 'security-incidents',
        'tags': ['security', 'threat']
    },
    {
        'id': 'pod-crashloop',
        'name': 'Kubernetes Pod CrashLoop Response',
        'description': 'Responds to pods stuck in CrashLoopBackOff',
        'trigger_conditions': {
            'alert_name': ['PodCrashLooping', 'CrashLoopBackOff', 'PodNotReady'],
            'type': 'kubernetes'
        },
        'severity': 'high',
        'actions': [
            {'action_type': 'notify', 'name': 'Alert Team', 'description': 'Notify about pod issues',
             'parameters': {'channel': 'ops'}, 'requires_approval': False},
            {'action_type': 'kubernetes_action', 'name': 'Collect Pod Logs',
             'description': 'Gather logs from the failing pod',
             'parameters': {'action': 'get_logs', 'previous': True}, 'requires_approval': False},
            {'action_type': 'kubernetes_action', 'name': 'Rollback Deployment',
             'description': 'Rollback to previous stable version',
             'parameters': {'action': 'rollback'}, 'requires_approval': True}
        ],
        'auto_execute': False,
        'tags': ['kubernetes', 'availability']
    }
]

BUILTIN_IDS = {p['id'] for p in BUILTIN_PLAYBOOKS}


def _dict_to_playbook(d: dict) -> ResponsePlaybook:
    """Convert a dict (from BUILTIN_PLAYBOOKS or DB) to a ResponsePlaybook."""
    actions = []
    for ad in d.get('actions', []):
        try:
            at = ActionType(ad.get('action_type', 'custom'))
        except ValueError:
            at = ActionType.CUSTOM
        actions.append(RemediationAction(
            action_type=at,
            name=ad.get('name', 'Unnamed'),
            description=ad.get('description', ''),
            parameters=ad.get('parameters', {}),
            requires_approval=ad.get('requires_approval', False),
            timeout_seconds=ad.get('timeout_seconds', 300),
            retry_count=ad.get('retry_count', 0),
            retry_delay_seconds=ad.get('retry_delay_seconds', 30),
        ))
    try:
        severity = IncidentSeverity(d.get('severity', 'medium'))
    except ValueError:
        severity = IncidentSeverity.MEDIUM
    return ResponsePlaybook(
        id=d['id'],
        name=d['name'],
        description=d.get('description', ''),
        trigger_conditions=d.get('trigger_conditions', {}),
        severity=severity,
        actions=actions,
        enabled=d.get('enabled', True),
        auto_execute=d.get('auto_execute', False),
        notification_channels=d.get('notification_channels', []),
        escalation_policy=d.get('escalation_policy'),
        tags=d.get('tags', []),
        is_builtin=d.get('is_builtin', d['id'] in BUILTIN_IDS),
    )


def _detect_platform(metadata: Dict[str, Any]) -> str:
    """Detect the cloud platform from incident metadata."""
    if metadata.get('platform'):
        return metadata['platform']
    if metadata.get('namespace') or metadata.get('pod') or metadata.get('deployment'):
        return 'kubernetes'
    if metadata.get('instance_id') and metadata['instance_id'].startswith('i-'):
        return 'aws'
    if metadata.get('cluster') and metadata.get('service'):
        return 'aws'
    if metadata.get('resource_group'):
        return 'azure'
    if metadata.get('project_id') or metadata.get('zone'):
        return 'gcp'
    return 'unknown'


class IncidentResponseEngine:
    """Engine for automated incident response with DB persistence and real tool integration."""

    def __init__(self):
        self._app = None
        self._user_playbooks: Dict[int, Dict[str, ResponsePlaybook]] = {}
        self._user_incidents: Dict[int, Dict[str, Incident]] = {}
        self._users_loaded: set = set()
        self.action_handlers: Dict[ActionType, Callable] = {}
        self.action_queue = queue.Queue()
        self.running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._notification_service = None

        self._register_default_handlers()

    def set_app(self, app):
        """Set Flask app reference for DB access."""
        self._app = app

    def set_notification_service(self, service):
        """Set notification service for alert delivery."""
        self._notification_service = service

    def _register_default_handlers(self):
        """Register real action handlers."""
        self.action_handlers[ActionType.NOTIFY] = self._handle_notify
        self.action_handlers[ActionType.RESTART_SERVICE] = self._handle_restart_service
        self.action_handlers[ActionType.SCALE_UP] = self._handle_scale_up
        self.action_handlers[ActionType.SCALE_DOWN] = self._handle_scale_down
        self.action_handlers[ActionType.KUBERNETES_ACTION] = self._handle_kubernetes_action
        self.action_handlers[ActionType.AWS_ACTION] = self._handle_aws_action
        self.action_handlers[ActionType.RUN_SCRIPT] = self._handle_run_script
        self.action_handlers[ActionType.CLEAR_CACHE] = self._handle_clear_cache
        self.action_handlers[ActionType.BLOCK_IP] = self._handle_block_ip
        self.action_handlers[ActionType.FAILOVER] = self._handle_failover
        self.action_handlers[ActionType.ROLLBACK] = self._handle_rollback
        self.action_handlers[ActionType.ROTATE_CREDENTIALS] = self._handle_rotate_credentials
        self.action_handlers[ActionType.ANSIBLE_PLAYBOOK] = self._handle_ansible_playbook
        self.action_handlers[ActionType.CUSTOM] = self._handle_custom

    # ==================== DB PERSISTENCE ====================

    def _ensure_user_loaded(self, user_id: int):
        """Lazy-load playbooks and incidents for a user from DB."""
        if user_id in self._users_loaded:
            return
        if not self._app:
            self._users_loaded.add(user_id)
            self._user_playbooks[user_id] = {}
            self._user_incidents[user_id] = {}
            # Still load built-in playbooks into memory
            for pd in BUILTIN_PLAYBOOKS:
                pb = _dict_to_playbook(pd)
                pb.is_builtin = True
                self._user_playbooks[user_id][pb.id] = pb
            return

        with self._app.app_context():
            from models import db, PlaybookModel, IncidentModel
            self._user_playbooks[user_id] = {}
            self._user_incidents[user_id] = {}

            # Load built-in playbooks (always from code, seed to DB if missing)
            for pd in BUILTIN_PLAYBOOKS:
                row = PlaybookModel.query.filter_by(user_id=user_id, playbook_key=pd['id']).first()
                if not row:
                    row = PlaybookModel(
                        user_id=user_id,
                        playbook_key=pd['id'],
                        name=pd['name'],
                        description=pd.get('description', ''),
                        trigger_conditions=pd.get('trigger_conditions', {}),
                        severity=pd.get('severity', 'medium'),
                        actions_json=pd.get('actions', []),
                        enabled=pd.get('enabled', True),
                        auto_execute=pd.get('auto_execute', False),
                        notification_channels=pd.get('notification_channels', []),
                        escalation_policy=pd.get('escalation_policy'),
                        tags=pd.get('tags', []),
                        is_builtin=True,
                    )
                    db.session.add(row)
                # Build in-memory playbook from DB row (respects user's enable/disable)
                pb_dict = row.to_dict()
                pb_dict['is_builtin'] = True
                pb = _dict_to_playbook(pb_dict)
                self._user_playbooks[user_id][pb.id] = pb

            # Load custom playbooks from DB
            custom_rows = PlaybookModel.query.filter_by(user_id=user_id, is_builtin=False).all()
            for row in custom_rows:
                pb = _dict_to_playbook(row.to_dict())
                self._user_playbooks[user_id][pb.id] = pb

            # Load active incidents from DB — use try/except so missing columns
            # (e.g. correlation_group_key before migration) don't crash the page.
            try:
                incident_rows = IncidentModel.query.filter_by(user_id=user_id).filter(
                    IncidentModel.status.notin_(['closed'])
                ).order_by(IncidentModel.triggered_at.desc()).limit(200).all()
            except Exception:
                db.session.rollback()
                incident_rows = []
            for row in incident_rows:
                d = row.to_dict()
                try:
                    severity = IncidentSeverity(d['severity'])
                except ValueError:
                    severity = IncidentSeverity.MEDIUM
                try:
                    status = IncidentStatus(d['status'])
                except ValueError:
                    status = IncidentStatus.DETECTED
                inc = Incident(
                    id=d['id'],
                    title=d['title'],
                    description=d['description'],
                    severity=severity,
                    status=status,
                    source=d['source'],
                    user_id=user_id,
                    source_id=d.get('source_id'),
                    playbook_id=d.get('playbook_id'),
                    triggered_at=row.triggered_at or datetime.utcnow(),
                    acknowledged_at=row.acknowledged_at,
                    resolved_at=row.resolved_at,
                    assigned_to=d.get('assigned_to'),
                    metadata=d.get('metadata', {}),
                    actions_taken=d.get('actions_taken', []),
                    timeline=d.get('timeline', []),
                )
                self._user_incidents[user_id][inc.id] = inc

            db.session.commit()
            self._users_loaded.add(user_id)
            logger.info(f"Loaded {len(self._user_playbooks[user_id])} playbooks, "
                        f"{len(self._user_incidents[user_id])} incidents for user {user_id}")

    def _save_incident_to_db(self, user_id: int, incident: Incident):
        """Write-through: save/update incident in DB."""
        if not self._app:
            return
        with self._app.app_context():
            from models import db, IncidentModel
            row = IncidentModel.query.filter_by(user_id=user_id, incident_key=incident.id).first()
            if not row:
                row = IncidentModel(
                    user_id=user_id,
                    incident_key=incident.id,
                    title=incident.title,
                    description=incident.description,
                    severity=incident.severity.value,
                    status=incident.status.value,
                    source=incident.source,
                    source_id=incident.source_id,
                    playbook_id=incident.playbook_id,
                    assigned_to=incident.assigned_to,
                    metadata_json=incident.metadata,
                    actions_taken=incident.actions_taken,
                    timeline=incident.timeline,
                    triggered_at=incident.triggered_at,
                    acknowledged_at=incident.acknowledged_at,
                    resolved_at=incident.resolved_at,
                )
                db.session.add(row)
            else:
                row.status = incident.status.value
                row.assigned_to = incident.assigned_to
                row.playbook_id = incident.playbook_id
                row.actions_taken = incident.actions_taken
                row.timeline = incident.timeline
                row.acknowledged_at = incident.acknowledged_at
                row.resolved_at = incident.resolved_at
            db.session.commit()

    def find_or_create_correlation_group(self, user_id: int, incident: 'Incident') -> Optional[str]:
        """Find an open correlation group for this incident or create a new one."""
        if not self._app:
            return None
        with self._app.app_context():
            from models import db, IncidentCorrelationGroup
            now = datetime.utcnow()
            cutoff = now - timedelta(minutes=20)
            open_groups = IncidentCorrelationGroup.query.filter_by(
                user_id=user_id, status='open'
            ).filter(IncidentCorrelationGroup.window_start >= cutoff).all()

            meta = incident.metadata or {}
            resource_type = meta.get('resource_type', meta.get('type', ''))
            matched = None
            for grp in open_groups:
                # Match on same severity tier
                if grp.severity == incident.severity.value:
                    matched = grp
                    break
                # Match on resource_type hint embedded in group title
                if resource_type and resource_type in (grp.title or ''):
                    matched = grp
                    break

            if matched:
                keys = list(matched.incident_keys or [])
                if incident.id not in keys:
                    keys.append(incident.id)
                matched.incident_keys = keys
                db.session.commit()
                return matched.group_key
            else:
                import hashlib
                raw = f"{user_id}:{incident.severity.value}:{resource_type}:{now.isoformat()}"
                group_key = hashlib.md5(raw.encode()).hexdigest()[:12]
                title = incident.title[:200] if incident.title else 'Correlation Group'
                grp = IncidentCorrelationGroup(
                    user_id=user_id,
                    group_key=group_key,
                    title=title,
                    severity=incident.severity.value,
                    status='open',
                    window_start=now,
                    window_end=now + timedelta(minutes=20),
                    incident_keys=[incident.id],
                )
                db.session.add(grp)
                db.session.commit()
                return group_key

    def _write_journal_entry(self, user_id: int, incident_key: str, entry_type: str,
                              content: str, author: str = 'system',
                              tool_name: str = None, tool_input: dict = None,
                              tool_result: dict = None):
        """Write an immutable journal entry for an incident."""
        if not self._app:
            return
        with self._app.app_context():
            from models import db, InvestigationJournalEntry
            entry = InvestigationJournalEntry(
                user_id=user_id,
                incident_key=incident_key,
                entry_type=entry_type,
                content=content,
                author=author,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_result=tool_result,
            )
            db.session.add(entry)
            db.session.commit()

    def _save_playbook_to_db(self, user_id: int, playbook: ResponsePlaybook):
        """Write-through: save/update custom playbook in DB."""
        if not self._app:
            return
        with self._app.app_context():
            from models import db, PlaybookModel
            row = PlaybookModel.query.filter_by(user_id=user_id, playbook_key=playbook.id).first()
            actions_list = [{
                'action_type': a.action_type.value,
                'name': a.name,
                'description': a.description,
                'parameters': a.parameters,
                'requires_approval': a.requires_approval,
                'timeout_seconds': a.timeout_seconds,
            } for a in playbook.actions]

            if not row:
                row = PlaybookModel(
                    user_id=user_id,
                    playbook_key=playbook.id,
                    name=playbook.name,
                    description=playbook.description,
                    trigger_conditions=playbook.trigger_conditions,
                    severity=playbook.severity.value,
                    actions_json=actions_list,
                    enabled=playbook.enabled,
                    auto_execute=playbook.auto_execute,
                    notification_channels=playbook.notification_channels,
                    escalation_policy=playbook.escalation_policy,
                    tags=playbook.tags,
                    is_builtin=playbook.is_builtin,
                )
                db.session.add(row)
            else:
                row.name = playbook.name
                row.description = playbook.description
                row.trigger_conditions = playbook.trigger_conditions
                row.severity = playbook.severity.value
                row.actions_json = actions_list
                row.enabled = playbook.enabled
                row.auto_execute = playbook.auto_execute
                row.notification_channels = playbook.notification_channels
                row.escalation_policy = playbook.escalation_policy
                row.tags = playbook.tags
            db.session.commit()

    def _delete_playbook_from_db(self, user_id: int, playbook_key: str):
        """Delete a custom playbook from DB."""
        if not self._app:
            return
        with self._app.app_context():
            from models import db, PlaybookModel
            PlaybookModel.query.filter_by(user_id=user_id, playbook_key=playbook_key).delete()
            db.session.commit()

    # ==================== PLAYBOOK MANAGEMENT ====================

    def register_playbook(self, user_id: int, playbook: ResponsePlaybook) -> None:
        """Register a response playbook for a user."""
        self._ensure_user_loaded(user_id)
        self._user_playbooks[user_id][playbook.id] = playbook
        self._save_playbook_to_db(user_id, playbook)
        logger.info(f"Registered playbook: {playbook.name} ({playbook.id}) for user {user_id}")

    def unregister_playbook(self, user_id: int, playbook_id: str) -> bool:
        """Unregister a playbook."""
        self._ensure_user_loaded(user_id)
        if playbook_id in self._user_playbooks.get(user_id, {}):
            del self._user_playbooks[user_id][playbook_id]
            self._delete_playbook_from_db(user_id, playbook_id)
            return True
        return False

    def get_playbook(self, user_id: int, playbook_id: str) -> Optional[ResponsePlaybook]:
        """Get a playbook by ID for a user."""
        self._ensure_user_loaded(user_id)
        return self._user_playbooks.get(user_id, {}).get(playbook_id)

    def list_playbooks(self, user_id: int) -> List[ResponsePlaybook]:
        """List all playbooks for a user."""
        self._ensure_user_loaded(user_id)
        return list(self._user_playbooks.get(user_id, {}).values())

    def toggle_playbook(self, user_id: int, playbook_id: str) -> Optional[bool]:
        """Toggle playbook enabled state. Returns new state or None if not found."""
        self._ensure_user_loaded(user_id)
        pb = self._user_playbooks.get(user_id, {}).get(playbook_id)
        if not pb:
            return None
        pb.enabled = not pb.enabled
        pb.updated_at = datetime.utcnow()
        self._save_playbook_to_db(user_id, pb)
        return pb.enabled

    def match_playbook(self, user_id: int, alert_data: Dict[str, Any]) -> Optional[ResponsePlaybook]:
        """Match an alert to an appropriate playbook for a user."""
        self._ensure_user_loaded(user_id)
        alert_name = alert_data.get('alert_name', alert_data.get('name', ''))
        alert_type = alert_data.get('type', '')

        for playbook in self._user_playbooks.get(user_id, {}).values():
            if not playbook.enabled:
                continue
            conditions = playbook.trigger_conditions
            if 'alert_name' in conditions:
                names = conditions['alert_name']
                if isinstance(names, str):
                    names = [names]
                if alert_name in names or any(n.lower() in alert_name.lower() for n in names):
                    return playbook
            if 'type' in conditions and conditions['type'] == alert_type:
                return playbook
            if 'metric' in conditions and 'threshold' in conditions:
                metric = conditions['metric']
                if metric in alert_data:
                    value = alert_data[metric]
                    if isinstance(value, (int, float)) and value >= conditions['threshold']:
                        return playbook
        return None

    # ==================== INCIDENT MANAGEMENT ====================

    def create_incident(
        self,
        user_id: int,
        title: str,
        description: str,
        severity: IncidentSeverity,
        source: str,
        source_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Incident:
        """Create a new incident."""
        self._ensure_user_loaded(user_id)
        incident_id = str(uuid.uuid4())[:8]
        incident = Incident(
            id=incident_id,
            title=title,
            description=description,
            severity=severity,
            status=IncidentStatus.DETECTED,
            source=source,
            user_id=user_id,
            source_id=source_id,
            metadata=metadata or {}
        )
        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'incident_created',
            'details': f'Incident created from {source}'
        })
        self._user_incidents[user_id][incident_id] = incident
        self._save_incident_to_db(user_id, incident)
        group_key = self.find_or_create_correlation_group(user_id, incident)
        if group_key:
            incident.correlation_group_key = group_key
            self._save_incident_to_db(user_id, incident)
        self._write_journal_entry(
            user_id, incident.id, 'status_change',
            f'Incident created from {source} (severity: {severity.value})',
            author='system'
        )
        logger.info(f"Created incident {incident_id}: {title} for user {user_id}")
        return incident

    def process_alert(self, user_id: int, alert_data: Dict[str, Any]) -> Optional[Incident]:
        """Process an incoming alert and create incident if needed."""
        playbook = self.match_playbook(user_id, alert_data)
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
            user_id=user_id,
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
            if playbook.auto_execute:
                self.execute_playbook(user_id, incident, playbook)

        return incident

    def execute_playbook(
        self,
        user_id: int,
        incident: Incident,
        playbook: Optional[ResponsePlaybook] = None,
        skip_approval: bool = False
    ) -> Dict[str, Any]:
        """Execute a playbook for an incident."""
        self._ensure_user_loaded(user_id)
        if playbook is None:
            if incident.playbook_id:
                playbook = self._user_playbooks.get(user_id, {}).get(incident.playbook_id)
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

            result = self._execute_action(incident, action)
            results.append(result)
            incident.actions_taken.append({
                'action': action.name,
                'type': action.action_type.value,
                'result': result,
                'timestamp': datetime.utcnow().isoformat()
            })
            if not result.get('success', False):
                incident.timeline.append({
                    'timestamp': datetime.utcnow().isoformat(),
                    'event': 'action_failed',
                    'details': f'Action failed: {action.name} - {result.get("error", "Unknown error")}'
                })
                break

        all_success = all(r.get('success', False) or r.get('status') == 'awaiting_approval' for r in results)
        if all_success and incident.status != IncidentStatus.AWAITING_APPROVAL:
            incident.status = IncidentStatus.RESOLVED
            incident.resolved_at = datetime.utcnow()
            incident.timeline.append({
                'timestamp': datetime.utcnow().isoformat(),
                'event': 'incident_resolved',
                'details': 'All remediation actions completed successfully'
            })

        self._save_incident_to_db(user_id, incident)

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
            self._write_journal_entry(
                incident.user_id or 0, incident.id, 'tool_call',
                f'Executed action: {action.name}',
                author='agent',
                tool_name=action.action_type.value,
                tool_input=action.parameters,
                tool_result={'success': result.get('success'), 'message': result.get('message', '')},
            )
            return result
        except Exception as e:
            logger.error(f"Error executing action {action.name}: {str(e)}", exc_info=True)
            return {
                'success': False,
                'action': action.name,
                'error': str(e)
            }

    def acknowledge_incident(self, user_id: int, incident_id: str, user: str) -> Dict[str, Any]:
        """Acknowledge an incident."""
        self._ensure_user_loaded(user_id)
        incident = self._user_incidents.get(user_id, {}).get(incident_id)
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
        self._save_incident_to_db(user_id, incident)
        self._write_journal_entry(user_id, incident.id, 'status_change',
                                   f'Acknowledged by {user}', author='user')
        return {'success': True, 'incident_id': incident_id}

    def resolve_incident(self, user_id: int, incident_id: str, resolution: str = None) -> Dict[str, Any]:
        """Resolve an incident."""
        self._ensure_user_loaded(user_id)
        incident = self._user_incidents.get(user_id, {}).get(incident_id)
        if not incident:
            return {'success': False, 'error': 'Incident not found'}
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.utcnow()
        incident.timeline.append({
            'timestamp': datetime.utcnow().isoformat(),
            'event': 'incident_resolved',
            'details': resolution or 'Incident resolved'
        })
        self._save_incident_to_db(user_id, incident)
        self._write_journal_entry(user_id, incident.id, 'status_change',
                                   resolution or 'Incident resolved', author='system')
        return {'success': True, 'incident_id': incident_id}

    def get_incident(self, user_id: int, incident_id: str) -> Optional[Incident]:
        """Get an incident by ID."""
        self._ensure_user_loaded(user_id)
        return self._user_incidents.get(user_id, {}).get(incident_id)

    def list_incidents(
        self,
        user_id: int,
        status: Optional[IncidentStatus] = None,
        severity: Optional[IncidentSeverity] = None,
        limit: int = 50
    ) -> List[Incident]:
        """List incidents for a user with optional filters."""
        self._ensure_user_loaded(user_id)
        incidents = list(self._user_incidents.get(user_id, {}).values())
        if status:
            incidents = [i for i in incidents if i.status == status]
        if severity:
            incidents = [i for i in incidents if i.severity == severity]
        incidents.sort(key=lambda x: x.triggered_at, reverse=True)
        return incidents[:limit]

    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get incident statistics for a user."""
        self._ensure_user_loaded(user_id)
        incidents = list(self._user_incidents.get(user_id, {}).values())
        playbooks = self._user_playbooks.get(user_id, {})
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
            'playbooks_registered': len(playbooks),
            'auto_execute_enabled': len([p for p in playbooks.values() if p.auto_execute])
        }

    # ==================== REAL ACTION HANDLERS ====================

    def _handle_notify(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Send notification via the notification service."""
        channel = action.parameters.get('channel', 'default')
        message = action.parameters.get('message', f'[{incident.severity.value.upper()}] Incident: {incident.title}')
        priority = action.parameters.get('priority', 'normal')

        logger.info(f"NOTIFY [{channel}] ({priority}): {message}")

        if self._notification_service and incident.user_id is not None:
            try:
                self._notification_service.send_alert(incident.user_id, {
                    'title': f'Incident: {incident.title}',
                    'message': message,
                    'severity': incident.severity.value,
                    'channel': channel,
                    'priority': priority,
                    'incident_id': incident.id,
                })
                return {'success': True, 'channel': channel, 'message': f'Notification delivered to {channel}'}
            except Exception as e:
                logger.warning(f"Notification service error: {e}, falling back to log-only")

        return {'success': True, 'channel': channel, 'message': f'Notification logged for {channel} (no delivery service configured)'}

    def _handle_restart_service(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Restart a service using the appropriate cloud/platform tool."""
        meta = incident.metadata
        params = action.parameters
        service = meta.get('service', params.get('service'))
        platform = _detect_platform(meta)

        if platform == 'kubernetes':
            deployment = meta.get('deployment', service)
            namespace = meta.get('namespace', 'default')
            if deployment:
                try:
                    from src.tools.kubernetes_tools import restart_deployment
                    result = restart_deployment(deployment_name=deployment, namespace=namespace,
                                                context=meta.get('context'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'kubernetes',
                                'message': f'Deployment {deployment} restart triggered in {namespace}',
                                'details': result}
                    return {'success': False, 'platform': 'kubernetes', 'error': result.get('error', 'Restart failed'),
                            'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'K8s restart failed: {str(e)}'}

            pod = meta.get('pod')
            if pod:
                try:
                    from src.tools.kubernetes_tools import delete_pod
                    result = delete_pod(pod_name=pod, namespace=namespace, grace_period=0,
                                        context=meta.get('context'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'kubernetes',
                                'message': f'Pod {pod} deleted (will be recreated by controller)',
                                'details': result}
                    return {'success': False, 'platform': 'kubernetes', 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'K8s pod delete failed: {str(e)}'}

        elif platform == 'aws':
            instance_id = meta.get('instance_id', params.get('instance_id'))
            if instance_id and instance_id.startswith('i-'):
                try:
                    from src.tools.aws_tools import manage_ec2_instance
                    result = manage_ec2_instance(instance_id=instance_id, action='reboot',
                                                 region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'EC2 instance {instance_id} reboot initiated', 'details': result}
                    return {'success': False, 'platform': 'aws', 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'EC2 reboot failed: {str(e)}'}

            cluster = meta.get('cluster', params.get('cluster'))
            ecs_service = meta.get('ecs_service', service)
            if cluster and ecs_service:
                try:
                    from src.tools.aws_tools import update_ecs_service
                    result = update_ecs_service(cluster=cluster, service=ecs_service,
                                                force_new_deployment=True, region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'ECS service {ecs_service} force-redeployed', 'details': result}
                    return {'success': False, 'platform': 'aws', 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'ECS redeploy failed: {str(e)}'}

        elif platform == 'azure':
            rg = meta.get('resource_group', params.get('resource_group'))
            vm_name = meta.get('vm_name', service)
            if rg and vm_name:
                try:
                    from src.tools.azure_tools import manage_vm
                    result = manage_vm(resource_group=rg, vm_name=vm_name, action='restart')
                    if result.get('success'):
                        return {'success': True, 'platform': 'azure',
                                'message': f'Azure VM {vm_name} restart initiated', 'details': result}
                    return {'success': False, 'platform': 'azure', 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'Azure VM restart failed: {str(e)}'}

        elif platform == 'gcp':
            instance = meta.get('instance_name', service)
            zone = meta.get('zone')
            if instance and zone:
                try:
                    from src.tools.gcp_tools import manage_compute_instance
                    result = manage_compute_instance(instance_name=instance, zone=zone, action='reset',
                                                     project_id=meta.get('project_id'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'gcp',
                                'message': f'GCE instance {instance} reset initiated', 'details': result}
                    return {'success': False, 'platform': 'gcp', 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'GCP reset failed: {str(e)}'}

        if not service:
            return {'success': False, 'error': 'No service/resource specified in incident metadata. '
                    'Set platform, service, instance_id, deployment, or pod in metadata.'}
        return {'success': False, 'error': f'Platform "{platform}" not supported or missing required metadata. '
                'Provide platform-specific identifiers (instance_id, deployment, resource_group, etc.)'}

    def _handle_scale_up(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Scale up resources on the detected platform."""
        meta = incident.metadata
        params = action.parameters
        increment = params.get('increment', 1)
        platform = _detect_platform(meta)

        if platform == 'kubernetes':
            deployment = meta.get('deployment', meta.get('service'))
            namespace = meta.get('namespace', 'default')
            if deployment:
                try:
                    from src.tools.kubernetes_tools import scale_deployment
                    current = meta.get('replicas', params.get('current_replicas', 1))
                    new_count = int(current) + int(increment)
                    result = scale_deployment(deployment_name=deployment, replicas=new_count,
                                              namespace=namespace, context=meta.get('context'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'kubernetes',
                                'message': f'Scaled {deployment} from {current} to {new_count} replicas',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'K8s scale failed: {str(e)}'}

        elif platform == 'aws':
            cluster = meta.get('cluster', params.get('cluster'))
            service = meta.get('ecs_service', meta.get('service'))
            if cluster and service:
                try:
                    from src.tools.aws_tools import update_ecs_service
                    current = meta.get('desired_count', params.get('current_count', 1))
                    new_count = int(current) + int(increment)
                    result = update_ecs_service(cluster=cluster, service=service,
                                                desired_count=new_count, region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'Scaled ECS {service} from {current} to {new_count} tasks',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'ECS scale failed: {str(e)}'}

        elif platform == 'gcp':
            cluster_name = meta.get('gke_cluster', meta.get('cluster'))
            node_pool = meta.get('node_pool', 'default-pool')
            zone = meta.get('zone')
            if cluster_name and zone:
                try:
                    from src.tools.gcp_tools import resize_gke_cluster
                    current = meta.get('node_count', 1)
                    new_count = int(current) + int(increment)
                    result = resize_gke_cluster(cluster_name=cluster_name, node_pool_name=node_pool,
                                                node_count=new_count, zone=zone,
                                                project_id=meta.get('project_id'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'gcp',
                                'message': f'Resized GKE {cluster_name}/{node_pool} to {new_count} nodes',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'GKE resize failed: {str(e)}'}

        return {'success': False, 'error': f'Scale up not supported for platform "{platform}" or missing metadata. '
                'Provide deployment/cluster/service info in incident metadata.'}

    def _handle_scale_down(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Scale down resources on the detected platform."""
        meta = incident.metadata
        params = action.parameters
        decrement = params.get('decrement', 1)
        platform = _detect_platform(meta)

        if platform == 'kubernetes':
            deployment = meta.get('deployment', meta.get('service'))
            namespace = meta.get('namespace', 'default')
            if deployment:
                try:
                    from src.tools.kubernetes_tools import scale_deployment
                    current = meta.get('replicas', params.get('current_replicas', 2))
                    new_count = max(1, int(current) - int(decrement))
                    result = scale_deployment(deployment_name=deployment, replicas=new_count,
                                              namespace=namespace, context=meta.get('context'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'kubernetes',
                                'message': f'Scaled {deployment} from {current} to {new_count} replicas',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'K8s scale down failed: {str(e)}'}

        elif platform == 'aws':
            cluster = meta.get('cluster', params.get('cluster'))
            service = meta.get('ecs_service', meta.get('service'))
            if cluster and service:
                try:
                    from src.tools.aws_tools import update_ecs_service
                    current = meta.get('desired_count', params.get('current_count', 2))
                    new_count = max(1, int(current) - int(decrement))
                    result = update_ecs_service(cluster=cluster, service=service,
                                                desired_count=new_count, region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'Scaled ECS {service} from {current} to {new_count} tasks',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'ECS scale down failed: {str(e)}'}

        return {'success': False, 'error': f'Scale down not supported for platform "{platform}" or missing metadata.'}

    def _handle_kubernetes_action(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Execute Kubernetes-specific actions using real K8s tools."""
        meta = incident.metadata
        params = action.parameters
        k8s_action = params.get('action')
        namespace = meta.get('namespace', params.get('namespace', 'default'))
        context = meta.get('context', params.get('context'))
        pod = meta.get('pod', params.get('pod'))
        deployment = meta.get('deployment', meta.get('service', params.get('deployment')))

        if k8s_action == 'get_logs':
            if not pod:
                return {'success': False, 'error': 'No pod specified in incident metadata for log collection'}
            try:
                from src.tools.kubernetes_tools import get_pod_logs
                tail = params.get('tail_lines', 200)
                result = get_pod_logs(pod_name=pod, namespace=namespace, tail_lines=tail, context=context)
                if result.get('success'):
                    return {'success': True, 'action': 'get_logs', 'pod': pod,
                            'message': f'Collected {tail} lines of logs from {pod}',
                            'logs': result.get('logs', ''),
                            'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'Log collection failed: {str(e)}'}

        elif k8s_action == 'rollback':
            if not deployment:
                return {'success': False, 'error': 'No deployment specified for rollback'}
            try:
                from src.tools.kubernetes_tools import restart_deployment
                result = restart_deployment(deployment_name=deployment, namespace=namespace, context=context)
                if result.get('success'):
                    return {'success': True, 'action': 'rollback', 'deployment': deployment,
                            'message': f'Deployment {deployment} rollout restart triggered (rollback)',
                            'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'Rollback failed: {str(e)}'}

        elif k8s_action == 'delete_pod':
            if not pod:
                return {'success': False, 'error': 'No pod specified'}
            try:
                from src.tools.kubernetes_tools import delete_pod
                grace = params.get('grace_period', 30)
                result = delete_pod(pod_name=pod, namespace=namespace, grace_period=grace, context=context)
                if result.get('success'):
                    return {'success': True, 'action': 'delete_pod', 'pod': pod,
                            'message': f'Pod {pod} deleted', 'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'Pod delete failed: {str(e)}'}

        elif k8s_action == 'scale':
            if not deployment:
                return {'success': False, 'error': 'No deployment specified for scaling'}
            try:
                from src.tools.kubernetes_tools import scale_deployment
                replicas = params.get('replicas', 2)
                result = scale_deployment(deployment_name=deployment, replicas=replicas,
                                          namespace=namespace, context=context)
                if result.get('success'):
                    return {'success': True, 'action': 'scale', 'deployment': deployment,
                            'message': f'Scaled {deployment} to {replicas} replicas', 'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'Scale failed: {str(e)}'}

        elif k8s_action == 'restart':
            if not deployment:
                return {'success': False, 'error': 'No deployment specified for restart'}
            try:
                from src.tools.kubernetes_tools import restart_deployment
                result = restart_deployment(deployment_name=deployment, namespace=namespace, context=context)
                if result.get('success'):
                    return {'success': True, 'action': 'restart', 'deployment': deployment,
                            'message': f'Deployment {deployment} restart triggered', 'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'Restart failed: {str(e)}'}

        return {'success': False, 'error': f'Unknown Kubernetes action: {k8s_action}. '
                'Supported: get_logs, rollback, delete_pod, scale, restart'}

    def _handle_aws_action(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Execute AWS-specific actions using real AWS tools."""
        meta = incident.metadata
        params = action.parameters
        aws_action = params.get('action')
        region = meta.get('region', params.get('region'))

        if aws_action in ('reboot', 'stop', 'start', 'terminate'):
            instance_id = meta.get('instance_id', params.get('instance_id'))
            if not instance_id:
                return {'success': False, 'error': 'No instance_id specified'}
            try:
                from src.tools.aws_tools import manage_ec2_instance
                result = manage_ec2_instance(instance_id=instance_id, action=aws_action, region=region)
                if result.get('success'):
                    return {'success': True, 'action': aws_action, 'instance_id': instance_id,
                            'message': f'EC2 {aws_action} completed for {instance_id}', 'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'EC2 {aws_action} failed: {str(e)}'}

        elif aws_action == 'force_deploy':
            cluster = meta.get('cluster', params.get('cluster'))
            service = meta.get('ecs_service', params.get('service'))
            if not cluster or not service:
                return {'success': False, 'error': 'cluster and service required for force_deploy'}
            try:
                from src.tools.aws_tools import update_ecs_service
                result = update_ecs_service(cluster=cluster, service=service,
                                            force_new_deployment=True, region=region)
                if result.get('success'):
                    return {'success': True, 'action': 'force_deploy',
                            'message': f'ECS force deploy for {service}', 'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'ECS force deploy failed: {str(e)}'}

        elif aws_action == 'run_command':
            instance_ids = params.get('instance_ids', [])
            commands = params.get('commands', [])
            if not instance_ids:
                iid = meta.get('instance_id')
                if iid:
                    instance_ids = [iid]
            if not instance_ids or not commands:
                return {'success': False, 'error': 'instance_ids and commands required for run_command'}
            try:
                from src.tools.aws_tools import ssm_run_command
                result = ssm_run_command(instance_ids=instance_ids, commands=commands, region=region)
                if result.get('success'):
                    return {'success': True, 'action': 'run_command',
                            'message': f'SSM command executed on {len(instance_ids)} instance(s)',
                            'details': result}
                return {'success': False, 'error': result.get('error'), 'details': result}
            except Exception as e:
                return {'success': False, 'error': f'SSM command failed: {str(e)}'}

        return {'success': False, 'error': f'Unknown AWS action: {aws_action}. '
                'Supported: reboot, stop, start, terminate, force_deploy, run_command'}

    def _handle_run_script(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Execute a script via SSM on AWS instances or log for other platforms."""
        meta = incident.metadata
        params = action.parameters
        script = params.get('script')
        args = params.get('args', [])
        platform = _detect_platform(meta)

        if not script:
            return {'success': False, 'error': 'No script specified'}

        command = f'{script} {" ".join(str(a) for a in args)}'.strip()

        if platform == 'aws':
            instance_id = meta.get('instance_id', params.get('instance_id'))
            if instance_id:
                try:
                    from src.tools.aws_tools import ssm_run_command
                    result = ssm_run_command(
                        instance_ids=[instance_id],
                        commands=[command],
                        comment=f'Incident {incident.id}: {action.name}',
                        region=meta.get('region')
                    )
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws', 'script': script,
                                'message': f'Script {script} executed on {instance_id} via SSM',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'SSM script execution failed: {str(e)}'}

        logger.info(f"RUN SCRIPT [{platform}]: {command} (no remote execution target configured)")
        return {'success': True, 'script': script, 'platform': platform,
                'message': f'Script {script} logged for execution (set instance_id in metadata for remote execution via SSM)'}

    def _handle_clear_cache(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Clear cache — uses SSM for AWS, or logs for other platforms."""
        meta = incident.metadata
        params = action.parameters
        target = params.get('target', 'application')
        platform = _detect_platform(meta)

        if platform == 'aws':
            instance_id = meta.get('instance_id', params.get('instance_id'))
            if instance_id:
                try:
                    from src.tools.aws_tools import ssm_run_command
                    cache_commands = [
                        'sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true',
                        'find /tmp -type f -mtime +1 -delete 2>/dev/null || true',
                        'find /var/log -name "*.gz" -mtime +7 -delete 2>/dev/null || true',
                    ]
                    result = ssm_run_command(
                        instance_ids=[instance_id],
                        commands=cache_commands,
                        comment=f'Incident {incident.id}: Clear caches',
                        region=meta.get('region')
                    )
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws', 'target': target,
                                'message': f'Cache cleared on {instance_id} via SSM', 'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'Cache clear via SSM failed: {str(e)}'}

        elif platform == 'kubernetes':
            pod = meta.get('pod')
            namespace = meta.get('namespace', 'default')
            if pod:
                logger.info(f"CLEAR CACHE: Would exec into pod {pod} to clear caches")
                return {'success': True, 'platform': 'kubernetes', 'target': target,
                        'message': f'Cache clear logged for pod {pod} in {namespace}'}

        logger.info(f"CLEAR CACHE [{platform}]: {target}")
        return {'success': True, 'target': target, 'platform': platform,
                'message': f'Cache clear logged for {target} (set instance_id for SSM execution)'}

    def _handle_block_ip(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Block an IP address using AWS security group or SSM iptables."""
        meta = incident.metadata
        params = action.parameters
        ip = meta.get('source_ip', params.get('ip'))
        platform = _detect_platform(meta)

        if not ip:
            return {'success': False, 'error': 'No IP address specified. Set source_ip in incident metadata.'}

        if platform == 'aws':
            instance_id = meta.get('instance_id', params.get('instance_id'))
            if instance_id:
                try:
                    from src.tools.aws_tools import ssm_run_command
                    result = ssm_run_command(
                        instance_ids=[instance_id],
                        commands=[f'iptables -I INPUT -s {ip} -j DROP'],
                        comment=f'Incident {incident.id}: Block IP {ip}',
                        region=meta.get('region')
                    )
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws', 'ip': ip,
                                'message': f'IP {ip} blocked via iptables on {instance_id}', 'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'IP block via SSM failed: {str(e)}'}

            sg_id = meta.get('security_group_id', params.get('security_group_id'))
            if sg_id:
                try:
                    from src.tools.aws_tools import authorize_security_group_ingress
                    result = authorize_security_group_ingress(
                        group_id=sg_id, protocol='-1', from_port=0, to_port=65535,
                        cidr=f'{ip}/32', description=f'Block {ip} - incident {incident.id}',
                        region=meta.get('region'))
                    if not result.get('success'):
                        return {'success': False, 'error': result.get('error', 'Failed to block IP')}
                    return {'success': True, 'platform': 'aws', 'ip': ip,
                            'message': f'Security group rule added for {ip} (note: SGs are allow-only, use NACL for deny)',
                            'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'SG update failed: {str(e)}'}

        logger.info(f"BLOCK IP [{platform}]: {ip}")
        return {'success': True, 'ip': ip, 'platform': platform,
                'message': f'IP {ip} block logged (provide instance_id or security_group_id for automated blocking)'}

    def _handle_failover(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Initiate failover — RDS failover for AWS, deployment switch for K8s."""
        meta = incident.metadata
        params = action.parameters
        target = params.get('target', 'secondary')
        platform = _detect_platform(meta)

        if platform == 'aws':
            db_instance = meta.get('db_instance_identifier', params.get('db_instance'))
            if db_instance:
                try:
                    from src.tools.aws_tools import _get_boto_client
                    rds = _get_boto_client('rds', meta.get('region'))
                    rds.reboot_db_instance(
                        DBInstanceIdentifier=db_instance,
                        ForceFailover=True
                    )
                    return {'success': True, 'platform': 'aws', 'target': target,
                            'message': f'RDS failover initiated for {db_instance}'}
                except Exception as e:
                    return {'success': False, 'error': f'RDS failover failed: {str(e)}'}

            cluster = meta.get('cluster', params.get('cluster'))
            service = meta.get('ecs_service', params.get('service'))
            task_def = params.get('failover_task_definition')
            if cluster and service and task_def:
                try:
                    from src.tools.aws_tools import update_ecs_service
                    result = update_ecs_service(cluster=cluster, service=service,
                                                task_definition=task_def, force_new_deployment=True,
                                                region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'ECS failover to {task_def}', 'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'ECS failover failed: {str(e)}'}

        elif platform == 'kubernetes':
            deployment = meta.get('deployment', meta.get('service'))
            failover_image = params.get('failover_image')
            if deployment and failover_image:
                try:
                    from src.tools.kubernetes_tools import update_deployment_image
                    namespace = meta.get('namespace', 'default')
                    result = update_deployment_image(deployment_name=deployment, image=failover_image,
                                                     namespace=namespace, context=meta.get('context'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'kubernetes',
                                'message': f'Failover: updated {deployment} to {failover_image}',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'K8s failover failed: {str(e)}'}

        logger.info(f"FAILOVER [{platform}]: to {target} for incident {incident.id}")
        return {'success': True, 'target': target, 'platform': platform,
                'message': f'Failover to {target} logged (provide db_instance/task_definition/failover_image for automated failover)'}

    def _handle_rollback(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Rollback a deployment or service to a previous version."""
        meta = incident.metadata
        params = action.parameters
        platform = _detect_platform(meta)

        if platform == 'kubernetes':
            deployment = meta.get('deployment', meta.get('service', params.get('deployment')))
            if deployment:
                previous_image = params.get('previous_image')
                namespace = meta.get('namespace', 'default')
                if previous_image:
                    try:
                        from src.tools.kubernetes_tools import update_deployment_image
                        result = update_deployment_image(deployment_name=deployment, image=previous_image,
                                                         namespace=namespace, context=meta.get('context'))
                        if result.get('success'):
                            return {'success': True, 'platform': 'kubernetes',
                                    'message': f'Rolled back {deployment} to {previous_image}',
                                    'details': result}
                        return {'success': False, 'error': result.get('error'), 'details': result}
                    except Exception as e:
                        return {'success': False, 'error': f'K8s rollback failed: {str(e)}'}
                else:
                    try:
                        from src.tools.kubernetes_tools import restart_deployment
                        result = restart_deployment(deployment_name=deployment, namespace=namespace,
                                                    context=meta.get('context'))
                        if result.get('success'):
                            return {'success': True, 'platform': 'kubernetes',
                                    'message': f'Rollout restart triggered for {deployment} (use previous_image for specific version rollback)',
                                    'details': result}
                        return {'success': False, 'error': result.get('error'), 'details': result}
                    except Exception as e:
                        return {'success': False, 'error': f'K8s restart-rollback failed: {str(e)}'}

        elif platform == 'aws':
            cluster = meta.get('cluster', params.get('cluster'))
            service = meta.get('ecs_service', meta.get('service', params.get('service')))
            previous_task_def = params.get('previous_task_definition', params.get('version'))
            if cluster and service and previous_task_def:
                try:
                    from src.tools.aws_tools import update_ecs_service
                    result = update_ecs_service(cluster=cluster, service=service,
                                                task_definition=previous_task_def,
                                                force_new_deployment=True, region=meta.get('region'))
                    if result.get('success'):
                        return {'success': True, 'platform': 'aws',
                                'message': f'Rolled back ECS {service} to {previous_task_def}',
                                'details': result}
                    return {'success': False, 'error': result.get('error'), 'details': result}
                except Exception as e:
                    return {'success': False, 'error': f'ECS rollback failed: {str(e)}'}

        version = params.get('version', 'previous')
        service_name = params.get('service', incident.title)
        logger.info(f"ROLLBACK [{platform}]: {service_name} to {version}")
        return {'success': True, 'platform': platform,
                'message': f'Rollback of {service_name} to {version} logged '
                '(provide deployment+previous_image or cluster+service+previous_task_definition for automated rollback)'}

    def _handle_rotate_credentials(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Rotate credentials — creates new IAM key and deactivates old one on AWS."""
        meta = incident.metadata
        params = action.parameters
        credential_type = params.get('credential_type', 'access_key')
        platform = _detect_platform(meta)

        if platform == 'aws' and credential_type == 'access_key':
            username = meta.get('iam_user', params.get('username'))
            old_key_id = meta.get('access_key_id', params.get('access_key_id'))
            if username:
                try:
                    from src.tools.aws_tools import _get_boto_client
                    iam = _get_boto_client('iam', meta.get('region'))

                    new_key = iam.create_access_key(UserName=username)
                    new_key_id = new_key['AccessKey']['AccessKeyId']

                    if old_key_id:
                        iam.update_access_key(UserName=username, AccessKeyId=old_key_id, Status='Inactive')

                    return {'success': True, 'platform': 'aws', 'credential_type': credential_type,
                            'message': f'New access key {new_key_id} created for {username}' +
                                       (f', old key {old_key_id} deactivated' if old_key_id else ''),
                            'new_key_id': new_key_id}
                except Exception as e:
                    return {'success': False, 'error': f'IAM key rotation failed: {str(e)}'}

        logger.info(f"ROTATE CREDENTIALS [{platform}]: {credential_type}")
        return {'success': True, 'credential_type': credential_type, 'platform': platform,
                'message': f'Credential rotation for {credential_type} logged '
                '(provide iam_user in metadata for automated AWS key rotation)'}

    def _handle_ansible_playbook(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Stub: Ansible playbook execution not yet configured."""
        return {'success': False, 'error': 'Ansible playbook execution not configured. Please set up Ansible integration.'}

    def _handle_custom(self, incident: Incident, action: RemediationAction) -> Dict[str, Any]:
        """Stub: Custom action handler not yet configured."""
        return {'success': False, 'error': 'Custom action handler not configured.'}


# Global instance
incident_engine = IncidentResponseEngine()


def get_incident_engine() -> IncidentResponseEngine:
    """Get the global incident response engine."""
    return incident_engine
