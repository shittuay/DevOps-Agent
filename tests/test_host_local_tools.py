"""Tools that act on the DevOps Agent server itself are off unless self-hosted.

command_tools, git_tools, docker_tools, terraform_tools and ansible_tools run
programs and read files on the machine hosting the app. On the hosted site that
is the production server, so a user could self-confirm `execute_command printenv`
or `cat .env` and read the platform's secrets (2026-10-22 review). They are now
registered only with DEVOPS_AGENT_HOST_TOOLS=true, on the chat agent and MCP.
"""
import os
from pathlib import Path

import pytest

from src.tools import host_local

ROOT = Path(__file__).resolve().parent.parent

HOST_TOOL_NAMES = {'execute_command', 'git_pull', 'docker_list_containers',
                   'terraform_apply', 'ansible_playbook_run'}


def _build_agent(monkeypatch, enabled: bool):
    import app as appmod
    monkeypatch.setenv('ANTHROPIC_API_KEY', os.environ.get('ANTHROPIC_API_KEY') or 'sk-ant-test-placeholder')
    if enabled:
        monkeypatch.setenv(host_local.HOST_TOOLS_ENV, 'true')
    else:
        monkeypatch.delenv(host_local.HOST_TOOLS_ENV, raising=False)
    prev_agent, prev_cfg = appmod.agent, appmod.app.config.get('DEVOPS_AGENT')
    appmod.agent = None
    appmod.app.config.pop('DEVOPS_AGENT', None)
    try:
        ok, err = appmod.initialize_agent()
        assert ok, err
        return set(appmod.agent.tools)
    finally:
        appmod.agent = prev_agent
        appmod.app.config['DEVOPS_AGENT'] = prev_cfg


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(host_local.HOST_TOOLS_ENV, raising=False)
    assert host_local.host_tools_enabled() is False
    monkeypatch.setenv(host_local.HOST_TOOLS_ENV, 'false')
    assert host_local.host_tools_enabled() is False
    monkeypatch.setenv(host_local.HOST_TOOLS_ENV, 'true')
    assert host_local.host_tools_enabled() is True


def test_chat_agent_has_no_host_tools_by_default(app, monkeypatch):
    tools = _build_agent(monkeypatch, enabled=False)
    assert not (HOST_TOOL_NAMES & tools)
    assert 'http_check' in tools


def test_self_hosted_opt_in_registers_them(app, monkeypatch):
    tools = _build_agent(monkeypatch, enabled=True)
    assert {'execute_command', 'git_pull', 'docker_list_containers'} <= tools


def test_mcp_catalog_has_no_host_tools_by_default(monkeypatch):
    from routes import mcp
    monkeypatch.delenv(host_local.HOST_TOOLS_ENV, raising=False)
    monkeypatch.setattr(mcp, '_tool_cache', None)
    monkeypatch.setattr(mcp, '_tool_map', None)
    _, tool_map = mcp._get_all_tools()
    assert not (HOST_TOOL_NAMES & set(tool_map))
    monkeypatch.setattr(mcp, '_tool_cache', None)
    monkeypatch.setattr(mcp, '_tool_map', None)


@pytest.mark.parametrize('command', ['/tmp/x/ls', './ls', '../bin/cat /etc/hosts', 'bin/ls', ''])
def test_execute_command_refuses_a_path_as_the_program(command):
    from src.tools.command_tools import execute_command
    result = execute_command(command)
    assert result['success'] is False


def test_execute_command_runs_the_allowlisted_program_from_path():
    from src.tools.command_tools import execute_command
    result = execute_command('echo ok')
    assert result['success'] is True and result['stdout'].strip() == 'ok'


def test_sandbox_run_is_admin_only_and_needs_the_flag():
    src = (ROOT / 'app.py').read_text(encoding='utf-8')
    block = src.split("@app.route('/api/sandbox/run'", 1)[1].split('@app.route(', 1)[0]
    assert '@_admin_required' in block
    assert 'host_tools_enabled()' in block
    assert "network=False" in block and "data.get('network'" not in block
