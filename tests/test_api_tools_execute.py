"""
Regression tests for POST /api/v1/tools/execute safety gating.

The endpoint used to reimplement its own 12-tool high-risk list instead of
calling SafetyValidator, so a write-scope API key could run execute_command,
the *_api_write passthroughs, and the entire medium-risk set with no
confirmation. These tests pin the fix: the endpoint routes every call through
SafetyValidator.validate_tool_call() (the same gate as the chat UI and MCP
server) and requires confirm:true for both high- and medium-risk tools.
"""

import pytest


@pytest.fixture
def agent_with_tools(app):
    """Register a fake DEVOPS_AGENT whose tools record calls instead of executing."""
    calls = []

    def _make(name):
        def _handler(**kwargs):
            calls.append((name, kwargs))
            return {'success': True, 'tool': name}
        return _handler

    tool_names = [
        'execute_command', 'ssm_run_command', 'aws_api_write',
        'manage_ec2_instance', 'list_ec2_instances', 'get_ec2_instances',
        'delete_vpc',
    ]

    class _FakeAgent:
        tools = {n: _make(n) for n in tool_names}

        def _set_cloud_user_context(self, user_id=None):
            calls.append(('_set_cloud_user_context', {'user_id': user_id}))

        def _clear_cloud_user_context(self):
            calls.append(('_clear_cloud_user_context', {}))

    _prev = app.config.get('DEVOPS_AGENT')
    app.config['DEVOPS_AGENT'] = _FakeAgent()
    app.config['_test_tool_calls'] = calls
    yield calls
    # Restore whatever was there (the real import-time agent), don't just drop it
    app.config['DEVOPS_AGENT'] = _prev
    app.config.pop('_test_tool_calls', None)


def test_initialize_agent_populates_config(app):
    """Regression: initialize_agent() (called at import under gunicorn) must
    populate app.config['DEVOPS_AGENT'] and be idempotent, so /api/v1 tool
    endpoints don't 503 per-worker. Eager import-time init is skipped under
    pytest, so invoke it explicitly here to exercise the same code path."""
    import app as appmod
    with app.app_context():
        ok, err = appmod.initialize_agent()
        assert ok, f"initialize_agent failed: {err}"
        a = app.config.get('DEVOPS_AGENT')
        assert a is not None, "DEVOPS_AGENT not set — REST tool endpoints would 503"
        assert 'execute_command' in a.tools
        # Idempotent: a second call is a no-op that still reports success
        ok2, _ = appmod.initialize_agent()
        assert ok2
    # Clean up so the module-level agent doesn't leak into other tests
    appmod.agent = None
    app.config.pop('DEVOPS_AGENT', None)


def _post(client, headers, tool, params=None, confirm=None):
    body = {'tool': tool}
    if params is not None:
        body['params'] = params
    if confirm is not None:
        body['confirm'] = confirm
    return client.post('/api/v1/tools/execute', json=body, headers=headers)


class TestExecuteToolSafetyGate:
    """Risky calls follow the chat approval rules: the first call files an
    approval request (202) and nothing runs. The old '"confirm": true' flag let
    any write-scope key skip approval and no longer does anything."""

    def _assert_pending(self, resp, calls):
        assert resp.status_code == 202, resp.get_json()
        body = resp.get_json()
        assert body['status'] == 'pending_approval'
        assert isinstance(body['approval_id'], int)
        assert [c for c in calls if not c[0].startswith('_')] == []
        return body

    def test_execute_command_blocked_without_confirm(self, client, api_headers, agent_with_tools):
        """The core gap: execute_command must NOT run unconfirmed via a write key."""
        resp = _post(client, api_headers, 'execute_command', {'command': 'whoami'})
        body = self._assert_pending(resp, agent_with_tools)
        assert body['risk_level'] in ('high', 'critical')

    def test_confirm_flag_no_longer_skips_approval(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'execute_command', {'command': 'whoami'}, confirm=True)
        self._assert_pending(resp, agent_with_tools)

    def test_generic_write_passthrough_requires_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'aws_api_write', {'action': 'anything'})
        assert resp.status_code in (202, 403)
        assert [c for c in agent_with_tools if not c[0].startswith('_')] == []

    def test_ec2_terminate_requires_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'manage_ec2_instance',
                     {'action': 'terminate', 'instance_id': 'i-123'})
        self._assert_pending(resp, agent_with_tools)

    def test_ec2_stop_is_medium_and_requires_confirm(self, client, api_headers, agent_with_tools):
        """Medium-risk (stop/reboot) was not checked at all by the old code."""
        resp = _post(client, api_headers, 'manage_ec2_instance',
                     {'action': 'stop', 'instance_id': 'i-123'})
        self._assert_pending(resp, agent_with_tools)

    def test_ec2_start_is_low_and_runs(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'manage_ec2_instance',
                     {'action': 'start', 'instance_id': 'i-123'})
        assert resp.status_code == 200
        assert ('manage_ec2_instance', {'action': 'start', 'instance_id': 'i-123'}) in agent_with_tools

    def test_read_only_tool_runs_without_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'get_ec2_instances', {})
        assert resp.status_code == 200
        assert ('get_ec2_instances', {}) in agent_with_tools

    def test_delete_prefix_still_requires_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'delete_vpc', {'vpc_id': 'vpc-1'})
        self._assert_pending(resp, agent_with_tools)

    def test_unknown_tool_404(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'not_a_real_tool', {})
        assert resp.status_code == 404

    def test_write_scope_required(self, client, agent_with_tools):
        """No API key → rejected before any tool logic."""
        resp = _post(client, {'Content-Type': 'application/json'},
                     'get_ec2_instances', {})
        assert resp.status_code in (401, 403)
