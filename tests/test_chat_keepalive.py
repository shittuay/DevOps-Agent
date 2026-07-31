"""Regression tests for the /api/chat 524 fix.

Cloudflare's edge proxy has a ~100s idle-connection timeout that can't be
raised below Enterprise tier. /api/chat previously sent zero bytes back to
the client until the entire (potentially 290s-long, for Kimi swarm tasks)
agent turn finished, so Cloudflare would kill the connection and return 524
while gunicorn kept working — confirmed live via a 499 in nginx's access log
followed by a successful completion in gunicorn's own log ~25s later.

The fix: the actual agent call now runs in a background thread while the
view streams a whitespace keep-alive byte every CHAT_KEEPALIVE_INTERVAL_SECONDS.
response.json() (browser) and json.loads() (Python) both ignore insignificant
leading whitespace around a JSON value per spec, so the frontend's existing
`const data = await kimiResp.json()` needs no changes.

These tests patch app.CHAT_KEEPALIVE_INTERVAL_SECONDS to a tiny value so they
don't have to wait out a real 15s interval.

Response bodies are read (get_data()/get_json()) *inside* the patch context,
not after — /api/chat's Response is a lazy generator (Flask/Werkzeug only
drives it when something actually consumes the body), so for a slow enough
generator that consumption can happen after a `with patch(...)` block has
already exited and reverted app.agent, causing spurious failures unrelated
to the code under test.
"""
import json
import time
from unittest.mock import MagicMock, patch

import pytest


def _mock_agent(process_message_isolated):
    agent = MagicMock()
    agent.tool_definitions = []
    agent.last_tools_used = []
    agent.pending_download = None
    agent.process_message_isolated = process_message_isolated
    return agent


def _ok_guardrail_result():
    from src.agent.guardrails import GuardrailResult
    return GuardrailResult(blocked=False, reason='', category='')


@pytest.fixture
def chatting_client(client, test_user, test_subscription):
    """An authenticated client with credits, ready to POST /api/chat."""
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPassword123!'
    })
    assert response.status_code == 302
    return client


def test_fast_agent_call_returns_valid_json_no_keepalive_needed(app, chatting_client):
    agent = _mock_agent(lambda **kwargs: "Here are your EC2 instances.")

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'list my ec2 instances'})
        assert resp.status_code == 200
        data = resp.get_json()

    assert data['response'] == "Here are your EC2 instances."
    assert 'credits_remaining' in data


def test_slow_agent_call_streams_keepalive_and_still_returns_valid_json(app, chatting_client):
    def _slow_process(**kwargs):
        time.sleep(0.3)
        return "Done after a while."

    agent = _mock_agent(_slow_process)

    with patch('app.agent', agent), \
         patch('app.CHAT_KEEPALIVE_INTERVAL_SECONDS', 0.05), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'run a long scan'})
        assert resp.status_code == 200
        raw = resp.get_data(as_text=True)

    # Proves the keep-alive mechanism actually engaged: real leading
    # whitespace bytes were sent before the JSON payload.
    assert raw != raw.lstrip(), "expected leading keep-alive whitespace before the JSON body"
    data = json.loads(raw)
    assert data['response'] == "Done after a while."


def test_background_agent_call_has_app_context_for_db_access(app, chatting_client, test_user):
    """Regression test: the background thread that runs the actual agent call
    (see _run_agent_call in app.py) must have a Flask app context pushed.

    Without it, any real (non-sandbox) tool call that resolves per-user cloud
    credentials via UserCloudCredential.query (services/credential_service.py),
    or logs a destructive-action audit trail via db.session
    (core.py's _audit_chat_deletion), raises "RuntimeError: Working outside
    of application context" — silently breaking every AWS/Azure/GCP tool call
    made through /api/chat. Simulate that by having the mocked
    process_message_isolated actually touch the DB from inside the thread.
    """
    from models import User

    def _process_touching_db(**kwargs):
        # Raises RuntimeError("Working outside of application context") if
        # this thread has no app context — exactly the bug being guarded against.
        User.query.filter_by(id=test_user.id).first()
        return "Queried the DB from the background thread just fine."

    agent = _mock_agent(_process_touching_db)

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'terminate my ec2 instance'})
        assert resp.status_code == 200
        data = resp.get_json()

    assert data['response'] == "Queried the DB from the background thread just fine."


def test_agent_exception_is_reported_not_dropped(app, chatting_client):
    def _raise(**kwargs):
        raise RuntimeError("boom")

    agent = _mock_agent(_raise)

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'trigger an error'})
        assert resp.status_code == 200  # streaming already committed to 200
        data = resp.get_json()

    assert 'boom' in data['response']


def test_successful_chat_still_deducts_credit_and_saves_message(app, chatting_client, test_user, test_subscription):
    from models import ChatMessage

    agent = _mock_agent(lambda **kwargs: "A response to save.")
    balance_before = test_subscription.credits_remaining

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'do something'})
        assert resp.status_code == 200
        data = resp.get_json()

    assert data['credits_remaining'] == balance_before - 1

    saved = ChatMessage.query.filter_by(
        user_id=test_user.id, role='assistant', content='A response to save.'
    ).first()
    assert saved is not None
