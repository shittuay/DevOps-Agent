"""The public status page checks real things (2026-10-14 audit).

AI, billing and email used to show "Operational" whenever an environment variable was
set, the "Last checked" time was the browser's clock at page load, and "Get notified"
took sign-ups that nothing ever emailed.
"""
import pytest


@pytest.fixture
def svc(app):
    from services.status_service import StatusService
    s = StatusService()
    s.set_app(app)
    return s


def _codes(monkeypatch, mapping):
    import services.status_service as ss
    calls = []

    def fake(url, headers=None, auth=None):
        calls.append(url)
        for prefix, code in mapping.items():
            if url.startswith(prefix):
                return code
        return 200
    monkeypatch.setattr(ss, '_http_status', fake)
    return calls


def test_key_alone_is_not_operational(svc, monkeypatch):
    monkeypatch.setenv('MOONSHOT_API_KEY', 'k')
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    _codes(monkeypatch, {'https://api.moonshot.ai': 401})
    assert svc._check_ai() == ('outage', 'Kimi rejected our credentials')


def test_one_provider_down_is_degraded(svc, monkeypatch):
    monkeypatch.setenv('MOONSHOT_API_KEY', 'k')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'a')
    _codes(monkeypatch, {'https://api.anthropic.com': None})
    status, detail = svc._check_ai()
    assert status == 'degraded' and 'Claude unreachable' in detail


def test_billing_and_email_are_probed(svc, monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk')
    monkeypatch.setenv('BREVO_API_KEY', 'b')
    monkeypatch.delenv('EMAIL_PROVIDER', raising=False)
    calls = _codes(monkeypatch, {'https://api.stripe.com': 503})
    assert svc._check_billing()[0] == 'degraded'
    assert svc._check_email()[0] == 'operational'
    assert any(c.startswith('https://api.brevo.com') for c in calls)


def test_results_are_cached(svc, monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk')
    calls = _codes(monkeypatch, {})
    svc.check_health()
    n = len(calls)
    svc.check_health()
    assert len(calls) == n, 'second call within CACHE_SECONDS must not probe again'
    assert svc.checked_at() is not None
    svc.check_health(force=True)
    assert len(calls) > n


def test_details_never_leak_exception_text(svc, monkeypatch):
    def boom(self):
        raise RuntimeError('postgresql://user:secret@db/x')
    monkeypatch.setattr(type(svc), '_check_billing', boom)
    _codes(monkeypatch, {})
    billing = next(s for s in svc.check_health(force=True) if s['key'] == 'billing')
    assert billing['status'] == 'unknown' and 'secret' not in billing['detail']


def test_page_has_no_signup_and_shows_check_time(client, monkeypatch):
    import services.status_service as ss
    _codes(monkeypatch, {})
    ss.status_service.check_health(force=True)
    body = client.get('/status').get_data(as_text=True)
    assert 'Get Notified' not in body and '/api/status/subscribe' not in body
    assert 'last check' in body
    assert client.post('/api/status/subscribe', json={'email': 'a@b.co'}).status_code in (404, 405)
    assert client.get('/status/confirm/abc').status_code == 404


def test_health_endpoint_reports_check_time(client, monkeypatch):
    _codes(monkeypatch, {})
    body = client.get('/api/status/health').get_json()
    assert body['checked_at'] and {s['key'] for s in body['services']} == {'api', 'db', 'ai', 'billing', 'email'}


def test_old_unsubscribe_links_still_work(client, app):
    from models import StatusSubscriber, db
    db.session.add(StatusSubscriber(email='old@example.com', token='tok123', confirmed=True))
    db.session.commit()
    assert 'unsubscribed' in client.get('/status/unsubscribe/tok123').get_data(as_text=True)
    assert StatusSubscriber.query.filter_by(email='old@example.com').first() is None
