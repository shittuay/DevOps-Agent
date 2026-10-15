"""The Dashboard only shows what it can back up (2026-10-14 audit).

- Idle and Spot recommendations used to be guessed from the instance *name* ("dev",
  "test", "worker") when CloudWatch had nothing; now no metrics means no recommendation.
- "Stopped for N days" used `last_synced`, which every sync resets, so it never fired.
  It now uses the time EC2 reports in StateTransitionReason.
- With no billing data the forecast was the estimate x 1.05. Now there is no forecast.
- "Apply" returned 501; it is now "Fix in chat", which opens chat with the text filled in.
"""
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ec2(user, name='web-1', status='running', meta=None, cost=70.0):
    from models import InfrastructureResource, db
    r = InfrastructureResource(user_id=user.id, cloud_provider='aws', resource_type='ec2',
                               resource_id=f'i-{name}', resource_name=name, region='us-east-1',
                               status=status, monthly_cost=cost,
                               resource_metadata=meta or {'instance_type': 't3.large'})
    db.session.add(r)
    db.session.commit()
    return r


def _no_aws(monkeypatch):
    import services.cost_explorer as ce
    import services.infrastructure_sync as sync

    def boom(*a, **k):
        raise RuntimeError('no credentials')
    monkeypatch.setattr(ce, 'get_instance_utilization', boom)
    monkeypatch.setattr(sync, 'check_unattached_volumes', lambda uid: None)


def test_no_metrics_means_no_idle_or_spot_guess(app, db_session, test_user, monkeypatch):
    from models import CostOptimization
    from services.infrastructure_sync import generate_cost_recommendations
    _no_aws(monkeypatch)
    _ec2(test_user, name='dev-batch-worker')
    generate_cost_recommendations(test_user.id)
    types = {r.recommendation_type for r in CostOptimization.query.filter_by(user_id=test_user.id)}
    assert types == set(), types


def test_low_cpu_still_recommends_stopping(app, db_session, test_user, monkeypatch):
    import services.cost_explorer as ce
    import services.infrastructure_sync as sync
    from models import CostOptimization
    monkeypatch.setattr(ce, 'get_instance_utilization',
                        lambda uid, rid, days=7: {'cpu': {'average': 1.0, 'max': 3.0}})
    monkeypatch.setattr(sync, 'check_unattached_volumes', lambda uid: None)
    _ec2(test_user)
    sync.generate_cost_recommendations(test_user.id)
    types = {r.recommendation_type for r in CostOptimization.query.filter_by(user_id=test_user.id)}
    assert 'idle_resource' in types


def test_stopped_days_come_from_ec2_not_last_sync(app, db_session, test_user, monkeypatch):
    from models import CostOptimization
    from services.infrastructure_sync import (_stopped_since_from_reason, days_stopped,
                                              generate_cost_recommendations)
    from src.utils.timeutils import utcnow
    _no_aws(monkeypatch)
    assert _stopped_since_from_reason('User initiated (2026-08-01 14:03:22 GMT)') == '2026-08-01T14:03:22'
    assert _stopped_since_from_reason('') is None

    since = (utcnow().replace(tzinfo=None) - timedelta(days=45)).isoformat()
    r = _ec2(test_user, name='old', status='stopped',
             meta={'instance_type': 't3.large', 'stopped_since': since})
    assert days_stopped(r) == 45
    _ec2(test_user, name='unknown', status='stopped')  # no time known: no recommendation
    generate_cost_recommendations(test_user.id)
    [rec] = CostOptimization.query.filter_by(user_id=test_user.id).all()
    assert rec.recommendation_type == 'unused_resource' and '45 days' in rec.title


def test_unsupported_pending_recommendations_are_cleared(app, db_session, test_user, monkeypatch):
    from models import CostOptimization, db
    from services.infrastructure_sync import generate_cost_recommendations
    _no_aws(monkeypatch)
    r = _ec2(test_user, name='dev-1')
    db.session.add(CostOptimization(user_id=test_user.id, resource_id=r.id, status='pending',
                                    recommendation_type='spot_instance', title='Spot: dev-1'))
    db.session.add(CostOptimization(user_id=test_user.id, resource_id=r.id, status='dismissed',
                                    recommendation_type='idle_resource', title='Idle: dev-1'))
    db.session.commit()
    generate_cost_recommendations(test_user.id)
    left = [(c.recommendation_type, c.status) for c in CostOptimization.query.filter_by(user_id=test_user.id)]
    assert left == [('idle_resource', 'dismissed')]


def test_dismissed_recommendation_stays_dismissed(app, db_session, test_user, monkeypatch):
    import services.cost_explorer as ce
    import services.infrastructure_sync as sync
    from models import CostOptimization, db
    monkeypatch.setattr(ce, 'get_instance_utilization',
                        lambda uid, rid, days=7: {'cpu': {'average': 1.0, 'max': 3.0}})
    monkeypatch.setattr(sync, 'check_unattached_volumes', lambda uid: None)
    r = _ec2(test_user, meta={'instance_type': 't3.micro'})
    db.session.add(CostOptimization(user_id=test_user.id, resource_id=r.id, status='dismissed',
                                    recommendation_type='idle_resource', title='x'))
    db.session.commit()
    sync.generate_cost_recommendations(test_user.id)
    assert CostOptimization.query.filter_by(user_id=test_user.id, status='pending').count() == 0


def test_each_unattached_volume_gets_its_own_row(app, db_session, test_user, monkeypatch):
    import services.infrastructure_sync as sync
    from models import CostOptimization

    class FakeEC2:
        def describe_volumes(self, **kw):
            return {'Volumes': [{'VolumeId': 'vol-a', 'Size': 10, 'VolumeType': 'gp3'},
                                {'VolumeId': 'vol-b', 'Size': 20, 'VolumeType': 'gp3'}]}
    monkeypatch.setattr(sync, '_get_user_boto_client', lambda uid, svc, *a, **k: FakeEC2())
    sync.check_unattached_volumes(test_user.id)
    titles = sorted(c.title for c in CostOptimization.query.filter_by(user_id=test_user.id))
    assert titles == ['Unattached EBS volume: vol-a', 'Unattached EBS volume: vol-b']


def test_no_invented_forecast_without_billing(authenticated_client, test_user, monkeypatch):
    import services.cost_explorer as ce
    from models import db
    _ec2(test_user)

    def boom(*a, **k):
        raise RuntimeError('Cost Explorer off')
    monkeypatch.setattr(ce, 'get_actual_costs', boom)
    body = authenticated_client.get('/api/dashboard/costs').get_json()
    assert body['source'] == 'estimate'
    assert body['forecast']['forecast_total'] is None
    assert body['total_cost'] == 70.0


def test_cost_explorer_services_are_merged_across_months(app, db_session, test_user, monkeypatch):
    import services.cost_explorer as ce

    def group(name, amt):
        return {'Keys': [name], 'Metrics': {'UnblendedCost': {'Amount': str(amt), 'Unit': 'USD'}}}

    class FakeCE:
        def get_cost_and_usage(self, **kw):
            if kw['Granularity'] == 'MONTHLY':
                return {'ResultsByTime': [{'Groups': [group('Amazon EC2', 10)]},
                                          {'Groups': [group('Amazon EC2', 5), group('Amazon S3', 1)]}]}
            return {'ResultsByTime': []}
    monkeypatch.setattr(ce, '_get_user_boto_client', lambda *a, **k: FakeCE())
    out = ce.get_actual_costs(test_user.id)
    assert out['services'] == [{'service': 'Amazon EC2', 'cost': 15.0, 'unit': 'USD'},
                               {'service': 'Amazon S3', 'cost': 1.0, 'unit': 'USD'}]
    assert out['source'] == 'cost_explorer'


def test_apply_is_replaced_by_fix_in_chat(authenticated_client):
    assert authenticated_client.post('/api/dashboard/recommendations/1/apply', json={}).status_code in (404, 405)
    html = (ROOT / 'templates' / 'dashboard_live.html').read_text()
    assert 'Fix in chat' in html and '_applyRec' not in html
    assert "'/chat?prefill='" in html
    assert "params.get('prefill')" in (ROOT / 'templates' / 'index.html').read_text()
    assert 'Estimated monthly cost' in html
