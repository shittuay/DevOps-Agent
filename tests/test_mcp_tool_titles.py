"""Every MCP tool has a title and a readOnlyHint/destructiveHint.

The Claude Connectors Directory submission portal flags any tool missing these. Until
2026-10-16 no tool had a title.
"""
from routes import mcp


def _listed_tools():
    resp = mcp._handle_tools_list(1, {}, user_id=1)
    return resp['result']['tools'] if 'result' in resp else resp.get_json()['result']['tools']


def test_every_tool_has_title_and_hint():
    tools = _listed_tools()
    assert len(tools) > 600
    bad = []
    for t in tools:
        ann = t.get('annotations', {})
        if not t.get('title') or not ann.get('title'):
            bad.append(f"{t['name']}: no title")
        if 'readOnlyHint' not in ann and 'destructiveHint' not in ann:
            bad.append(f"{t['name']}: no hint")
    assert not bad, bad[:20]


def test_titles_are_readable():
    assert mcp._tool_title('get_ec2_instances') == 'Get EC2 Instances'
    assert mcp._tool_title('pagerduty_list_incidents') == 'PagerDuty List Incidents'
    assert mcp._tool_title('list_eks_clusters') == 'List EKS Clusters'
    titles = {t['name']: t['title'] for t in _listed_tools()}
    assert titles['devopsagent_health'] == 'DevOps Agent Health'
