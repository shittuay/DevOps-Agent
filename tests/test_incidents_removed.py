"""Incidents and Analysis were removed (2026-10-13): the /incidents pages and
playbooks, services/incident_response.py, the /analysis root-cause pages and
services/root_cause_analyzer.py, plus everything that only fed or read them:
ChatOps incident commands, the developer API's /v1/incidents endpoints, the
public /status page's incident list, CI/CD webhook failure -> incident creation,
incident Slack notifications, and the incident counts in the health score,
analytics and weekly digest.

Kept on purpose: the agent's PagerDuty/OpsGenie tools, the "Incident Response"
workflows (chat diagnostics), the incident_runbooks skill, and CrisisIncident
(guardrail crisis logging, unrelated). The incident tables stay in the database,
unused, as Monitoring's did.
"""
import importlib

import pytest


@pytest.mark.parametrize('path', ['/incidents/', '/analysis/', '/api/incidents',
                                  '/analytics/api/incidents/stats', '/analytics/api/alerts/summary'])
def test_removed_routes_are_gone(authenticated_client, path):
    assert authenticated_client.get(path).status_code == 404


@pytest.mark.parametrize('module', ['services.incident_response', 'services.root_cause_analyzer',
                                    'routes.incidents', 'routes.analysis'])
def test_removed_modules_are_gone(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize('path', [
    '/dashboard', '/chat', '/chatops/', '/drift/', '/notifications/',
    '/webhooks/', '/settings', '/analytics/', '/status', '/docs', '/developers',
    '/api-gateway/docs',
])
def test_pages_render_without_incident_or_analysis_links(authenticated_client, path):
    resp = authenticated_client.get(path, follow_redirects=True)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    body = resp.get_data(as_text=True)
    for target in ('/incidents', '/analysis'):
        assert f'href="{target}' not in body
        assert f"href='{target}" not in body
    assert '/api-gateway/v1/incidents' not in body


def test_status_page_no_longer_lists_incidents(client):
    body = client.get('/status').get_data(as_text=True)
    assert 'Recent Incidents' not in body


def test_chatops_offers_no_incident_commands():
    from services.chatops_service import ChatOpsService

    names = set(ChatOpsService().commands)
    assert not names & {'status', 'incidents', 'incident', 'ack', 'resolve',
                        'playbooks', 'execute', 'analyze', 'rca'}
    assert {'help', 'deployments', 'oncall', 'link'} <= names


def test_developer_api_has_no_incident_endpoints(app):
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert not any('/v1/incidents' in r for r in rules)


def test_webhook_failures_no_longer_create_incidents():
    import inspect
    from services import webhook_integrations

    assert '_handle_failure_event' not in inspect.getsource(webhook_integrations)


def test_health_score_ignores_incidents():
    import inspect
    from services import health_score

    assert 'IncidentModel' not in inspect.getsource(health_score)


def test_pagerduty_and_opsgenie_tools_are_kept():
    from src.tools.alerting_tools import get_tools

    names = {t['name'] for t in get_tools()}
    assert {'pagerduty_list_incidents', 'opsgenie_list_alerts'} <= names
