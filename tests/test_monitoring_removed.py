"""Monitoring was removed (2026-10-13): the /monitoring page and the
services/proactive_monitoring.py engine behind it, including its 60s scheduler
tick, its alert->incident auto-creation, and the ChatOps /alerts and /metrics
commands. The agent's Prometheus/Datadog/Grafana tools are unaffected.

Guards that the route and engine stay gone and that nothing still links or
url_for()s to them — six page templates carried url_for('monitoring.…'), each of
which would 500 its page once the blueprint was unregistered.
"""
import importlib

import pytest


def test_monitoring_route_is_gone(authenticated_client):
    assert authenticated_client.get('/monitoring/').status_code == 404


@pytest.mark.parametrize('path', [
    '/dashboard', '/chat', '/chatops/', '/drift/',
    '/notifications/', '/scaling/', '/webhooks/',
])
def test_pages_render_without_monitoring_link(authenticated_client, path):
    resp = authenticated_client.get(path, follow_redirects=True)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    body = resp.get_data(as_text=True)
    assert 'href="/monitoring' not in body
    assert "href='/monitoring" not in body


def test_engine_and_scheduler_tick_are_gone():
    with pytest.raises(ImportError):
        importlib.import_module('services.proactive_monitoring')

    import inspect
    from services import scheduler
    assert 'monitoring_tick' not in inspect.getsource(scheduler)


def test_chatops_no_longer_offers_monitoring_commands():
    from services.chatops_service import ChatOpsService

    names = set(ChatOpsService().commands)
    assert not names & {'alerts', 'metrics'}
