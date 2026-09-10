"""ChatOps must never return fabricated infrastructure data.

`_cmd_metrics` and `_cmd_oncall` used to return fully hardcoded numbers/rosters
(e.g. "CPU Utilization: 45% (avg)", a static "@devops-team"/"@sre-team"
schedule) with no monitoring or alerting backend behind them at all — a Slack
user typing `/metrics` or `/oncall` got canned output indistinguishable from a
real query. Found by the 2026-09-10 scheduled audit; same fabrication-bug
shape as CLAUDE.md's "every feature runs against a real cloud account" rule
documents for Drift/Predictive-Scaling/Analytics/performance_optimizer.
"""
from services.chatops_service import ChatOpsService


def test_metrics_command_does_not_fabricate_data():
    service = ChatOpsService()
    response = service.process_message("/metrics")

    assert "45%" not in response.text
    assert "1.2k/min" not in response.text
    assert "0.05%" not in response.text
    assert "not" in response.text.lower() or "isn't" in response.text.lower()


def test_oncall_command_does_not_fabricate_data():
    service = ChatOpsService()
    response = service.process_message("/oncall")

    assert "@devops-team" not in response.text
    assert "@sre-team" not in response.text
    assert "not" in response.text.lower() or "isn't" in response.text.lower()
