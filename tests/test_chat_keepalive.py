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


def test_background_thread_has_app_context_for_db_access(app, chatting_client, test_user):
    """agent.process_message_isolated runs on a background OS thread (see the
    524-fix in CLAUDE_RUNBOOK.md) — but real tool calls do DB work from that
    thread (credential_service.py's UserCloudCredential.query, skills_engine's
    UserSkillActivation query, etc.), which raises "Working outside of
    application context" unless the thread pushes its own app context. The
    other tests in this file fully mock process_message_isolated and never
    exercise that path; this one performs a real ORM query inside the fake
    agent call to prove the background thread can actually reach the DB.
    """
    from models import UsageLog

    def _process_touching_db(**kwargs):
        # Same shape as a real credential lookup / skills-engine query —
        # requires an active Flask app context to not raise.
        count = UsageLog.query.filter_by(user_id=test_user.id).count()
        return f"ok, saw {count} prior usage log(s)"

    agent = _mock_agent(_process_touching_db)

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'list my ec2 instances'})
        assert resp.status_code == 200
        data = resp.get_json()

    assert data['response'].startswith('ok, saw'), (
        f"expected a real DB-backed response, got an error instead: {data['response']!r}"
    )


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


# ---------------------------------------------------------------------------
# Turn-deadline + worker-thread finalization (2026-08-13)
#
# The keep-alive above commits a 200 to the client with its first whitespace
# byte, long before the JSON body exists. So when a turn outlived gunicorn's
# --timeout the arbiter killed the worker and the browser was left with a 200
# whose body was nothing but whitespace — surfacing as a bare
# "Unexpected end of JSON input". Two changes close that:
#   * the view stops waiting at CHAT_MAX_TURN_SECONDS and emits a real JSON
#     body, so the client always gets something parseable; and
#   * the turn is recorded by the worker thread rather than the request
#     generator, so a response cut short never loses work whose tools already
#     changed real cloud infrastructure.
# The second change also fixes tool attribution: last_tools_used /
# pending_download are threading.local()-backed, so the request thread could
# only ever see its own empty defaults.
# ---------------------------------------------------------------------------

def _thread_local_agent(process_message_isolated):
    """A fake agent whose per-request state is genuinely thread-local.

    MagicMock attributes are plain shared values, which cannot reproduce the
    bug these tests cover — src/agent/core.py backs `last_tools_used` and
    `pending_download` with threading.local() (_greenlet_local_property), so
    only the thread that ran the turn can read what the turn set.
    """
    import threading as _threading

    class _FakeAgent:
        def __init__(self):
            self.tool_definitions = []
            self._local = _threading.local()

        @property
        def last_tools_used(self):
            return getattr(self._local, 'tools', [])

        @property
        def pending_download(self):
            return getattr(self._local, 'download', None)

        @pending_download.setter
        def pending_download(self, value):
            self._local.download = value

        def process_message_isolated(self, **kwargs):
            return process_message_isolated(self, **kwargs)

    return _FakeAgent()


def test_turn_exceeding_deadline_returns_parseable_json_not_a_truncated_body(app, chatting_client):
    def _very_slow(**kwargs):
        time.sleep(1.5)
        return "Finished eventually."

    agent = _mock_agent(_very_slow)

    with patch('app.agent', agent), \
         patch('app.CHAT_KEEPALIVE_INTERVAL_SECONDS', 0.05), \
         patch('app.CHAT_MAX_TURN_SECONDS', 0.1), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'run a very long workflow'})
        assert resp.status_code == 200
        raw = resp.get_data(as_text=True)

    # The whole point: whatever happens, the body parses. Before the deadline
    # existed this was whitespace only and json.loads raised.
    data = json.loads(raw)
    assert data['still_running'] is True
    assert data['response'], "the early return must still carry an explanation for the user"


def test_turn_is_still_persisted_when_the_deadline_closes_the_response(app, chatting_client, test_user):
    """The response ending early must not discard the turn — its tools may
    already have created real infrastructure."""
    from models import ChatMessage

    def _very_slow(**kwargs):
        time.sleep(0.8)
        return "Late but real answer."

    agent = _mock_agent(_very_slow)

    with patch('app.agent', agent), \
         patch('app.CHAT_KEEPALIVE_INTERVAL_SECONDS', 0.05), \
         patch('app.CHAT_MAX_TURN_SECONDS', 0.1), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'run a very long workflow'})
        assert json.loads(resp.get_data(as_text=True))['still_running'] is True

        # The worker thread is still running; it persists the turn on its own.
        deadline = time.monotonic() + 10
        saved = None
        while time.monotonic() < deadline:
            saved = ChatMessage.query.filter_by(
                user_id=test_user.id, role='assistant', content='Late but real answer.'
            ).first()
            if saved is not None:
                break
            time.sleep(0.05)

    assert saved is not None, (
        "the agent turn finished after the response closed and was never recorded"
    )


def test_tools_used_are_attributed_to_the_usage_log(app, chatting_client, test_user):
    """last_tools_used is thread-local: read from the request thread it is
    always empty, which silently logged every /api/chat turn as a plain
    agent_message with no tool name."""
    from models import UsageLog

    def _process(self, **kwargs):
        self._local.tools = ['run_instances', 'create_security_group']
        return "Launched an instance."

    agent = _thread_local_agent(_process)

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'launch an ec2 instance'})
        assert resp.status_code == 200
        assert resp.get_json()['response'] == "Launched an instance."

    logs = UsageLog.query.filter_by(user_id=test_user.id).all()
    tool_names = {log.tool_name for log in logs}
    assert 'run_instances' in tool_names, (
        f"tool attribution lost — usage logs recorded {tool_names}"
    )
    assert any(log.action_type == 'tool_use' for log in logs)


def test_pending_download_from_the_worker_thread_reaches_the_client(app, chatting_client):
    """pending_download is thread-local too — a generated keypair set during
    the turn was invisible to the request thread, so the download link was
    silently dropped."""
    def _process(self, **kwargs):
        self.pending_download = {
            'filename': 'my-key.pem',
            'content': 'PRIVATE KEY',
            'content_type': 'application/x-pem-file',
        }
        return "Created a keypair."

    agent = _thread_local_agent(_process)

    with patch('app.agent', agent), \
         patch('src.agent.guardrails.screen_message', return_value=_ok_guardrail_result()):
        resp = chatting_client.post('/api/chat', json={'message': 'create a keypair'})
        assert resp.status_code == 200
        data = resp.get_json()

    assert data.get('download_filename') == 'my-key.pem'
    assert data.get('download_url', '').startswith('/api/download/')
