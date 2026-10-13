"""Workflow input forms: validation, placeholder rendering, the execute endpoint,
the client-IP prefill endpoint, catalog seeding refresh, and static checks over
every starter workflow (each input used, each placeholder declared, each named
tool real).
"""
import importlib
import re

import pytest

from services.starter_workflows import STARTER_WORKFLOWS, seed_workflow_templates
from services.workflow_inputs import (
    MIN_SECRET_LENGTH, placeholders_in, render_steps, spec_problems, validate_inputs,
)


# ----------------------------------------------------------------- validation

def test_defaults_fill_blank_fields():
    specs = [{'key': 'region', 'label': 'Region', 'default': 'us-east-1'}]
    values, errors = validate_inputs(specs, {})
    assert errors == {} and values == {'region': 'us-east-1'}


def test_required_blank_is_an_error_and_optional_blank_is_marked():
    specs = [{'key': 'a', 'label': 'A'}, {'key': 'b', 'label': 'B', 'required': False}]
    values, errors = validate_inputs(specs, {'a': '  '})
    assert errors == {'a': 'Required.'}
    assert values == {'b': 'not specified'}


@pytest.mark.parametrize('raw', ['0.0.0.0/0', '*', 'anywhere', '::/0'])
def test_cidr_refuses_the_whole_internet_by_default(raw):
    specs = [{'key': 'allowed_cidr', 'label': 'IP', 'type': 'cidr'}]
    _, errors = validate_inputs(specs, {'allowed_cidr': raw})
    assert 'allowed_cidr' in errors


def test_cidr_world_allowed_only_when_declared_and_host_bits_normalized():
    specs = [{'key': 'c', 'label': 'C', 'type': 'cidr', 'allow_world': True}]
    assert validate_inputs(specs, {'c': '*'})[0] == {'c': '0.0.0.0/0'}
    specs = [{'key': 'c', 'label': 'C', 'type': 'cidr'}]
    assert validate_inputs(specs, {'c': '203.0.113.10/24'})[0] == {'c': '203.0.113.0/24'}
    assert 'c' in validate_inputs(specs, {'c': 'not-an-ip'})[1]


def test_secret_is_generated_when_blank_and_validated_when_given():
    specs = [{'key': 'k', 'label': 'K', 'type': 'secret'}]
    first, _ = validate_inputs(specs, {})
    second, _ = validate_inputs(specs, {})
    assert len(first['k']) >= MIN_SECRET_LENGTH and first['k'] != second['k']
    assert 'k' in validate_inputs(specs, {'k': 'short'})[1]
    assert 'k' in validate_inputs(specs, {'k': 'has spaces in it but is long'})[1]
    good = 'A' * MIN_SECRET_LENGTH
    assert validate_inputs(specs, {'k': good})[0] == {'k': good}


def test_number_bounds_and_select_options():
    specs = [{'key': 'n', 'label': 'N', 'type': 'number', 'min': 1, 'max': 4},
             {'key': 's', 'label': 'S', 'type': 'select', 'options': ['x', 'y'], 'default': 'x'}]
    assert validate_inputs(specs, {'n': '3', 's': 'y'}) == ({'n': '3', 's': 'y'}, {})
    _, errors = validate_inputs(specs, {'n': '9', 's': 'z'})
    assert set(errors) == {'n', 's'}
    assert 'n' in validate_inputs(specs, {'n': 'two'})[1]


@pytest.mark.parametrize('raw', ['a{b}', 'a`b', 'line\nbreak', 'x' * 201])
def test_text_rejects_prompt_breaking_characters_and_overlong_values(raw):
    specs = [{'key': 't', 'label': 'T'}]
    assert 't' in validate_inputs(specs, {'t': raw})[1]


def test_pattern_is_a_full_match():
    specs = [{'key': 't', 'label': 'T', 'pattern': r'[a-z]+', 'pattern_hint': 'letters'}]
    assert validate_inputs(specs, {'t': 'abc'})[1] == {}
    assert validate_inputs(specs, {'t': 'abc; rm -rf /'})[1] == {'t': 'letters'}


def test_undeclared_and_non_dict_submissions_are_ignored():
    specs = [{'key': 'a', 'label': 'A', 'default': 'x'}]
    assert validate_inputs(specs, {'a': 'y', 'evil': 'z'})[0] == {'a': 'y'}
    assert validate_inputs(specs, ['not', 'a', 'dict'])[0] == {'a': 'x'}


# ------------------------------------------------------------------ rendering

def test_render_replaces_declared_keys_and_leaves_json_braces_alone():
    steps = ['tags {"Name": "web"} in {region}', 'keep {undeclared} as is']
    out = render_steps(steps, {'region': 'eu-west-1'})
    assert out == ['tags {"Name": "web"} in eu-west-1', 'keep {undeclared} as is']


def test_spec_problems_catches_unused_inputs_and_orphan_placeholders():
    specs = [{'key': 'used', 'label': 'U'}, {'key': 'unused', 'label': 'X'}]
    problems = spec_problems(specs, ['uses {used} and {orphan}'])
    assert any('unused' in p for p in problems)
    assert any('orphan' in p for p in problems)


# ---------------------------------------------------- the starter catalog itself

@pytest.mark.parametrize('wf', STARTER_WORKFLOWS, ids=lambda wf: wf['name'])
def test_every_starter_workflow_spec_is_consistent(wf):
    assert spec_problems(wf.get('inputs', []), wf['steps']) == []


def test_no_form_workflow_still_asks_for_its_inputs_in_chat():
    for wf in STARTER_WORKFLOWS:
        if wf.get('inputs'):
            text = ' '.join(wf['steps'])
            assert 'Before creating anything, ask me for' not in text, wf['name']
            assert not re.search(r'\b(MODEL_ID|API_KEY|PROJECT|ZONE|REGION)\b', text), wf['name']


def test_cidr_inputs_only_allow_the_world_for_public_web_apps():
    world_ok = {'EC2 + Nginx Web Server Setup', 'Container App on ECS Fargate + Load Balancer'}
    for wf in STARTER_WORKFLOWS:
        for spec in wf.get('inputs', []):
            if spec.get('type') == 'cidr' and spec.get('allow_world'):
                assert wf['name'] in world_ok, f'{wf["name"]} lets {spec["key"]} be 0.0.0.0/0'


def test_no_workflow_ships_a_default_password():
    for wf in STARTER_WORKFLOWS:
        text = ' '.join(wf['steps'])
        assert 'PASSWORD=admin' not in text, wf['name']


# Tools each new (form-driven) workflow names; a renamed tool would turn a step
# into a guess, so every one must exist in the live catalog.
NEW_WORKFLOW_TOOLS = {
    'Static Website on S3 + CloudFront (HTTPS)': {
        'aws_api_read', 'aws_api_write', 'create_cloudfront_invalidation', 'create_s3_bucket',
        'http_check', 'put_s3_bucket_policy'},
    'Container App on ECS Fargate + Load Balancer': {
        'attach_iam_role_policy', 'authorize_security_group_ingress', 'aws_api_write',
        'create_ecs_cluster', 'create_iam_role', 'create_listener', 'create_load_balancer',
        'create_security_group', 'create_service', 'create_target_group', 'delete_ecs_cluster',
        'delete_load_balancer', 'delete_target_group', 'describe_target_health',
        'get_cloudwatch_logs', 'get_iam_role', 'http_check', 'list_subnets', 'list_vpcs',
        'update_ecs_service'},
    'Create an EKS Cluster (Ready for kubectl)': {
        'associate_eks_access_policy', 'attach_iam_role_policy', 'aws_api_read',
        'create_eks_access_entry', 'create_eks_cluster', 'create_eks_node_group', 'create_iam_role',
        'delete_eks_cluster', 'describe_eks_cluster', 'list_eks_clusters', 'list_subnets',
        'list_vpcs'},
    'Deploy an App to Kubernetes': {
        'create_deployment', 'create_namespace', 'create_service', 'delete_namespace',
        'describe_pod', 'get_deployment_rollout_status', 'get_deployments', 'get_namespaces',
        'get_nodes', 'get_pod_logs', 'get_pods', 'get_services', 'http_check',
        'rollback_deployment', 'update_deployment_image'},
    'Troubleshoot Failing Kubernetes Pods': {
        'describe_node', 'describe_pod', 'get_cluster_events', 'get_nodes', 'get_pod_logs',
        'get_pods', 'get_previous_container_logs', 'top_pods'},
    'Investigate High CPU on an EC2 Instance': {
        'aws_api_read', 'get_ec2_console_output', 'get_ec2_instances',
        'list_ssm_managed_instances', 'ssm_run_command'},
    'Diagnose a Website That Is Down': {
        'aws_api_read', 'describe_target_health', 'get_ec2_instances', 'http_check',
        'list_acm_certificates', 'list_cloudfront_distributions', 'list_load_balancers',
        'list_route53_zones', 'tcp_check'},
    'Investigate an AWS Cost Spike': {
        'aws_api_read', 'get_cost_summary', 'list_ec2_all_regions', 'list_load_balancers',
        'list_s3_buckets'},
    'AWS Security Baseline (CloudTrail + GuardDuty)': {
        'aws_api_read', 'aws_api_write', 'create_s3_bucket', 'list_cloudtrail_trails',
        'put_s3_bucket_policy'},
    'Terraform Remote State Backend on S3': {
        'aws_api_read', 'create_dynamodb_table', 'create_s3_bucket', 'get_s3_bucket_info',
        'put_s3_lifecycle_policy'},
}

# Read-only workflows: diagnosing must never change anything.
READ_ONLY_WORKFLOWS = ('Troubleshoot Failing Kubernetes Pods', 'Diagnose a Website That Is Down',
                       'Investigate an AWS Cost Spike')


def _catalog_names():
    names = set()
    for mod_name in ('aws_tools', 'azure_tools', 'gcp_tools', 'kubernetes_tools',
                     'verification_tools', 'devops_operations_tools', 'cicd_tools'):
        mod = importlib.import_module('src.tools.' + mod_name)
        names.update(t['name'] for t in mod.get_tools())
    return names


def test_new_workflows_name_only_real_tools():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    catalog = _catalog_names()
    for name, tools in NEW_WORKFLOW_TOOLS.items():
        assert name in by_name, f'{name} missing from the catalog'
        text = ' '.join(by_name[name]['steps'])
        for tool in tools:
            assert tool in text, f'{tool} no longer referenced in {name}; update this test'
            assert tool in catalog, f'{name} tells the agent to call {tool}, which does not exist'
        assert by_name[name].get('inputs'), f'{name} should open an input form'


def test_read_only_workflows_never_call_a_write_tool():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    for name in READ_ONLY_WORKFLOWS:
        text = ' '.join(by_name[name]['steps'])
        for marker in ('aws_api_write', 'create_', 'delete_', 'terminate_', 'update_'):
            assert marker not in text, f'read-only {name} mentions {marker}'


# ------------------------------------------------------------------ endpoints

def _make_template(app, user_id, inputs, steps):
    from models import db, WorkflowTemplate

    with app.app_context():
        tpl = WorkflowTemplate(name='Form workflow', description='d', category='test',
                               is_public=True, created_by=user_id, steps=steps, inputs=inputs)
        db.session.add(tpl)
        db.session.commit()
        return tpl.id


def test_execute_rejects_bad_inputs_before_creating_anything(authenticated_client, test_user, app):
    from models import Conversation, WorkflowExecution

    tid = _make_template(app, test_user.id,
                         [{'key': 'allowed_cidr', 'label': 'Your IP', 'type': 'cidr'}],
                         ['open port 80 to {allowed_cidr}'])
    with app.app_context():
        before = (Conversation.query.count(), WorkflowExecution.query.count())

    resp = authenticated_client.post(f'/api/workflows/{tid}/execute',
                                     json={'inputs': {'allowed_cidr': '0.0.0.0/0'}})
    assert resp.status_code == 400
    assert 'allowed_cidr' in resp.get_json()['fields']
    with app.app_context():
        assert (Conversation.query.count(), WorkflowExecution.query.count()) == before


def test_execute_fills_values_into_the_prompt(authenticated_client, test_user, app):
    tid = _make_template(app, test_user.id,
                         [{'key': 'allowed_cidr', 'label': 'Your IP', 'type': 'cidr'},
                          {'key': 'region', 'label': 'Region', 'default': 'us-east-1'}],
                         ['open port 80 to {allowed_cidr} with tags {"a": 1} in {region}'])
    resp = authenticated_client.post(f'/api/workflows/{tid}/execute',
                                     json={'inputs': {'allowed_cidr': '203.0.113.7'}})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    prompt = resp.get_json()['prompt']
    assert 'open port 80 to 203.0.113.7/32 with tags {"a": 1} in us-east-1' in prompt
    assert 'Do not ask me for them again' in prompt
    assert '{allowed_cidr}' not in prompt


def test_client_ip_returns_a_host_cidr_for_public_addresses_only(authenticated_client):
    resp = authenticated_client.get('/api/workflows/client-ip',
                                    headers={'CF-Connecting-IP': '8.8.8.8'})
    assert resp.get_json() == {'cidr': '8.8.8.8/32'}
    resp = authenticated_client.get('/api/workflows/client-ip',
                                    headers={'CF-Connecting-IP': '10.0.0.5'})
    assert resp.get_json() == {'cidr': None}
    resp = authenticated_client.get('/api/workflows/client-ip',
                                    headers={'CF-Connecting-IP': 'garbage'})
    assert resp.get_json() == {'cidr': None}


def test_client_ip_requires_login(client):
    resp = client.get('/api/workflows/client-ip')
    assert resp.status_code in (302, 401)


# -------------------------------------------------------------------- seeding

def test_seed_refreshes_curated_rows_with_edited_steps(app):
    from models import db, WorkflowTemplate

    target = STARTER_WORKFLOWS[0]
    with app.app_context():
        seed_workflow_templates()
        row = WorkflowTemplate.query.filter_by(name=target['name'], created_by=None).first()
        row.steps = ['stale step']
        row.inputs = []
        db.session.commit()

        seed_workflow_templates()
        row = WorkflowTemplate.query.filter_by(name=target['name'], created_by=None).first()
        assert row.steps == target['steps']
        assert (row.inputs or []) == target.get('inputs', [])
