"""
Analytics Service Tests

Guards against services/analytics_service.py ever fabricating cost, resource,
incident or deployment data again — see CLAUDE.md's "every feature runs
against a real cloud account" rule (flagged by the 2026-09-02 scheduled audit
as the same _ensure_sample_data()-style fabrication already fixed in
services/predictive_scaling.py, at larger scope). The service previously
seeded 90 days of random.uniform()-generated cost/resource/incident/deploy/
API-call time series plus hardcoded per-service/per-team cost dollar figures,
byte-identical in shape for every user regardless of whether a cloud account
was connected. Fixed by routing every metric through a real source
(services.cost_explorer / InfrastructureResource / IncidentModel / UsageLog)
with an honest empty/zero/`available: False` result when no real data exists,
never invented numbers.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from services.analytics_service import AnalyticsService, TimeRange


class TestNoFabricatedData:
    """A fresh user with no cloud account and no history gets honest zeros."""

    def test_no_sample_data_methods_remain(self):
        service = AnalyticsService(user_id=1)
        assert not hasattr(service, '_ensure_sample_data')
        assert not hasattr(service, '_time_series_cache')
        assert not hasattr(service, '_cost_by_service')
        assert not hasattr(service, '_cost_by_team')

    def test_random_is_not_imported(self):
        import services.analytics_service as mod
        assert not hasattr(mod, 'random')

    def test_dashboard_metrics_zero_for_unknown_user(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        with patch('services.cost_explorer.get_actual_costs', side_effect=Exception('no creds')):
            data = service.get_dashboard_metrics(days=30)
        assert data['cost']['current_month'] == 0
        assert data['resources']['total'] == 0
        assert data['incidents']['this_month'] == 0
        assert data['deployments']['this_month'] == 0
        assert data['deployments']['available'] is False

    def test_cost_analytics_empty_for_unknown_user(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        with patch('services.cost_explorer.get_actual_costs', side_effect=Exception('no creds')):
            data = service.get_cost_analytics(datetime.utcnow() - timedelta(days=30), datetime.utcnow())
        assert data['by_service'] == {}
        assert data['by_resource'] == {}
        assert data['total'] == 0

    def test_forecast_unavailable_without_credentials(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        with patch(
            'services.cost_explorer.get_cost_forecast',
            return_value={'forecast_total': None, 'error': 'Insufficient data for forecast'},
        ):
            forecast = service.forecast_costs(30)
        assert forecast['available'] is False
        assert forecast['monthly_projection'] == 0.0

    def test_resource_utilization_zero_for_unknown_user(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        data = service.get_resource_utilization()
        assert data['total_resources'] == 0
        assert data['by_type'] == {}
        # utilization_avg is honestly None (not collected), never invented
        assert data['utilization_avg'] is None

    def test_alerts_summary_zero_for_unknown_user(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        data = service.get_alerts_summary(days=7)
        assert data['total'] == 0
        assert data['critical'] == 0
        assert data['open'] == 0

    def test_deployment_stats_honestly_unavailable(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        data = service.get_deployment_stats(days=30)
        assert data['available'] is False
        assert data['total'] == 0
        assert data['success_rate'] is None

    def test_time_series_no_fabricated_points(self, app, db_session):
        service = AnalyticsService(user_id=999999)
        with patch('services.cost_explorer.get_actual_costs', side_effect=Exception('no creds')):
            series = service.get_time_series('daily_cost', TimeRange.MONTH)
        assert series.data_points == []


class TestRealDataFlowsThrough:
    """Once real DB rows exist, the service reports them accurately."""

    def test_resource_utilization_reflects_real_synced_resources(self, app, db_session, test_user):
        from models import InfrastructureResource, db

        r1 = InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', resource_name='real-1', status='running', monthly_cost=10.0,
        )
        r2 = InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='rds',
            resource_id='db-real1', resource_name='real-db', status='available', monthly_cost=20.0,
        )
        terminated = InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-dead1', resource_name='dead-1', status='terminated', monthly_cost=5.0,
        )
        db.session.add_all([r1, r2, terminated])
        db.session.commit()

        service = AnalyticsService(user_id=test_user.id)
        data = service.get_resource_utilization()

        assert data['total_resources'] == 2  # terminated resource excluded
        assert data['by_type'] == {'ec2': 1, 'rds': 1}

    def test_cost_analytics_falls_back_to_real_db_aggregate(self, app, db_session, test_user):
        from models import InfrastructureResource, db

        db.session.add(InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real2', resource_name='real-2', status='running', monthly_cost=42.5,
        ))
        db.session.commit()

        service = AnalyticsService(user_id=test_user.id)
        with patch('services.cost_explorer.get_actual_costs', side_effect=Exception('AWS credentials not configured')):
            data = service.get_cost_analytics(datetime.utcnow() - timedelta(days=30), datetime.utcnow())

        assert data['source'] == 'database'
        assert data['by_service'] == {'ec2': 42.5}
        assert data['total'] == 42.5

    def test_cost_analytics_uses_real_cost_explorer_when_available(self, app, db_session, test_user):
        fake_ce_result = {
            'total_cost': 123.45,
            'period_days': 30,
            'services': [{'service': 'AmazonEC2', 'cost': 123.45, 'unit': 'USD'}],
            'daily_trend': [{'date': '2026-09-01', 'cost': 4.0}],
            'start_date': '2026-08-01',
            'end_date': '2026-09-01',
        }
        service = AnalyticsService(user_id=test_user.id)
        with patch('services.cost_explorer.get_actual_costs', return_value=dict(fake_ce_result)):
            data = service.get_cost_analytics(datetime.utcnow() - timedelta(days=30), datetime.utcnow())

        assert data['by_service'] == {'AmazonEC2': 123.45}
        assert data['total'] == 123.45

    def test_alerts_summary_counts_real_incidents(self, app, db_session, test_user):
        from models import IncidentModel, db

        now = datetime.utcnow()
        db.session.add_all([
            IncidentModel(
                user_id=test_user.id, incident_key='inc-1', title='t1',
                severity='critical', status='resolved', triggered_at=now,
            ),
            IncidentModel(
                user_id=test_user.id, incident_key='inc-2', title='t2',
                severity='low', status='detected', triggered_at=now,
            ),
        ])
        db.session.commit()

        service = AnalyticsService(user_id=test_user.id)
        data = service.get_alerts_summary(days=7)

        assert data['total'] == 2
        assert data['critical'] == 1
        assert data['low'] == 1
        assert data['resolved'] == 1
        assert data['open'] == 1

    def test_incidents_isolated_per_user(self, app, db_session, test_user):
        from models import IncidentModel, User, db

        other = User(email='other-analytics@example.com', username='otheranalytics', full_name='Other')
        other.set_password('TestPassword123!')
        db.session.add(other)
        db.session.commit()

        db.session.add(IncidentModel(
            user_id=other.id, incident_key='inc-other', title='not mine',
            severity='critical', status='detected', triggered_at=datetime.utcnow(),
        ))
        db.session.commit()

        service = AnalyticsService(user_id=test_user.id)
        data = service.get_alerts_summary(days=7)
        assert data['total'] == 0

        db.session.delete(IncidentModel.query.filter_by(incident_key='inc-other').first())
        db.session.delete(other)
        db.session.commit()

    def test_api_calls_time_series_reflects_real_usage_logs(self, app, db_session, test_user):
        from models import UsageLog, db

        db.session.add(UsageLog(
            user_id=test_user.id, action_type='tool_use', tool_name='list_ec2_instances',
            success=True, created_at=datetime.utcnow(),
        ))
        db.session.commit()

        service = AnalyticsService(user_id=test_user.id)
        series = service.get_time_series('api_calls', TimeRange.WEEK)

        assert sum(p.value for p in series.data_points) == 1
