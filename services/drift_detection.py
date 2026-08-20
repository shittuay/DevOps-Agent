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


class DriftScanError(Exception):
    """Raised when live state cannot be read, so a scan must abort.

    Kept distinct from drift itself: "I could not read your account" and
    "your account has drifted" are opposite conclusions, and reporting the
    first as the second is how this feature came to invent findings.
    """


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
        # Baselines and reports are persisted to the DB (DriftBaselineModel /
        # DriftReportModel) - see those models' docstrings for why: this
        # service is a module-level singleton, and production runs multiple
        # gunicorn workers, so per-process dicts made baselines/reports
        # invisible across workers and wiped them on every deploy.
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
        from models import db, DriftBaselineModel

        row = DriftBaselineModel.query.filter_by(
            user_id=user_id,
            resource_type=resource.resource_type.value,
            resource_id=resource.resource_id
        ).first()

        if row is None:
            row = DriftBaselineModel(
                user_id=user_id,
                resource_type=resource.resource_type.value,
                resource_id=resource.resource_id
            )
            db.session.add(row)

        row.resource_name = resource.resource_name
        row.expected_config = resource.expected_config
        row.tags = resource.tags
        row.last_updated = resource.last_updated
        db.session.commit()

        key = f"{resource.resource_type.value}:{resource.resource_id}"
        logger.info(f"Baseline added/updated: {key}")

    def remove_baseline(self, user_id: int, resource_type: ResourceType, resource_id: str):
        """Remove a baseline resource."""
        from models import db, DriftBaselineModel

        deleted = DriftBaselineModel.query.filter_by(
            user_id=user_id,
            resource_type=resource_type.value,
            resource_id=resource_id
        ).delete()
        db.session.commit()

        if deleted:
            logger.info(f"Baseline removed: {resource_type.value}:{resource_id}")

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

        logger.info(f"Imported {self.get_baseline_count(user_id)} resources from Terraform state")

    def _map_terraform_type(self, tf_type: str) -> Optional[ResourceType]:
        """Map Terraform resource type to internal type.

        Only maps types `_get_actual_state` actually has a fetcher for. A
        baseline for a type with no fetcher makes every future scan of the
        WHOLE account raise DriftScanError the moment it reaches that one
        baseline (scan_for_drift has no per-baseline error isolation), so
        importing an unsupported type must be a no-op (same as an unknown
        `tf_type` already is below), not a landmine for the next scan.
        """
        mapping = {
            'aws_instance': ResourceType.EC2_INSTANCE,
            'aws_security_group': ResourceType.EC2_SECURITY_GROUP,
            'aws_s3_bucket': ResourceType.S3_BUCKET,
            'aws_db_instance': ResourceType.RDS_INSTANCE,
        }
        return mapping.get(tf_type)

    def scan_for_drift(self, user_id: int) -> DriftReport:
        """Scan all baselined resources for drift against the user's live cloud account.

        Raises DriftScanError if the account can't be read (no credentials, denied
        permissions, unsupported resource type). A scan that cannot see the real
        infrastructure must fail, not emit findings — see CLAUDE.md's "every feature
        runs against a real cloud account".
        """
        import uuid

        report_id = str(uuid.uuid4())[:8]
        scan_start = datetime.utcnow()
        drift_items = []
        user_baselines = self.get_baselines(user_id)

        for baseline in user_baselines:
            # Get actual state
            actual_config = self._get_actual_state(
                user_id, baseline.resource_type, baseline.resource_id
            )

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

        self._save_report(user_id, report)
        logger.info(f"Drift scan completed: {len(drift_items)} drifts found in {report.drifted_resources} resources")

        return report

    def _get_actual_state(self, user_id: int, resource_type: ResourceType,
                          resource_id: str) -> Optional[dict]:
        """Read a resource's live state from AWS using the user's own credentials.

        Returns the normalized config, or None when the resource does not exist
        (the caller turns that into a single REMOVED finding). Raises
        DriftScanError when the account can't be read at all — an unreadable
        account must abort the scan, never be reported as drift.

        This previously returned hardcoded dicts and no RDS branch at all, so
        every user got an identical fictional report — including a critical
        "security group open to 0.0.0.0/0" alert that was a literal in the
        source, and 6 phantom "property removed" rows for RDS (the missing
        branch fell through to `return {}`, which _compare_configs reads as
        "every expected property vanished").
        """
        from services.credential_service import get_user_boto_client

        try:
            if resource_type == ResourceType.EC2_INSTANCE:
                return self._fetch_ec2_instance(get_user_boto_client(user_id, 'ec2'), resource_id)
            if resource_type == ResourceType.EC2_SECURITY_GROUP:
                return self._fetch_security_group(get_user_boto_client(user_id, 'ec2'), resource_id)
            if resource_type == ResourceType.S3_BUCKET:
                return self._fetch_s3_bucket(get_user_boto_client(user_id, 's3'), resource_id)
            if resource_type == ResourceType.RDS_INSTANCE:
                return self._fetch_rds_instance(get_user_boto_client(user_id, 'rds'), resource_id)
        except DriftScanError:
            raise
        except Exception as e:
            # Credential/permission/network failures are not drift.
            raise DriftScanError(
                f"Could not read {resource_type.value} '{resource_id}' from AWS: {e}"
            ) from e

        raise DriftScanError(
            f"Drift detection does not support {resource_type.value} yet — "
            "remove this baseline or add a fetcher for it."
        )

    @staticmethod
    def _fetch_ec2_instance(ec2, resource_id: str) -> Optional[dict]:
        from botocore.exceptions import ClientError
        try:
            resp = ec2.describe_instances(InstanceIds=[resource_id])
        except ClientError as e:
            if e.response['Error']['Code'] in ('InvalidInstanceID.NotFound', 'InvalidInstanceID.Malformed'):
                return None
            raise

        reservations = resp.get('Reservations', [])
        instances = reservations[0].get('Instances', []) if reservations else []
        if not instances:
            return None
        return DriftDetectionService._normalize_ec2_instance(instances[0])

    @staticmethod
    def _normalize_ec2_instance(inst: dict) -> Optional[dict]:
        """Shared by scan and capture. Both MUST use this: if a captured baseline
        had a different key set than a scan produces, every baseline would show
        drift the instant it was created."""
        state = (inst.get('State') or {}).get('Name')
        # A terminated instance is gone for drift purposes.
        if state == 'terminated':
            return None

        return {
            'id': inst.get('InstanceId'),
            'instance_type': inst.get('InstanceType'),
            'state': state,
            'security_groups': [g.get('GroupId') for g in inst.get('SecurityGroups', [])],
            'tags': {t['Key']: t['Value'] for t in inst.get('Tags', [])},
        }

    @staticmethod
    def _fetch_security_group(ec2, resource_id: str) -> Optional[dict]:
        from botocore.exceptions import ClientError
        try:
            resp = ec2.describe_security_groups(GroupIds=[resource_id])
        except ClientError as e:
            if e.response['Error']['Code'] in ('InvalidGroup.NotFound', 'InvalidGroupId.Malformed'):
                return None
            raise

        groups = resp.get('SecurityGroups', [])
        if not groups:
            return None
        return DriftDetectionService._normalize_security_group(groups[0])

    @staticmethod
    def _normalize_security_group(sg: dict) -> dict:
        # Flatten to the {port, cidr} shape baselines are written in. One rule can
        # carry several CIDRs, so it expands to one entry each.
        ingress = []
        for perm in sg.get('IpPermissions', []):
            port = perm.get('FromPort')
            for rng in perm.get('IpRanges', []):
                ingress.append({'port': port, 'cidr': rng.get('CidrIp')})
            for rng in perm.get('Ipv6Ranges', []):
                ingress.append({'port': port, 'cidr': rng.get('CidrIpv6')})

        return {
            'id': sg.get('GroupId'),
            'name': sg.get('GroupName'),
            'vpc_id': sg.get('VpcId'),
            'ingress': ingress,
        }

    @staticmethod
    def _fetch_s3_bucket(s3, resource_id: str) -> Optional[dict]:
        from botocore.exceptions import ClientError
        try:
            s3.head_bucket(Bucket=resource_id)
        except ClientError as e:
            if e.response['Error']['Code'] in ('404', 'NoSuchBucket'):
                return None
            raise

        def _quiet(fn, default, not_configured_codes=()):
            """Some sub-config calls raise a specific 'never configured' error code —
            that's a real value (disabled/absent), not an error, so only THOSE codes
            get swallowed. Anything else (AccessDenied, throttling, ...) means the
            account couldn't be read and must propagate — an unreadable bucket must
            never render as a clean/default finding, since that fabricates drift."""
            try:
                return fn()
            except ClientError as e:
                if e.response['Error']['Code'] in not_configured_codes:
                    return default
                raise

        # get_bucket_versioning never raises for "never enabled" (it just omits
        # 'Status' from the response), so any ClientError here is a real read
        # failure and must propagate rather than be swallowed as "disabled".
        versioning = s3.get_bucket_versioning(Bucket=resource_id).get('Status') == 'Enabled'
        encryption = _quiet(
            lambda: (
                s3.get_bucket_encryption(Bucket=resource_id)
                ['ServerSideEncryptionConfiguration']['Rules'][0]
                ['ApplyServerSideEncryptionByDefault']['SSEAlgorithm']
            ),
            None,
            not_configured_codes=('ServerSideEncryptionConfigurationNotFoundError',),
        )
        pab = _quiet(
            lambda: s3.get_public_access_block(Bucket=resource_id)['PublicAccessBlockConfiguration'],
            {},
            not_configured_codes=('NoSuchPublicAccessBlockConfiguration',),
        )

        return {
            'name': resource_id,
            'versioning': versioning,
            'encryption': encryption,
            'public_access_block': {
                'block_public_acls': pab.get('BlockPublicAcls', False),
                'block_public_policy': pab.get('BlockPublicPolicy', False),
            },
        }

    @staticmethod
    def _fetch_rds_instance(rds, resource_id: str) -> Optional[dict]:
        from botocore.exceptions import ClientError
        try:
            resp = rds.describe_db_instances(DBInstanceIdentifier=resource_id)
        except ClientError as e:
            if e.response['Error']['Code'] == 'DBInstanceNotFound':
                return None
            raise

        instances = resp.get('DBInstances', [])
        if not instances:
            return None
        return DriftDetectionService._normalize_rds_instance(instances[0])

    @staticmethod
    def _normalize_rds_instance(db: dict) -> dict:
        return {
            'id': db.get('DBInstanceIdentifier'),
            'engine': db.get('Engine'),
            'engine_version': db.get('EngineVersion'),
            'instance_class': db.get('DBInstanceClass'),
            'publicly_accessible': db.get('PubliclyAccessible'),
            'storage_encrypted': db.get('StorageEncrypted'),
            'multi_az': db.get('MultiAZ'),
        }

    def capture_baselines_from_account(self, user_id: int,
                                       resource_types: Optional[list] = None) -> dict:
        """Snapshot the user's live cloud resources as baselines.

        This is the cloud-account-native way to get started: pin what you have
        right now, then any later change shows as drift. Terraform state import
        is the other path, for infrastructure that's already declared.

        Reuses the same normalizers the scan uses, so a freshly captured baseline
        compares clean. Raises DriftScanError when the account can't be read.
        """
        from services.credential_service import get_user_boto_client

        wanted = set(resource_types or [
            ResourceType.EC2_INSTANCE, ResourceType.EC2_SECURITY_GROUP,
            ResourceType.S3_BUCKET, ResourceType.RDS_INSTANCE,
        ])
        captured = {}

        try:
            if ResourceType.EC2_INSTANCE in wanted or ResourceType.EC2_SECURITY_GROUP in wanted:
                ec2 = get_user_boto_client(user_id, 'ec2')

            if ResourceType.EC2_INSTANCE in wanted:
                count = 0
                for page in ec2.get_paginator('describe_instances').paginate():
                    for reservation in page.get('Reservations', []):
                        for inst in reservation.get('Instances', []):
                            config = self._normalize_ec2_instance(inst)
                            if config is None:
                                continue  # terminated
                            self.add_baseline(user_id, BaselineResource(
                                resource_type=ResourceType.EC2_INSTANCE,
                                resource_id=inst['InstanceId'],
                                resource_name=config['tags'].get('Name') or inst['InstanceId'],
                                expected_config=config,
                                tags=config['tags'],
                            ))
                            count += 1
                captured['ec2_instance'] = count

            if ResourceType.EC2_SECURITY_GROUP in wanted:
                count = 0
                for page in ec2.get_paginator('describe_security_groups').paginate():
                    for sg in page.get('SecurityGroups', []):
                        config = self._normalize_security_group(sg)
                        self.add_baseline(user_id, BaselineResource(
                            resource_type=ResourceType.EC2_SECURITY_GROUP,
                            resource_id=sg['GroupId'],
                            resource_name=sg.get('GroupName') or sg['GroupId'],
                            expected_config=config,
                        ))
                        count += 1
                captured['security_group'] = count

            if ResourceType.RDS_INSTANCE in wanted:
                rds = get_user_boto_client(user_id, 'rds')
                count = 0
                for page in rds.get_paginator('describe_db_instances').paginate():
                    for db in page.get('DBInstances', []):
                        config = self._normalize_rds_instance(db)
                        self.add_baseline(user_id, BaselineResource(
                            resource_type=ResourceType.RDS_INSTANCE,
                            resource_id=db['DBInstanceIdentifier'],
                            resource_name=db['DBInstanceIdentifier'],
                            expected_config=config,
                        ))
                        count += 1
                captured['rds_instance'] = count

            if ResourceType.S3_BUCKET in wanted:
                s3 = get_user_boto_client(user_id, 's3')
                count = 0
                for bucket in s3.list_buckets().get('Buckets', []):
                    name = bucket['Name']
                    # Per-bucket sub-config calls; skip anything we can't read
                    # (cross-region/denied) rather than pinning a half-empty baseline.
                    try:
                        config = self._fetch_s3_bucket(s3, name)
                    except Exception:
                        logger.warning(f"Skipping bucket {name} during capture - not readable")
                        continue
                    if config is None:
                        continue
                    self.add_baseline(user_id, BaselineResource(
                        resource_type=ResourceType.S3_BUCKET,
                        resource_id=name,
                        resource_name=name,
                        expected_config=config,
                    ))
                    count += 1
                captured['s3_bucket'] = count

        except DriftScanError:
            raise
        except Exception as e:
            raise DriftScanError(f"Could not read your AWS account: {e}") from e

        total = sum(captured.values())
        logger.info(f"Captured {total} baseline(s) from AWS for user {user_id}: {captured}")
        return {'total': total, 'by_type': captured}

    def _compare_configs(self, expected: dict, actual: dict, resource_type: ResourceType,
                         resource_id: str, resource_name: str, report_id: str,
                         start_idx: int, path: str = "") -> list[DriftItem]:
        """Compare expected and actual configurations recursively."""
        drift_items = []
        idx = start_idx

        _MISSING = object()

        for key, expected_value in expected.items():
            current_path = f"{path}.{key}" if path else key
            # Sentinel, not .get(key): a live value that is legitimately None
            # (e.g. an unencrypted bucket) is a changed value, not a removed property.
            actual_value = actual.get(key, _MISSING)

            if actual_value is _MISSING:
                # Property removed
                actual_value = None
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

        # Properties present live but absent from the baseline are NOT drift. A
        # baseline is a subset of the properties you chose to pin; every real
        # resource carries many more. Reporting them produced pure noise with
        # impossible remediation ("Remove property 'id'" for an EC2 instance id).
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

    def _save_report(self, user_id: int, report: DriftReport):
        """Persist a scan result to the DB."""
        from models import db, DriftReportModel

        row = DriftReportModel(
            id=report.id,
            user_id=user_id,
            scan_started=report.scan_started,
            scan_completed=report.scan_completed,
            total_resources=report.total_resources,
            drifted_resources=report.drifted_resources,
            drift_items=[self._drift_item_to_dict(d) for d in report.drift_items],
            summary=report.summary
        )
        db.session.add(row)
        db.session.commit()

    @staticmethod
    def _drift_item_to_dict(item: DriftItem) -> dict:
        return {
            'id': item.id,
            'resource_type': item.resource_type.value,
            'resource_id': item.resource_id,
            'resource_name': item.resource_name,
            'drift_type': item.drift_type.value,
            'severity': item.severity.value,
            'expected_value': item.expected_value,
            'actual_value': item.actual_value,
            'property_path': item.property_path,
            'description': item.description,
            'detected_at': item.detected_at.isoformat(),
            'remediation_suggestion': item.remediation_suggestion
        }

    @staticmethod
    def _drift_item_from_dict(d: dict) -> DriftItem:
        return DriftItem(
            id=d['id'],
            resource_type=ResourceType(d['resource_type']),
            resource_id=d['resource_id'],
            resource_name=d['resource_name'],
            drift_type=DriftType(d['drift_type']),
            severity=DriftSeverity(d['severity']),
            expected_value=d['expected_value'],
            actual_value=d['actual_value'],
            property_path=d['property_path'],
            description=d['description'],
            detected_at=datetime.fromisoformat(d['detected_at']),
            remediation_suggestion=d.get('remediation_suggestion', '')
        )

    @classmethod
    def _report_from_row(cls, row) -> DriftReport:
        return DriftReport(
            id=row.id,
            scan_started=row.scan_started,
            scan_completed=row.scan_completed,
            total_resources=row.total_resources,
            drifted_resources=row.drifted_resources,
            drift_items=[cls._drift_item_from_dict(d) for d in (row.drift_items or [])],
            summary=row.summary or {}
        )

    def get_report(self, user_id: int, report_id: str) -> Optional[DriftReport]:
        """Get a specific drift report."""
        from models import DriftReportModel

        row = DriftReportModel.query.filter_by(id=report_id, user_id=user_id).first()
        return self._report_from_row(row) if row else None

    def get_recent_reports(self, user_id: int, limit: int = 10) -> list[DriftReport]:
        """Get recent drift reports."""
        from models import DriftReportModel

        rows = DriftReportModel.query.filter_by(user_id=user_id) \
            .order_by(DriftReportModel.scan_completed.desc()).limit(limit).all()
        return [self._report_from_row(row) for row in rows]

    def get_baseline_count(self, user_id: int) -> int:
        """Get number of baselined resources."""
        from models import DriftBaselineModel

        return DriftBaselineModel.query.filter_by(user_id=user_id).count()

    def get_baselines(self, user_id: int, resource_type: Optional[ResourceType] = None) -> list[BaselineResource]:
        """Get all baselines, optionally filtered by type."""
        from models import DriftBaselineModel

        query = DriftBaselineModel.query.filter_by(user_id=user_id)
        if resource_type:
            query = query.filter_by(resource_type=resource_type.value)

        return [
            BaselineResource(
                resource_type=ResourceType(row.resource_type),
                resource_id=row.resource_id,
                resource_name=row.resource_name,
                expected_config=row.expected_config or {},
                tags=row.tags or {},
                last_updated=row.last_updated
            )
            for row in query.all()
        ]


# Global instance
_drift_service: Optional[DriftDetectionService] = None


def get_drift_service() -> DriftDetectionService:
    """Get or create the global drift detection service."""
    global _drift_service
    if _drift_service is None:
        _drift_service = DriftDetectionService()
    return _drift_service
