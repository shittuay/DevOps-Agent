"""Regression tests for the 2026-09-12 scheduled audit's ChatOps findings.

Three issues were found in services/chatops_service.py / routes/chatops.py,
none previously covered by any test:

1. `_cmd_metrics`/`_cmd_oncall` returned hardcoded fake numbers/roster as if
   real, with no `[Sandbox]` label — the fabricated-data pattern CLAUDE.md's
   "every feature runs against a real cloud account" rule exists to prevent.
2. Every incident/monitoring command called IncidentResponseEngine /
   ProactiveMonitoringService methods without the `user_id` those methods
   require, so they either raised TypeError or silently mis-bound a Slack
   string into the user_id slot. There was also no way to map a Slack/Teams
   identity to an app user at all.
3. The Slack webhook signature check had no replay-window, so a captured
   valid signature+body pair was replayable indefinitely.

Fixed by: routing every command through a per-request app_user_id resolved
from a new ChatOpsIdentity mapping (created via a `/link <code>` command that
redeems a ChatOpsLinkCode generated on the logged-in ChatOps page), pulling
real data for /metrics (from the user's monitoring rules) and /oncall (from
PagerDuty/OpsGenie, failing closed when neither is configured), and adding a
timestamp freshness check to the Slack signature verification.
"""
import hashlib
import hmac
import time
from datetime import datetime, timedelta

import pytest

from routes import chatops as chatops_routes
from services.chatops_service import get_chatops_service, ChatPlatform
from src.utils.timeutils import utcnow


# ==================== Slack signature replay window ====================

def _sign(secret: str, timestamp: str, body: bytes) -> str:
    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    return 'v0=' + hmac.new(secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()


def test_slack_signature_rejects_stale_timestamp():
    secret = 'test-signing-secret'
    body = b'command=/devops&text=status'
    stale_timestamp = str(int(time.time()) - 600)  # 10 minutes old
    signature = _sign(secret, stale_timestamp, body)

    assert chatops_routes._verify_slack_signature(secret, stale_timestamp, signature, body) is False


def test_slack_signature_accepts_fresh_valid_signature():
    secret = 'test-signing-secret'
    body = b'command=/devops&text=status'
    fresh_timestamp = str(int(time.time()))
    signature = _sign(secret, fresh_timestamp, body)

    assert chatops_routes._verify_slack_signature(secret, fresh_timestamp, signature, body) is True


def test_slack_signature_rejects_valid_hmac_replayed_later():
    """A signature that was valid when issued must not verify once stale,
    even though the HMAC itself is untouched — this is the replay case."""
    secret = 'test-signing-secret'
    body = b'command=/devops&text=resolve INC-1'
    original_timestamp = str(int(time.time()))
    signature = _sign(secret, original_timestamp, body)

    # Simulate the same request replayed long after the signing window.
    with_stale_clock = str(int(time.time()) - 3600)
    assert chatops_routes._verify_slack_signature(secret, with_stale_clock, signature, body) is False


# ==================== Fabricated-data regressions ====================

def test_oncall_fails_closed_without_any_integration_configured(monkeypatch):
    monkeypatch.delenv('PAGERDUTY_API_KEY', raising=False)
    monkeypatch.delenv('OPSGENIE_API_KEY', raising=False)

    service = get_chatops_service()
    response = service._cmd_oncall([])

    # The invariant is "says it has nothing real, names no one", not any exact
    # wording — #197 reworded this message after this test was written, and an
    # exact-prose assertion would fail on a correct implementation.
    text = response.text.lower()
    assert any(p in text for p in ('not configured', 'no on-call integration',
                                   "isn't connected", 'not connected')), response.text
    # Must never fall back to the old hardcoded roster, under any wording.
    assert '@devops-team' not in response.text
    assert '@sre-team' not in response.text
    assert 'primary:' not in text


def test_metrics_command_never_returns_hardcoded_placeholder_numbers(app, test_user):
    service = get_chatops_service()
    response = service._cmd_metrics([], app_user_id=test_user.id)

    for fabricated in ('45% (avg)', '62% (avg)', '0.05%', '120ms', 'Replication Lag: 0ms'):
        assert fabricated not in response.text


# ==================== Identity linking + per-user wiring ====================

def test_status_command_without_linked_identity_asks_to_link():
    service = get_chatops_service()
    response = service.process_message('status', user_id='slack-U-unlinked', platform=ChatPlatform.SLACK)

    assert 'link' in response.text.lower()
    assert 'system status' not in response.text.lower()


def test_help_command_does_not_require_linking():
    """requires_auth=False commands must dispatch even with no linked identity."""
    service = get_chatops_service()
    response = service.process_message('help', user_id='slack-U-unlinked', platform=ChatPlatform.SLACK)

    assert 'available commands' in response.text.lower()


def test_link_code_flow_unlocks_user_scoped_commands(app, test_user, db_session):
    from models import ChatOpsIdentity, ChatOpsLinkCode, db

    service = get_chatops_service()
    platform_user_id = 'slack-U-link-test'

    code = 'TESTLNK1'
    link_code = ChatOpsLinkCode(
        user_id=test_user.id, code=code,
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.session.add(link_code)
    db.session.commit()

    link_response = service.process_message(
        f'link {code}', user_id=platform_user_id, platform=ChatPlatform.SLACK
    )
    assert 'linked' in link_response.text.lower()

    identity = ChatOpsIdentity.query.filter_by(
        platform='slack', platform_user_id=platform_user_id
    ).first()
    assert identity is not None
    assert identity.user_id == test_user.id

    # The code must be single-use.
    db.session.refresh(link_code)
    assert link_code.used_at is not None

    # Now a requires_auth command should resolve the identity and actually run.
    status_response = service.process_message(
        'status', user_id=platform_user_id, platform=ChatPlatform.SLACK
    )
    assert 'system status' in status_response.text.lower()

    db.session.delete(identity)
    db.session.delete(link_code)
    db.session.commit()


def test_link_code_cannot_be_reused(app, test_user, db_session):
    from models import ChatOpsIdentity, ChatOpsLinkCode, db

    service = get_chatops_service()
    code = 'ONETIME1'
    link_code = ChatOpsLinkCode(
        user_id=test_user.id, code=code,
        expires_at=utcnow() + timedelta(minutes=10),
    )
    db.session.add(link_code)
    db.session.commit()

    first = service.process_message(f'link {code}', user_id='slack-U-a', platform=ChatPlatform.SLACK)
    assert 'linked' in first.text.lower()

    second = service.process_message(f'link {code}', user_id='slack-U-b', platform=ChatPlatform.SLACK)
    assert 'invalid' in second.text.lower() or 'expired' in second.text.lower()

    identity_b = ChatOpsIdentity.query.filter_by(platform='slack', platform_user_id='slack-U-b').first()
    assert identity_b is None

    identity_a = ChatOpsIdentity.query.filter_by(platform='slack', platform_user_id='slack-U-a').first()
    db.session.delete(identity_a)
    db.session.delete(link_code)
    db.session.commit()


def test_link_code_rejects_expired_code(app, test_user, db_session):
    from models import ChatOpsIdentity, ChatOpsLinkCode, db

    service = get_chatops_service()
    code = 'EXPIRED1'
    link_code = ChatOpsLinkCode(
        user_id=test_user.id, code=code,
        expires_at=utcnow() - timedelta(minutes=1),
    )
    db.session.add(link_code)
    db.session.commit()

    response = service.process_message(f'link {code}', user_id='slack-U-c', platform=ChatPlatform.SLACK)
    assert 'invalid' in response.text.lower() or 'expired' in response.text.lower()

    assert ChatOpsIdentity.query.filter_by(platform='slack', platform_user_id='slack-U-c').first() is None

    db.session.delete(link_code)
    db.session.commit()


# ==================== Direct handler regressions (no more TypeError/AttributeError) ====================

def test_playbooks_command_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_playbooks([], app_user_id=test_user.id)
    assert response.text


def test_alerts_command_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_alerts([], app_user_id=test_user.id)
    assert 'no active alerts' in response.text.lower()


def test_incident_detail_not_found_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_incident_detail(['does-not-exist'], app_user_id=test_user.id)
    assert 'not found' in response.text.lower()


def test_execute_incident_not_found_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_execute(['does-not-exist'], app_user_id=test_user.id)
    assert 'not found' in response.text.lower()


def test_analyze_incident_not_found_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_analyze(['does-not-exist'], app_user_id=test_user.id)
    assert 'not found' in response.text.lower()


def test_acknowledge_incident_not_found_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_acknowledge(['does-not-exist'], app_user_id=test_user.id)
    assert 'failed to acknowledge' in response.text.lower()


def test_resolve_incident_not_found_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_resolve(['does-not-exist'], app_user_id=test_user.id)
    assert 'failed to resolve' in response.text.lower()


def test_status_command_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_status([], app_user_id=test_user.id)
    assert 'system status' in response.text.lower()


def test_incidents_list_command_runs_without_error(app, test_user):
    service = get_chatops_service()
    response = service._cmd_incidents([], app_user_id=test_user.id)
    assert response.text


# ==================== Scheduled audit (2026-09-26): /deployments bypassed
# both identity linking and the admin boundary the web UI enforces ====================

def test_deployments_command_refuses_unlinked_identity():
    """Unlike every other per-user command, `_cmd_deployments` never called
    `_require_app_user()` — it ran for a completely unlinked chat identity."""
    service = get_chatops_service()
    response = service.process_message(
        'deployments', user_id='slack-U-unlinked-deploy', platform=ChatPlatform.SLACK
    )
    assert 'link' in response.text.lower()


def test_deployments_command_refuses_non_admin_user(app, test_user):
    """WebhookEventRecord has no per-user column at all — it's the same
    platform-wide CI/CD stream /webhooks/api/events gates behind
    @admin_required. A regular linked user must still be refused."""
    service = get_chatops_service()
    assert test_user.role != 'admin'

    response = service._cmd_deployments([], app_user_id=test_user.id)
    assert 'admin' in response.text.lower()


def test_deployments_command_allows_admin_user(app, test_user, db_session):
    from models import db

    test_user.role = 'admin'
    db.session.commit()
    try:
        service = get_chatops_service()
        response = service._cmd_deployments([], app_user_id=test_user.id)
        assert 'admin-only' not in response.text.lower()
    finally:
        test_user.role = 'user'
        db.session.commit()
