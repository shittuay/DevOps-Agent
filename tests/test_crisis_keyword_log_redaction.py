"""
Regression test for the 2026-09-11 scheduled-audit finding: screen_message()
logged the verbatim matched self-harm keyword text (e.g. "kill myself",
"suicide") via logger.warning() on every crisis detection. That logger
writes to general application logs (journalctl / logs/agent.log / whatever
aggregator ingests them) — a much broader-access, longer/less-controlled
channel than the purpose-built, admin-role-gated CrisisIncident audit trail
(models.py, /api/admin/crisis-incidents) that already stores the same
keywords for the support team. Fixed by logging severity + a match count
only; the raw keywords still flow to GuardrailResult.crisis_keywords and
from there into CrisisIncident, unchanged. See CLAUDE_RUNBOOK.md.
"""

import logging

from src.agent.guardrails import screen_message


class TestCrisisKeywordLogRedaction:
    def test_raw_crisis_keyword_text_not_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger='src.agent.guardrails'):
            result = screen_message("I want to kill myself")

        assert result.blocked is True
        assert result.is_crisis is True
        # The matched phrase must never appear in the log output verbatim.
        assert 'kill myself' not in caplog.text.lower()

    def test_crisis_result_still_carries_keywords_for_the_audit_trail(self):
        """GuardrailResult.crisis_keywords must still be populated — that's
        what CrisisIncident.crisis_keywords (access-controlled) is built
        from in app.py / routes/curriculum.py. Only the general-log line
        should stop carrying the raw text."""
        result = screen_message("I want to kill myself")
        assert 'kill myself' in result.crisis_keywords

    def test_severity_still_logged_for_ops_visibility(self, caplog):
        with caplog.at_level(logging.WARNING, logger='src.agent.guardrails'):
            screen_message("I want to kill myself")

        assert 'severity=high' in caplog.text
