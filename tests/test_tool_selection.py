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


def _build_multi_provider_registry():
    """Synthetic catalog with a large k8s category, a small eks one, the
    provider escape hatches, azure/gcp, and the always-on base."""
    defs, cats = [], {}

    def add(names, module_category):
        for n in names:
            defs.append(_td(n))
            cats[n] = classify_tool(n, module_category)

    add([f'list_eks_thing_{i}' for i in range(28)], 'aws')
    add([f'ec2_tool_{i}' for i in range(29)], 'aws')
    add([f'rds_tool_{i}' for i in range(32)], 'aws')
    add(['aws_api_read', 'aws_api_write'], 'aws')
    add([f'k8s_tool_{i}' for i in range(76)] + ['k8s_api_read', 'k8s_api_write'], 'kubernetes')
    add([f'azure_tool_{i}' for i in range(37)] + ['azure_api_read', 'azure_api_write'], 'azure')
    add([f'gcp_tool_{i}' for i in range(40)] + ['gcp_api_read', 'gcp_api_write'], 'gcp')
    add([f'docker_tool_{i}' for i in range(22)], 'docker')
    add(['run_command', 'run_shell'], 'command')
    add(['devops_op'], 'devops_operations')
    defs.append(_td('search_tools'))
    cats['search_tools'] = 'meta'
    return defs, cats


def _names(subset):
    return {t['name'] for t in subset}


def test_search_tools_always_present():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "list my ec2 instances", max_tools=100)
    assert 'search_tools' in _names(subset)


def test_escape_hatches_scoped_to_implicated_providers():
    """A plain AWS request must carry only the AWS escape hatch, not all four
    providers'. Production, 2026-09-02: k8s_api_read executed for a "create an
    ec2 instance" request purely because every hatch was always offered,
    though nothing about the request implicated Kubernetes. See
    CLAUDE_RUNBOOK.md."""
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "list my ec2 instances", max_tools=100)
    names = _names(subset)
    assert 'aws_api_read' in names and 'aws_api_write' in names
    for hatch in ('azure_api_read', 'azure_api_write', 'gcp_api_read', 'gcp_api_write',
                  'k8s_api_read', 'k8s_api_write'):
        assert hatch not in names, f"{hatch} offered for an AWS-only request"
    # ...and the scoped hatch doesn't drag the rest of its category along.
    assert not any(n.startswith('azure_tool_') for n in names)
    assert not any(n.startswith('k8s_tool_') for n in names)


def test_escape_hatches_scoped_to_each_provider_named():
    """A genuinely cross-cloud request keeps every hatch it actually implicates.
    Uses explicit category keywords rather than a generic noun like "vm" —
    a bare generic noun legitimately spans all providers when unscoped
    (see test_generic_noun_spans_providers_when_unknown); this test checks
    the separate case of two providers both named outright."""
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(
        defs, cats, "list my aws ec2 instances and azure resource groups", max_tools=200
    )
    names = _names(subset)
    assert 'aws_api_read' in names
    assert 'azure_api_read' in names
    assert 'gcp_api_read' not in names
    assert 'k8s_api_read' not in names


def test_kubernetes_request_gets_only_the_k8s_hatch():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "list my kubernetes pods", max_tools=100)
    names = _names(subset)
    assert 'k8s_api_read' in names and 'k8s_api_write' in names
    assert 'aws_api_read' not in names
    assert 'gcp_api_read' not in names


def test_tied_top_categories_are_both_kept_even_over_cap():
    """'pods in my eks cluster' names Kubernetes (pod) and EKS equally; the cap
    used to keep whichever sorted first and silently drop the other 76 tools."""
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "show me the pods in my eks cluster", max_tools=100)
    names = _names(subset)
    assert any(n.startswith('k8s_tool_') for n in names)
    assert any(n.startswith('list_eks_thing_') for n in names)
    assert not any(n.startswith('azure_tool_') for n in names)


def test_follow_up_keeps_previous_turns_categories():
    defs, cats = _build_multi_provider_registry()
    history = ["list my ec2 instances", "which ones are stopped?"]
    subset = select_tool_definitions(defs, cats, "yes go ahead", max_tools=100,
                                     history_messages=history)
    assert subset is not None, "a follow-up with prior context must not fall back to the full catalog"
    names = _names(subset)
    assert any(n.startswith('ec2_tool_') for n in names)
    assert not any(n.startswith('gcp_tool_') for n in names)


def test_no_signal_at_all_still_returns_none():
    defs, cats = _build_multi_provider_registry()
    assert select_tool_definitions(defs, cats, "yes go ahead", max_tools=100,
                                   history_messages=["thanks", "ok"]) is None


def test_generic_noun_spans_providers_when_unknown():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "restart the web server", max_tools=200)
    names = _names(subset)
    assert any(n.startswith('ec2_tool_') for n in names)
    assert any(n.startswith('azure_tool_') for n in names)
    assert any(n.startswith('gcp_tool_') for n in names)


def test_generic_noun_filtered_to_connected_providers():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(
        defs, cats, "restart the web server", max_tools=200,
        connected_providers={'aws': False, 'azure': True, 'gcp': False},
    )
    names = _names(subset)
    assert any(n.startswith('azure_tool_') for n in names)
    assert not any(n.startswith('ec2_tool_') for n in names)
    assert not any(n.startswith('gcp_tool_') for n in names)


def test_explicit_provider_mention_is_never_filtered():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(
        defs, cats, "list my azure vms", max_tools=200,
        connected_providers={'aws': True, 'azure': False, 'gcp': False},
    )
    assert any(n.startswith('azure_tool_') for n in _names(subset))


def test_containers_are_not_just_local_docker():
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "list my running containers", max_tools=200)
    names = _names(subset)
    assert any(n.startswith('k8s_tool_') for n in names)
    assert any(n.startswith('list_eks_thing_') for n in names)


def test_bare_region_seeds_aws_services():
    """'list all resources in us-east-1' names no AWS service and previously
    matched nothing, falling back to the entire catalog."""
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "list all resources in us-east-1", max_tools=100)
    assert subset is not None
    names = _names(subset)
    assert any(n.startswith('ec2_tool_') for n in names)
    assert 'aws_api_read' in names


def test_aws_seed_stays_within_cap():
    """The seeded services are a guess, not something the user named, so they
    must not claim the cap-exempt 'tied top score' slot."""
    defs, cats = _build_multi_provider_registry()
    subset = select_tool_definitions(defs, cats, "what is my aws bill this month", max_tools=100)
    assert len(subset) <= 100
