"""
Regression guards for the 2026-09-02 tool-dispatch incident.

Two independent bugs let Kimi call ``nmap_port_scan`` 150 times in 71 seconds
for a "create an ec2 instance" request, never once calling ``create_ec2_instance``:

1. ``app.py`` passed ``tools_override=scope_tools(...)`` on every chat turn.
   ``scope_tools`` documents that it ignores ``max_tools`` and returns ALL ~742
   tools reordered, and any non-None ``tools_override`` makes
   ``core._maybe_select_tools`` early-return. Progressive tool loading was
   therefore dead on the primary chat path, and the model chose from 742 tools.

2. Nothing detected that a failing tool call was byte-identical to the one
   before it, so the tool loop re-ran the same doomed call until the iteration
   cap, burning the user's credits.

These tests fail if either regression is reintroduced.
"""
import ast
import json
import os

import pytest

from src.agent.tool_selection import classify_tool, select_tool_definitions


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Bug 1: the chat path must not smuggle a full tool list in as an override.
# ---------------------------------------------------------------------------

def _agent_call_keywords(func_name):
    """Every keyword arg passed to agent.process_message_* calls in app.py."""
    src = open(os.path.join(REPO_ROOT, 'app.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == func_name:
            calls.append({kw.arg for kw in node.keywords if kw.arg})
    return calls


@pytest.mark.parametrize('entry_point', [
    'process_message_isolated',
    'process_message_streaming',
])
def test_chat_path_never_passes_tools_override(entry_point):
    """
    A non-None tools_override disables progressive tool loading entirely
    (core.py: ``if self._tools_override is not None: return``). The chat routes
    must pass max_tools and let the agent narrow the catalog itself.
    """
    calls = _agent_call_keywords(entry_point)
    assert calls, f"no {entry_point} call sites found in app.py — did the route move?"
    for kwargs in calls:
        assert 'tools_override' not in kwargs, (
            f"app.py passes tools_override to {entry_point}. That silently disables "
            f"progressive tool loading and ships all ~742 tool schemas to the model."
        )


@pytest.mark.parametrize('entry_point', [
    'process_message_isolated',
    'process_message_streaming',
])
def test_chat_path_passes_max_tools(entry_point):
    """The per-tier cap has to reach _maybe_select_tools to be enforced."""
    calls = _agent_call_keywords(entry_point)
    assert calls, f"no {entry_point} call sites found in app.py"
    for kwargs in calls:
        assert 'max_tools' in kwargs, (
            f"app.py must pass max_tools to {entry_point} so the per-tier cap applies."
        )


def test_ec2_request_selects_ec2_tools_and_excludes_pentest():
    """
    The real catalog, the real message from the incident. Selection must reach
    the EC2 tools and must not surface the nmap tools that were actually called.
    """
    import importlib
    from src.agent.tool_selection import module_category_from_name

    modules = [
        'command_tools', 'aws_tools', 'gcp_tools', 'azure_tools', 'kubernetes_tools',
        'git_tools', 'github_tools', 'docker_tools', 'cicd_tools', 'terraform_tools',
        'monitoring_tools', 'ansible_tools', 'alerting_tools', 'pentest_tools',
        'sonarqube_tools', 'nexus_tools', 'devops_operations_tools',
    ]
    defs, cats = [], {}
    for name in modules:
        mod = importlib.import_module(f'src.tools.{name}')
        category = module_category_from_name(mod.__name__)
        for tool in mod.get_tools():
            defs.append({
                'name': tool['name'],
                'description': tool.get('description', ''),
                'input_schema': tool.get('input_schema', {}),
            })
            cats[tool['name']] = classify_tool(tool['name'], category)

    subset = select_tool_definitions(defs, cats, 'create an ec2 instance', 100)

    assert subset, "selection returned nothing — the full catalog would be sent"
    assert len(subset) < len(defs) / 4, (
        f"selection barely narrowed the catalog: {len(subset)} of {len(defs)}"
    )
    names = {td['name'] for td in subset}
    assert 'create_ec2_instance' in names
    assert 'create_ec2_keypair' in names
    assert not any('nmap' in n for n in names), (
        "pentest tools reached an EC2 request — this is the exact set the model "
        "picked from during the 2026-09-02 incident"
    )


def test_pentest_disabled_by_default_in_config():
    """
    pentest.enabled: true registers 12 attack tools into every user's catalog.
    Only an unset PENTEST_ALLOWED_TARGETS stopped a real scan on 2026-09-02.
    """
    import yaml
    for rel in ('config/config.yaml', 'config/config.yaml.example'):
        path = os.path.join(REPO_ROOT, rel)
        if not os.path.exists(path):
            continue
        cfg = yaml.safe_load(open(path, encoding='utf-8'))
        assert cfg.get('pentest', {}).get('enabled') is False, (
            f"{rel} enables pentest tools by default"
        )


# ---------------------------------------------------------------------------
# Bug 2: identical failing tool calls must stop repeating.
# ---------------------------------------------------------------------------

class _GuardHost:
    """Minimal stand-in exercising the repeat-guard methods off DevOpsAgent."""

    def __init__(self):
        from src.agent.core import DevOpsAgent
        import logging
        self._repeat_guard = {}
        self._turn_guard_notes = []
        self.logger = logging.getLogger('test')
        self.MAX_IDENTICAL_TOOL_FAILURES = DevOpsAgent.MAX_IDENTICAL_TOOL_FAILURES
        self._repeat_key = DevOpsAgent._repeat_key
        for name in ('_repeat_guard_blocked', '_repeat_guard_result',
                     '_repeat_guard_record', '_note_guard'):
            setattr(self, name, getattr(DevOpsAgent, name).__get__(self, _GuardHost))


FAIL = {'success': False, 'error': 'Unauthorized target'}
OK = {'success': True}


def test_repeat_guard_blocks_after_threshold():
    host = _GuardHost()
    args = {'target': 'scanme.nmap.org'}

    for _ in range(host.MAX_IDENTICAL_TOOL_FAILURES):
        assert not host._repeat_guard_blocked('nmap_port_scan', args)
        host._repeat_guard_record('nmap_port_scan', args, FAIL)

    assert host._repeat_guard_blocked('nmap_port_scan', args)
    blocked = host._repeat_guard_result('nmap_port_scan')
    assert blocked['success'] is False
    assert blocked['repeat_guard'] is True
    assert 'nmap_port_scan' in blocked['error']


def test_repeat_guard_ignores_different_arguments():
    """Same tool, different args, is a different call and must not be blocked."""
    host = _GuardHost()
    for i in range(host.MAX_IDENTICAL_TOOL_FAILURES + 2):
        host._repeat_guard_record('get_ec2_instances', {'region': f'us-east-{i}'}, FAIL)
    assert not host._repeat_guard_blocked('get_ec2_instances', {'region': 'us-east-9'})


def test_repeat_guard_resets_on_success():
    host = _GuardHost()
    args = {'region': 'us-east-1'}
    for _ in range(host.MAX_IDENTICAL_TOOL_FAILURES):
        host._repeat_guard_record('get_ec2_instances', args, FAIL)
    assert host._repeat_guard_blocked('get_ec2_instances', args)

    host._repeat_guard_record('get_ec2_instances', args, OK)
    assert not host._repeat_guard_blocked('get_ec2_instances', args)


def test_repeat_key_is_argument_order_insensitive():
    host = _GuardHost()
    a = host._repeat_key('t', {'b': 2, 'a': 1})
    b = host._repeat_key('t', {'a': 1, 'b': 2})
    assert a == b


def test_repeat_key_survives_unserializable_arguments():
    """A tool arg that json cannot encode must not raise inside the guard."""
    host = _GuardHost()
    key = host._repeat_key('t', {'when': object()})
    assert key.startswith('t:')


def test_all_three_execution_paths_are_guarded():
    """
    Kimi non-streaming, Kimi streaming, and Claude each dispatch tools in their
    own block. A guard added to only one leaves the incident reproducible on
    the other two.
    """
    src = open(os.path.join(REPO_ROOT, 'src/agent/core.py'), encoding='utf-8').read()
    assert src.count('_repeat_guard_blocked(tool_name, tool_input)') == 3, (
        "expected the repeat guard on all three tool-execution paths"
    )
    assert src.count('_repeat_guard_record(tool_name, tool_input, result)') == 3, (
        "expected failure recording on all three tool-execution paths"
    )
