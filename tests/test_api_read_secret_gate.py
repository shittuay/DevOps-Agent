"""A generic *_api_read call that returns a secret needs the same confirmation
as the dedicated tool for it, and its approved result is never stored as-is.

Until 2026-11-19, aws_api_read('secretsmanager', 'get_secret_value', ...) or
azure_api_read('storage', 'storage_accounts.list_keys', ...) ran as low risk,
with no confirmation, while get_secret_value / list_storage_account_keys were
high risk.
"""
import pytest

from src.agent.safety import SafetyValidator
from services.secret_detector import discloses_secret, escape_hatch_secret_read
from services.approval_service import stored_result
from src.agent.core import _stored_change_result


SECRET_CALLS = [
    ('aws_api_read', {'service': 'secretsmanager', 'operation': 'get_secret_value',
                      'params': {'SecretId': 'db'}}),
    ('aws_api_read', {'service': 'SSM', 'operation': 'get_parameter',
                      'params': {'Name': '/app/db', 'WithDecryption': True}}),
    ('aws_api_read', {'service': 'ssm', 'operation': 'get_parameters_by_path',
                      'params': {'Path': '/', 'WithDecryption': True}}),
    ('aws_api_read', {'service': 'sts', 'operation': 'get_session_token'}),
    ('aws_api_read', {'service': 'ecr', 'operation': 'get_authorization_token'}),
    ('aws_api_read', {'service': 'ec2', 'operation': 'get_password_data', 'params': {'InstanceId': 'i-1'}}),
    ('azure_api_read', {'client_type': 'storage', 'operation_path': 'storage_accounts.list_keys'}),
    ('azure_api_read', {'client_type': 'container',
                        'operation_path': 'managed_clusters.list_cluster_admin_credentials'}),
    ('k8s_api_read', {'api_group': 'core', 'method': 'read_namespaced_secret',
                      'params': {'name': 'db', 'namespace': 'default'}}),
    ('k8s_api_read', {'api_group': 'core', 'method': 'list_secret_for_all_namespaces'}),
]

PLAIN_READS = [
    ('aws_api_read', {'service': 'ec2', 'operation': 'describe_instances'}),
    ('aws_api_read', {'service': 'secretsmanager', 'operation': 'list_secrets'}),
    ('aws_api_read', {'service': 'ssm', 'operation': 'describe_parameters'}),
    # Without WithDecryption this is metadata; the agent resolves AMIs this way.
    # It was gated (and its result hidden as a download) from 2026-11-19 to 11-25.
    ('aws_api_read', {'service': 'ssm', 'operation': 'get_parameter',
                      'params': {'Name': '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64'}}),
    ('azure_api_read', {'client_type': 'compute', 'operation_path': 'virtual_machines.list_all'}),
    ('k8s_api_read', {'api_group': 'core', 'method': 'list_namespaced_pod', 'params': {'namespace': 'x'}}),
    ('aws_api_read', None),
]


@pytest.fixture(scope='module')
def validator():
    return SafetyValidator()


@pytest.mark.parametrize('tool,args', SECRET_CALLS)
def test_secret_reads_need_confirmation(validator, tool, args):
    result = validator.validate_tool_call(tool, args)
    assert result.requires_confirmation
    assert result.risk_level in ('high', 'critical')
    assert discloses_secret(tool, args)


@pytest.mark.parametrize('tool,args', PLAIN_READS)
def test_plain_reads_stay_low_risk(validator, tool, args):
    assert escape_hatch_secret_read(tool, args) is None
    result = validator.validate_tool_call(tool, args or {})
    assert not result.requires_confirmation
    assert result.risk_level == 'low'


def test_approved_secret_read_is_not_stored():
    args = {'service': 'ssm', 'operation': 'get_parameter', 'params': {'Name': '/db', 'WithDecryption': True}}
    raw = {'success': True, 'result': {'Parameter': {'Name': '/db', 'Value': 'hunter2-plaintext'}}}
    safe, download = stored_result('aws_api_read', raw, 5, args)
    assert 'hunter2-plaintext' not in str(safe)
    assert download and 'hunter2-plaintext' in download['content']
    assert 'hunter2-plaintext' not in str(_stored_change_result('aws_api_read', raw, args))


def test_plain_read_result_is_kept():
    args = {'service': 'ec2', 'operation': 'describe_instances'}
    raw = {'success': True, 'result': {'Reservations': [{'InstanceId': 'i-abc'}]}}
    safe, download = stored_result('aws_api_read', raw, 5, args)
    assert download is None
    assert 'i-abc' in str(safe)
