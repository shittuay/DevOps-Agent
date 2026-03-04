"""
Infrastructure Drift Detection Service for DevOps Agent.

Compares actual infrastructure state against expected state (from Terraform,
CloudFormation, or defined baselines) to detect configuration drift.
"""

import logging
import json
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DriftSeverity(Enum):
    """Severity of detected drift."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DriftType(Enum):
    """Types of infrastructure drift."""
    ADDED = "added"  # Resource exists but not in expected state
    REMOVED = "removed"  # Resource missing from actual state
    MODIFIED = "modified"  # Resource properties differ
    SECURITY = "security"  # Security-related drift


class ResourceType(Enum):
    """Types of resources to monitor for drift."""
    EC2_INSTANCE = "ec2_instance"
    EC2_SECURITY_GROUP = "security_group"
    S3_BUCKET = "s3_bucket"
    RDS_INSTANCE = "rds_instance"
    IAM_ROLE = "iam_role"
    IAM_POLICY = "iam_policy"
    LAMBDA_FUNCTION = "lambda_function"
    EKS_CLUSTER = "eks_cluster"
    VPC = "vpc"
    SUBNET = "subnet"
    LOAD_BALANCER = "load_balancer"


@dataclass
class DriftItem:
    """A single detected drift."""
    id: str
    resource_type: ResourceType
    resource_id: str
    resource_name: str
    drift_type: DriftType
    severity: DriftSeverity
    expected_value: Any
    actual_value: Any
    property_path: str  # e.g., "SecurityGroups[0].IpPermissions"
    description: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    remediation_suggestion: str = ""


@dataclass
class DriftReport:
    """Report of drift detection scan."""
    id: str
    scan_started: datetime
    scan_completed: datetime
    total_resources: int
    drifted_resources: int
    drift_items: list[DriftItem]
    summary: dict


@dataclass
class BaselineResource:
    """Expected state of a resource."""
    resource_type: ResourceType
    resource_id: str
    resource_name: str
    expected_config: dict
    tags: dict = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.utcnow)


class DriftDetectionService:
    """
    Service for detecting infrastructure drift.

    Features:
    - Compare actual vs expected infrastructure state
    - Detect security-critical changes
    - Track drift over time
    - Generate remediation suggestions
    """

    def __init__(self):
        # Keyed by user_id for data isolation
        self.baselines: dict[int, dict[str, BaselineResource]] = {}
        self.reports: dict[int, list[DriftReport]] = {}
        self.drift_rules: list[dict] = []
        self._load_default_rules()

    def _load_default_rules(self):
        """Load default drift detection rules."""
        self.drift_rules = [
            # Security Group Rules
            {
                'resource_type': ResourceType.EC2_SECURITY_GROUP,
                'property': 'IpPermissions',
                'severity': DriftSeverity.CRITICAL,
                'check': 'ingress_open_to_world',
                'description': 'Security group allows ingress from 0.0.0.0/0'
            },
            # S3 Bucket Rules
            {
                'resource_type': ResourceType.S3_BUCKET,
                'property': 'PublicAccessBlock',
                'severity': DriftSeverity.HIGH,
                'check': 'public_access_enabled',
                'description': 'S3 bucket has public access enabled'
            },
            # RDS Rules
            {
                'resource_type': ResourceType.RDS_INSTANCE,
                'property': 'PubliclyAccessible',
                'severity': DriftSeverity.CRITICAL,
                'check': 'publicly_accessible',
                'description': 'RDS instance is publicly accessible'
            },
            # IAM Rules
            {
                'resource_type': ResourceType.IAM_ROLE,
                'property': 'AssumeRolePolicyDocument',
                'severity': DriftSeverity.HIGH,
                'check': 'trust_policy_changed',
                'description': 'IAM role trust policy has changed'
            },
            # EC2 Instance Rules
            {
                'resource_type': ResourceType.EC2_INSTANCE,
                'property': 'InstanceType',
                'severity': DriftSeverity.LOW,
                'check': 'value_changed',
                'description': 'EC2 instance type has changed'
            },
        ]

    def add_baseline(self, user_id: int, resource: BaselineResource):
        """Add or update a baseline resource."""
        key = f"{resource.resource_type.value}:{resource.resource_id}"
        user_baselines = self.baselines.setdefault(user_id, {})
        user_baselines[key] = resource
        logger.info(f"Baseline added/updated: {key}")

    def remove_baseline(self, user_id: int, resource_type: ResourceType, resource_id: str):
        """Remove a baseline resource."""
        key = f"{resource_type.value}:{resource_id}"
        user_baselines = self.baselines.get(user_id, {})
        if key in user_baselines:
            del user_baselines[key]
            logger.info(f"Baseline removed: {key}")

    def import_terraform_state(self, user_id: int, state_data: dict):
        """Import baselines from Terraform state."""
        resources = state_data.get('resources', [])

        for resource in resources:
            resource_type = self._map_terraform_type(resource.get('type', ''))
            if not resource_type:
                continue

            for instance in resource.get('instances', []):
                attributes = instance.get('attributes', {})
                resource_id = attributes.get('id', attributes.get('arn', ''))

                if resource_id:
                    self.add_baseline(user_id, BaselineResource(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        resource_name=resource.get('name', resource_id),
                        expected_config=attributes,
                        tags=attributes.get('tags', {})
                    ))

        user_baselines = self.baselines.get(user_id, {})
        logger.info(f"Imported {len(user_baselines)} resources from Terraform state")

    def _map_terraform_type(self, tf_type: str) -> Optional[ResourceType]:
        """Map Terraform resource type to internal type."""
        mapping = {
            'aws_instance': ResourceType.EC2_INSTANCE,
            'aws_security_group': ResourceType.EC2_SECURITY_GROUP,
            'aws_s3_bucket': ResourceType.S3_BUCKET,
            'aws_db_instance': ResourceType.RDS_INSTANCE,
            'aws_iam_role': ResourceType.IAM_ROLE,
            'aws_iam_policy': ResourceType.IAM_POLICY,
            'aws_lambda_function': ResourceType.LAMBDA_FUNCTION,
            'aws_eks_cluster': ResourceType.EKS_CLUSTER,
            'aws_vpc': ResourceType.VPC,
            'aws_subnet': ResourceType.SUBNET,
            'aws_lb': ResourceType.LOAD_BALANCER,
            'aws_alb': ResourceType.LOAD_BALANCER,
        }
        return mapping.get(tf_type)

    def scan_for_drift(self, user_id: int) -> DriftReport:
        """Scan all baselined resources for drift."""
        import uuid
        import time

        report_id = str(uuid.uuid4())[:8]
        scan_start = datetime.utcnow()
        drift_items = []
        user_baselines = self.baselines.get(user_id, {})

        for key, baseline in user_baselines.items():
            # Get actual state
            actual_config = self._get_actual_state(baseline.resource_type, baseline.resource_id)

            if actual_config is None:
                # Resource no longer exists
                drift_items.append(DriftItem(
                    id=f"drift-{report_id}-{len(drift_items)}",
                    resource_type=baseline.resource_type,
                    resource_id=baseline.resource_id,
                    resource_name=baseline.resource_name,
                    drift_type=DriftType.REMOVED,
                    severity=DriftSeverity.HIGH,
                    expected_value="exists",
                    actual_value="missing",
                    property_path="",
                    description=f"Resource {baseline.resource_name} no longer exists",
                    remediation_suggestion="Re-create resource or update baseline"
                ))
                continue

            # Compare configurations
            drifts = self._compare_configs(
                baseline.expected_config,
                actual_config,
                baseline.resource_type,
                baseline.resource_id,
                baseline.resource_name,
                report_id,
                len(drift_items)
            )
            drift_items.extend(drifts)

        # Apply security rules
        security_drifts = self._apply_security_rules(drift_items)
        drift_items.extend(security_drifts)

        scan_end = datetime.utcnow()

        # Build report
        report = DriftReport(
            id=report_id,
            scan_started=scan_start,
            scan_completed=scan_end,
            total_resources=len(user_baselines),
            drifted_resources=len(set(d.resource_id for d in drift_items)),
            drift_items=drift_items,
            summary=self._build_summary(drift_items)
        )

        user_reports = self.reports.setdefault(user_id, [])
        user_reports.append(report)
        logger.info(f"Drift scan completed: {len(drift_items)} drifts found in {report.drifted_resources} resources")

        return report

    def _get_actual_state(self, resource_type: ResourceType, resource_id: str) -> Optional[dict]:
        """Get actual state of a resource from AWS."""
        # In a real implementation, this would call AWS APIs
        # For now, return simulated data

        # Simulate some resources existing with slight changes
        if resource_type == ResourceType.EC2_INSTANCE:
            return {
                'id': resource_id,
                'instance_type': 't3.medium',  # May have changed
                'state': 'running',
                'security_groups': ['sg-12345'],
                'tags': {'Environment': 'production'}
            }
        elif resource_type == ResourceType.EC2_SECURITY_GROUP:
            return {
                'id': resource_id,
                'name': 'web-sg',
                'vpc_id': 'vpc-12345',
                'ingress': [
                    {'port': 443, 'cidr': '0.0.0.0/0'},  # Changed!
                    {'port': 80, 'cidr': '10.0.0.0/8'}
                ]
            }
        elif resource_type == ResourceType.S3_BUCKET:
            return {
                'name': resource_id,
                'versioning': True,
                'encryption': 'AES256',
                'public_access_block': {
                    'block_public_acls': True,
                    'block_public_policy': True
                }
            }

        return {}

    def _compare_configs(self, expected: dict, actual: dict, resource_type: ResourceType,
                         resource_id: str, resource_name: str, report_id: str,
                         start_idx: int, path: str = "") -> list[DriftItem]:
        """Compare expected and actual configurations recursively."""
        drift_items = []
        idx = start_idx

        for key, expected_value in expected.items():
            current_path = f"{path}.{key}" if path else key
            actual_value = actual.get(key)

            if actual_value is None:
                # Property removed
                drift_items.append(DriftItem(
                    id=f"drift-{report_id}-{idx}",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    drift_type=DriftType.MODIFIED,
                    severity=self._get_property_severity(resource_type, key),
                    expected_value=expected_value,
                    actual_value=None,
                    property_path=current_path,
                    description=f"Property '{key}' was removed",
                    remediation_suggestion=f"Restore property '{key}' to expected value"
                ))
                idx += 1
            elif isinstance(expected_value, dict) and isinstance(actual_value, dict):
                # Recurse into nested objects
                nested_drifts = self._compare_configs(
                    expected_value, actual_value, resource_type,
                    resource_id, resource_name, report_id, idx, current_path
                )
                drift_items.extend(nested_drifts)
                idx += len(nested_drifts)
            elif expected_value != actual_value:
                # Value changed
                drift_items.append(DriftItem(
                    id=f"drift-{report_id}-{idx}",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    drift_type=DriftType.MODIFIED,
                    severity=self._get_property_severity(resource_type, key),
                    expected_value=expected_value,
                    actual_value=actual_value,
                    property_path=current_path,
                    description=f"Property '{key}' changed from '{expected_value}' to '{actual_value}'",
                    remediation_suggestion=f"Update '{key}' back to '{expected_value}'"
                ))
                idx += 1

        # Check for added properties
        for key, actual_value in actual.items():
            if key not in expected:
                current_path = f"{path}.{key}" if path else key
                drift_items.append(DriftItem(
                    id=f"drift-{report_id}-{idx}",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    resource_name=resource_name,
                    drift_type=DriftType.ADDED,
                    severity=DriftSeverity.LOW,
                    expected_value=None,
                    actual_value=actual_value,
                    property_path=current_path,
                    description=f"New property '{key}' was added",
                    remediation_suggestion=f"Remove property '{key}' or update baseline"
                ))
                idx += 1

        return drift_items

    def _get_property_severity(self, resource_type: ResourceType, property_name: str) -> DriftSeverity:
        """Determine severity based on resource type and property."""
        critical_properties = {
            ResourceType.EC2_SECURITY_GROUP: ['ingress', 'egress', 'ip_permissions'],
            ResourceType.IAM_ROLE: ['assume_role_policy', 'trust_policy'],
            ResourceType.IAM_POLICY: ['policy_document'],
            ResourceType.S3_BUCKET: ['public_access_block', 'acl'],
            ResourceType.RDS_INSTANCE: ['publicly_accessible', 'storage_encrypted'],
        }

        high_properties = {
            ResourceType.EC2_INSTANCE: ['instance_type', 'security_groups'],
            ResourceType.LAMBDA_FUNCTION: ['runtime', 'handler'],
            ResourceType.EKS_CLUSTER: ['version', 'endpoint_public_access'],
        }

        prop_lower = property_name.lower()

        if resource_type in critical_properties:
            if any(p in prop_lower for p in critical_properties[resource_type]):
                return DriftSeverity.CRITICAL

        if resource_type in high_properties:
            if any(p in prop_lower for p in high_properties[resource_type]):
                return DriftSeverity.HIGH

        return DriftSeverity.MEDIUM

    def _apply_security_rules(self, drift_items: list[DriftItem]) -> list[DriftItem]:
        """Apply security-specific rules to detect dangerous configurations."""
        security_drifts = []

        for rule in self.drift_rules:
            for drift in drift_items:
                if drift.resource_type != rule['resource_type']:
                    continue

                if rule['property'].lower() not in drift.property_path.lower():
                    continue

                # Check for specific security violations
                if rule['check'] == 'ingress_open_to_world':
                    if '0.0.0.0/0' in str(drift.actual_value):
                        drift.drift_type = DriftType.SECURITY
                        drift.severity = DriftSeverity.CRITICAL
                        drift.description = f"SECURITY: {rule['description']}"

        return security_drifts

    def _build_summary(self, drift_items: list[DriftItem]) -> dict:
        """Build summary statistics from drift items."""
        from collections import Counter

        severity_counts = Counter(d.severity.value for d in drift_items)
        type_counts = Counter(d.drift_type.value for d in drift_items)
        resource_type_counts = Counter(d.resource_type.value for d in drift_items)

        return {
            'total_drifts': len(drift_items),
            'by_severity': dict(severity_counts),
            'by_type': dict(type_counts),
            'by_resource_type': dict(resource_type_counts),
            'critical_count': severity_counts.get('critical', 0),
            'security_issues': sum(1 for d in drift_items if d.drift_type == DriftType.SECURITY)
        }

    def get_report(self, user_id: int, report_id: str) -> Optional[DriftReport]:
        """Get a specific drift report."""
        user_reports = self.reports.get(user_id, [])
        for report in user_reports:
            if report.id == report_id:
                return report
        return None

    def get_recent_reports(self, user_id: int, limit: int = 10) -> list[DriftReport]:
        """Get recent drift reports."""
        user_reports = self.reports.get(user_id, [])
        return sorted(user_reports, key=lambda r: r.scan_completed, reverse=True)[:limit]

    def get_baseline_count(self, user_id: int) -> int:
        """Get number of baselined resources."""
        return len(self.baselines.get(user_id, {}))

    def get_baselines(self, user_id: int, resource_type: Optional[ResourceType] = None) -> list[BaselineResource]:
        """Get all baselines, optionally filtered by type."""
        user_baselines = self.baselines.get(user_id, {})
        baselines = list(user_baselines.values())
        if resource_type:
            baselines = [b for b in baselines if b.resource_type == resource_type]
        return baselines


# Global instance
_drift_service: Optional[DriftDetectionService] = None


def get_drift_service() -> DriftDetectionService:
    """Get or create the global drift detection service."""
    global _drift_service
    if _drift_service is None:
        _drift_service = DriftDetectionService()
    return _drift_service
