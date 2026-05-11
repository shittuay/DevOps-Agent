"""
Proactive Monitoring Service for DevOps Agent.

Monitors infrastructure metrics and triggers alerts based on configurable rules.
Integrates with the incident response system for automated remediation.
Persists rules and alerts to DB with per-user isolation.
"""

import os
import threading
import time
import logging
from collections import deque
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
import uuid
import requests

logger = logging.getLogger(__name__)


class MetricSource(Enum):
    """Supported metric sources."""
    PROMETHEUS = "prometheus"
    CLOUDWATCH = "cloudwatch"
    DATADOG = "datadog"
    CUSTOM = "custom"


class AlertCondition(Enum):
    """Alert condition operators."""
    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"
    EQUAL = "eq"
    NOT_EQUAL = "ne"


class AlertState(Enum):
    """Alert states."""
    OK = "ok"
    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"


@dataclass
class MonitoringRuleState:
    """In-memory runtime state for a monitoring rule."""
    id: str
    name: str
    description: str
    source: MetricSource
    query: str
    condition: AlertCondition
    threshold: float
    duration_seconds: int = 60
    severity: str = "medium"
    labels: dict = field(default_factory=dict)
    enabled: bool = True
    check_interval_seconds: int = 30
    state: AlertState = AlertState.OK
    last_value: Optional[float] = None
    last_check: Optional[datetime] = None
    pending_since: Optional[datetime] = None
    firing_since: Optional[datetime] = None
    db_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source.value if isinstance(self.source, MetricSource) else self.source,
            "query": self.query,
            "condition": self.condition.value if isinstance(self.condition, AlertCondition) else self.condition,
            "threshold": self.threshold,
            "duration_seconds": self.duration_seconds,
            "severity": self.severity,
            "labels": self.labels,
            "enabled": self.enabled,
            "check_interval_seconds": self.check_interval_seconds,
            "state": self.state.value if isinstance(self.state, AlertState) else self.state,
            "last_value": self.last_value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "pending_since": self.pending_since.isoformat() if self.pending_since else None,
            "firing_since": self.firing_since.isoformat() if self.firing_since else None,
        }


@dataclass
class MonitoringAlertState:
    """In-memory runtime state for an alert."""
    id: str
    rule_id: str
    rule_name: str
    severity: str
    value: float
    threshold: float
    condition: str
    message: str
    labels: dict
    fired_at: datetime
    resolved_at: Optional[datetime] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    incident_id: Optional[str] = None
    db_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "value": self.value,
            "threshold": self.threshold,
            "condition": self.condition,
            "message": self.message,
            "labels": self.labels,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "incident_id": self.incident_id,
        }


class MetricCollector:
    """Collects metrics from various sources."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._collectors = {
            MetricSource.PROMETHEUS: self._collect_prometheus,
            MetricSource.CLOUDWATCH: self._collect_cloudwatch,
            MetricSource.DATADOG: self._collect_datadog,
            MetricSource.CUSTOM: self._collect_custom,
        }

    def collect(self, source: MetricSource, query: str) -> Optional[float]:
        collector = self._collectors.get(source)
        if not collector:
            logger.error(f"Unknown metric source: {source}")
            return None
        try:
            return collector(query)
        except Exception as e:
            logger.error(f"Failed to collect metric from {source.value}: {e}")
            return None

    def _collect_prometheus(self, query: str) -> Optional[float]:
        prometheus_url = os.environ.get('PROMETHEUS_URL', self.config.get("prometheus_url", "http://localhost:9090"))
        try:
            response = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={"query": query},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
                results = data.get("data", {}).get("result", [])
                if results:
                    value = results[0].get("value", [None, None])[1]
                    return float(value) if value is not None else None
            return None
        except requests.RequestException as e:
            logger.warning(f"Prometheus query failed: {e}")
            return None

    def _collect_cloudwatch(self, query: str) -> Optional[float]:
        try:
            import boto3
            parts = query.split("/")
            if len(parts) < 3:
                logger.error(f"Invalid CloudWatch query format: {query}")
                return None
            namespace, metric_name, dimension_str = parts[0], parts[1], parts[2]
            dimensions = []
            if dimension_str:
                for dim in dimension_str.split(","):
                    if "=" in dim:
                        name, value = dim.split("=", 1)
                        dimensions.append({"Name": name, "Value": value})
            client = boto3.client("cloudwatch")
            response = client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=datetime.utcnow() - timedelta(minutes=5),
                EndTime=datetime.utcnow(),
                Period=60,
                Statistics=["Average"]
            )
            datapoints = response.get("Datapoints", [])
            if datapoints:
                sorted_points = sorted(datapoints, key=lambda x: x["Timestamp"], reverse=True)
                return sorted_points[0].get("Average")
            return None
        except Exception as e:
            logger.warning(f"CloudWatch query failed: {e}")
            return None

    def _collect_datadog(self, query: str) -> Optional[float]:
        api_key = self.config.get("datadog_api_key")
        app_key = self.config.get("datadog_app_key")
        if not api_key or not app_key:
            logger.warning("Datadog credentials not configured")
            return None
        try:
            now = int(time.time())
            response = requests.get(
                "https://api.datadoghq.com/api/v1/query",
                params={"query": query, "from": now - 300, "to": now},
                headers={"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            series = data.get("series", [])
            if series and series[0].get("pointlist"):
                points = series[0]["pointlist"]
                return float(points[-1][1]) if points else None
            return None
        except requests.RequestException as e:
            logger.warning(f"Datadog query failed: {e}")
            return None

    def _collect_custom(self, query: str) -> Optional[float]:
        custom_handlers = self.config.get("custom_handlers", {})
        handler = custom_handlers.get(query)
        if callable(handler):
            try:
                return float(handler())
            except Exception as e:
                logger.warning(f"Custom metric collection failed: {e}")
                return None
        return None


# Default rule definitions (seeded per-user on first access)
DEFAULT_RULES = [
    dict(rule_key="cpu-high", name="High CPU Usage",
         description="Alert when CPU usage exceeds 80%",
         source="prometheus",
         query='100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
         condition="gt", threshold=80.0, duration_seconds=120, severity="high",
         labels={"category": "performance", "component": "cpu"}),
    dict(rule_key="memory-high", name="High Memory Usage",
         description="Alert when memory usage exceeds 85%",
         source="prometheus",
         query='(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
         condition="gt", threshold=85.0, duration_seconds=120, severity="high",
         labels={"category": "performance", "component": "memory"}),
    dict(rule_key="disk-high", name="High Disk Usage",
         description="Alert when disk usage exceeds 90%",
         source="prometheus",
         query='(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100',
         condition="gt", threshold=90.0, duration_seconds=60, severity="critical",
         labels={"category": "storage", "component": "disk"}),
    dict(rule_key="http-errors-high", name="High HTTP Error Rate",
         description="Alert when HTTP 5xx error rate exceeds 5%",
         source="prometheus",
         query='sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100',
         condition="gt", threshold=5.0, duration_seconds=60, severity="critical",
         labels={"category": "availability", "component": "http"}),
    dict(rule_key="response-time-high", name="High Response Time",
         description="Alert when p95 response time exceeds 2 seconds",
         source="prometheus",
         query='histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))',
         condition="gt", threshold=2.0, duration_seconds=120, severity="medium",
         labels={"category": "performance", "component": "latency"}),
    dict(rule_key="pod-restarts-high", name="High Pod Restart Rate",
         description="Alert when pod restarts exceed 5 in 10 minutes",
         source="prometheus",
         query='sum(increase(kube_pod_container_status_restarts_total[10m]))',
         condition="gt", threshold=5.0, duration_seconds=30, severity="high",
         labels={"category": "kubernetes", "component": "pods"}),
    dict(rule_key="pending-pods", name="Pending Pods",
         description="Alert when there are pending pods for more than 5 minutes",
         source="prometheus",
         query='sum(kube_pod_status_phase{phase="Pending"})',
         condition="gt", threshold=0, duration_seconds=300, severity="medium",
         labels={"category": "kubernetes", "component": "pods"}),
    dict(rule_key="node-not-ready", name="Node Not Ready",
         description="Alert when a Kubernetes node is not ready",
         source="prometheus",
         query='sum(kube_node_status_condition{condition="Ready",status="false"})',
         condition="gt", threshold=0, duration_seconds=60, severity="critical",
         labels={"category": "kubernetes", "component": "nodes"}),
]


class ProactiveMonitoringService:
    """
    Proactive monitoring service with DB persistence and per-user isolation.

    Rules and alerts are stored in the database and cached in memory.
    The daemon thread checks all loaded users' rules periodically.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.collector = MetricCollector(config)
        self._user_rules: dict[int, dict[str, MonitoringRuleState]] = {}
        self._user_alerts: dict[int, dict[str, MonitoringAlertState]] = {}
        self._user_alert_history: dict[int, deque] = {}
        self._users_loaded: set[int] = set()
        self._max_alert_history = 500
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._alert_callbacks: list[Callable] = []
        self._incident_engine = None
        self._app = None
        self._flush_counter = 0

    def set_app(self, app):
        """Set Flask app reference for DB access in daemon thread."""
        self._app = app

    def set_incident_engine(self, engine):
        """Set the incident response engine for integration."""
        self._incident_engine = engine

    def add_alert_callback(self, callback: Callable):
        """Add a callback for alert events: callback(event_type, alert_dict, user_id=None)."""
        self._alert_callbacks.append(callback)

    # ---- User loading and seeding ----

    def _ensure_user_loaded(self, user_id: int):
        """Load user's rules from DB into memory if not already loaded."""
        if user_id in self._users_loaded:
            return
        if not self._app:
            return

        with self._app.app_context():
            from models import MonitoringRuleModel, MonitoringAlertModel, db

            db_rules = MonitoringRuleModel.query.filter_by(user_id=user_id).all()

            if not db_rules:
                self._seed_default_rules(user_id)
                db_rules = MonitoringRuleModel.query.filter_by(user_id=user_id).all()

            self._user_rules[user_id] = {}
            for r in db_rules:
                state = MonitoringRuleState(
                    id=r.rule_key, name=r.name, description=r.description or '',
                    source=MetricSource(r.source), query=r.metric_query,
                    condition=AlertCondition(r.condition), threshold=r.threshold,
                    duration_seconds=r.duration_seconds, severity=r.severity,
                    labels=r.labels or {}, enabled=r.enabled,
                    check_interval_seconds=r.check_interval_seconds,
                    state=AlertState(r.state or 'ok'),
                    last_value=r.last_value, last_check=r.last_check,
                    db_id=r.id,
                )
                self._user_rules[user_id][r.rule_key] = state

            self._user_alerts[user_id] = {}
            db_alerts = MonitoringAlertModel.query.filter_by(
                user_id=user_id, resolved_at=None
            ).all()
            for a in db_alerts:
                alert_state = MonitoringAlertState(
                    id=a.alert_key, rule_id=a.rule_key, rule_name=a.rule_name,
                    severity=a.severity, value=a.value, threshold=a.threshold,
                    condition=a.condition or '', message=a.message or '',
                    labels=a.labels or {}, fired_at=a.fired_at,
                    resolved_at=a.resolved_at, acknowledged=a.acknowledged,
                    acknowledged_by=a.acknowledged_by, incident_id=a.incident_id,
                    db_id=a.id,
                )
                self._user_alerts[user_id][a.alert_key] = alert_state

            self._user_alert_history.setdefault(user_id, deque(maxlen=self._max_alert_history))
            self._users_loaded.add(user_id)

    def _seed_default_rules(self, user_id: int):
        """Insert default monitoring rules into DB for a new user."""
        from models import MonitoringRuleModel, db

        for rd in DEFAULT_RULES:
            rule = MonitoringRuleModel(
                user_id=user_id,
                rule_key=rd['rule_key'], name=rd['name'],
                description=rd.get('description', ''),
                source=rd['source'], metric_query=rd['query'],
                condition=rd['condition'], threshold=rd['threshold'],
                duration_seconds=rd.get('duration_seconds', 60),
                severity=rd.get('severity', 'medium'),
                labels=rd.get('labels', {}),
                enabled=False, check_interval_seconds=30,
            )
            db.session.add(rule)
        db.session.commit()

    # ---- Public API (all user-scoped) ----

    def add_rule(self, user_id: int, rule_state: MonitoringRuleState) -> str:
        """Add a monitoring rule for a user (persists to DB)."""
        self._ensure_user_loaded(user_id)

        with self._app.app_context():
            from models import MonitoringRuleModel, db

            db_rule = MonitoringRuleModel(
                user_id=user_id,
                rule_key=rule_state.id, name=rule_state.name,
                description=rule_state.description,
                source=rule_state.source.value if isinstance(rule_state.source, MetricSource) else rule_state.source,
                metric_query=rule_state.query,
                condition=rule_state.condition.value if isinstance(rule_state.condition, AlertCondition) else rule_state.condition,
                threshold=rule_state.threshold,
                duration_seconds=rule_state.duration_seconds,
                severity=rule_state.severity,
                labels=rule_state.labels,
                enabled=rule_state.enabled,
                check_interval_seconds=rule_state.check_interval_seconds,
            )
            db.session.add(db_rule)
            db.session.commit()
            rule_state.db_id = db_rule.id

        self._user_rules.setdefault(user_id, {})[rule_state.id] = rule_state
        logger.info(f"Added monitoring rule '{rule_state.name}' for user {user_id}")
        return rule_state.id

    def remove_rule(self, user_id: int, rule_key: str) -> bool:
        """Remove a monitoring rule (deletes from DB)."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        if rule_key not in rules:
            return False

        with self._app.app_context():
            from models import MonitoringRuleModel, db
            MonitoringRuleModel.query.filter_by(user_id=user_id, rule_key=rule_key).delete()
            db.session.commit()

        del rules[rule_key]
        logger.info(f"Removed monitoring rule '{rule_key}' for user {user_id}")
        return True

    def enable_rule(self, user_id: int, rule_key: str) -> bool:
        """Enable a monitoring rule."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        if rule_key not in rules:
            return False

        rules[rule_key].enabled = True
        with self._app.app_context():
            from models import MonitoringRuleModel, db
            MonitoringRuleModel.query.filter_by(
                user_id=user_id, rule_key=rule_key
            ).update({'enabled': True})
            db.session.commit()
        return True

    def disable_rule(self, user_id: int, rule_key: str) -> bool:
        """Disable a monitoring rule."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        if rule_key not in rules:
            return False

        rules[rule_key].enabled = False
        with self._app.app_context():
            from models import MonitoringRuleModel, db
            MonitoringRuleModel.query.filter_by(
                user_id=user_id, rule_key=rule_key
            ).update({'enabled': False})
            db.session.commit()
        return True

    def enable_all_rules(self, user_id: int):
        """Enable all monitoring rules for a user."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        for rule in rules.values():
            rule.enabled = True
        with self._app.app_context():
            from models import MonitoringRuleModel, db
            MonitoringRuleModel.query.filter_by(user_id=user_id).update({'enabled': True})
            db.session.commit()

    def disable_all_rules(self, user_id: int):
        """Disable all monitoring rules for a user."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        for rule in rules.values():
            rule.enabled = False
        with self._app.app_context():
            from models import MonitoringRuleModel, db
            MonitoringRuleModel.query.filter_by(user_id=user_id).update({'enabled': False})
            db.session.commit()

    def get_rules(self, user_id: int) -> list[dict]:
        """Get all monitoring rules for a user."""
        self._ensure_user_loaded(user_id)
        return [r.to_dict() for r in self._user_rules.get(user_id, {}).values()]

    def get_active_alerts(self, user_id: int) -> list[dict]:
        """Get active (unresolved) alerts for a user."""
        self._ensure_user_loaded(user_id)
        return [
            a.to_dict()
            for a in self._user_alerts.get(user_id, {}).values()
            if a.resolved_at is None
        ]

    def get_alert_history(self, user_id: int, limit: int = 100) -> list[dict]:
        """Get alert history for a user (from DB for full history)."""
        self._ensure_user_loaded(user_id)

        with self._app.app_context():
            from models import MonitoringAlertModel
            db_alerts = MonitoringAlertModel.query.filter_by(user_id=user_id).order_by(
                MonitoringAlertModel.fired_at.desc()
            ).limit(limit).all()
            return [a.to_dict() for a in db_alerts]

    def acknowledge_alert(self, user_id: int, alert_key: str, user_email: str) -> bool:
        """Acknowledge an alert."""
        self._ensure_user_loaded(user_id)
        alerts = self._user_alerts.get(user_id, {})
        if alert_key not in alerts:
            return False

        alerts[alert_key].acknowledged = True
        alerts[alert_key].acknowledged_by = user_email

        with self._app.app_context():
            from models import MonitoringAlertModel, db
            MonitoringAlertModel.query.filter_by(
                user_id=user_id, alert_key=alert_key
            ).update({'acknowledged': True, 'acknowledged_by': user_email})
            db.session.commit()
        return True

    def check_now(self, user_id: int, rule_key: str = None) -> dict:
        """Immediately check a specific rule or all rules for a user."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        results = {}

        if rule_key and rule_key not in rules:
            return {"error": f"Rule {rule_key!r} not found"}

        rules_to_check = [rules[rule_key]] if rule_key else list(rules.values())

        for rule in rules_to_check:
            if rule.enabled:
                try:
                    self._check_rule(user_id, rule)
                    results[rule.id] = {
                        "name": rule.name,
                        "state": rule.state.value if isinstance(rule.state, AlertState) else rule.state,
                        "last_value": rule.last_value,
                        "threshold": rule.threshold,
                    }
                except Exception as e:
                    results[rule.id] = {"error": str(e)}
        return results

    def get_status(self, user_id: int) -> dict:
        """Get monitoring status for a user (per-user, not global)."""
        self._ensure_user_loaded(user_id)
        rules = self._user_rules.get(user_id, {})
        alerts = self._user_alerts.get(user_id, {})
        user_has_enabled_rules = any(r.enabled for r in rules.values())
        return {
            "running": user_has_enabled_rules,
            "rules_total": len(rules),
            "rules_enabled": sum(1 for r in rules.values() if r.enabled),
            "alerts_active": len([a for a in alerts.values() if a.resolved_at is None]),
            "alerts_firing": sum(1 for r in rules.values() if r.state == AlertState.FIRING),
            "alerts_pending": sum(1 for r in rules.values() if r.state == AlertState.PENDING),
        }

    # ---- Rule checking and alerting ----

    def _evaluate_condition(self, value: float, condition: AlertCondition, threshold: float) -> bool:
        if condition == AlertCondition.GREATER_THAN:
            return value > threshold
        elif condition == AlertCondition.LESS_THAN:
            return value < threshold
        elif condition == AlertCondition.GREATER_THAN_OR_EQUAL:
            return value >= threshold
        elif condition == AlertCondition.LESS_THAN_OR_EQUAL:
            return value <= threshold
        elif condition == AlertCondition.EQUAL:
            return value == threshold
        elif condition == AlertCondition.NOT_EQUAL:
            return value != threshold
        return False

    def _check_rule(self, user_id: int, rule: MonitoringRuleState):
        """Check a single monitoring rule."""
        if not rule.enabled:
            return

        value = self.collector.collect(rule.source, rule.query)
        rule.last_check = datetime.utcnow()

        if value is None:
            return

        rule.last_value = value
        condition_met = self._evaluate_condition(value, rule.condition, rule.threshold)

        if condition_met:
            if rule.state == AlertState.OK:
                rule.state = AlertState.PENDING
                rule.pending_since = datetime.utcnow()
            elif rule.state == AlertState.PENDING:
                if rule.pending_since:
                    duration = (datetime.utcnow() - rule.pending_since).total_seconds()
                    if duration >= rule.duration_seconds:
                        rule.state = AlertState.FIRING
                        rule.firing_since = datetime.utcnow()
                        self._fire_alert(user_id, rule, value)
        else:
            if rule.state in [AlertState.PENDING, AlertState.FIRING]:
                if rule.state == AlertState.FIRING:
                    self._resolve_alert(user_id, rule)
                rule.state = AlertState.OK
                rule.pending_since = None
                rule.firing_since = None

    def _fire_alert(self, user_id: int, rule: MonitoringRuleState, value: float):
        """Fire an alert for a rule."""
        alert_key = str(uuid.uuid4())[:8]
        condition_str = f"{rule.condition.value if isinstance(rule.condition, AlertCondition) else rule.condition} {rule.threshold}"
        message = f"{rule.name}: Current value {value:.2f} {condition_str}"

        alert = MonitoringAlertState(
            id=alert_key, rule_id=rule.id, rule_name=rule.name,
            severity=rule.severity, value=value, threshold=rule.threshold,
            condition=condition_str, message=message,
            labels=rule.labels.copy(), fired_at=datetime.utcnow()
        )

        self._user_alerts.setdefault(user_id, {})[alert_key] = alert
        logger.warning(f"ALERT FIRING [user={user_id}]: {message}")

        # Persist to DB
        if self._app:
            try:
                with self._app.app_context():
                    from models import MonitoringAlertModel, MonitoringRuleModel, db
                    db_rule = MonitoringRuleModel.query.filter_by(
                        user_id=user_id, rule_key=rule.id
                    ).first()
                    db_alert = MonitoringAlertModel(
                        user_id=user_id, alert_key=alert_key,
                        rule_db_id=db_rule.id if db_rule else None,
                        rule_key=rule.id, rule_name=rule.name,
                        severity=rule.severity, value=value,
                        threshold=rule.threshold, condition=condition_str,
                        message=message, labels=rule.labels.copy(),
                        fired_at=alert.fired_at,
                    )
                    db.session.add(db_alert)
                    db.session.commit()
                    alert.db_id = db_alert.id
                    from services.notification_service import notify_alert as _notify_alert
                    _notify_alert(user_id, alert.to_dict())
            except Exception as e:
                logger.error(f"Failed to persist alert to DB: {e}")

        for callback in self._alert_callbacks:
            try:
                callback("firing", alert.to_dict(), user_id=user_id)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        if self._incident_engine:
            try:
                alert_payload = {
                    "alertname": rule.name.lower().replace(" ", "-"),
                    "severity": rule.severity,
                    "description": message,
                    "labels": rule.labels,
                    "value": value,
                    "threshold": rule.threshold,
                    "source": "proactive-monitoring",
                }
                incident = self._incident_engine.process_alert(user_id, alert_payload)
                if incident:
                    alert.incident_id = incident.id
                    if self._app and alert.db_id:
                        with self._app.app_context():
                            from models import MonitoringAlertModel, db
                            MonitoringAlertModel.query.filter_by(id=alert.db_id).update(
                                {'incident_id': incident.id}
                            )
                            db.session.commit()
            except Exception as e:
                logger.error(f"Failed to create incident for alert: {e}")

    def _resolve_alert(self, user_id: int, rule: MonitoringRuleState):
        """Resolve alerts for a rule."""
        alerts = self._user_alerts.get(user_id, {})
        resolved_keys = []

        for alert_key, alert in alerts.items():
            if alert.rule_id == rule.id and alert.resolved_at is None:
                alert.resolved_at = datetime.utcnow()
                resolved_keys.append(alert_key)
                logger.info(f"ALERT RESOLVED [user={user_id}]: {rule.name}")

                history = self._user_alert_history.setdefault(user_id, deque(maxlen=self._max_alert_history))
                history.append(alert)

                # Persist resolution to DB
                if self._app and alert.db_id:
                    try:
                        with self._app.app_context():
                            from models import MonitoringAlertModel, db
                            MonitoringAlertModel.query.filter_by(id=alert.db_id).update(
                                {'resolved_at': alert.resolved_at}
                            )
                            db.session.commit()
                    except Exception as e:
                        logger.error(f"Failed to persist alert resolution: {e}")

                for callback in self._alert_callbacks:
                    try:
                        callback("resolved", alert.to_dict(), user_id=user_id)
                    except Exception as e:
                        logger.error(f"Alert callback failed: {e}")

        for key in resolved_keys:
            del alerts[key]

    # ---- Daemon thread ----

    def _monitoring_loop(self):
        """Main monitoring loop - checks all loaded users' rules."""
        logger.info("Proactive monitoring started")
        last_checks: dict[str, datetime] = {}

        while self._running:
            now = datetime.utcnow()

            for user_id in list(self._user_rules.keys()):
                rules = self._user_rules.get(user_id, {})
                for rule_key, rule in list(rules.items()):
                    check_key = f"{user_id}:{rule_key}"
                    last_check = last_checks.get(check_key)
                    if last_check is None or (now - last_check).total_seconds() >= rule.check_interval_seconds:
                        try:
                            self._check_rule(user_id, rule)
                            last_checks[check_key] = now
                        except Exception as e:
                            logger.error(f"Error checking rule {rule.name} for user {user_id}: {e}")

            # Periodic flush of rule state to DB (every ~60s)
            self._flush_counter += 1
            if self._flush_counter % 12 == 0:
                self._flush_rule_states()
                # Clean stale entries from last_checks
                valid_keys = {f"{uid}:{rk}" for uid, rules in self._user_rules.items() for rk in rules}
                stale = [k for k in last_checks if k not in valid_keys]
                for k in stale:
                    del last_checks[k]

            time.sleep(5)

        logger.info("Proactive monitoring stopped")

    def _flush_rule_states(self):
        """Write current rule state (last_value, last_check, state) back to DB."""
        if not self._app:
            return
        try:
            with self._app.app_context():
                from models import MonitoringRuleModel, db
                for user_id, rules in self._user_rules.items():
                    for rule_key, rule in rules.items():
                        state_val = rule.state.value if isinstance(rule.state, AlertState) else rule.state
                        MonitoringRuleModel.query.filter_by(
                            user_id=user_id, rule_key=rule_key
                        ).update({
                            'state': state_val,
                            'last_value': rule.last_value,
                            'last_check': rule.last_check,
                        })
                db.session.commit()
        except Exception as e:
            logger.error(f"Failed to flush rule states to DB: {e}")

    # ---- Service lifecycle ----

    def start(self):
        """Start the monitoring service."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._thread.start()
        logger.info("Proactive monitoring service started")

    def stop(self):
        """Stop the monitoring service."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None
        self._flush_rule_states()
        logger.info("Proactive monitoring service stopped")

    def is_running(self) -> bool:
        return self._running


monitoring_service = ProactiveMonitoringService()


def get_monitoring_service() -> ProactiveMonitoringService:
    """Get the global monitoring service instance."""
    return monitoring_service
