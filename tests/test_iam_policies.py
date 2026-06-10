"""Validate the published least-privilege IAM policy JSON files.

These files are public trust artifacts (linked from settings/onboarding),
so they must stay valid, within IAM size limits, and must never grant the
data-access actions we promise to exclude.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IAM_DIR = ROOT / 'static' / 'iam'
READONLY = IAM_DIR / 'devops-agent-readonly.json'
MANAGEMENT = IAM_DIR / 'devops-agent-management.json'
CF_TEMPLATE = ROOT / 'cloudformation' / 'devops-agent-role.json'

# IAM counts only non-whitespace characters against the managed policy limit
IAM_MANAGED_POLICY_CHAR_LIMIT = 6144

DATA_ACCESS_ACTIONS = {
    's3:GetObject',
    's3:Get*',
    's3:*',
    'secretsmanager:GetSecretValue',
    'secretsmanager:Get*',
    'ssm:GetParameter',
    'ssm:GetParameters',
    'ssm:GetParametersByPath',
    'ssm:Get*',
    'ssm:*',
    'lambda:GetFunction',
    'lambda:Get*',
    'dynamodb:GetItem',
    'dynamodb:Query',
    'dynamodb:Scan',
}

MUTATING_VERBS = re.compile(
    r':(Create|Delete|Put|Update|Modify|Terminate|Start|Stop|Reboot|Attach|'
    r'Detach|Associate|Disassociate|Run|Invoke|Send|Set|Add|Remove|Tag|Untag|'
    r'Register|Deregister|Enable|Disable|Authorize|Revoke|Import|Restore)'
)


def _load(path):
    return json.loads(path.read_text())


def _actions(policy):
    actions = []
    for stmt in policy['Statement']:
        a = stmt['Action']
        actions.extend([a] if isinstance(a, str) else a)
    return actions


@pytest.mark.parametrize('path', [READONLY, MANAGEMENT], ids=['readonly', 'management'])
def test_policy_is_valid_and_well_formed(path):
    policy = _load(path)
    assert policy['Version'] == '2012-10-17'
    assert policy['Statement'], 'policy must have at least one statement'
    for stmt in policy['Statement']:
        assert stmt['Effect'] == 'Allow', 'published policies are allow-only'
        assert stmt.get('Sid'), 'every statement needs a Sid for auditability'
        assert stmt.get('Resource') == '*'


@pytest.mark.parametrize('path', [READONLY, MANAGEMENT], ids=['readonly', 'management'])
def test_policy_fits_iam_managed_policy_limit(path):
    non_whitespace = re.sub(r'\s', '', path.read_text())
    assert len(non_whitespace) <= IAM_MANAGED_POLICY_CHAR_LIMIT


def test_readonly_policy_grants_no_data_access():
    actions = set(_actions(_load(READONLY)))
    leaked = actions & DATA_ACCESS_ACTIONS
    assert not leaked, f'read-only policy grants data access: {leaked}'


def test_readonly_policy_grants_no_mutations():
    for action in _actions(_load(READONLY)):
        assert not MUTATING_VERBS.search(action), f'mutating action in read-only policy: {action}'


def test_management_policy_keeps_iam_and_secret_values_locked_down():
    actions = _actions(_load(MANAGEMENT))
    for action in actions:
        service, _, verb = action.partition(':')
        if service == 'iam':
            assert verb.startswith(('Get', 'List')) or action == 'iam:PassRole', \
                f'management policy must not grant IAM writes: {action}'
        if service == 'secretsmanager':
            assert 'GetSecretValue' not in verb and verb != '*' and not verb.startswith('Get'), \
                f'management policy must not read secret values: {action}'
        if service == 'ssm':
            assert verb != '*' and not verb.startswith('GetParameter'), \
                f'management policy must not read SSM parameter values: {action}'


def test_management_passrole_is_conditioned_to_aws_services():
    policy = _load(MANAGEMENT)
    passrole = [s for s in policy['Statement'] if s['Action'] == 'iam:PassRole']
    assert len(passrole) == 1
    services = passrole[0]['Condition']['StringEquals']['iam:PassedToService']
    assert all(s.endswith('.amazonaws.com') for s in services)


def test_cloudformation_template_embeds_published_policies():
    """The quick-create template must stay in sync with the published policy
    files. If this fails, re-run scripts/build_cf_template.py and re-upload."""
    template = _load(CF_TEMPLATE)
    policies = template['Resources']['DevOpsAgentRole']['Properties']['Policies']
    assert len(policies) == 1
    branches = policies[0]['PolicyDocument']['Fn::If']
    assert branches[0] == 'IsManagement'
    assert branches[1] == _load(MANAGEMENT), 'template management policy out of sync'
    assert branches[2] == _load(READONLY), 'template readonly policy out of sync'


def test_cloudformation_template_trust_policy_requires_external_id():
    template = _load(CF_TEMPLATE)
    assert template['Parameters']['ExternalId']['MinLength'] >= 8
    assert template['Parameters']['PolicyLevel']['Default'] == 'ReadOnly'
    trust = template['Resources']['DevOpsAgentRole']['Properties']['AssumeRolePolicyDocument']
    condition = trust['Statement'][0]['Condition']['StringEquals']
    assert condition['sts:ExternalId'] == {'Ref': 'ExternalId'}
