"""Tests for the IAM policy freshness check (stale efs:*/opensearch:* grants)."""
import pytest
from botocore.exceptions import ClientError

from services import credential_service
from services.credential_service import (
    _stale_policy_actions,
    check_aws_policy_freshness,
)

ROLE_CREDS = {'auth_mode': 'role_arn',
              'role_arn': 'arn:aws:iam::111122223333:role/devops-agent-role',
              'external_id': 'x' * 16}

STALE_DOC = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Allow', 'Action': ['ec2:*', 'efs:*', 'opensearch:*'], 'Resource': '*'}]}
FIXED_DOC = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Allow', 'Action': ['ec2:*', 'elasticfilesystem:*', 'es:*'], 'Resource': '*'}]}


class FakeIam:
    def __init__(self, inline=None, attached=None, error=None):
        self.inline = inline or {}
        self.attached = attached or []
        self.error = error

    def _raise_if_error(self):
        if self.error:
            raise ClientError({'Error': {'Code': self.error, 'Message': ''}}, 'ListRolePolicies')

    def list_role_policies(self, RoleName):
        self._raise_if_error()
        return {'PolicyNames': list(self.inline)}

    def get_role_policy(self, RoleName, PolicyName):
        return {'PolicyDocument': self.inline[PolicyName]}

    def list_attached_role_policies(self, RoleName):
        return {'AttachedPolicies': [
            {'PolicyArn': arn, 'PolicyName': arn.rsplit('/', 1)[-1]}
            for arn, _ in self.attached]}

    def get_policy(self, PolicyArn):
        return {'Policy': {'DefaultVersionId': 'v1'}}

    def get_policy_version(self, PolicyArn, VersionId):
        doc = dict(self.attached)[PolicyArn]
        return {'PolicyVersion': {'Document': doc}}


@pytest.fixture
def wire(monkeypatch):
    def _wire(creds, iam):
        monkeypatch.setattr(credential_service, 'get_user_aws_credentials', lambda uid: creds)
        monkeypatch.setattr(credential_service, 'get_user_boto_client', lambda uid, svc, region=None: iam)
    return _wire


def test_stale_actions_detects_dead_prefixes_case_insensitively():
    doc = {'Statement': {'Effect': 'Allow', 'Action': 'EFS:Describe*', 'Resource': '*'}}
    assert _stale_policy_actions(doc) == ['EFS:Describe*']
    assert _stale_policy_actions(STALE_DOC) == ['efs:*', 'opensearch:*']
    assert _stale_policy_actions(FIXED_DOC) == []


def test_not_applicable_without_role_arn_mode(wire):
    wire(None, None)
    assert check_aws_policy_freshness(1) == {'applicable': False}
    wire({'auth_mode': 'access_key', 'access_key': 'AKIA...'}, None)
    assert check_aws_policy_freshness(1) == {'applicable': False}


def test_outdated_inline_policy_is_flagged(wire):
    wire(ROLE_CREDS, FakeIam(inline={'DevOpsAgentPolicy': STALE_DOC}))
    result = check_aws_policy_freshness(1)
    assert result['applicable'] and result['outdated'] is True
    assert result['stale_actions'] == ['efs:*', 'opensearch:*']
    assert result['checked_policies'] == ['DevOpsAgentPolicy']


def test_fixed_policy_passes(wire):
    wire(ROLE_CREDS, FakeIam(inline={'DevOpsAgentPolicy': FIXED_DOC}))
    result = check_aws_policy_freshness(1)
    assert result['outdated'] is False and result['stale_actions'] == []


def test_customer_managed_attached_policy_is_inspected(wire):
    arn = 'arn:aws:iam::111122223333:policy/devops-agent-management'
    wire(ROLE_CREDS, FakeIam(attached=[(arn, STALE_DOC)]))
    result = check_aws_policy_freshness(1)
    assert result['outdated'] is True
    assert result['checked_policies'] == ['devops-agent-management']


def test_aws_managed_attached_policies_are_skipped(wire):
    aws_managed = 'arn:aws:iam::aws:policy/ReadOnlyAccess'
    wire(ROLE_CREDS, FakeIam(attached=[(aws_managed, STALE_DOC)]))
    result = check_aws_policy_freshness(1)
    assert result['outdated'] is False and result['checked_policies'] == []


def test_access_denied_returns_unknown_not_crash(wire):
    wire(ROLE_CREDS, FakeIam(error='AccessDenied'))
    result = check_aws_policy_freshness(1)
    assert result['applicable'] and result['outdated'] is None
    assert result['error'] == 'AccessDenied'
