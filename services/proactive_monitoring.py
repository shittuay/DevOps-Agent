"""
Proactive Monitoring Service for DevOps Agent.

Monitors infrastructure metrics and triggers alerts based on configurable rules.
Integrates with the incident response system for automated remediation.
"""

import asyncio
import threading
import time
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
import json
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
class MonitoringRule:
    """A monitoring rule that defines what to check and when to alert."""
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

    # State tracking
    state: AlertState = AlertState.OK
    last_value: Optional[float] = None
    last_check: Optional[datetime] = None
    pending_since: Optional[datetime] = None
    firing_since: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source.value,
            "query": self.query,
            "condition": self.condition.value,
            "threshold": self.threshold,
            "duration_seconds": self.duration_seconds,
            "severity": self.severity,
            "labels": self.labels,
            "enabled": self.enabled,
            "check_interval_seconds": self.check_interval_seconds,
            "state": self.state.value,
            "last_value": self.last_value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
        }


@dataclass
class Alert:
    """An active or historical alert."""
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
            "fired_at": self.fired_at.isoformat(),
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
        """Collect a metric value from the specified source."""
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
        """Query Prometheus for a metric."""
        prometheus_url = self.config.get("prometheus_url", "http://localhost:9090")

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
        """Query AWS CloudWatch for a metric."""
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
        """Query Datadog for a metric."""
        api_key = self.config.get("datadog_api_key")
        app_key = self.config.get("datadog_app_key")

        if not api_key or not app_key:
            logger.warning("Datadog credentials not configured")
            return None

        try:
            now = int(time.time())
            response = requests.get(
                "https://api.datadoghq.com/api/v1/query",
                params={
                    "query": query,
                    "from": now - 300,
                    "to": now
                },
                headers={
                    "DD-API-KEY": api_key,
                    "DD-APPLICATION-KEY": app_key
                },
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
        """Execute a custom metric collection query."""
        custom_handlers = self.config.get("custom_handlers", {})
        handler = custom_handlers.get(query)

        if callable(handler):
            try:
                return float(handler())
            except Exception as e:
                logger.warning(f"Custom metric collection failed: {e}")
                return None
        return None


class ProactiveMonitoringService:
    """
    Main proactive monitoring service.

    Runs periodic checks against defined rules and triggers alerts
    when conditions are met.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.collector = MetricCollector(config)
        self.rules: dict[str, MonitoringRule] = {}
        self.alerts: dict[str, Alert] = {}
        self.alert_history: list[Alert] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._alert_callbacks: list[Callable] = []
        self._incident_engine = None

        self._load_default_rules()

    def _load_default_rules(self):
        """Load default monitoring rules."""
        default_rules = [
            MonitoringRule(
                id="cpu-high",
                name="High CPU Usage",
                description="Alert when CPU usage exceeds 80%",
                source=MetricSource.PROMETHEUS,
                query='100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
                condition=AlertCondition.GREATER_THAN,
                threshold=80.0,
                duration_seconds=120,
                severity="high",
                labels={"category": "performance", "component": "cpu"}
            ),
            MonitoringRule(
                id="memory-high",
                name="High Memory Usage",
                description="Alert when memory usage exceeds 85%",
                source=MetricSource.PROMETHEUS,
                query='(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
                condition=AlertCondition.GREATER_THAN,
                threshold=85.0,
                duration_seconds=120,
                severity="high",
                labels={"category": "performance", "component": "memory"}
            ),
            MonitoringRule(
                id="disk-high",
                name="High Disk Usage",
                description="Alert when disk usage exceeds 90%",
                source=MetricSource.PROMETHEUS,
                query='(1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) * 100',
                condition=AlertCondition.GREATER_THAN,
                threshold=90.0,
                duration_seconds=60,
                severity="critical",
                labels={"category": "storage", "component": "disk"}
            ),
            MonitoringRule(
                id="http-errors-high",
                name="High HTTP Error Rate",
                description="Alert when HTTP 5xx error rate exceeds 5%",
                source=MetricSource.PROMETHEUS,
                query='sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100',
                condition=AlertCondition.GREATER_THAN,
                threshold=5.0,
                duration_seconds=60,
                severity="critical",
                labels={"category": "availability", "component": "http"}
            ),
            MonitoringRule(
                id="response-time-high",
                name="High Response Time",
                description="Alert when average response time exceeds 2 seconds",
                source=MetricSource.PROMETHEUS,
                query='histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))',
                condition=AlertCondition.GREATER_THAN,
                threshold=2.0,
                duration_seconds=120,
                severity="medium",
                labels={"category": "performance", "component": "latency"}
            ),
            MonitoringRule(
                id="pod-restarts-high",
                name="High Pod Restart Rate",
                description="Alert when pod restarts exceed 5 in 10 minutes",
                source=MetricSource.PROMETHEUS,
                query='sum(increase(kube_pod_container_status_restarts_total[10m]))',
                condition=AlertCondition.GREATER_THAN,
                threshold=5.0,
                duration_seconds=30,
                severity="high",
                labels={"category": "kubernetes", "component": "pods"}
            ),
            MonitoringRule(
                id="pending-pods",
                name="Pending Pods",
                description="Alert when there are pending pods for more than 5 minutes",
                source=MetricSource.PROMETHEUS,
                query='sum(kube_pod_status_phase{phase="Pending"})',
                condition=AlertCondition.GREATER_THAN,
                threshold=0,
                duration_seconds=300,
                severity="medium",
                labels={"category": "kubernetes", "component": "pods"}
            ),
            MonitoringRule(
                id="node-not-ready",
                name="Node Not Ready",
                description="Alert when a Kubernetes node is not ready",
                source=MetricSource.PROMETHEUS,
                query='sum(kube_node_status_condition{condition="Ready",status="false"})',
                condition=AlertCondition.GREATER_THAN,
                threshold=0,
                duration_seconds=60,
                severity="critical",
                labels={"category": "kubernetes", "component": "nodes"}
            ),
        ]

        for rule in default_rules:
            self.rules[rule.id] = rule

    def set_incident_engine(self, engine):
        """Set the incident response engine for integration."""
        self._incident_engine = engine

    def add_rule(self, rule: MonitoringRule) -> str:
        """Add a monitoring rule."""
        self.rules[rule.id] = rule
        logger.info(f"Added monitoring rule: {rule.name}")
        return rule.id

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a monitoring rule."""
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info(f"Removed monitoring rule: {rule_id}")
            return True
        return False

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a monitoring rule."""
        if rule_id in self.rules:
            self.rules[rule_id].enabled = True
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a monitoring rule."""
        if rule_id in self.rules:
            self.rules[rule_id].enabled = False
            return True
        return False

    def get_rules(self) -> list[dict]:
        """Get all monitoring rules."""
        return [rule.to_dict() for rule in self.rules.values()]

    def get_active_alerts(self) -> list[dict]:
        """Get all active (firing) alerts."""
        return [
            alert.to_dict()
            for alert in self.alerts.values()
            if alert.resolved_at is None
        ]

    def get_alert_history(self, limit: int = 100) -> list[dict]:
        """Get alert history."""
        return [alert.to_dict() for alert in self.alert_history[-limit:]]

    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """Acknowledge an alert."""
        if alert_id in self.alerts:
            self.alerts[alert_id].acknowledged = True
            self.alerts[alert_id].acknowledged_by = user
            return True
        return False

    def add_alert_callback(self, callback: Callable):
        """Add a callback to be called when alerts fire or resolve."""
        self._alert_callbacks.append(callback)

    def _evaluate_condition(self, value: float, condition: AlertCondition, threshold: float) -> bool:
        """Evaluate if a metric value meets the alert condition."""
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

    def _check_rule(self, rule: MonitoringRule):
        """Check a single monitoring rule."""
        if not rule.enabled:
            return

        value = self.collector.collect(rule.source, rule.query)
        rule.last_check = datetime.utcnow()

        if value is None:
            logger.debug(f"No value collected for rule {rule.name}")
            return

        rule.last_value = value
        condition_met = self._evaluate_condition(value, rule.condition, rule.threshold)

        if condition_met:
            if rule.state == AlertState.OK:
                rule.state = AlertState.PENDING
                rule.pending_since = datetime.utcnow()
                logger.info(f"Rule {rule.name} entered PENDING state (value={value})")

            elif rule.state == AlertState.PENDING:
                if rule.pending_since:
                    duration = (datetime.utcnow() - rule.pending_since).total_seconds()
                    if duration >= rule.duration_seconds:
                        rule.state = AlertState.FIRING
                        rule.firing_since = datetime.utcnow()
                        self._fire_alert(rule, value)
        else:
            if rule.state in [AlertState.PENDING, AlertState.FIRING]:
                if rule.state == AlertState.FIRING:
                    self._resolve_alert(rule)
                rule.state = AlertState.OK
                rule.pending_since = None
                rule.firing_since = None

    def _fire_alert(self, rule: MonitoringRule, value: float):
        """Fire an alert for a rule."""
        alert_id = str(uuid.uuid4())[:8]

        condition_str = f"{rule.condition.value} {rule.threshold}"
        message = f"{rule.name}: Current value {value:.2f} {condition_str}"

        alert = Alert(
            id=alert_id,
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity,
            value=value,
            threshold=rule.threshold,
            condition=condition_str,
            message=message,
            labels=rule.labels.copy(),
            fired_at=datetime.utcnow()
        )

        self.alerts[alert_id] = alert
        logger.warning(f"ALERT FIRING: {message}")

        for callback in self._alert_callbacks:
            try:
                callback("firing", alert.to_dict())
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
                incident = self._incident_engine.process_alert(alert_payload)
                if incident:
                    alert.incident_id = incident.id
                    logger.info(f"Created incident {incident.id} for alert {alert_id}")
            except Exception as e:
                logger.error(f"Failed to create incident for alert: {e}")

    def _resolve_alert(self, rule: MonitoringRule):
        """Resolve alerts for a rule."""
        for alert in self.alerts.values():
            if alert.rule_id == rule.id and alert.resolved_at is None:
                alert.resolved_at = datetime.utcnow()
                self.alert_history.append(alert)
                logger.info(f"ALERT RESOLVED: {rule.name}")

                for callback in self._alert_callbacks:
                    try:
                        callback("resolved", alert.to_dict())
                    except Exception as e:
                        logger.error(f"Alert callback failed: {e}")

        self.alerts = {
            k: v for k, v in self.alerts.items()
            if v.rule_id != rule.id or v.resolved_at is None
        }

    def _monitoring_loop(self):
        """Main monitoring loop."""
        logger.info("Proactive monitoring started")

        last_checks: dict[str, datetime] = {}

        while self._running:
            now = datetime.utcnow()

            for rule_id, rule in list(self.rules.items()):
                last_check = last_checks.get(rule_id)

                if last_check is None or (now - last_check).total_seconds() >= rule.check_interval_seconds:
                    try:
                        self._check_rule(rule)
                        last_checks[rule_id] = now
                    except Exception as e:
                        logger.error(f"Error checking rule {rule.name}: {e}")

            time.sleep(5)

        logger.info("Proactive monitoring stopped")

    def start(self):
        """Start the monitoring service."""
        if self._running:
            logger.warning("Monitoring service already running")
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
        logger.info("Proactive monitoring service stopped")

    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._running

    def check_now(self, rule_id: str = None) -> dict:
        """Immediately check a specific rule or all rules."""
        results = {}

        rules_to_check = [self.rules[rule_id]] if rule_id else self.rules.values()

        for rule in rules_to_check:
            if rule.enabled:
                try:
                    self._check_rule(rule)
                    results[rule.id] = {
                        "name": rule.name,
                        "state": rule.state.value,
                        "last_value": rule.last_value,
                        "threshold": rule.threshold,
                    }
                except Exception as e:
                    results[rule.id] = {"error": str(e)}

        return results

    def get_status(self) -> dict:
        """Get the current status of the monitoring service."""
        return {
            "running": self._running,
            "rules_total": len(self.rules),
            "rules_enabled": sum(1 for r in self.rules.values() if r.enabled),
            "alerts_active": len([a for a in self.alerts.values() if a.resolved_at is None]),
            "alerts_firing": sum(1 for r in self.rules.values() if r.state == AlertState.FIRING),
            "alerts_pending": sum(1 for r in self.rules.values() if r.state == AlertState.PENDING),
        }


monitoring_service = ProactiveMonitoringService()


def get_monitoring_service() -> ProactiveMonitoringService:
    """Get the global monitoring service instance."""
    return monitoring_service
