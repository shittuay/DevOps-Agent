"""Tests for the /metrics Prometheus scrape endpoint (routes/metrics.py)."""


def test_metrics_disabled_without_token(client, monkeypatch):
    monkeypatch.delenv('METRICS_TOKEN', raising=False)
    resp = client.get('/metrics')
    assert resp.status_code == 403


def test_metrics_requires_auth_header(client, monkeypatch):
    monkeypatch.setenv('METRICS_TOKEN', 'test-metrics-token')
    resp = client.get('/metrics')
    assert resp.status_code == 403


def test_metrics_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv('METRICS_TOKEN', 'test-metrics-token')
    resp = client.get('/metrics', headers={'Authorization': 'Bearer wrong-token'})
    assert resp.status_code == 403


def test_metrics_returns_prometheus_text_with_correct_token(client, monkeypatch):
    monkeypatch.setenv('METRICS_TOKEN', 'test-metrics-token')

    # Generate at least one recorded request before scraping.
    client.get('/health')

    resp = client.get('/metrics', headers={'Authorization': 'Bearer test-metrics-token'})
    assert resp.status_code == 200
    assert resp.mimetype == 'text/plain'
    body = resp.get_data(as_text=True)
    assert 'http_requests_total' in body
    assert 'http_request_duration_seconds' in body
