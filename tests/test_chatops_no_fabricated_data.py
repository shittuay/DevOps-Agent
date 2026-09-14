"""Regression: ChatOps `/metrics` and `/oncall` must never return fabricated
infrastructure numbers -- the same "hardcoded data presented as real" class
CLAUDE.md's non-negotiable rule is written around, and the same class
already fixed once in this file (2026-09-12, dead command handlers) and
independently in services/predictive_scaling.py and
services/analytics_service.py. `_cmd_metrics`/`_cmd_oncall` previously
returned a byte-identical, hardcoded "*Metrics Summary*"/"*On-Call
Schedule*" block on every call regardless of the account, with no
`[Sandbox]`/`[Sample]` marker. Found by a 2026-09-14 scheduled audit.
"""
import pytest

from services.chatops_service import ChatOpsService


@pytest.fixture
def service():
    return ChatOpsService()


def test_metrics_fails_closed_with_no_monitoring_integration(service, monkeypatch):
    monkeypatch.delenv('DATADOG_API_KEY', raising=False)
    monkeypatch.delenv('DATADOG_APP_KEY', raising=False)

    response = service._cmd_metrics([], app_user_id=1)

    assert 'No monitoring integration is configured' in response.text
    # None of the old hardcoded numbers should ever appear again.
    assert '45% (avg)' not in response.text
    assert '1.2k/min' not in response.text


def test_metrics_reports_real_datadog_monitor_state(service, monkeypatch):
    monkeypatch.setenv('DATADOG_API_KEY', 'x')
    monkeypatch.setenv('DATADOG_APP_KEY', 'y')

    def fake_get_datadog_monitors(**kwargs):
        return {
            'success': True,
            'count': 2,
            'monitors': [
                {'name': 'high-cpu-web-01', 'overall_state': 'Alert', 'tags': ['team:web']},
                {'name': 'disk-space-db-01', 'overall_state': 'OK', 'tags': ['team:db']},
            ],
        }

    monkeypatch.setattr(
        'src.tools.monitoring_tools.get_datadog_monitors', fake_get_datadog_monitors
    )

    response = service._cmd_metrics([], app_user_id=1)

    assert 'Alert: 1' in response.text
    assert 'high-cpu-web-01' in response.text
    assert '45% (avg)' not in response.text  # old fabricated line never reappears


def test_metrics_surfaces_a_real_datadog_error_instead_of_guessing(service, monkeypatch):
    monkeypatch.setenv('DATADOG_API_KEY', 'x')
    monkeypatch.setenv('DATADOG_APP_KEY', 'y')
    monkeypatch.setattr(
        'src.tools.monitoring_tools.get_datadog_monitors',
        lambda **kwargs: {'success': False, 'error': 'timeout'},
    )

    response = service._cmd_metrics([], app_user_id=1)
    assert 'Could not reach Datadog' in response.text


def test_oncall_fails_closed_with_no_alerting_integration(service, monkeypatch):
    monkeypatch.delenv('PAGERDUTY_API_KEY', raising=False)
    monkeypatch.delenv('OPSGENIE_API_KEY', raising=False)

    response = service._cmd_oncall([], app_user_id=1)

    assert 'No on-call integration is configured' in response.text
    assert '@devops-team' not in response.text
    assert '@sre-team' not in response.text


def test_oncall_reports_real_pagerduty_schedule(service, monkeypatch):
    monkeypatch.setenv('PAGERDUTY_API_KEY', 'x')

    def fake_list_oncalls(**kwargs):
        return {
            'success': True,
            'count': 1,
            'oncalls': [{
                'user': 'Priya N.',
                'user_email': 'priya@example.com',
                'schedule': 'Primary On-Call',
                'escalation_policy': 'Prod Escalation',
                'escalation_level': 1,
            }],
        }

    monkeypatch.setattr(
        'src.tools.alerting_tools.pagerduty_list_oncalls', fake_list_oncalls
    )

    response = service._cmd_oncall([], app_user_id=1)

    assert 'Priya N.' in response.text
    assert 'Primary On-Call' in response.text
    assert '@devops-team' not in response.text  # old fabricated line never reappears


def test_oncall_surfaces_a_real_pagerduty_error_instead_of_guessing(service, monkeypatch):
    monkeypatch.setenv('PAGERDUTY_API_KEY', 'x')
    monkeypatch.setattr(
        'src.tools.alerting_tools.pagerduty_list_oncalls',
        lambda **kwargs: {'success': False, 'error': 'unauthorized'},
    )

    response = service._cmd_oncall([], app_user_id=1)
    assert 'Could not reach PagerDuty' in response.text
