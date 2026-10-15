"""Alerts that were promised now actually go out (2026-10-14 audit).

- Outgoing webhooks: nothing ever called trigger_webhook. resource.created/deleted are
  now sent from change history; resource.updated / alert.triggered are no longer offered.
- Teams channels were saved but _send_async only delivered to Slack.
- Budget alerts were saved and never checked.
- The weekly digest ran every 168h from process start and sent only if that moment was
  a Sunday. The cost_check and security_scan jobs only logged (and matched nobody).
"""
from datetime import date, timedelta

import pytest


class _Thread:
    """Run 'background' work inline so tests can see it."""
    def __init__(self, target=None, args=(), daemon=None, name=None, **kw):
        self._t, self._a = target, args

    def start(self):
        self._t(*self._a)


# ── outgoing webhooks ──────────────────────────────────────────────────────

def _hook(user, events, url='https://hooks.example.com/x'):
    from models import WebhookEndpoint, db
    h = WebhookEndpoint(user_id=user.id, name='ci', url=url, secret='s', events=events)
    db.session.add(h)
    db.session.commit()
    return h


def test_resource_events_reach_subscribed_webhooks(app, db_session, test_user, monkeypatch):
    import threading
    import services.api_gateway as gw
    sent = []
    monkeypatch.setattr(threading, 'Thread', _Thread)
    monkeypatch.setattr(gw.APIGatewayService, 'trigger_webhook',
                        lambda self, event, payload, user_id=None: sent.append((event, payload, user_id)))
    _hook(test_user, ['resource.deleted'])
    with app.app_context():
        assert gw.dispatch_webhook_event(test_user.id, 'resource.created', {'x': 1}) is False
        assert gw.dispatch_webhook_event(test_user.id, 'resource.deleted', {'resource': {'id': 'i-1'}})
    [(event, payload, uid)] = sent
    assert event == 'resource.deleted' and uid == test_user.id
    assert payload['resource'] == {'id': 'i-1'} and payload['event'] == 'resource.deleted'


def test_undelivered_events_are_not_offered(app, db_session, test_user):
    import services.api_gateway as gw
    from routes.api_gateway import _WEBHOOK_EVENTS
    assert {e['id'] for e in _WEBHOOK_EVENTS} == set(gw.DELIVERED_EVENTS) == {
        'resource.created', 'resource.deleted', 'cost.threshold'}
    _hook(test_user, ['alert.triggered'])
    with app.app_context():
        assert gw.dispatch_webhook_event(test_user.id, 'alert.triggered', {}) is False


def test_one_blocked_endpoint_does_not_stop_the_rest(app, db_session, test_user, monkeypatch):
    import services.api_gateway as gw
    from models import WebhookDelivery
    posted = []

    class Resp:
        status_code, text = 200, 'ok'
    monkeypatch.setattr(gw, '_is_safe_webhook_url', lambda url: 'internal' not in url)
    monkeypatch.setattr(gw, 'safe_request', lambda m, url, **kw: posted.append(url) or Resp())
    _hook(test_user, ['resource.created'], url='https://internal.example/x')
    _hook(test_user, ['resource.created'], url='https://ok.example/x')
    gw.APIGatewayService().trigger_webhook('resource.created', {'a': 1}, user_id=test_user.id)
    assert posted == ['https://ok.example/x']
    statuses = sorted(d.status for d in WebhookDelivery.query.all())
    assert statuses == ['failed', 'success']


def test_audit_row_dispatches_the_event(app, db_session, test_user, monkeypatch):
    import services.api_gateway as gw
    from src.agent.core import DevOpsAgent
    calls = []
    monkeypatch.setattr(gw, 'dispatch_webhook_event', lambda uid, ev, payload: calls.append((uid, ev, payload)))
    import logging
    import threading
    agent = DevOpsAgent.__new__(DevOpsAgent)
    agent._local = threading.local()
    agent.logger = logging.getLogger('test')
    agent._current_user_id = test_user.id
    agent._current_conversation_id = None
    with app.app_context():
        agent._audit_infrastructure_change('delete_s3_bucket', {'bucket_name': 'logs-1'},
                                           {'success': True, '_verification': {'status': 'confirmed'}})
    assert calls and calls[0][1] == 'resource.deleted'
    assert calls[0][2]['resource']['id'] == 'logs-1'


def test_webhook_form_requires_a_real_event(authenticated_client):
    resp = authenticated_client.post('/api-gateway/webhooks/create', data={
        'name': 'x', 'url': 'https://example.com/h', 'events': ['alert.triggered']})
    assert resp.status_code in (400, 303)


# ── Teams delivery ─────────────────────────────────────────────────────────

def test_teams_channels_get_notifications(app, db_session, test_user, monkeypatch):
    import threading
    import services.notification_service as ns
    from models import UserNotificationChannel, db
    monkeypatch.setattr(threading, 'Thread', _Thread)
    got = []
    monkeypatch.setattr(ns.TeamsClient, 'send', lambda self, n: got.append(('teams', self.webhook_url)))
    monkeypatch.setattr(ns.SlackClient, 'send_webhook', lambda self, n, channel=None: got.append(('slack', self.webhook_url)))
    db.session.add(UserNotificationChannel(user_id=test_user.id, channel_type='teams', name='t',
                                           webhook_url='https://teams.example/w'))
    db.session.add(UserNotificationChannel(user_id=test_user.id, channel_type='slack', name='s',
                                           webhook_url='https://hooks.slack.com/x'))
    db.session.commit()
    with app.app_context():
        ns._send_async(test_user.id, 'cost', ns.Notification(title='t', message='m'))
    assert sorted(got) == [('slack', 'https://hooks.slack.com/x'), ('teams', 'https://teams.example/w')]


# ── budget alerts ──────────────────────────────────────────────────────────

def test_period_windows():
    from services.budget_alerts import period_window
    wed = date(2026, 10, 14)
    assert period_window('monthly', wed)[:2] == (date(2026, 10, 1), date(2026, 10, 15))
    assert period_window('weekly', wed)[:2] == (date(2026, 10, 12), date(2026, 10, 15))
    assert period_window('daily', wed)[:2] == (date(2026, 10, 13), wed)


def _budget(user, threshold=100.0, period='monthly'):
    from models import BudgetAlert, db
    a = BudgetAlert(user_id=user.id, name='AWS', threshold_amount=threshold, period=period)
    db.session.add(a)
    db.session.commit()
    return a


def test_budget_over_threshold_notifies_once_per_period(app, db_session, test_user, monkeypatch):
    import services.budget_alerts as ba
    notes = []
    monkeypatch.setattr(ba, 'period_spend', lambda uid, p, today=None: (150.0, 'this month', today.replace(day=1)))
    monkeypatch.setattr(ba, '_notify', lambda uid, alert, spend, label: notes.append(spend))
    a = _budget(test_user)
    assert ba.check_user_budgets(test_user.id)['triggered'] == 1
    assert a.last_checked_amount == 150.0 and a.last_triggered is not None
    assert ba.check_user_budgets(test_user.id, force=True)['triggered'] == 0
    assert notes == [150.0]
    assert ba.check_user_budgets(test_user.id)['checked'] == 0, 'checked at most once a day'


def test_budget_under_threshold_is_quiet(app, db_session, test_user, monkeypatch):
    import services.budget_alerts as ba
    monkeypatch.setattr(ba, 'period_spend', lambda uid, p, today=None: (40.0, 'this month', today.replace(day=1)))
    monkeypatch.setattr(ba, '_notify', lambda *a: pytest.fail('should not notify'))
    a = _budget(test_user)
    assert ba.check_user_budgets(test_user.id) == {'checked': 1, 'triggered': 0, 'unreadable': 0}
    assert a.last_checked_amount == 40.0


def test_unreadable_billing_is_not_reported_as_under_budget(app, db_session, test_user, monkeypatch):
    import services.budget_alerts as ba

    def boom(uid, p, today=None):
        raise ba.BudgetCheckError('AccessDenied')
    monkeypatch.setattr(ba, 'period_spend', boom)
    a = _budget(test_user)
    assert ba.check_user_budgets(test_user.id)['unreadable'] == 1
    assert a.last_checked_amount is None and a.last_checked_at is None


def test_budget_spend_reads_cost_explorer(app, db_session, test_user, monkeypatch):
    import services.cost_explorer as ce
    from services.budget_alerts import period_spend
    seen = {}

    class FakeCE:
        def get_cost_and_usage(self, **kw):
            seen.update(kw)
            return {'ResultsByTime': [{'Total': {'UnblendedCost': {'Amount': '12.5'}}},
                                      {'Total': {'UnblendedCost': {'Amount': '7.25'}}}]}
    monkeypatch.setattr(ce, '_get_user_boto_client', lambda *a, **k: FakeCE())
    spend, label, start = period_spend(test_user.id, 'monthly', date(2026, 10, 14))
    assert spend == 19.75 and start == date(2026, 10, 1)
    assert seen['TimePeriod'] == {'Start': '2026-10-01', 'End': '2026-10-15'}


def test_budget_api_validates_input(authenticated_client):
    assert authenticated_client.post('/api/budget-alerts', json={'name': 'x', 'threshold_amount': 'abc'}).status_code == 400
    assert authenticated_client.post('/api/budget-alerts', json={'name': 'x', 'threshold_amount': 5, 'period': 'yearly'}).status_code == 400
    assert authenticated_client.post('/api/budget-alerts', json={'name': 'x', 'threshold_amount': 5}).status_code == 201


# ── scheduler ──────────────────────────────────────────────────────────────

def test_log_only_jobs_are_gone_and_budget_check_runs():
    import inspect
    import services.scheduler as sch
    src = inspect.getsource(sch._scheduler_loop) + inspect.getsource(sch._run_task)
    assert 'cost_check' not in src and 'security_scan' not in src
    assert 'budget_check' in src
    assert not hasattr(sch, '_run_cost_anomaly_check') and not hasattr(sch, '_run_security_scan')


def test_weekly_digest_sends_once_per_sunday(app, db_session, test_user, monkeypatch):
    import services.scheduler as sch
    import services.email_service as es
    from datetime import datetime
    from models import UserCloudCredential, db
    db.session.add(UserCloudCredential(user_id=test_user.id, cloud_provider='aws',
                                       credentials_encrypted='x', is_active=True))
    db.session.commit()
    sunday = datetime(2026, 10, 18, 9, 0)
    monkeypatch.setattr(sch, 'utcnow', lambda: sunday)
    sent, bodies = [], []
    monkeypatch.setattr(es.EmailService, 'send_email',
                        lambda self, to, subj, html, text=None: sent.append(to) or bodies.append(html) or True)
    import services.health_score as hs
    monkeypatch.setattr(hs, 'calculate_health_score', lambda uid: {'grade': 'B', 'score': 80})
    sch._run_weekly_digest(db)
    sch._run_weekly_digest(db)
    assert sent == [test_user.email]
    assert f'/email/unsubscribe?user_id={test_user.id}&amp;token=' in bodies[0] or \
        f'/email/unsubscribe?user_id={test_user.id}&token=' in bodies[0]
    monkeypatch.setattr(sch, 'utcnow', lambda: sunday + timedelta(days=7))
    sch._run_weekly_digest(db)
    assert len(sent) == 2

    test_user.email_opt_out = True
    db.session.commit()
    monkeypatch.setattr(sch, 'utcnow', lambda: sunday + timedelta(days=14))
    sch._run_weekly_digest(db)
    assert len(sent) == 2, 'unsubscribed users get no digest'


def test_signature_matches_the_raw_body(app, db_session, test_user, monkeypatch):
    import hashlib
    import hmac
    import services.api_gateway as gw
    got = {}

    class Resp:
        status_code, text = 200, 'ok'

    def fake(method, url, **kw):
        got.update(kw)
        return Resp()
    monkeypatch.setattr(gw, '_is_safe_webhook_url', lambda url: True)
    monkeypatch.setattr(gw, 'safe_request', fake)
    _hook(test_user, ['resource.created'])
    gw.APIGatewayService().trigger_webhook('resource.created', {'b': 2, 'a': 1}, user_id=test_user.id)
    expected = 'sha256=' + hmac.new(b's', got['data'], hashlib.sha256).hexdigest()
    assert got['headers']['X-DevOps-Agent-Signature'] == expected
    assert got['headers']['X-DevOps-Agent-Delivery'] != 'new'
