"""Tests for progressive tool loading (src/agent/tool_selection.py)."""
from src.agent.tool_selection import (
    classify_tool,
    select_tool_definitions,
    module_category_from_name,
)


def _td(name: str):
    return {'name': name, 'description': f'{name} description', 'input_schema': {}}


def _build_registry():
    """Synthetic catalog: AWS ec2/s3/iam (30 each) + sonar + nexus + always + meta."""
    defs, cats = [], {}

    def add(names, module_category):
        for n in names:
            defs.append(_td(n))
            cats[n] = classify_tool(n, module_category)

    add([f'ec2_tool_{i}' for i in range(30)], 'aws')
    add([f's3_tool_{i}' for i in range(30)], 'aws')
    add([f'iam_tool_{i}' for i in range(30)], 'aws')
    add([f'get_sonar_metric_{i}' for i in range(12)], 'sonarqube')
    add([f'nexus_op_{i}' for i in range(12)], 'nexus')
    add(['run_command', 'run_shell'], 'command')
    add(['devops_op'], 'devops_operations')
    # The meta search tool (registered by core, category 'meta').
    defs.append(_td('search_tools'))
    cats['search_tools'] = 'meta'
    return defs, cats


def test_module_category_from_name():
    assert module_category_from_name('src.tools.aws_tools') == 'aws'
    assert module_category_from_name('kubernetes_tools') == 'kubernetes'
    assert module_category_from_name('cicd_tools') == 'cicd'


def test_classify_tool_aws_service_level():
    assert classify_tool('terminate_ec2_instance', 'aws') == 'aws.ec2'
    assert classify_tool('list_s3_buckets', 'aws') == 'aws.s3'
    assert classify_tool('create_iam_role', 'aws') == 'aws.iam'
    assert classify_tool('describe_rds_instances', 'aws') == 'aws.rds'
    # Non-AWS falls back to module category.
    assert classify_tool('get_sonar_issues', 'sonarqube') == 'sonarqube'
    assert classify_tool('list_pods', 'kubernetes') == 'kubernetes'


def test_select_narrows_to_relevant_service():
    defs, cats = _build_registry()
    subset = select_tool_definitions(defs, cats, "list my ec2 instances", max_tools=60)
    assert subset is not None
    names = {t['name'] for t in subset}
    # ec2 tools included, unrelated providers excluded.
    assert any(n.startswith('ec2_tool_') for n in names)
    assert not any(n.startswith('get_sonar_metric_') for n in names)
    assert not any(n.startswith('nexus_op_') for n in names)
    # Always-on categories + the search escape hatch are present.
    assert 'run_command' in names
    assert 'devops_op' in names
    assert 'search_tools' in names


def test_select_returns_none_on_no_match():
    defs, cats = _build_registry()
    assert select_tool_definitions(defs, cats, "asdf qwerty zzz", max_tools=60) is None


def test_select_respects_max_tools_cap():
    defs, cats = _build_registry()
    # "instance" gives aws.ec2 score 2 (ec2 + instance) so it's the forced top
    # category; s3/iam score 1 and get dropped once the cap is hit.
    subset = select_tool_definitions(
        defs, cats, "show ec2 instance and s3 and iam", max_tools=60
    )
    assert subset is not None
    names = {t['name'] for t in subset}
    assert len(subset) <= 60
    assert any(n.startswith('ec2_tool_') for n in names)  # primary target kept
    assert 'search_tools' in names


def test_general_aws_mention_seeds_common_services():
    defs, cats = _build_registry()
    subset = select_tool_definitions(defs, cats, "audit my aws account", max_tools=200)
    assert subset is not None
    names = {t['name'] for t in subset}
    assert any(n.startswith('ec2_tool_') for n in names)
    assert any(n.startswith('s3_tool_') for n in names)
    assert any(n.startswith('iam_tool_') for n in names)
