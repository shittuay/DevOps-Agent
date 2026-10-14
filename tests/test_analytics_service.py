"""services/analytics_service.py must never fabricate data.

Found by a scheduled audit (already flagged, unfixed, in CLAUDE.md): the
"Advanced Analytics Dashboard" (`/analytics/*`) built every metric from
`_ensure_sample_data()` — hardcoded per-service/per-team cost breakdowns and a
`random`-seeded 90-day history feeding a forecast with `random.uniform()`
noise on top. Every user saw byte-identical fabricated numbers regardless of
what (if anything) was in their connected cloud account — the same bug class
already fixed once for Drift Detection and Predictive Scaling. Fixed by
sourcing every metric from the user's real AWS Cost Explorer/CloudWatch data
(via services/cost_explorer.py, already used elsewhere) or this app's own
per-user tables (InfrastructureResource, IncidentModel, UsageLog), falling
back to honest zeros/empty series rather than invented numbers.
"""
from datetime import datetime, timedelta

from services.analytics_service import AnalyticsService, CostForecast, DataPoint
from src.utils.timeutils import utcnow


def test_empty_account_returns_zeros_not_fabricated_data(app, db_session, test_user):
    """A user with no cloud account connected and nothing synced must see
    honest zeros/empty structures everywhere — never the old hardcoded
    $450 EC2 / $280 RDS breakdown or a random-noise forecast."""
    service = AnalyticsService(test_user.id)

    metrics = service.get_dashboard_metrics()
    assert metrics['cost']['current_month'] == 0
    assert metrics['resources']['total'] == 0
    assert 'incidents' not in metrics
    assert metrics['deployments']['this_month'] == 0

    breakdown = service.get_cost_breakdown()
    assert breakdown['by_service'] == {}
    assert breakdown['total'] == 0

    util = service.get_resource_utilization()
    assert util['total_resources'] == 0
    assert util['utilization_avg'] == 0.0

    deploy = service.get_deployment_stats()
    assert deploy['total'] == 0
    assert deploy['success_rate'] == 0.0

    forecast = service.forecast_costs(30)
    assert forecast['monthly_projection'] == 0


def test_dashboard_metrics_reflect_real_synced_resources_only(app, db_session, test_user):
    """Cost/resource/deployment metrics must come from this user's
    real rows, and never another user's."""
    from models import User, InfrastructureResource, UsageLog

    # Reuse test_user's already-hashed password rather than introducing a new
    # literal credential-shaped string in test code.
    other = User(email='other-analytics@example.com', username='other_analytics',
                 password_hash=test_user.password_hash)
    db_session.add(other)
    db_session.commit()

    now = utcnow()
    db_session.add_all([
        InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-real1', status='running', monthly_cost=42.5,
            created_at=now - timedelta(days=10),
        ),
        InfrastructureResource(
            user_id=test_user.id, cloud_provider='aws', resource_type='rds',
            resource_id='db-real1', status='available', monthly_cost=10.0,
            created_at=now - timedelta(days=5),
        ),
        # Belongs to a different user — must never leak into test_user's totals.
        InfrastructureResource(
            user_id=other.id, cloud_provider='aws', resource_type='ec2',
            resource_id='i-other', status='running', monthly_cost=999.0,
            created_at=now,
        ),
        UsageLog(
            user_id=test_user.id, action_type='tool_use', tool_name='terraform_apply',
            success=True, created_at=now - timedelta(days=1),
        ),
        UsageLog(
            user_id=test_user.id, action_type='tool_use', tool_name='terraform_apply',
            success=False, created_at=now - timedelta(days=2),
        ),
        UsageLog(
            user_id=other.id, action_type='tool_use', tool_name='terraform_apply',
            success=True, created_at=now,
        ),
    ])
    db_session.commit()

    service = AnalyticsService(test_user.id)

    metrics = service.get_dashboard_metrics()
    assert metrics['resources']['total'] == 2
    assert metrics['deployments']['this_month'] == 2

    breakdown = service.get_cost_breakdown()
    assert breakdown['total'] == 52.5
    assert breakdown['by_service'] == {'ec2': 42.5, 'rds': 10.0}
    # No per-team cost attribution exists in this schema — must stay honestly
    # empty rather than reintroduce the old hardcoded Development/Production/
    # Staging/Testing split.
    assert breakdown['by_team'] == {}

    util = service.get_resource_utilization()
    assert util['total_resources'] == 2
    assert util['by_type'] == {'ec2': 1, 'rds': 1}

    deploy = service.get_deployment_stats(days=7)
    assert deploy['total'] == 2
    assert deploy['successful'] == 1
    assert deploy['failed'] == 1
    assert deploy['success_rate'] == 50.0

    other_service = AnalyticsService(other.id)
    other_metrics = other_service.get_dashboard_metrics()
    assert other_metrics['resources']['total'] == 1


def test_cost_forecast_has_no_random_noise(app, db_session):
    """CostForecast previously added `random.uniform()` variance on top of the
    projection. Identical historical input must now yield an identical
    forecast every time."""
    now = utcnow()
    historical = [DataPoint(now - timedelta(days=10 - i), 100.0 + i) for i in range(10)]

    first = CostForecast(historical)
    first.generate_forecast(5)
    second = CostForecast(historical)
    second.generate_forecast(5)

    assert [p.value for p in first.forecast] == [p.value for p in second.forecast]
