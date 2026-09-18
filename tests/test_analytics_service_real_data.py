"""
Regression tests for services/analytics_service.py.

Guards against the fabricated-data bug flagged in CLAUDE.md's "Non-negotiable: every
feature runs against a real cloud account" section: AnalyticsService used to invent
every metric (90 days of random.uniform/randint/choices cost/resource/incident/
deployment/api-call history, hardcoded per-service cost breakdowns, a forecast with
random jitter on top) for every user regardless of whether they had a cloud account
connected. It must now derive every metric from real per-user data (InfrastructureResource,
IncidentModel, UsageLog, UserCloudCredential) and report empty/zero when there is
nothing real to show, never a canned or randomized value.
"""

from datetime import datetime, timedelta

import pytest


def _make_credential(db_session, user_id, provider='aws'):
    from models import UserCloudCredential

    cred = UserCloudCredential(
        user_id=user_id,
        cloud_provider=provider,
        credentials_encrypted='ignored-in-this-test',
        is_active=True,
    )
    db_session.add(cred)
    db_session.commit()
    return cred


def _make_resource(db_session, user_id, resource_type='ec2', monthly_cost=100.0, status='running'):
    from models import InfrastructureResource

    resource = InfrastructureResource(
        user_id=user_id,
        cloud_provider='aws',
        resource_type=resource_type,
        resource_id=f'{resource_type}-{monthly_cost}',
        status=status,
        monthly_cost=monthly_cost,
    )
    db_session.add(resource)
    db_session.commit()
    return resource


def _make_incident(db_session, user_id, severity='critical', status='detected', triggered_at=None):
    from models import IncidentModel
    import uuid

    incident = IncidentModel(
        user_id=user_id,
        incident_key=str(uuid.uuid4())[:16],
        title='Test incident',
        severity=severity,
        status=status,
        source='manual',
        triggered_at=triggered_at or datetime.utcnow(),
    )
    db_session.add(incident)
    db_session.commit()
    return incident


def _make_usage_log(db_session, user_id, tool_name='list_ec2_instances', created_at=None):
    from models import UsageLog

    log = UsageLog(
        user_id=user_id,
        action_type='tool_use',
        tool_name=tool_name,
        success=True,
        created_at=created_at or datetime.utcnow(),
    )
    db_session.add(log)
    db_session.commit()
    return log


class TestNoFabricationWithoutAccount:
    """A user with no connected cloud account and no real data must get zeros, never invented numbers."""

    def test_cost_breakdown_empty_without_account(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        service = AnalyticsService(test_user.id)
        breakdown = service.get_cost_breakdown()
        assert breakdown['by_service'] == {}
        assert breakdown['by_team'] == {}
        assert breakdown['total'] == 0

    def test_cost_time_series_empty_without_account(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService, TimeRange

        service = AnalyticsService(test_user.id)
        series = service.get_time_series('daily_cost', TimeRange.MONTH)
        assert series.data_points == []

    def test_dashboard_metrics_zero_without_data(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        service = AnalyticsService(test_user.id)
        metrics = service.get_dashboard_metrics()
        assert metrics['cost']['current_month'] == 0
        assert metrics['resources']['total'] == 0
        assert metrics['incidents']['this_month'] == 0
        assert metrics['deployments']['this_month'] == 0

    def test_resource_utilization_has_no_fabricated_percentage(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        service = AnalyticsService(test_user.id)
        util = service.get_resource_utilization()
        assert util['total_resources'] == 0
        assert util['by_type'] == {}
        # No CPU/memory monitoring source is wired in — must not invent a percentage.
        assert util['utilization_avg'] is None

    def test_deployment_stats_never_fabricated(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        service = AnalyticsService(test_user.id)
        stats = service.get_deployment_stats()
        assert stats == {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'success_rate': None,
            'avg_duration_minutes': None,
            'trend': 'stable',
        }

    def test_forecast_empty_without_real_history(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        service = AnalyticsService(test_user.id)
        forecast = service.forecast_costs(days=30)
        assert forecast['historical'] == []
        assert forecast['forecast'] == []
        assert forecast['monthly_projection'] == 0


class TestRealDataIsUsed:
    """With real per-user rows present, the service must report those values exactly — no randomness."""

    def test_cost_breakdown_uses_real_infrastructure_resources(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        _make_credential(db_session, test_user.id)
        _make_resource(db_session, test_user.id, resource_type='ec2', monthly_cost=120.5)
        _make_resource(db_session, test_user.id, resource_type='ec2', monthly_cost=30.0)
        _make_resource(db_session, test_user.id, resource_type='rds', monthly_cost=80.25)
        _make_resource(db_session, test_user.id, resource_type='s3', monthly_cost=5.0, status='terminated')

        service = AnalyticsService(test_user.id)
        breakdown = service.get_cost_breakdown()

        assert breakdown['by_service'] == {'EC2': 150.5, 'RDS': 80.25}
        assert breakdown['total'] == pytest.approx(230.75)

    def test_cost_breakdown_ignores_other_users_resources(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService
        from models import User, db

        other = User(email='other-analytics@example.com', username='otheranalytics')
        other.set_password('Password123!')
        db.session.add(other)
        db.session.commit()

        _make_credential(db_session, test_user.id)
        _make_resource(db_session, other.id, resource_type='ec2', monthly_cost=999.0)

        service = AnalyticsService(test_user.id)
        breakdown = service.get_cost_breakdown()
        assert breakdown['by_service'] == {}
        assert breakdown['total'] == 0

        db.session.delete(other)
        db.session.commit()

    def test_resource_utilization_counts_real_resources_by_type(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        _make_resource(db_session, test_user.id, resource_type='ec2', monthly_cost=10)
        _make_resource(db_session, test_user.id, resource_type='ec2', monthly_cost=10)
        _make_resource(db_session, test_user.id, resource_type='rds', monthly_cost=10)

        service = AnalyticsService(test_user.id)
        util = service.get_resource_utilization()
        assert util['by_type'] == {'ec2': 2, 'rds': 1}
        assert util['total_resources'] == 3

    def test_alerts_summary_reflects_real_incident_severities(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        _make_incident(db_session, test_user.id, severity='critical', status='detected')
        _make_incident(db_session, test_user.id, severity='high', status='resolved')
        _make_incident(db_session, test_user.id, severity='low', status='closed')

        service = AnalyticsService(test_user.id)
        summary = service.get_alerts_summary(days=30)
        assert summary['total'] == 3
        assert summary['critical'] == 1
        assert summary['high'] == 1
        assert summary['low'] == 1
        assert summary['medium'] == 0
        assert summary['resolved'] == 2
        assert summary['open'] == 1

    def test_alerts_summary_excludes_incidents_outside_window(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService

        _make_incident(
            db_session, test_user.id, severity='critical',
            triggered_at=datetime.utcnow() - timedelta(days=60),
        )

        service = AnalyticsService(test_user.id)
        summary = service.get_alerts_summary(days=7)
        assert summary['total'] == 0

    def test_api_calls_time_series_uses_real_usage_logs(self, app, db_session, test_user):
        from services.analytics_service import AnalyticsService, TimeRange

        _make_usage_log(db_session, test_user.id)
        _make_usage_log(db_session, test_user.id)

        service = AnalyticsService(test_user.id)
        series = service.get_time_series('api_calls', TimeRange.MONTH)
        assert sum(p.value for p in series.data_points) == 2

    def test_no_random_module_used(self):
        """The whole point of this fix: no randomness anywhere in the module."""
        import services.analytics_service as mod
        import inspect

        source = inspect.getsource(mod)
        assert 'random' not in source, (
            "analytics_service.py must not use the random module — "
            "every metric must come from real data or report as unavailable/zero"
        )
