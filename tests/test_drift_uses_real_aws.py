"""Drift detection must read the user's real cloud account — never canned data.

`_get_actual_state()` used to return hardcoded dicts under a "# In a real
implementation, this would call AWS APIs" comment, with no RDS branch at all.
Every user got a byte-identical report: a critical "security group open to
0.0.0.0/0" alert that was a literal in the source, and 6 phantom "property
removed" rows for RDS (the missing branch fell through to `return {}`, which
_compare_configs reads as "every expected property vanished") — reported against
an AWS account that contained no database whatsoever.

See CLAUDE.md, "every feature runs against a real cloud account".
"""
import pytest

from services.drift_detection import (
    DriftDetectionService, BaselineResource, ResourceType, DriftScanError, DriftType,
)
from tests.drift_fakes import FakeEc2, FakeRds, FakeS3, patch_boto, clear_drift_state


@pytest.fixture(autouse=True)
def _isolate_baselines(app, db_session):
    with app.app_context():
        clear_drift_state()
    yield


def _rds_baseline():
    return BaselineResource(
        resource_type=ResourceType.RDS_INSTANCE,
        resource_id='mydb-instance',
        resource_name='production-database',
        expected_config={
            'engine': 'postgres',
            'engine_version': '14.9',
            'instance_class': 'db.t3.medium',
            'publicly_accessible': False,
            'storage_encrypted': True,
            'multi_az': True,
        },
    )


def _live_rds(**overrides):
    db = {
        'DBInstanceIdentifier': 'mydb-instance',
        'Engine': 'postgres',
        'EngineVersion': '14.9',
        'DBInstanceClass': 'db.t3.medium',
        'PubliclyAccessible': False,
        'StorageEncrypted': True,
        'MultiAZ': True,
    }
    db.update(overrides)
    return db


def test_scan_fails_when_no_cloud_account_attached(app, db_session, test_user, monkeypatch):
    """The headline rule: no account means no report, never invented findings."""
    service = DriftDetectionService()
    service.add_baseline(test_user.id, _rds_baseline())

    patch_boto(monkeypatch, {}, error=Exception('AWS credentials not configured.'))

    with pytest.raises(DriftScanError):
        service.scan_for_drift(test_user.id)


def test_matching_rds_produces_no_drift(app, db_session, test_user, monkeypatch):
    """A database that matches its baseline is clean — the old code reported 6 drifts."""
    service = DriftDetectionService()
    service.add_baseline(test_user.id, _rds_baseline())
    patch_boto(monkeypatch, {'rds': FakeRds({'mydb-instance': _live_rds()})})

    report = service.scan_for_drift(test_user.id)
    assert report.summary['total_drifts'] == 0


def test_missing_rds_is_one_removed_finding_not_six_property_removals(
    app, db_session, test_user, monkeypatch
):
    """This is exactly what the reporter saw: 6 rows for a database that doesn't exist."""
    service = DriftDetectionService()
    service.add_baseline(test_user.id, _rds_baseline())
    patch_boto(monkeypatch, {'rds': FakeRds({})})  # account has no databases

    report = service.scan_for_drift(test_user.id)

    assert len(report.drift_items) == 1
    item = report.drift_items[0]
    assert item.drift_type == DriftType.REMOVED
    assert report.summary['by_resource_type'].get('rds_instance') == 1


def test_real_rds_values_are_reported(app, db_session, test_user, monkeypatch):
    """Drift must reflect the live account, not a canned diff."""
    service = DriftDetectionService()
    service.add_baseline(test_user.id, _rds_baseline())
    patch_boto(monkeypatch, {'rds': FakeRds({
        'mydb-instance': _live_rds(StorageEncrypted=False, DBInstanceClass='db.t3.large'),
    })})

    report = service.scan_for_drift(test_user.id)
    drifted = {d.property_path: (d.expected_value, d.actual_value) for d in report.drift_items}

    assert drifted['storage_encrypted'] == (True, False)
    assert drifted['instance_class'] == ('db.t3.medium', 'db.t3.large')


def test_security_group_ingress_comes_from_aws(app, db_session, test_user, monkeypatch):
    """The old code hardcoded a 0.0.0.0/0 ingress rule and flagged it critical for everyone."""
    service = DriftDetectionService()
    service.add_baseline(test_user.id, BaselineResource(
        resource_type=ResourceType.EC2_SECURITY_GROUP,
        resource_id='sg-real',
        resource_name='web-sg',
        expected_config={'ingress': [{'port': 443, 'cidr': '10.0.0.0/8'}]},
    ))
    patch_boto(monkeypatch, {'ec2': FakeEc2(security_groups={'sg-real': {
        'GroupId': 'sg-real', 'GroupName': 'web-sg', 'VpcId': 'vpc-real',
        'IpPermissions': [
            {'FromPort': 443, 'IpRanges': [{'CidrIp': '10.0.0.0/8'}], 'Ipv6Ranges': []},
        ],
    }})})

    report = service.scan_for_drift(test_user.id)

    # locked-down group, so nothing should be raised — least of all a 0.0.0.0/0 alert
    assert report.summary['total_drifts'] == 0
    assert '0.0.0.0/0' not in str(report.drift_items)


def test_terminated_instance_counts_as_gone(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    service.add_baseline(test_user.id, BaselineResource(
        resource_type=ResourceType.EC2_INSTANCE,
        resource_id='i-dead',
        resource_name='old-box',
        expected_config={'instance_type': 't3.small'},
    ))
    patch_boto(monkeypatch, {'ec2': FakeEc2(instances={'i-dead': {
        'InstanceId': 'i-dead', 'InstanceType': 't3.small',
        'State': {'Name': 'terminated'}, 'SecurityGroups': [], 'Tags': [],
    }})})

    report = service.scan_for_drift(test_user.id)
    assert [d.drift_type for d in report.drift_items] == [DriftType.REMOVED]


def test_s3_bucket_state_read_from_aws(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    service.add_baseline(test_user.id, BaselineResource(
        resource_type=ResourceType.S3_BUCKET,
        resource_id='real-bucket',
        resource_name='real-bucket',
        expected_config={'versioning': True, 'encryption': 'AES256'},
    ))
    patch_boto(monkeypatch, {'s3': FakeS3({'real-bucket': {
        'versioning': False, 'encryption': None, 'pab': {},
    }})})

    report = service.scan_for_drift(test_user.id)
    drifted = {d.property_path: (d.expected_value, d.actual_value) for d in report.drift_items}

    assert drifted['versioning'] == (True, False)


def test_no_hardcoded_sample_resources_remain_in_source():
    """The sample baselines and canned state that produced the fictional report."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ('services/drift_detection.py', 'routes/drift.py'):
        source = (root / rel).read_text(encoding='utf-8')
        for token in ('i-0abc123def456', 'sg-12345', 'my-app-data-bucket', 'import/sample'):
            assert token not in source, f"{rel} still contains hardcoded sample data: {token}"
