"""Regression test: ChatOps /oncall and /status showed fabricated
or mismatched data instead of the user's real state.

Found during a scheduled security review (see CLAUDE.md's "Non-negotiable:
every feature runs against a real cloud account" section for the standing
rule this violates, and CLAUDE_RUNBOOK.md for the same class of bug fixed
previously in Drift Detection and Predictive Scaling).

`services/chatops_service.py`'s `_cmd_metrics` and `_cmd_oncall` returned a
fixed block of hardcoded numbers/names ("CPU Utilization: 45% (avg)",
"Primary: @devops-team") to every user regardless of account, with no
`_require_app_user()` call and no real data lookup at all — unlike every
sibling command in the file (`_cmd_status`, `_cmd_incidents`, ...), which all
resolve the calling user and read real per-user state. (`/metrics` and `/alerts`
were removed with the monitoring engine on 2026-10-13.)

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


def test_oncall_no_longer_fabricates_schedule(chatops):
    response = chatops._cmd_oncall([])

    assert '@devops-team' not in response.text
    assert '@sre-team' not in response.text
    assert 'PagerDuty' in response.text or 'OpsGenie' in response.text


def test_status_reports_real_incident_counts_without_monitoring(chatops, monkeypatch):
    """/status reads the caller's incident stats. The monitoring engine was removed
    on 2026-10-13, so the reply must no longer carry a Monitoring section."""
    class _FakeEngine:
        def get_stats(self, user_id):
            assert user_id == 42
            return {'active': 1, 'by_severity': {'critical': 0}, 'resolved_last_24h': 3}

    monkeypatch.setattr(
        'services.incident_response.get_incident_engine',
        lambda: _FakeEngine(),
    )

    response = chatops._cmd_status([], app_user_id=42)

    assert 'Active: 1' in response.text
    assert 'Resolved (24h): 3' in response.text
    assert 'Monitoring' not in response.text
    assert '@devops-team' not in response.text
