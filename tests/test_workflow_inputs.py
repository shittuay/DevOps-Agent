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
    'Production PostgreSQL on RDS': {
        'authorize_security_group_ingress', 'aws_api_read', 'aws_api_write', 'create_db_subnet_group',
        'create_security_group', 'delete_rds_instance', 'describe_rds_instance', 'list_subnets', 'list_vpcs',
        'modify_rds_instance'},
    'Database Restore Drill (RDS)': {
        'aws_api_read', 'create_rds_snapshot', 'delete_rds_instance', 'delete_rds_snapshot',
        'describe_rds_instance', 'list_rds_snapshots', 'restore_rds_from_snapshot'},
    'CloudWatch Alarms + Email Alerts for an EC2 Instance': {
        'create_cloudwatch_alarm', 'create_sns_topic', 'delete_cloudwatch_alarm', 'delete_sns_topic',
        'get_ec2_instances', 'list_cloudwatch_alarms', 'subscribe_sns_topic'},
    'HTTPS Certificate for Your Domain (ACM + Route 53)': {
        'aws_api_read', 'create_route53_record', 'list_acm_certificates', 'list_route53_zones',
        'request_acm_certificate'},
    'Find Publicly Exposed S3 Buckets': {
        'aws_api_read', 'get_s3_bucket_policy', 'list_s3_buckets', 'set_s3_public_access_block'},
    'IAM Hygiene Audit': {
        'generate_iam_credential_report', 'get_iam_account_summary', 'get_iam_credential_report',
        'list_iam_roles', 'list_iam_services_last_accessed'},
    'Compliance Readiness Check (SOC 2 / HIPAA / PCI DSS)': {'get_security_findings', 'run_compliance_check'},
    'Find Idle Resources Wasting Money': {
        'aws_api_read', 'create_ebs_snapshot', 'delete_ebs_snapshot', 'delete_ebs_volume', 'get_ec2_instances',
        'list_ebs_volumes', 'list_elastic_ips', 'list_nat_gateways', 'release_elastic_ip'},
    'Autoscale a Kubernetes Deployment': {'create_hpa', 'delete_hpa', 'describe_deployment', 'list_hpas',
                                          'top_pods'},
    'Safe Rollout with Automatic Rollback': {
        'describe_deployment', 'get_pod_logs', 'get_pods', 'rollback_deployment', 'rollout_history',
        'rollout_status', 'run_smoke_test', 'update_deployment_image'},
    'Kubernetes Cluster Health Check': {'describe_node', 'get_cluster_events', 'get_nodes', 'k8s_api_read',
                                        'list_pvcs', 'top_nodes'},
    'Secure Linux VM on Azure': {'create_resource_group', 'create_virtual_machine', 'delete_resource_group',
                                 'get_vm_details', 'tcp_check'},
    'Azure SQL Database Locked to Your IP': {
        'create_resource_group', 'create_sql_database', 'create_sql_firewall_rule', 'create_sql_server',
        'delete_resource_group', 'delete_sql_server', 'tcp_check'},
    'Deploy a Container to Google Cloud Run': {
        'delete_cloud_run_service', 'deploy_cloud_run_service', 'http_check', 'list_cloud_run_services'},
    'Cloud SQL Database on GCP': {'create_cloud_sql_instance', 'delete_cloud_sql_instance',
                                  'list_cloud_sql_instances'},
    'Multi-Cloud Inventory and Cost Snapshot': {
        'get_cost_summary', 'get_ec2_instances', 'get_infrastructure_summary',
        'get_optimization_recommendations', 'list_cloud_sql_instances', 'list_compute_instances',
        'list_rds_instances', 'list_virtual_machines'},
    'Fix a Failing GitHub Actions Run': {
        'get_github_run_jobs', 'get_github_workflow_runs', 'list_github_runners', 'list_github_secrets',
        'rerun_failed_github_jobs'},
    'Debug a Failing GitLab Pipeline': {
        'get_gitlab_job_log', 'get_gitlab_pipeline', 'list_gitlab_jobs', 'list_gitlab_pipelines',
        'retry_gitlab_pipeline'},
    'Debug a Failing Jenkins Build': {
        'get_jenkins_build_logs', 'get_jenkins_job_config', 'get_jenkins_job_status', 'get_jenkins_queue',
        'list_jenkins_nodes', 'trigger_jenkins_job'},
    'CI/CD Pipeline Health Report': {
        'get_github_workflow_runs', 'get_github_workflow_usage', 'list_github_environments',
        'list_github_runners', 'list_github_workflows'},
    'Release Readiness Check (SonarQube + CI)': {
        'get_github_workflow_runs', 'get_sonar_hotspots', 'get_sonar_issues', 'get_sonar_project_quality'},
    'On-Call Shift Handoff Report': {
        'opsgenie_get_alert', 'opsgenie_get_oncall', 'opsgenie_list_alerts', 'opsgenie_list_schedules',
        'pagerduty_get_incident', 'pagerduty_list_incidents', 'pagerduty_list_oncalls'},
    'Page the On-Call Engineer (PagerDuty)': {
        'pagerduty_add_note', 'pagerduty_create_incident', 'pagerduty_get_incident',
        'pagerduty_list_incidents', 'pagerduty_list_services'},
}

# Integration workflows run only on the user's own connection; none may ask for a pasted token.
INTEGRATION_WORKFLOWS = (
    'Fix a Failing GitHub Actions Run', 'Debug a Failing GitLab Pipeline', 'Debug a Failing Jenkins Build',
    'CI/CD Pipeline Health Report', 'Release Readiness Check (SonarQube + CI)',
    'On-Call Shift Handoff Report', 'Page the On-Call Engineer (PagerDuty)')

# Diagnose-then-offer workflows: the one write they may make waits for an explicit yes.
CONFIRM_BEFORE_WRITE = {
    'Fix a Failing GitHub Actions Run': 'rerun_failed_github_jobs',
    'Debug a Failing GitLab Pipeline': 'retry_gitlab_pipeline',
    'Debug a Failing Jenkins Build': 'trigger_jenkins_job',
    'Page the On-Call Engineer (PagerDuty)': 'pagerduty_create_incident',
}

# Read-only workflows: diagnosing must never change anything.
READ_ONLY_WORKFLOWS = ('Troubleshoot Failing Kubernetes Pods', 'Diagnose a Website That Is Down',
                       'Investigate an AWS Cost Spike', 'IAM Hygiene Audit',
                       'Compliance Readiness Check (SOC 2 / HIPAA / PCI DSS)',
                       'Kubernetes Cluster Health Check', 'Multi-Cloud Inventory and Cost Snapshot',
                       'CI/CD Pipeline Health Report', 'Release Readiness Check (SonarQube + CI)',
                       'On-Call Shift Handoff Report')

# Workflows that leave billed resources running must tell the user how to remove them.
PROVISIONING_WORKFLOWS = (
    'Production PostgreSQL on RDS', 'Database Restore Drill (RDS)',
    'CloudWatch Alarms + Email Alerts for an EC2 Instance', 'Secure Linux VM on Azure',
    'Azure SQL Database Locked to Your IP', 'Deploy a Container to Google Cloud Run',
    'Cloud SQL Database on GCP', 'Container App on ECS Fargate + Load Balancer',
    'Static Website on S3 + CloudFront (HTTPS)', 'Create an EKS Cluster (Ready for kubectl)')

# Audits that offer a fix must not apply it before the user names what to change.
ASK_BEFORE_CHANGING = ('Find Publicly Exposed S3 Buckets', 'Find Idle Resources Wasting Money')


def _catalog_names():
    names = set()
    for mod_name in ('aws_tools', 'azure_tools', 'gcp_tools', 'kubernetes_tools',
                     'verification_tools', 'devops_operations_tools', 'cicd_tools',
                     'alerting_tools', 'sonarqube_tools'):
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
        # Declared explicitly; an account-wide audit may need none and starts on one click.
        assert 'inputs' in by_name[name], f'{name} should declare its inputs'


def test_provisioning_workflows_end_with_teardown():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    for name in PROVISIONING_WORKFLOWS:
        assert 'teardown' in by_name[name]['steps'][-1].lower() or 'clean up' in \
            by_name[name]['steps'][-1].lower(), f'{name} must end with how to remove what it created'


def test_fix_offering_audits_ask_before_changing_anything():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    for name in ASK_BEFORE_CHANGING:
        text = ' '.join(by_name[name]['steps'])
        assert 'Do not' in text and 'only those' in text, f'{name} must wait for the user to pick items'


def test_new_databases_are_never_public():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    rds = ' '.join(by_name['Production PostgreSQL on RDS']['steps'])
    assert 'PubliclyAccessible false' in rds and 'StorageEncrypted true' in rds
    assert 'ManageMasterUserPassword true' in rds and 'DeletionProtection true' in rds
    azure_sql = ' '.join(by_name['Azure SQL Database Locked to Your IP']['steps'])
    assert 'start_ip and end_ip both {client_ip}' in azure_sql
    assert 'Do not add the 0.0.0.0' in azure_sql
    cloud_sql = ' '.join(by_name['Cloud SQL Database on GCP']['steps'])
    assert 'Add no authorized networks' in cloud_sql


def test_integration_workflows_use_the_users_own_connection():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    for name in INTEGRATION_WORKFLOWS:
        steps = by_name[name]['steps']
        assert 'Settings > Integrations' in steps[0], f'{name} must start by pointing at the user connection'
        assert 'do not ask me to paste a token' in steps[0]
        assert not any(i['type'] == 'secret' for i in by_name[name]['inputs']), f'{name} asks for a secret'


def test_diagnose_then_offer_workflows_wait_for_a_yes():
    by_name = {wf['name']: wf for wf in STARTER_WORKFLOWS}
    for name, write_tool in CONFIRM_BEFORE_WRITE.items():
        step = next(s for s in by_name[name]['steps'] if write_tool in s)
        assert 'I say yes' in step, f'{name} must not call {write_tool} before the user agrees'


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
