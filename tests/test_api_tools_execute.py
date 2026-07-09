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

    app.config['DEVOPS_AGENT'] = _FakeAgent()
    app.config['_test_tool_calls'] = calls
    yield calls
    app.config.pop('DEVOPS_AGENT', None)
    app.config.pop('_test_tool_calls', None)


def _post(client, headers, tool, params=None, confirm=None):
    body = {'tool': tool}
    if params is not None:
        body['params'] = params
    if confirm is not None:
        body['confirm'] = confirm
    return client.post('/api/v1/tools/execute', json=body, headers=headers)


class TestExecuteToolSafetyGate:
    def test_execute_command_blocked_without_confirm(self, client, api_headers, agent_with_tools):
        """The core gap: execute_command must NOT run unconfirmed via a write key."""
        resp = _post(client, api_headers, 'execute_command', {'command': 'whoami'})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body['requires_confirm'] is True
        assert body['risk_level'] in ('high', 'critical')
        # Handler must not have executed
        assert agent_with_tools == []

    def test_execute_command_runs_with_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'execute_command', {'command': 'whoami'}, confirm=True)
        assert resp.status_code == 200
        assert ('execute_command', {'command': 'whoami'}) in agent_with_tools

    def test_generic_write_passthrough_requires_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'aws_api_write', {'action': 'anything'})
        assert resp.status_code in (403, 409)
        assert agent_with_tools == []

    def test_ec2_terminate_requires_confirm(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'manage_ec2_instance',
                     {'action': 'terminate', 'instance_id': 'i-123'})
        assert resp.status_code == 409
        assert resp.get_json()['requires_confirm'] is True
        assert agent_with_tools == []

    def test_ec2_stop_is_medium_and_requires_confirm(self, client, api_headers, agent_with_tools):
        """Medium-risk (stop/reboot) was not checked at all by the old code."""
        resp = _post(client, api_headers, 'manage_ec2_instance',
                     {'action': 'stop', 'instance_id': 'i-123'})
        assert resp.status_code == 409
        assert agent_with_tools == []

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
        assert resp.status_code == 409
        assert agent_with_tools == []

    def test_unknown_tool_404(self, client, api_headers, agent_with_tools):
        resp = _post(client, api_headers, 'not_a_real_tool', {})
        assert resp.status_code == 404

    def test_write_scope_required(self, client, agent_with_tools):
        """No API key → rejected before any tool logic."""
        resp = _post(client, {'Content-Type': 'application/json'},
                     'get_ec2_instances', {})
        assert resp.status_code in (401, 403)
