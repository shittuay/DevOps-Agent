"""Regression: drift baselines and reports must survive across separate
DriftDetectionService instances, not just the process that created them.

The service used to store everything in plain Python dicts on the
module-level singleton (`get_drift_service()`). Production runs multiple
gunicorn workers, each its own process: a baseline added on one worker was
invisible to a scan on another ("No baselines configured" even after adding
one), and every report vanished on the next deploy. Each test below builds a
*fresh* DriftDetectionService() to stand in for "a different worker" -- if
data only lived in that instance's memory, these would fail.
"""
from services.drift_detection import (
    DriftDetectionService, BaselineResource, ResourceType,
)


def _ec2_baseline():
    return BaselineResource(
        resource_type=ResourceType.EC2_INSTANCE,
        resource_id='i-test123',
        resource_name='test-instance',
        expected_config={'instance_type': 't3.small', 'state': 'running'},
        tags={'Environment': 'test'}
    )


def test_baseline_visible_from_a_different_service_instance(app, db_session, test_user):
    DriftDetectionService().add_baseline(test_user.id, _ec2_baseline())

    other_worker = DriftDetectionService()
    assert other_worker.get_baseline_count(test_user.id) == 1
    baselines = other_worker.get_baselines(test_user.id)
    assert baselines[0].resource_id == 'i-test123'


def test_scan_report_visible_from_a_different_service_instance(app, db_session, test_user):
    DriftDetectionService().add_baseline(test_user.id, _ec2_baseline())

    scanning_worker = DriftDetectionService()
    report = scanning_worker.scan_for_drift(test_user.id)

    reading_worker = DriftDetectionService()
    fetched = reading_worker.get_report(test_user.id, report.id)
    assert fetched is not None
    assert fetched.id == report.id
    assert fetched.summary == report.summary

    recent = reading_worker.get_recent_reports(test_user.id)
    assert any(r.id == report.id for r in recent)


def test_remove_baseline_persists_across_instances(app, db_session, test_user):
    DriftDetectionService().add_baseline(test_user.id, _ec2_baseline())
    assert DriftDetectionService().get_baseline_count(test_user.id) == 1

    DriftDetectionService().remove_baseline(test_user.id, ResourceType.EC2_INSTANCE, 'i-test123')
    assert DriftDetectionService().get_baseline_count(test_user.id) == 0


def test_add_baseline_upserts_rather_than_duplicates(app, db_session, test_user):
    service = DriftDetectionService()
    service.add_baseline(test_user.id, _ec2_baseline())
    updated = _ec2_baseline()
    updated.expected_config = {'instance_type': 't3.large', 'state': 'running'}
    service.add_baseline(test_user.id, updated)

    assert service.get_baseline_count(test_user.id) == 1
    baseline = service.get_baselines(test_user.id)[0]
    assert baseline.expected_config['instance_type'] == 't3.large'
