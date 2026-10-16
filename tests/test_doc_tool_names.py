"""Tool names written in agent skills and the connector submission must exist.

The built-in skills are injected into the agent's prompt, so a made-up name sends the
model after a tool it cannot call. The connector submission's examples are what
Anthropic's reviewers try. Both named `list_pods` / `list_ec2_instances`, which never
existed (the real tools are `get_pods` / `get_ec2_instances`), until 2026-10-16.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERBS = ('get_', 'list_', 'describe_', 'create_', 'delete_', 'update_', 'terminate_',
         'manage_', 'run_', 'scale_', 'restart_', 'rollback_', 'start_', 'stop_')


def _catalog():
    names = set()
    for f in (ROOT / 'src' / 'tools').glob('*_tools.py'):
        names.update(re.findall(r"""['"]name['"]\s*:\s*['"]([a-z0-9_]+)['"]""", f.read_text()))
    return names


def _named_tools(text):
    return {t for t in re.findall(r'`([a-z][a-z0-9_]+)`', text) if t.startswith(VERBS)}


def test_tool_names_in_skills_and_submission_exist():
    catalog = _catalog()
    files = sorted((ROOT / 'skills').glob('*.md')) + [ROOT / 'mcp' / 'CONNECTOR_SUBMISSION.md']
    missing = {f'{f.relative_to(ROOT)}: {t}'
               for f in files for t in _named_tools(f.read_text()) if t not in catalog}
    assert not missing, sorted(missing)
