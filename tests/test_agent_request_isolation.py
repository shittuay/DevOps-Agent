"""A shared DevOpsAgent must not leak per-request state across concurrent requests.

Production runs one gunicorn gevent worker for the whole process
(``--workers 1 --worker-connections 1000``), so a single DevOpsAgent instance is
shared by every concurrent request; gevent monkey-patches threading.local() to be
greenlet-local. Before this fix, conversation/_current_user_id/_sandbox_mode/
_tools_override/_trust_tool_results/_current_conversation_id/_pending_approval/
_last_tools_used/pending_download were plain instance attributes, so one request
could clobber or read another concurrent request's values the moment either
yielded on I/O (e.g. waiting on the Claude/Kimi API) — cross-user conversation
leakage, wrong-user audit/billing attribution, misdelivered downloads, and (worst)
a sandboxed "simulate this delete" request silently executing for real if a
concurrent non-sandbox request's _sandbox_mode=False won the race.

These tests use real OS threads (not gevent greenlets) to prove the underlying
threading.local()-backed storage is genuinely per-execution-context — gevent's
greenlet-local behavior is the same threading.local() API, just scheduled
cooperatively instead of preemptively.
"""
import threading
from unittest.mock import MagicMock, patch


def _agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        agent = DevOpsAgent(cfg)
    agent.logger = MagicMock()
    return agent


def test_current_user_id_isolated_across_threads():
    agent = _agent()
    step1_done = threading.Event()
    step2_done = threading.Event()
    results = {}

    def request_a():
        agent._current_user_id = 'user-A'
        step1_done.set()
        step2_done.wait(timeout=5)
        # If state were shared, request_b would have overwritten this by now.
        results['a'] = agent._current_user_id

    def request_b():
        step1_done.wait(timeout=5)
        agent._current_user_id = 'user-B'
        results['b'] = agent._current_user_id
        step2_done.set()

    ta = threading.Thread(target=request_a)
    tb = threading.Thread(target=request_b)
    ta.start()
    tb.start()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert results['a'] == 'user-A', "request A's user id was clobbered by request B"
    assert results['b'] == 'user-B'


def test_sandbox_mode_isolated_across_threads():
    """The scariest failure mode: a sandboxed (simulate-only) request must never
    see another concurrent request's real (non-sandbox) flag."""
    agent = _agent()
    step1_done = threading.Event()
    step2_done = threading.Event()
    results = {}

    def sandboxed_request():
        agent._sandbox_mode = True
        step1_done.set()
        step2_done.wait(timeout=5)
        results['sandboxed_still_true'] = agent._sandbox_mode is True

    def real_request():
        step1_done.wait(timeout=5)
        agent._sandbox_mode = False
        step2_done.set()

    t1 = threading.Thread(target=sandboxed_request)
    t2 = threading.Thread(target=real_request)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results['sandboxed_still_true'], (
        "a concurrent non-sandbox request flipped _sandbox_mode to False for the "
        "sandboxed request — this would have let a simulated destructive action "
        "execute for real"
    )


def test_conversation_and_pending_download_isolated_across_threads():
    agent = _agent()
    step1_done = threading.Event()
    step2_done = threading.Event()
    results = {}

    def request_a():
        agent.conversation = 'A-conversation'
        agent.pending_download = {'filename': 'a.pem'}
        step1_done.set()
        step2_done.wait(timeout=5)
        results['a_conv'] = agent.conversation
        results['a_download'] = agent.pending_download

    def request_b():
        step1_done.wait(timeout=5)
        agent.conversation = 'B-conversation'
        agent.pending_download = {'filename': 'b.pem'}
        step2_done.set()

    ta = threading.Thread(target=request_a)
    tb = threading.Thread(target=request_b)
    ta.start()
    tb.start()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert results['a_conv'] == 'A-conversation'
    assert results['a_download'] == {'filename': 'a.pem'}, (
        "request A would have been handed request B's keypair/download"
    )


def test_last_tools_used_isolated_across_threads():
    agent = _agent()
    step1_done = threading.Event()
    step2_done = threading.Event()
    results = {}

    def request_a():
        agent._last_tools_used = []
        agent._last_tools_used.append('delete_ec2_instance')
        step1_done.set()
        step2_done.wait(timeout=5)
        results['a_tools'] = list(agent._last_tools_used)

    def request_b():
        step1_done.wait(timeout=5)
        agent._last_tools_used = []
        agent._last_tools_used.append('list_s3_buckets')
        step2_done.set()

    ta = threading.Thread(target=request_a)
    tb = threading.Thread(target=request_b)
    ta.start()
    tb.start()
    ta.join(timeout=5)
    tb.join(timeout=5)

    assert results['a_tools'] == ['delete_ec2_instance'], (
        "request A's tool-usage/audit trail picked up request B's tool call — "
        "this is the wrong-user billing/audit attribution failure mode"
    )


def test_fresh_thread_gets_safe_defaults_not_a_shared_mutable():
    """Unset greenlets/threads must get their own default, not a shared mutable
    object that a later .append() from a different thread would contaminate."""
    agent = _agent()
    results = {}

    def reader():
        results['trust'] = agent._trust_tool_results
        results['sandbox'] = agent._sandbox_mode
        results['user_id'] = agent._current_user_id
        results['tools'] = agent._last_tools_used
        agent._last_tools_used.append('should-not-leak')

    t1 = threading.Thread(target=reader)
    t1.start()
    t1.join(timeout=5)

    assert results['trust'] is True
    assert results['sandbox'] is False
    assert results['user_id'] is None
    assert results['tools'] == ['should-not-leak']

    # A second, unrelated thread must not see the first thread's mutation.
    results2 = {}

    def second_reader():
        results2['tools'] = list(agent._last_tools_used)

    t2 = threading.Thread(target=second_reader)
    t2.start()
    t2.join(timeout=5)

    assert results2['tools'] == [], (
        "the default empty list was shared across threads instead of being "
        "freshly created per thread"
    )
