"""
Analytics Service Tests

Guards against the Advanced Analytics Dashboard ever fabricating data again —
see CLAUDE.md's "every feature runs against a real cloud account" rule. Before
this fix, `AnalyticsService._ensure_sample_data()` unconditionally seeded a
90-day fake cost/incident/deployment/API-call history (via `random.uniform`/
`random.randint`/`random.choices`), a hardcoded `_cost_by_service` /
`_cost_by_team` dollar breakdown byte-identical for every user, and
`get_resource_utilization()` regenerated a fresh `random.uniform(40, 75)`
"utilization_avg" on every single call — all with no `[Sandbox]` label and no
dependency on whether the user had a cloud account connected at all.

Fixed by removing `_ensure_sample_data()` entirely and backing every metric
with a real SQL aggregation over this user's own rows (InfrastructureResource,
IncidentModel, InfrastructureChange), failing closed with
`data_available: False` when the user has no connected/previously-synced
cloud account.
"""

from datetime import datetime, timedelta

from services.analytics_service import AnalyticsService, AnalyticsDataError


class TestNoFabricatedDataWithoutAnAccount:
    """A user with no cloud account connected and nothing ever synced must
    get an honest "no data" response, never sample numbers."""

    def test_cost_breakdown_fails_closed(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.get_cost_breakdown()
        assert result['data_available'] is False
        assert result['by_service'] == {}
        assert result['by_team'] == {}
        assert result['total'] == 0
        assert 'message' in result and result['message']

    def test_dashboard_metrics_fails_closed(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.get_dashboard_metrics()
        assert result['data_available'] is False
        assert result['cost']['current_month'] == 0
        assert result['resources']['total'] == 0
        assert result['incidents']['this_month'] == 0
        assert result['deployments']['this_month'] == 0

    def test_resource_utilization_fails_closed(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.get_resource_utilization()
        assert result['data_available'] is False
        assert result['total_resources'] == 0
        assert result['by_type'] == {}

    def test_alerts_summary_fails_closed(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.get_alerts_summary()
        assert result['data_available'] is False
        assert result['total'] == 0

    def test_deployment_stats_fails_closed(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.get_deployment_stats()
        assert result['data_available'] is False
        assert result['total'] == 0

    def test_forecast_fails_closed_with_no_account(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        result = service.forecast_costs()
        assert result['data_available'] is False
        assert result['status'] == 'no_account'
        assert result['monthly_projection'] is None

    def test_time_series_returns_none_with_no_account(self, app, db_session, test_user):
        from services.analytics_service import TimeRange
        service = AnalyticsService(test_user.id)
        for name in ('daily_cost', 'resource_count', 'incidents', 'deployments', 'api_calls'):
            assert service.get_time_series(name, TimeRange.MONTH) is None

    def test_no_user_id_is_treated_as_no_account(self, app, db_session):
        service = AnalyticsService(None)
        result = service.get_cost_breakdown()
        assert result['data_available'] is False

    def test_require_data_source_raises(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        import pytest
        with pytest.raises(AnalyticsDataError):
            service._require_data_source()


class TestNoRandomnessAnywhere:
    """Regression guard for the specific fabrication bug: no method may ever
    invent a number via `random.*`."""

    def test_module_never_imports_or_calls_random(self):
        """AST-based, not a text search — the module's own docstrings
        legitimately mention `random.uniform` when describing the bug this
        file used to have."""
        import ast
        import services.analytics_service as mod

        tree = ast.parse(open(mod.__file__).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name == 'random' for a in node.names), \
                    "analytics_service.py must never import random again"
            if isinstance(node, ast.Name) and node.id == 'random':
                raise AssertionError("analytics_service.py references `random` outside a comment/docstring")

    def test_ensure_sample_data_no_longer_exists(self, app, db_session, test_user):
        service = AnalyticsService(test_user.id)
        assert not hasattr(service, '_ensure_sample_data')

    def test_forecast_is_deterministic_and_never_invents_a_projection(
        self, app, db_session, test_user
    ):
        from models import db, InfrastructureResource
        db.session.add(InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', monthly_cost=42.0,
        ))
        db.session.commit()

        service = AnalyticsService(test_user.id)
        first = service.forecast_costs()
        second = service.forecast_costs()
        assert first == second
        assert first['status'] == 'insufficient_data'
        assert first['monthly_projection'] is None
        assert first['forecast'] == []

    def test_resource_utilization_avg_is_never_a_random_percentage(
        self, app, db_session, test_user
    ):
        from models import db, InfrastructureResource
        db.session.add(InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', monthly_cost=10.0,
        ))
        db.session.commit()

        service = AnalyticsService(test_user.id)
        first = service.get_resource_utilization()
        second = service.get_resource_utilization()
        assert first['utilization_avg'] is None
        assert second['utilization_avg'] is None
        assert first['utilization_available'] is False


class TestRealDataProducesRealMetrics:
    """Once a user has real synced/logged rows, metrics reflect exactly
    those rows — nothing hardcoded, nothing extra."""

    def test_cost_breakdown_reflects_real_resources_only(self, app, db_session, test_user):
        from models import db, InfrastructureResource
        db.session.add_all([
            InfrastructureResource(
                user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
                resource_id='i-real1', monthly_cost=100.0,
            ),
            InfrastructureResource(
                user_id=test_user.id, cloud_provider='aws', resource_type='rds',
                resource_id='db-real1', monthly_cost=50.0,
            ),
        ])
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_cost_breakdown()

        assert result['data_available'] is True
        assert result['by_service'] == {'EC2': 100.0, 'RDS': 50.0}
        assert result['total'] == 150.0
        # The hardcoded figures this bug used to ship, regardless of account:
        assert result['by_service'].get('S3') != 45.0
        assert result['by_service'].get('Lambda') != 35.0

    def test_by_team_is_always_unavailable_no_team_data_source_exists(
        self, app, db_session, test_user
    ):
        """There is no team_id (or any team association) anywhere on
        InfrastructureResource, so a real per-team cost split cannot be
        computed. Documents the intentional gap rather than fabricating one
        (see CLAUDE_RUNBOOK.md)."""
        from models import db, InfrastructureResource
        db.session.add(InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', monthly_cost=100.0,
        ))
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_cost_breakdown()
        assert result['by_team'] == {}
        assert result['by_team_available'] is False

    def test_resource_utilization_counts_real_resources(self, app, db_session, test_user):
        from models import db, InfrastructureResource
        db.session.add_all([
            InfrastructureResource(
                user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
                resource_id='i-1', monthly_cost=1.0,
            ),
            InfrastructureResource(
                user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
                resource_id='i-2', monthly_cost=1.0,
            ),
            InfrastructureResource(
                user_id=test_user.id, cloud_provider='aws', resource_type='rds',
                resource_id='db-1', monthly_cost=1.0,
            ),
        ])
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_resource_utilization()
        assert result['total_resources'] == 3
        assert result['by_type'] == {'ec2': 2, 'rds': 1}

    def test_alerts_summary_reflects_real_incidents(self, app, db_session, test_user):
        from models import db, IncidentModel
        now = datetime.utcnow()
        db.session.add_all([
            IncidentModel(
                user_id=test_user.id, incident_key='inc-real-1', title='Real incident 1',
                severity='critical', status='resolved', triggered_at=now - timedelta(days=1),
            ),
            IncidentModel(
                user_id=test_user.id, incident_key='inc-real-2', title='Real incident 2',
                severity='low', status='detected', triggered_at=now - timedelta(days=2),
            ),
        ])
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_alerts_summary(days=7)
        assert result['data_available'] is True
        assert result['total'] == 2
        assert result['critical'] == 1
        assert result['low'] == 1
        assert result['resolved'] == 1
        assert result['open'] == 1

    def test_deployment_stats_reflects_real_changes_with_no_invented_split(
        self, app, db_session, test_user
    ):
        from models import db, InfrastructureChange
        db.session.add(InfrastructureChange(
            user_id=test_user.id, action_type='create', resource_type='ec2',
            resource_id='i-real1', title='[Chat] Create Ec2 Instance', status='executed',
        ))
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_deployment_stats(days=30)
        assert result['data_available'] is True
        assert result['total'] == 1
        # No real failure signal exists for this table (only successes are
        # ever written) — must not be fabricated as a 92%/8% split.
        assert result['success_rate'] is None
        assert result['success_rate_available'] is False
        assert result['avg_duration_minutes'] is None

    def test_dashboard_metrics_composes_real_submetrics(self, app, db_session, test_user):
        from models import db, InfrastructureResource
        db.session.add(InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', monthly_cost=77.0,
        ))
        db.session.commit()

        service = AnalyticsService(test_user.id)
        result = service.get_dashboard_metrics()
        assert result['data_available'] is True
        assert result['cost']['current_month'] == 77.0
        assert result['resources']['total'] == 1

    def test_metrics_are_isolated_per_user(self, app, db_session, test_user):
        from models import db, User, InfrastructureResource

        other = User(email='other-analytics@example.com', username='otheranalytics',
                     full_name='Other User')
        other.set_password('TestPassword123!')
        db.session.add(other)
        db.session.commit()

        db.session.add(InfrastructureResource(
            user_id=other.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-other', monthly_cost=999.0,
        ))
        db.session.commit()

        try:
            # test_user has nothing synced — must still fail closed even
            # though *some* user in the DB has real data.
            mine = AnalyticsService(test_user.id).get_cost_breakdown()
            assert mine['data_available'] is False
            assert mine['total'] == 0

            theirs = AnalyticsService(other.id).get_cost_breakdown()
            assert theirs['data_available'] is True
            assert theirs['total'] == 999.0
        finally:
            db.session.delete(other)
            db.session.commit()
