"""Capturing baselines from the live cloud account.

Removing the fake `/api/import/sample` endpoint left no way at all to create a
baseline through the UI, which made drift unusable — you could only scan zero
baselines. Capture reads the user's real account instead.
"""
import pytest

from services.drift_detection import (
    DriftDetectionService, ResourceType, DriftScanError,
)
from tests.drift_fakes import FakeEc2, FakeRds, FakeS3, patch_boto, clear_drift_state


@pytest.fixture(autouse=True)
def _isolate_baselines(app, db_session):
    with app.app_context():
        clear_drift_state()
    yield


def _account(monkeypatch):
    """A small but realistic account."""
    ec2 = FakeEc2(
        instances={'i-real1': {
            'InstanceId': 'i-real1', 'InstanceType': 't3.small',
            'State': {'Name': 'running'},
            'SecurityGroups': [{'GroupId': 'sg-real'}],
            'Tags': [{'Key': 'Name', 'Value': 'web-1'}],
        }},
        security_groups={'sg-real': {
            'GroupId': 'sg-real', 'GroupName': 'web-sg', 'VpcId': 'vpc-1',
            'IpPermissions': [
                {'FromPort': 443, 'IpRanges': [{'CidrIp': '10.0.0.0/8'}], 'Ipv6Ranges': []},
            ],
        }},
    )
    rds = FakeRds({'prod-db': {
        'DBInstanceIdentifier': 'prod-db', 'Engine': 'postgres', 'EngineVersion': '15.4',
        'DBInstanceClass': 'db.t3.medium', 'PubliclyAccessible': False,
        'StorageEncrypted': True, 'MultiAZ': True,
    }})
    s3 = FakeS3({'real-bucket': {'versioning': True, 'encryption': 'AES256', 'pab': {
        'BlockPublicAcls': True, 'BlockPublicPolicy': True,
    }}})
    patch_boto(monkeypatch, {'ec2': ec2, 'rds': rds, 's3': s3})


def test_capture_snapshots_every_resource_type(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    _account(monkeypatch)

    result = service.capture_baselines_from_account(test_user.id)

    assert result['by_type'] == {
        'ec2_instance': 1, 'security_group': 1, 'rds_instance': 1, 's3_bucket': 1,
    }
    assert service.get_baseline_count(test_user.id) == 4


def test_captured_baseline_scans_clean(app, db_session, test_user, monkeypatch):
    """The one that matters: capture then scan an unchanged account = zero drift.

    Capture and scan must share normalizers. If capture wrote a different key
    shape than the scan reads back, every baseline would report drift the moment
    it was created.
    """
    service = DriftDetectionService()
    _account(monkeypatch)

    service.capture_baselines_from_account(test_user.id)
    report = service.scan_for_drift(test_user.id)

    assert report.summary['total_drifts'] == 0, [
        (d.resource_id, d.property_path, d.expected_value, d.actual_value)
        for d in report.drift_items
    ]


def test_change_after_capture_is_detected(app, db_session, test_user, monkeypatch):
    """Capture, then someone opens the security group to the world."""
    service = DriftDetectionService()
    _account(monkeypatch)
    service.capture_baselines_from_account(test_user.id)

    opened = FakeEc2(
        instances={'i-real1': {
            'InstanceId': 'i-real1', 'InstanceType': 't3.small',
            'State': {'Name': 'running'},
            'SecurityGroups': [{'GroupId': 'sg-real'}],
            'Tags': [{'Key': 'Name', 'Value': 'web-1'}],
        }},
        security_groups={'sg-real': {
            'GroupId': 'sg-real', 'GroupName': 'web-sg', 'VpcId': 'vpc-1',
            'IpPermissions': [
                {'FromPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}], 'Ipv6Ranges': []},
            ],
        }},
    )
    rds = FakeRds({'prod-db': {
        'DBInstanceIdentifier': 'prod-db', 'Engine': 'postgres', 'EngineVersion': '15.4',
        'DBInstanceClass': 'db.t3.medium', 'PubliclyAccessible': False,
        'StorageEncrypted': True, 'MultiAZ': True,
    }})
    s3 = FakeS3({'real-bucket': {'versioning': True, 'encryption': 'AES256', 'pab': {
        'BlockPublicAcls': True, 'BlockPublicPolicy': True,
    }}})
    patch_boto(monkeypatch, {'ec2': opened, 'rds': rds, 's3': s3})

    report = service.scan_for_drift(test_user.id)

    ingress = [d for d in report.drift_items if d.property_path.startswith('ingress')]
    assert ingress, "opening a security group to 0.0.0.0/0 must be detected"
    assert '0.0.0.0/0' in str(ingress[0].actual_value)


def test_capture_without_credentials_raises(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    patch_boto(monkeypatch, {}, error=Exception('AWS credentials not configured.'))

    with pytest.raises(DriftScanError):
        service.capture_baselines_from_account(test_user.id)

    assert service.get_baseline_count(test_user.id) == 0


def test_capture_skips_terminated_instances(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    patch_boto(monkeypatch, {'ec2': FakeEc2(instances={'i-dead': {
        'InstanceId': 'i-dead', 'InstanceType': 't3.small',
        'State': {'Name': 'terminated'}, 'SecurityGroups': [], 'Tags': [],
    }})})

    result = service.capture_baselines_from_account(
        test_user.id, [ResourceType.EC2_INSTANCE]
    )
    assert result['total'] == 0


def test_capture_can_be_limited_to_one_type(app, db_session, test_user, monkeypatch):
    service = DriftDetectionService()
    _account(monkeypatch)

    result = service.capture_baselines_from_account(
        test_user.id, [ResourceType.RDS_INSTANCE]
    )
    assert result['by_type'] == {'rds_instance': 1}


def test_capture_endpoint_reports_failure_honestly(
    authenticated_client, app, db_session, test_user, monkeypatch
):
    """No account attached must surface as an error, never an empty success."""
    from models import db

    test_user.role = 'approver'
    db.session.commit()

    patch_boto(monkeypatch, {}, error=Exception('AWS credentials not configured.'))

    resp = authenticated_client.post('/drift/api/baselines/capture', json={})
    assert resp.status_code == 502
    body = resp.get_json()
    assert body['success'] is False
    assert body['scan_failed'] is True
