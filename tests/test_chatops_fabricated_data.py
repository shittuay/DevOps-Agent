"""Regression test: ChatOps /metrics, /oncall, and /status showed fabricated
or mismatched data instead of the user's real state.

Found during a scheduled security review (see CLAUDE.md's "Non-negotiable:
every feature runs against a real cloud account" section for the standing
rule this violates, and CLAUDE_RUNBOOK.md for the same class of bug fixed
previously in Drift Detection and Predictive Scaling).

`services/chatops_service.py`'s `_cmd_metrics` and `_cmd_oncall` returned a
fixed block of hardcoded numbers/names ("CPU Utilization: 45% (avg)",
"Primary: @devops-team") to every user regardless of account, with no
`_require_app_user()` call and no real data lookup at all — unlike every
sibling command in the file (`_cmd_status`, `_cmd_incidents`, `_cmd_alerts`,
...), which all resolve the calling user and read real per-user state.

Separately, `_cmd_status` read `mon_status.get('active_rules', 0)` and
`mon_status.get('alerts_count', 0)`, but `ProactiveMonitoringService.get_status()`
actually returns `rules_enabled` and `alerts_active` — neither key it read
exists in that dict, so "Active Rules" and "Active Alerts" silently always
displayed 0 no matter how many rules/alerts a user actually had.
"""
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from services.chatops_service import ChatOpsService, _UnresolvedAppUser
import pytest


@pytest.fixture
def chatops():
    return ChatOpsService()


def test_metrics_with_no_rules_reports_honestly(chatops, monkeypatch):
    class _FakeMonitoring:
        def get_rules(self, user_id):
            assert user_id == 42
            return []

    monkeypatch.setattr(
        'services.proactive_monitoring.get_monitoring_service',
        lambda: _FakeMonitoring(),
    )

    response = chatops._cmd_metrics([], app_user_id=42)

    assert 'No monitoring rules are configured' in response.text
    # None of the old fabricated numbers should ever appear again.
    assert '45%' not in response.text
    assert 'Replication Lag' not in response.text


def test_metrics_with_rules_shows_real_values(chatops, monkeypatch):
    class _FakeMonitoring:
        def get_rules(self, user_id):
            return [{
                'name': 'cpu-high',
                'source': 'prometheus',
                'state': 'firing',
                'last_value': 72.5,
                'last_check': '2026-09-13T00:00:00',
                'condition': 'gt',
                'threshold': 80,
                'labels': {'service': 'web'},
            }]

    monkeypatch.setattr(
        'services.proactive_monitoring.get_monitoring_service',
        lambda: _FakeMonitoring(),
    )

    response = chatops._cmd_metrics([], app_user_id=42)

    assert 'cpu-high' in response.text
    assert '72.5' in response.text
    assert 'prometheus' in response.text
    # The old static demo values must be gone.
    assert '45%' not in response.text
    assert '1.2k/min' not in response.text


def test_metrics_requires_app_user(chatops):
    with pytest.raises(_UnresolvedAppUser):
        chatops._cmd_metrics([])


def test_oncall_no_longer_fabricates_schedule(chatops):
    response = chatops._cmd_oncall([])

    assert '@devops-team' not in response.text
    assert '@sre-team' not in response.text
    assert 'PagerDuty' in response.text or 'OpsGenie' in response.text


def test_status_reports_real_alert_and_rule_counts(chatops, monkeypatch):
    class _FakeEngine:
        def get_stats(self, user_id):
            return {'active': 1, 'by_severity': {'critical': 0}, 'resolved_last_24h': 3}

    class _FakeMonitoring:
        def get_status(self, user_id):
            return {
                'running': True,
                'rules_total': 5,
                'rules_enabled': 4,
                'alerts_active': 7,
                'alerts_firing': 2,
                'alerts_pending': 1,
            }

    monkeypatch.setattr(
        'services.incident_response.get_incident_engine',
        lambda: _FakeEngine(),
    )
    monkeypatch.setattr(
        'services.proactive_monitoring.get_monitoring_service',
        lambda: _FakeMonitoring(),
    )

    response = chatops._cmd_status([], app_user_id=42)

    assert 'Active Rules: 4' in response.text
    assert 'Active Alerts: 7' in response.text
