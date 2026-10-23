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


def test_create_tools_are_never_read_only():
    tools = {t['name']: t['annotations'] for t in _listed_tools()}
    assert tools['create_listener']['readOnlyHint'] is False
    # run_smoke_test only sends HTTP probes.
    writes = [n for n, a in tools.items()
              if a.get('readOnlyHint') and n != 'run_smoke_test' and n.split('_')[0] in
              ('create', 'delete', 'update', 'put', 'set', 'run', 'terminate', 'modify')]
    assert not writes, writes
    # still read-only
    for n in ('docker_list_containers', 'rollout_status', 'pagerduty_list_incidents'):
        assert tools[n]['readOnlyHint'] is True, n


def test_descriptions_do_not_steer_the_model():
    """Directory policy: no instructions about other tools or model behaviour."""
    import re
    tools = _listed_tools()
    names = {t['name'] for t in tools}
    steering = re.compile(r'(?i)\b(you must|always call|never use|use this instead|'
                          r'instead of calling|call this after|use \w+ first|'
                          r'confirm .* with the user)\b')
    bad = []
    for t in tools:
        d = t['description']
        others = [n for n in names if n != t['name'] and re.search(r'\b' + re.escape(n) + r'\b', d)]
        if others:
            bad.append(f"{t['name']} names {others}")
        if steering.search(d):
            bad.append(f"{t['name']}: {steering.search(d).group(0)}")
    assert not bad, bad


def test_overrides_only_cover_real_tools():
    names = {t['name'] for t in _listed_tools()}
    assert set(mcp._MCP_DESCRIPTIONS) <= names


HINTS = ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint')


def test_every_hint_is_explicitly_true_or_false():
    """Directory reviews reject a connector whose hints are unset (null) on any tool."""
    bad = [f"{t['name']}: {h}={t['annotations'].get(h)!r}"
           for t in _listed_tools() for h in HINTS
           if not isinstance(t['annotations'].get(h), bool)]
    assert not bad, bad[:20]


def test_tools_that_change_existing_settings_are_destructive():
    """2026-10-23: every medium-risk tool said destructiveHint false (about 200 tools)."""
    tools = {t['name']: t['annotations'] for t in _listed_tools()}
    for n in ('revoke_security_group_ingress', 'put_iam_inline_policy', 'put_s3_bucket_policy',
              'update_cloudformation_stack', 'replace_route', 'restore_rds_to_point_in_time',
              'manage_ec2_instance', 'delete_vpc'):
        assert tools[n]['destructiveHint'] is True, n
        assert tools[n]['readOnlyHint'] is False, n
    from src.agent.safety import SafetyValidator
    sv = SafetyValidator()
    wrong = [n for n, a in tools.items() if n != 'devopsagent_health'
             and sv.validate_tool_call(n, {}).risk_level != 'low' and not a['destructiveHint']]
    assert not wrong, wrong[:20]


def test_read_only_and_idempotent_hints():
    tools = {t['name']: t['annotations'] for t in _listed_tools()}
    for n in ('aws_api_read', 'find_ami', 'pagerduty_get_incident', 'docker_get_stats',
              'top_pods', 'get_ec2_instances'):
        assert tools[n]['readOnlyHint'] is True and tools[n]['idempotentHint'] is True, n
    assert tools['create_ec2_instance']['readOnlyHint'] is False
    assert tools['create_ec2_instance']['destructiveHint'] is False
    assert tools['create_ec2_instance']['idempotentHint'] is False
    assert tools['put_s3_bucket_policy']['idempotentHint'] is True
    assert tools['aws_api_write']['readOnlyHint'] is False
    # A destructive tool is never read-only.
    assert not [n for n, a in tools.items() if a['readOnlyHint'] and a['destructiveHint']]
