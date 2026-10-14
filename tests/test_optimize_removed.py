"""The Optimize area was removed (2026-10-13): it served the same hardcoded sample
recommendations (i-0abc123def456, "$150 savings") to every user from
services/performance_optimizer.py, violating the real-cloud-account rule.

Guards that the route stays gone and that nothing still links or url_for()s to it —
scaling/dashboard.html's url_for('optimization.…') would otherwise 500 /scaling.
"""
import pytest


def test_optimization_route_is_gone(authenticated_client):
    assert authenticated_client.get('/optimization/').status_code == 404


@pytest.mark.parametrize('path', ['/dashboard', '/chat', '/workflows'])
def test_pages_render_without_optimize_link(authenticated_client, path):
    resp = authenticated_client.get(path, follow_redirects=True)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    assert 'href="/optimization' not in resp.get_data(as_text=True)
