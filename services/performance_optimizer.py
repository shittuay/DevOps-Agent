"""
Performance Optimization Service for DevOps Agent.

Analyzes infrastructure metrics and provides optimization recommendations
for cost reduction, performance improvement, and resource efficiency.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
from dataclasses import dataclass, field
import uuid

logger = logging.getLogger(__name__)


class OptimizationType(Enum):
    """Types of optimization recommendations."""
    COST = "cost"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"
    SECURITY = "security"
    SCALABILITY = "scalability"


class ResourceType(Enum):
    """Types of resources that can be optimized."""
    EC2_INSTANCE = "ec2_instance"
    RDS_INSTANCE = "rds_instance"
    EBS_VOLUME = "ebs_volume"
    S3_BUCKET = "s3_bucket"
    LAMBDA_FUNCTION = "lambda_function"
    KUBERNETES_POD = "kubernetes_pod"
    KUBERNETES_NODE = "kubernetes_node"
    LOAD_BALANCER = "load_balancer"
    DATABASE = "database"
    CACHE = "cache"
    CONTAINER = "container"
    NETWORK = "network"


class Priority(Enum):
    """Recommendation priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Status(Enum):
    """Recommendation status (in-memory only — not persisted to DB).

    Note: This service stores recommendations in memory, not in the CostOptimization
    DB model. The DB model uses different status strings: 'pending', 'applied',
    'dismissed'. If these two systems are ever bridged, map:
      Status.IMPLEMENTED -> 'applied'
      Status.IN_PROGRESS -> 'in_progress' (add to DB model first)
      Status.SCHEDULED   -> 'scheduled'   (add to DB model first)
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    DISMISSED = "dismissed"
    SCHEDULED = "scheduled"


@dataclass
class Recommendation:
    """An optimization recommendation."""
    id: str
    title: str
    description: str
    optimization_type: OptimizationType
    resource_type: ResourceType
    resource_id: Optional[str]
    priority: Priority
    estimated_savings: Optional[float] = None
    estimated_savings_percent: Optional[float] = None
    impact: str = ""
    action_steps: list = field(default_factory=list)
    auto_fixable: bool = False
    risk_level: str = "low"
    status: Status = Status.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    implemented_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "optimization_type": self.optimization_type.value,
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "priority": self.priority.value,
            "estimated_savings": self.estimated_savings,
            "estimated_savings_percent": self.estimated_savings_percent,
            "impact": self.impact,
            "action_steps": self.action_steps,
            "auto_fixable": self.auto_fixable,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "implemented_at": self.implemented_at.isoformat() if self.implemented_at else None,
            "metadata": self.metadata,
        }


@dataclass
class AnalysisResult:
    """Result of a performance analysis."""
    resource_type: ResourceType
    resource_id: str
    metrics: dict
    recommendations: list[Recommendation]
    health_score: float
    analyzed_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "metrics": self.metrics,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "health_score": self.health_score,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


class ResourceAnalyzer:
    """Base class for resource analyzers."""

    def analyze(self, resource_data: dict) -> list[Recommendation]:
        """Analyze a resource and return recommendations."""
        raise NotImplementedError


class EC2Analyzer(ResourceAnalyzer):
    """Analyzer for EC2 instances."""

    def analyze(self, resource_data: dict) -> list[Recommendation]:
        recommendations = []
        instance_id = resource_data.get("instance_id", "unknown")
        instance_type = resource_data.get("instance_type", "unknown")

        # Check CPU utilization
        avg_cpu = resource_data.get("avg_cpu_percent", 0)
        if avg_cpu < 10:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Underutilized EC2 Instance: {instance_id}",
                description=f"Instance {instance_id} has average CPU utilization of {avg_cpu:.1f}%. "
                           "Consider downsizing or terminating this instance.",
                optimization_type=OptimizationType.COST,
                resource_type=ResourceType.EC2_INSTANCE,
                resource_id=instance_id,
                priority=Priority.HIGH,
                estimated_savings_percent=50,
                impact="Reduce compute costs by right-sizing",
                action_steps=[
                    "Review workload requirements",
                    "Consider switching to a smaller instance type",
                    "If consistently underutilized, consider using Spot instances",
                    "Implement auto-scaling if workload varies"
                ],
                auto_fixable=False,
                risk_level="medium"
            ))
        elif avg_cpu > 80:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"High CPU Usage on {instance_id}",
                description=f"Instance {instance_id} has high CPU utilization ({avg_cpu:.1f}%). "
                           "Consider upgrading or optimizing workload.",
                optimization_type=OptimizationType.PERFORMANCE,
                resource_type=ResourceType.EC2_INSTANCE,
                resource_id=instance_id,
                priority=Priority.HIGH,
                impact="Improve application performance and prevent throttling",
                action_steps=[
                    "Profile application to identify CPU-intensive operations",
                    "Consider upgrading to a larger instance type",
                    "Implement horizontal scaling with auto-scaling groups",
                    "Optimize code and queries causing high CPU usage"
                ],
                auto_fixable=False,
                risk_level="low"
            ))

        # Check memory utilization
        avg_memory = resource_data.get("avg_memory_percent", 0)
        if avg_memory > 85:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"High Memory Usage on {instance_id}",
                description=f"Instance {instance_id} has high memory utilization ({avg_memory:.1f}%). "
                           "Risk of OOM errors.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.EC2_INSTANCE,
                resource_id=instance_id,
                priority=Priority.CRITICAL,
                impact="Prevent out-of-memory errors and application crashes",
                action_steps=[
                    "Identify memory-heavy processes",
                    "Consider upgrading to a memory-optimized instance",
                    "Implement memory leak detection",
                    "Add swap space as a temporary measure"
                ],
                auto_fixable=False,
                risk_level="high"
            ))

        # Check for old generation instances
        old_gen_prefixes = ['t1.', 't2.', 'm1.', 'm2.', 'm3.', 'c1.', 'c3.']
        if any(instance_type.startswith(prefix) for prefix in old_gen_prefixes):
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Outdated Instance Generation: {instance_id}",
                description=f"Instance {instance_id} is using an older generation type ({instance_type}). "
                           "Newer generations offer better price-performance.",
                optimization_type=OptimizationType.COST,
                resource_type=ResourceType.EC2_INSTANCE,
                resource_id=instance_id,
                priority=Priority.MEDIUM,
                estimated_savings_percent=20,
                impact="Better performance at similar or lower cost",
                action_steps=[
                    "Compare pricing of current vs newer generation instances",
                    "Test workload on newer instance type",
                    "Schedule migration during maintenance window",
                    "Update launch templates and auto-scaling configurations"
                ],
                auto_fixable=False,
                risk_level="low"
            ))

        return recommendations


class RDSAnalyzer(ResourceAnalyzer):
    """Analyzer for RDS instances."""

    def analyze(self, resource_data: dict) -> list[Recommendation]:
        recommendations = []
        db_id = resource_data.get("db_instance_id", "unknown")

        # Check connection utilization
        connections_used = resource_data.get("connections_percent", 0)
        if connections_used > 80:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"High Connection Usage on {db_id}",
                description=f"RDS instance {db_id} is using {connections_used:.1f}% of available connections. "
                           "Consider implementing connection pooling.",
                optimization_type=OptimizationType.PERFORMANCE,
                resource_type=ResourceType.RDS_INSTANCE,
                resource_id=db_id,
                priority=Priority.HIGH,
                impact="Prevent connection exhaustion and improve reliability",
                action_steps=[
                    "Implement connection pooling (e.g., PgBouncer, ProxySQL)",
                    "Review application connection management",
                    "Increase max_connections parameter if appropriate",
                    "Consider RDS Proxy for serverless workloads"
                ],
                auto_fixable=False,
                risk_level="medium"
            ))

        # Check storage utilization
        storage_used = resource_data.get("storage_percent", 0)
        if storage_used > 85:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"High Storage Usage on {db_id}",
                description=f"RDS instance {db_id} is using {storage_used:.1f}% of allocated storage.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.RDS_INSTANCE,
                resource_id=db_id,
                priority=Priority.CRITICAL,
                impact="Prevent database outage due to storage exhaustion",
                action_steps=[
                    "Enable storage auto-scaling",
                    "Archive or delete old data",
                    "Review and optimize table storage",
                    "Consider partitioning large tables"
                ],
                auto_fixable=True,
                risk_level="medium"
            ))

        # Check for Multi-AZ
        if not resource_data.get("multi_az", False):
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Single-AZ Deployment: {db_id}",
                description=f"RDS instance {db_id} is not configured for Multi-AZ. "
                           "This poses a risk to availability.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.RDS_INSTANCE,
                resource_id=db_id,
                priority=Priority.MEDIUM,
                impact="Improve database availability and enable automatic failover",
                action_steps=[
                    "Evaluate availability requirements",
                    "Enable Multi-AZ deployment",
                    "Test failover procedure",
                    "Update connection strings if needed"
                ],
                auto_fixable=True,
                risk_level="low"
            ))

        return recommendations


class KubernetesAnalyzer(ResourceAnalyzer):
    """Analyzer for Kubernetes resources."""

    def analyze(self, resource_data: dict) -> list[Recommendation]:
        recommendations = []
        resource_name = resource_data.get("name", "unknown")
        resource_namespace = resource_data.get("namespace", "default")

        # Check resource requests vs limits
        cpu_request = resource_data.get("cpu_request", 0)
        cpu_limit = resource_data.get("cpu_limit", 0)
        memory_request = resource_data.get("memory_request", 0)
        memory_limit = resource_data.get("memory_limit", 0)

        if cpu_request == 0 or memory_request == 0:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Missing Resource Requests: {resource_name}",
                description=f"Pod {resource_name} in namespace {resource_namespace} does not have "
                           "resource requests defined. This can lead to scheduling issues.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.KUBERNETES_POD,
                resource_id=f"{resource_namespace}/{resource_name}",
                priority=Priority.HIGH,
                impact="Improve scheduling efficiency and prevent resource contention",
                action_steps=[
                    "Analyze actual resource usage patterns",
                    "Set appropriate CPU and memory requests",
                    "Consider using Vertical Pod Autoscaler for recommendations",
                    "Update deployment manifests"
                ],
                auto_fixable=False,
                risk_level="medium"
            ))

        if cpu_limit == 0 or memory_limit == 0:
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Missing Resource Limits: {resource_name}",
                description=f"Pod {resource_name} does not have resource limits. "
                           "This can lead to resource exhaustion on nodes.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.KUBERNETES_POD,
                resource_id=f"{resource_namespace}/{resource_name}",
                priority=Priority.MEDIUM,
                impact="Prevent noisy neighbor issues and improve cluster stability",
                action_steps=[
                    "Set appropriate resource limits based on requirements",
                    "Consider using LimitRange for namespace defaults",
                    "Monitor for OOMKilled events after setting limits"
                ],
                auto_fixable=False,
                risk_level="low"
            ))

        # Check replica count
        replicas = resource_data.get("replicas", 1)
        if replicas == 1 and resource_data.get("critical", False):
            recommendations.append(Recommendation(
                id=str(uuid.uuid4())[:8],
                title=f"Single Replica Deployment: {resource_name}",
                description=f"Critical service {resource_name} has only 1 replica. "
                           "This poses a risk to availability.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.KUBERNETES_POD,
                resource_id=f"{resource_namespace}/{resource_name}",
                priority=Priority.HIGH,
                impact="Improve service availability and enable zero-downtime deployments",
                action_steps=[
                    "Increase replica count to at least 2",
                    "Configure Pod Disruption Budget",
                    "Set up Horizontal Pod Autoscaler",
                    "Ensure anti-affinity rules for pod distribution"
                ],
                auto_fixable=True,
                risk_level="low"
            ))

        return recommendations


class PerformanceOptimizer:
    """
    Main performance optimization service.

    Analyzes infrastructure and provides optimization recommendations.
    """

    def __init__(self):
        # Keyed by user_id for data isolation
        self.recommendations: dict[int, dict[str, Recommendation]] = {}
        self.analyzers = {
            ResourceType.EC2_INSTANCE: EC2Analyzer(),
            ResourceType.RDS_INSTANCE: RDSAnalyzer(),
            ResourceType.KUBERNETES_POD: KubernetesAnalyzer(),
        }

    def _get_user_recommendations(self, user_id: int) -> dict[str, Recommendation]:
        """Get or initialize per-user recommendations dict."""
        if user_id not in self.recommendations:
            self.recommendations[user_id] = {}
            self._generate_sample_recommendations(user_id)
        return self.recommendations[user_id]

    def _generate_sample_recommendations(self, user_id: int):
        """Generate sample recommendations for demo purposes."""
        user_recs = self.recommendations.setdefault(user_id, {})
        samples = [
            Recommendation(
                id="rec-001",
                title="Right-size underutilized EC2 instances",
                description="3 EC2 instances have consistently low CPU utilization (<10%). "
                           "Consider downsizing to smaller instance types.",
                optimization_type=OptimizationType.COST,
                resource_type=ResourceType.EC2_INSTANCE,
                resource_id="i-0abc123def456",
                priority=Priority.HIGH,
                estimated_savings=150.00,
                estimated_savings_percent=40,
                impact="Reduce monthly EC2 costs by approximately $150",
                action_steps=[
                    "Review instance utilization metrics",
                    "Identify appropriate smaller instance type",
                    "Schedule resize during maintenance window",
                    "Monitor performance after resize"
                ],
                auto_fixable=False,
                risk_level="medium"
            ),
            Recommendation(
                id="rec-002",
                title="Enable RDS Multi-AZ for production database",
                description="Production RDS instance 'prod-db' is running in single-AZ mode. "
                           "Enable Multi-AZ for improved availability.",
                optimization_type=OptimizationType.RELIABILITY,
                resource_type=ResourceType.RDS_INSTANCE,
                resource_id="prod-db",
                priority=Priority.CRITICAL,
                impact="Improve database availability to 99.95% SLA",
                action_steps=[
                    "Review Multi-AZ pricing impact",
                    "Enable Multi-AZ in RDS console",
                    "Verify failover mechanism",
                    "Update monitoring for Multi-AZ"
                ],
                auto_fixable=True,
                risk_level="low"
            ),
            Recommendation(
                id="rec-003",
                title="Implement Kubernetes HPA for API service",
                description="API service experiences traffic spikes but lacks auto-scaling. "
                           "Configure Horizontal Pod Autoscaler.",
                optimization_type=OptimizationType.SCALABILITY,
                resource_type=ResourceType.KUBERNETES_POD,
                resource_id="default/api-service",
                priority=Priority.MEDIUM,
                impact="Handle traffic spikes automatically without manual intervention",
                action_steps=[
                    "Define CPU/memory thresholds for scaling",
                    "Create HPA manifest",
                    "Test scaling behavior under load",
                    "Set up alerts for scaling events"
                ],
                auto_fixable=False,
                risk_level="low"
            ),
            Recommendation(
                id="rec-004",
                title="Convert EBS volumes to gp3",
                description="5 EBS volumes are using gp2 type. Converting to gp3 can reduce costs "
                           "while improving performance.",
                optimization_type=OptimizationType.COST,
                resource_type=ResourceType.EBS_VOLUME,
                resource_id="vol-0xyz789",
                priority=Priority.MEDIUM,
                estimated_savings=45.00,
                estimated_savings_percent=20,
                impact="Reduce EBS costs by 20% with same or better performance",
                action_steps=[
                    "Identify gp2 volumes eligible for conversion",
                    "Snapshot volumes before conversion",
                    "Convert volumes to gp3",
                    "Verify application performance"
                ],
                auto_fixable=True,
                risk_level="low"
            ),
            Recommendation(
                id="rec-005",
                title="Enable S3 Intelligent-Tiering",
                description="S3 bucket 'data-archive' has 500GB of infrequently accessed data. "
                           "Enable Intelligent-Tiering for automatic cost optimization.",
                optimization_type=OptimizationType.COST,
                resource_type=ResourceType.S3_BUCKET,
                resource_id="data-archive",
                priority=Priority.LOW,
                estimated_savings=30.00,
                estimated_savings_percent=30,
                impact="Automatically optimize storage costs based on access patterns",
                action_steps=[
                    "Review bucket access patterns",
                    "Configure Intelligent-Tiering",
                    "Set up lifecycle policies",
                    "Monitor cost changes"
                ],
                auto_fixable=True,
                risk_level="low"
            ),
        ]

        for rec in samples:
            user_recs[rec.id] = rec

    def analyze_resource(self, user_id: int, resource_type: ResourceType, resource_data: dict) -> AnalysisResult:
        """Analyze a specific resource and generate recommendations."""
        analyzer = self.analyzers.get(resource_type)
        if not analyzer:
            logger.warning(f"No analyzer for resource type: {resource_type}")
            return AnalysisResult(
                resource_type=resource_type,
                resource_id=resource_data.get("id", "unknown"),
                metrics={},
                recommendations=[],
                health_score=100.0
            )

        recommendations = analyzer.analyze(resource_data)

        user_recs = self._get_user_recommendations(user_id)
        for rec in recommendations:
            user_recs[rec.id] = rec

        health_score = self._calculate_health_score(recommendations)

        return AnalysisResult(
            resource_type=resource_type,
            resource_id=resource_data.get("id", "unknown"),
            metrics=resource_data,
            recommendations=recommendations,
            health_score=health_score
        )

    def _calculate_health_score(self, recommendations: list[Recommendation]) -> float:
        """Calculate a health score based on recommendations."""
        if not recommendations:
            return 100.0

        deductions = {
            Priority.CRITICAL: 30,
            Priority.HIGH: 15,
            Priority.MEDIUM: 5,
            Priority.LOW: 2,
        }

        score = 100.0
        for rec in recommendations:
            score -= deductions.get(rec.priority, 0)

        return max(0.0, score)

    def get_recommendations(self, user_id: int,
                           optimization_type: OptimizationType = None,
                           resource_type: ResourceType = None,
                           priority: Priority = None,
                           status: Status = None) -> list[dict]:
        """Get recommendations with optional filters."""
        user_recs = self._get_user_recommendations(user_id)
        results = []

        for rec in user_recs.values():
            if optimization_type and rec.optimization_type != optimization_type:
                continue
            if resource_type and rec.resource_type != resource_type:
                continue
            if priority and rec.priority != priority:
                continue
            if status and rec.status != status:
                continue

            results.append(rec.to_dict())

        results.sort(key=lambda x: (
            ["critical", "high", "medium", "low"].index(x["priority"]),
            x["created_at"]
        ))

        return results

    def get_recommendation(self, user_id: int, rec_id: str) -> Optional[dict]:
        """Get a specific recommendation by ID."""
        user_recs = self._get_user_recommendations(user_id)
        rec = user_recs.get(rec_id)
        return rec.to_dict() if rec else None

    def update_recommendation_status(self, user_id: int, rec_id: str, status: Status) -> bool:
        """Update the status of a recommendation."""
        user_recs = self._get_user_recommendations(user_id)
        if rec_id not in user_recs:
            return False

        rec = user_recs[rec_id]
        rec.status = status

        if status == Status.IMPLEMENTED:
            rec.implemented_at = datetime.utcnow()

        return True

    def dismiss_recommendation(self, user_id: int, rec_id: str, reason: str = None) -> bool:
        """Dismiss a recommendation."""
        user_recs = self._get_user_recommendations(user_id)
        if rec_id not in user_recs:
            return False

        rec = user_recs[rec_id]
        rec.status = Status.DISMISSED
        if reason:
            rec.metadata["dismiss_reason"] = reason

        return True

    def get_summary(self, user_id: int) -> dict:
        """Get a summary of all recommendations."""
        user_recs = self._get_user_recommendations(user_id)
        total = len(user_recs)
        by_type = {}
        by_priority = {}
        by_status = {}
        total_savings = 0.0

        for rec in user_recs.values():
            opt_type = rec.optimization_type.value
            by_type[opt_type] = by_type.get(opt_type, 0) + 1

            prio = rec.priority.value
            by_priority[prio] = by_priority.get(prio, 0) + 1

            stat = rec.status.value
            by_status[stat] = by_status.get(stat, 0) + 1

            if rec.estimated_savings and rec.status == Status.PENDING:
                total_savings += rec.estimated_savings

        return {
            "total_recommendations": total,
            "by_type": by_type,
            "by_priority": by_priority,
            "by_status": by_status,
            "potential_monthly_savings": total_savings,
            "pending_count": by_status.get("pending", 0),
            "critical_count": by_priority.get("critical", 0),
        }


_optimizer: Optional[PerformanceOptimizer] = None


def get_performance_optimizer() -> PerformanceOptimizer:
    """Get or create the global performance optimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = PerformanceOptimizer()
    return _optimizer
