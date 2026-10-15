"""Preparation for moving the platform to a new AWS account.

- The migration bridge (PLATFORM_BRIDGE_ROLE_ARN) only engages after a direct
  AssumeRole is denied, keeps the customer's External ID, and is a no-op when unset.
- The CloudFormation template URL is configuration, not a literal in two templates.
- Every workflow that talks to AWS uses OIDC with a repo-variable role ARN.
"""
import re
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from services import credential_service
from scripts.count_role_arn_customers import summarize

ROOT = Path(__file__).resolve().parent.parent
CUSTOMER_ROLE = 'arn:aws:iam::111122223333:role/DevOpsAgentRole'
BRIDGE_ROLE = 'arn:aws:iam::188046727805:role/devops-agent-migration-bridge'


def _denied():
    return ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'no'}}, 'AssumeRole')


def _creds(tag):
    return {'AccessKeyId': f'AK{tag}', 'SecretAccessKey': f'SK{tag}', 'SessionToken': f'ST{tag}'}


class FakeSts:
    """One fake STS client per boto3.client() call; behaviour keyed by caller identity."""

    def __init__(self, calls, identity, outcomes):
        self.calls, self.identity, self.outcomes = calls, identity, outcomes

    def assume_role(self, **params):
        self.calls.append((self.identity, params))
        outcome = self.outcomes[(self.identity, params['RoleArn'])]
        if isinstance(outcome, Exception):
            raise outcome
        return {'Credentials': outcome}


@pytest.fixture
def sts(monkeypatch):
    calls, outcomes = [], {}

    def client(service, **kwargs):
        assert service == 'sts'
        identity = kwargs.get('aws_access_key_id', 'platform')
        return FakeSts(calls, identity, outcomes)

    monkeypatch.setattr(credential_service.boto3, 'client', client)
    return calls, outcomes


def test_direct_success_never_touches_the_bridge(sts, monkeypatch):
    calls, outcomes = sts
    monkeypatch.setenv('PLATFORM_BRIDGE_ROLE_ARN', BRIDGE_ROLE)
    outcomes[('platform', CUSTOMER_ROLE)] = _creds('direct')
    assert credential_service._assume_role(CUSTOMER_ROLE, 'ext-1') == _creds('direct')
    assert [c[1]['RoleArn'] for c in calls] == [CUSTOMER_ROLE]


def test_denied_without_bridge_fails_with_trust_policy_hint(sts, monkeypatch):
    calls, outcomes = sts
    monkeypatch.delenv('PLATFORM_BRIDGE_ROLE_ARN', raising=False)
    outcomes[('platform', CUSTOMER_ROLE)] = _denied()
    with pytest.raises(Exception, match='trust policy'):
        credential_service._assume_role(CUSTOMER_ROLE, 'ext-1')
    assert len(calls) == 1


def test_denied_with_bridge_chains_and_keeps_the_external_id(sts, monkeypatch):
    calls, outcomes = sts
    monkeypatch.setenv('PLATFORM_BRIDGE_ROLE_ARN', BRIDGE_ROLE)
    outcomes[('platform', CUSTOMER_ROLE)] = _denied()
    outcomes[('platform', BRIDGE_ROLE)] = _creds('bridge')
    outcomes[('AKbridge', CUSTOMER_ROLE)] = _creds('chained')

    assert credential_service._assume_role(CUSTOMER_ROLE, 'ext-1') == _creds('chained')
    chained = calls[-1]
    assert chained[0] == 'AKbridge'
    assert chained[1]['ExternalId'] == 'ext-1'
    assert chained[1]['DurationSeconds'] <= 3600  # chained sessions cannot exceed 1h


def test_bridge_failure_reports_the_original_denial(sts, monkeypatch):
    _, outcomes = sts
    monkeypatch.setenv('PLATFORM_BRIDGE_ROLE_ARN', BRIDGE_ROLE)
    outcomes[('platform', CUSTOMER_ROLE)] = _denied()
    outcomes[('platform', BRIDGE_ROLE)] = _denied()
    with pytest.raises(Exception, match='Access denied when assuming role'):
        credential_service._assume_role(CUSTOMER_ROLE)


def test_non_denial_errors_do_not_use_the_bridge(sts, monkeypatch):
    calls, outcomes = sts
    monkeypatch.setenv('PLATFORM_BRIDGE_ROLE_ARN', BRIDGE_ROLE)
    outcomes[('platform', CUSTOMER_ROLE)] = ClientError(
        {'Error': {'Code': 'ValidationError', 'Message': 'bad'}}, 'AssumeRole')
    with pytest.raises(Exception, match='Failed to assume role'):
        credential_service._assume_role(CUSTOMER_ROLE)
    assert len(calls) == 1


def test_summarize_splits_role_and_key_connections_without_secrets():
    result = summarize([
        (1, 'a@x.io', {'role_arn': CUSTOMER_ROLE, 'external_id': 'secret-ext'}),
        (2, 'b@x.io', {'access_key': 'AKIA', 'secret_key': 's'}),
        (3, 'c@x.io', None),
    ])
    assert result['role_arn'] == [(1, 'a@x.io', CUSTOMER_ROLE)]
    assert result['access_key'] == 1 and result['unreadable'] == 1
    assert 'secret-ext' not in repr(result)


@pytest.mark.parametrize('path', ['/settings', '/onboarding'])
def test_cf_template_url_comes_from_config(authenticated_client, monkeypatch, path):
    import app as app_module

    url = 'https://new-cf-bucket.s3.amazonaws.com/devops-agent-role.json'
    monkeypatch.setattr(app_module, 'CF_TEMPLATE_URL', url)
    html = authenticated_client.get(path).get_data(as_text=True)
    assert url in html
    assert 'devopsagent-cf-templates' not in html


def test_templates_do_not_hardcode_the_cf_bucket():
    for name in ('settings.html', 'onboarding.html'):
        assert 'devopsagent-cf-templates' not in (ROOT / 'templates' / name).read_text()


def test_aws_workflows_use_oidc_with_a_configurable_role():
    for wf in sorted((ROOT / '.github' / 'workflows').glob('*.yml')):
        text = wf.read_text()
        if 'configure-aws-credentials' not in text:
            continue
        assert 'aws-access-key-id' not in text, f'{wf.name} still uses long-lived keys'
        assert 'id-token: write' in text, f'{wf.name} cannot request an OIDC token'
        for line in re.findall(r'role-to-assume:.*', text):
            assert 'vars.AWS_DEPLOY_ROLE_ARN' in line, f'{wf.name}: {line}'


def test_update_stack_instructions_keep_every_template_parameter():
    """An update-stack that omits a parameter resets it to the template default.

    For RoleName that replaces the role, giving it a new ARN, so the customer's saved
    connection breaks. Every update-stack command we hand out must keep them all.
    """
    import json

    params = json.loads((ROOT / 'cloudformation' / 'devops-agent-role.json').read_text())['Parameters']
    sources = [ROOT / 'templates' / 'settings.html', ROOT / 'docs' / 'iam-policies.md',
               ROOT / 'docs' / 'aws-account-migration.md']
    for path in sources:
        text = path.read_text()
        assert 'update-stack' in text, f'{path.name} no longer shows update-stack; update this test'
        for name in params:
            if name == 'AllowSelfGrant':
                # Leaving it out resets it to 'No', the safe default, and UsePreviousValue is
                # rejected for stacks created before the parameter existed (2026-10-15).
                continue
            assert f'ParameterKey={name},UsePreviousValue=true' in text, f'{path.name} omits {name}'
