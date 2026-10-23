"""AWS permission requests (owner request, 2026-10-15).

When AWS refuses an action for lack of a permission, the agent writes the smallest
policy that allows it and asks the account owner yes/no. On yes it is added either
by the owner in AWS (manual) or by the agent to its own boundary-capped role (self,
opt-in), and the original call is retried.
"""
from types import SimpleNamespace

import pytest

from services import aws_permissions as ap

DENIED_RUN = {
    'success': False, 'error_code': 'UnauthorizedOperation',
    'error': ('An error occurred (UnauthorizedOperation) when calling the RunInstances operation: '
              'You are not authorized to perform this operation. User: '
              'arn:aws:sts::123456789012:assumed-role/DevOpsAgentRole/devops-agent is not authorized '
              'to perform: ec2:RunInstances on resource: arn:aws:ec2:us-east-1:123456789012:instance/*'),
}


def _denied(op, code='AccessDenied', extra=''):
    return {'success': False, 'error': f'An error occurred ({code}) when calling the {op} operation: {extra}'}


@pytest.fixture
def creds(monkeypatch):
    state = {'creds': {'auth_mode': 'role_arn', 'role_arn': 'arn:aws:iam::123456789012:role/DevOpsAgentRole',
                       'external_id': 'x' * 8, 'region': 'us-east-1', 'self_grant': False}}
    monkeypatch.setattr('services.credential_service.get_user_aws_credentials', lambda uid: state['creds'])
    return state


@pytest.fixture
def clean_requests(app, db_session):
    from models import ApprovalRequest, db
    yield
    db.session.rollback()
    ApprovalRequest.query.filter_by(tool_name=ap.PERMISSION_TOOL).delete(synchronize_session=False)
    db.session.commit()


# --- working out what's missing -------------------------------------------------------

def test_reads_the_action_aws_names():
    d = ap.parse_denial('create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    assert d['action'] == 'ec2:RunInstances' and not d['explicit_deny']
    assert d['principal_arn'].endswith('assumed-role/DevOpsAgentRole/devops-agent')


def test_falls_back_to_the_operation_for_generic_calls():
    d = ap.parse_denial('aws_api_write', {'service': 'elbv2', 'operation': 'create_load_balancer'},
                        _denied('CreateLoadBalancer'))
    assert d['action'] == 'elasticloadbalancing:CreateLoadBalancer'
    d = ap.parse_denial('get_s3_bucket_info', {}, _denied('HeadBucket', code='AccessDenied'), 'aws.s3')
    assert d['action'] == 's3:ListBucket'


def test_not_an_access_denial():
    assert ap.parse_denial('create_ec2_instance', {}, {'success': False, 'error': 'InvalidAMIID.NotFound'}) is None
    assert ap.parse_denial('create_ec2_instance', {}, {'success': True}) is None


def test_explicit_deny_is_not_proposed(creds):
    res = dict(DENIED_RUN, error=DENIED_RUN['error'] + ' with an explicit deny in a service control policy')
    assert ap.build_request(1, 'create_ec2_instance', {}, res, 'aws.ec2') is None


def test_policy_is_minimal():
    p = ap.build_policy('ec2:RunInstances', 'arn:aws:ec2:us-east-1:1:instance/*')
    assert p['Statement'][0]['Action'] == ['ec2:RunInstances'] and p['Statement'][0]['Resource'] == '*'
    arn = 'arn:aws:ec2:us-east-1:1:instance/i-0123'
    assert ap.build_policy('ec2:TerminateInstances', arn)['Statement'][0]['Resource'] == arn


def test_sensitive_actions():
    for a in ('iam:CreateRole', 'sts:AssumeRole', 'secretsmanager:GetSecretValue', 'kms:Decrypt', 'ec2:*',
              # Credential-vending reads (2026-10-22 review)
              'secretsmanager:BatchGetSecretValue', 'ec2:GetPasswordData',
              'redshift:GetClusterCredentials', 'redshift-serverless:GetCredentials',
              'ssm:GetParameterHistory'):
        assert ap.is_sensitive(a), a
    assert not ap.is_sensitive('ec2:RunInstances')


# --- filing the request ------------------------------------------------------------------

def test_manual_by_default_with_steps(creds, test_user, clean_requests):
    req = ap.file_request(test_user.id, None, 'create_ec2_instance', {'ami_id': 'ami-1'}, DENIED_RUN, 'aws.ec2')
    ti = req.tool_input
    assert req.tool_name == ap.PERMISSION_TOOL and req.risk_level == 'high'
    assert ti['mode'] == 'manual' and ti['action'] == 'ec2:RunInstances'
    assert 'put-role-policy --role-name DevOpsAgentRole' in ti['manual']['cli']
    assert 'ec2:RunInstances' in req.risk_reason
    again = ap.file_request(test_user.id, None, 'create_ec2_instance', {'ami_id': 'ami-1'}, DENIED_RUN, 'aws.ec2')
    assert again.id == req.id, 'one pending request per missing permission'


def test_self_mode_only_when_enabled_and_never_for_sensitive(creds, test_user, clean_requests):
    creds['creds']['self_grant'] = True
    req = ap.file_request(test_user.id, None, 'create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    assert req.tool_input['mode'] == 'self'
    iam = ap.file_request(test_user.id, None, 'create_iam_role', {}, _denied('CreateRole'), 'aws.iam')
    assert iam.tool_input['action'] == 'iam:CreateRole'
    assert iam.tool_input['mode'] == 'manual' and iam.tool_input['sensitive'] is True


# --- applying it ---------------------------------------------------------------------------

def _req(test_user, ti):
    return SimpleNamespace(id=1, requester_id=test_user.id, conversation_id=None, tool_input=ti)


def test_self_grant_adds_policy_and_retries(creds, test_user, monkeypatch):
    creds['creds']['self_grant'] = True
    ti = ap.build_request(test_user.id, 'create_ec2_instance', {'ami_id': 'ami-1'}, DENIED_RUN, 'aws.ec2')
    put = []
    monkeypatch.setattr(ap, '_put_self_policy', lambda uid, principal, policy: put.append((principal['name'], policy)))
    monkeypatch.setattr(ap, 'RETRY_DELAYS', (0,))
    calls = []
    out = ap.execute_grant(_req(test_user, ti), lambda n, i: calls.append((n, i)) or {'success': True})
    assert put and put[0][0] == 'DevOpsAgentRole'
    assert calls == [('create_ec2_instance', {'ami_id': 'ami-1'})]
    assert out['success'] is True and 'DevOps Agent' in out['granted_by']


def test_self_grant_turned_off_since_is_not_applied(creds, test_user, monkeypatch):
    creds['creds']['self_grant'] = True
    ti = ap.build_request(test_user.id, 'create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    creds['creds']['self_grant'] = False
    monkeypatch.setattr(ap, '_put_self_policy', lambda *a: pytest.fail('must not edit the role'))
    monkeypatch.setattr(ap, 'RETRY_DELAYS', (0,))
    out = ap.execute_grant(_req(test_user, ti), lambda n, i: {'success': True})
    assert out['success'] is True and out['granted_by'] == 'you'


def test_sensitive_is_never_self_granted(test_user, monkeypatch, creds):
    creds['creds']['self_grant'] = True
    ti = {'mode': 'self', 'action': 'iam:CreateRole', 'policy': ap.build_policy('iam:CreateRole'),
          'original_tool': 'create_iam_role', 'original_input': {}}
    monkeypatch.setattr(ap, '_put_self_policy', lambda *a: pytest.fail('must not edit the role'))
    out = ap.execute_grant(_req(test_user, ti), lambda n, i: pytest.fail('must not retry'))
    assert out['success'] is False and 'never grants itself' in out['error']


def test_next_missing_permission_is_filed(creds, test_user, monkeypatch, clean_requests):
    ti = ap.build_request(test_user.id, 'create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    monkeypatch.setattr(ap, 'RETRY_DELAYS', (0,))
    monkeypatch.setattr(ap, 'category_of', lambda name: 'aws.ec2')
    nxt = _denied('CreateTags', code='UnauthorizedOperation')
    out = ap.execute_grant(_req(test_user, ti), lambda n, i: nxt)
    assert out['success'] is False
    assert out['next_permission_request']['missing_permission'] == 'ec2:CreateTags'
    assert 'ec2:CreateTags' in out['error']


def test_still_denied_explains(creds, test_user, monkeypatch):
    ti = ap.build_request(test_user.id, 'create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    monkeypatch.setattr(ap, 'RETRY_DELAYS', (0,))
    out = ap.execute_grant(_req(test_user, ti), lambda n, i: DENIED_RUN)
    assert out['success'] is False and 'still refuses' in out['error']


# --- wiring --------------------------------------------------------------------------------

def _fake_agent(uid, category='aws.ec2', sandbox=False):
    import logging
    return SimpleNamespace(_sandbox_mode=sandbox, _current_user_id=uid, _current_conversation_id=None,
                           tool_categories={'create_ec2_instance': category}, _pending_approval=None,
                           logger=logging.getLogger('test'))


def test_agent_turns_denial_into_request_and_card(creds, test_user, clean_requests):
    from src.agent.core import DevOpsAgent
    fake = _fake_agent(test_user.id)
    out = DevOpsAgent._maybe_request_aws_permission(fake, 'create_ec2_instance', {}, DENIED_RUN)
    note = out['_permission_request']
    assert note['missing_permission'] == 'ec2:RunInstances'
    assert fake._pending_approval['tool_name'] == ap.PERMISSION_TOOL
    assert fake._pending_approval['permission']['policy']['Statement'][0]['Action'] == ['ec2:RunInstances']


def test_agent_hook_skips_sandbox_and_other_clouds(creds, test_user):
    from src.agent.core import DevOpsAgent
    for fake in (_fake_agent(test_user.id, sandbox=True), _fake_agent(test_user.id, category='azure'),
                 _fake_agent(None)):
        assert DevOpsAgent._maybe_request_aws_permission(fake, 'create_ec2_instance', {}, DENIED_RUN) is DENIED_RUN
        assert fake._pending_approval is None


def test_the_model_cannot_ask_for_a_permission_directly():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for f in list((root / 'src' / 'tools').glob('*.py')) + [root / 'src' / 'agent' / 'core.py']:
        assert f"'{ap.PERMISSION_TOOL}'" not in f.read_text(), f'{f.name} must not register it as a tool'


def test_confirming_runs_the_grant(creds, test_user, monkeypatch, clean_requests):
    from services import approval_service
    req = ap.file_request(test_user.id, None, 'create_ec2_instance', {}, DENIED_RUN, 'aws.ec2')
    seen = []
    monkeypatch.setattr('services.aws_permissions.execute_grant',
                        lambda r, run: seen.append(r.id) or {'success': True})
    assert approval_service._execute_tool(req) == {'success': True}
    assert seen == [req.id]


def test_kimi_streaming_shows_the_card():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'src' / 'agent' / 'core.py').read_text()
    assert src.count('An AWS permission request filed by _invoke_tool') == 1


# --- the setting -----------------------------------------------------------------------------

def test_self_grant_setting_needs_role_and_boundary(app, db_session, test_user, monkeypatch):
    from models import UserCloudCredential, db
    from services import credential_service as cs
    monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY', 'test-key-for-permission-requests')
    cred = UserCloudCredential(user_id=test_user.id, cloud_provider='aws', is_active=True)
    cred.set_credentials({'access_key': 'AKIAX', 'secret_key': 's'})
    db.session.add(cred)
    db.session.commit()
    try:
        ok, msg = cs.set_aws_self_grant(test_user.id, True)
        assert not ok and 'Role ARN' in msg

        cred.set_credentials({'role_arn': 'arn:aws:iam::123456789012:role/R', 'external_id': 'x' * 8})
        db.session.commit()
        role = {'Role': {}}
        monkeypatch.setattr(cs, 'get_user_boto_client',
                            lambda uid, svc: SimpleNamespace(get_role=lambda RoleName: role))
        ok, msg = cs.set_aws_self_grant(test_user.id, True)
        assert not ok and 'permissions boundary' in msg

        role['Role'] = {'PermissionsBoundary': {'PermissionsBoundaryArn': 'arn:aws:iam::1:policy/B'}}
        assert cs.set_aws_self_grant(test_user.id, True)[0]
        assert cs.get_user_aws_credentials(test_user.id)['self_grant'] is True
        assert cs.set_aws_self_grant(test_user.id, False)[0]
        assert cs.get_user_aws_credentials(test_user.id)['self_grant'] is False
    finally:
        db.session.delete(cred)
        db.session.commit()


def test_a_refused_read_asks_for_the_service_reads_once():
    """Owner feedback (2026-10-15): checking GuardDuty took one request per API call."""
    denied = {'success': False, 'error_code': 'AccessDeniedException', 'error': (
        'User: arn:aws:sts::188046727805:assumed-role/DevOpsAgentRole/devops-agent is not '
        'authorized to perform: guardduty:ListDetectors on resource: '
        'arn:aws:guardduty:us-east-1:188046727805:detector/*')}
    d = ap.parse_denial('aws_api_read', {'service': 'guardduty'}, denied)
    policy = ap.build_policy(d['action'], d['resource'])
    assert policy['Statement'][0]['Action'] == ['guardduty:ListDetectors', 'guardduty:List*', 'guardduty:Describe*']
    assert policy['Statement'][0]['Resource'] == '*'
    get = ap.build_policy('guardduty:GetFindings')['Statement'][0]['Action']
    assert get == ['guardduty:GetFindings', 'guardduty:List*', 'guardduty:Describe*']
    assert not any(ap.is_sensitive(a) for a in get)


def test_bundles_never_widen_writes_or_identity():
    assert ap.build_policy('ec2:TerminateInstances')['Statement'][0]['Action'] == ['ec2:TerminateInstances']
    assert ap.build_policy('iam:ListRoles')['Statement'][0]['Action'] == ['iam:ListRoles']
    for a in ('ec2:*', 's3:Get*', 'iam:List*', 'secretsmanager:GetSecretValue'):
        assert ap.is_sensitive(a), a
