"""Regression test: ChatOps /oncall (and the since-removed /status) showed fabricated
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
were removed with the monitoring engine on 2026-10-13, and the incident
commands, /status included, with Incidents later that day.)

Separately, `_cmd_status` read `mon_status.get('active_rules', 0)` and
`mon_status.get('alerts_count', 0)`, but `ProactiveMonitoringService.get_status()`
actually returns `rules_enabled` and `alerts_active` — neither key it read
exists in that dict, so "Active Rules" and "Active Alerts" silently always
displayed 0 no matter how many rules/alerts a user actually had.
"""
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from services.chatops_service import ChatOpsService
import pytest


@pytest.fixture
def chatops():
    return ChatOpsService()


def test_oncall_no_longer_fabricates_schedule(chatops):
    response = chatops._cmd_oncall([])

    assert '@devops-team' not in response.text
    assert '@sre-team' not in response.text
    assert 'PagerDuty' in response.text or 'OpsGenie' in response.text
