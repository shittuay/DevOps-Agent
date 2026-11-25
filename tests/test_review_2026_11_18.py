"""2026-11-18 scheduled review: the generic read tools must not return secrets, and a
failed login must not reveal whether the account exists."""
from unittest.mock import patch

import pytest

from src.tools import aws_tools, azure_tools, kubernetes_tools


@pytest.mark.parametrize('op,params', [
    ('get_secret_value', {'SecretId': 'x'}),
    ('batch_get_secret_value', {}),
    ('get_password_data', {'InstanceId': 'i-1'}),
    ('get_authorization_token', {}),
    ('get_session_token', {}),
    ('get_federation_token', {'Name': 'x'}),
    ('get_cluster_credentials', {}),
    ('get_role_credentials', {}),
    ('get_instance_access_details', {}),
    ('get_relational_database_master_user_password', {}),
    ('get_parameter', {'Name': '/db/pw', 'WithDecryption': True}),
    ('get_parameters_by_path', {'Path': '/', 'WithDecryption': True}),
])
def test_aws_api_read_refuses_secret_reads(op, params):
    with patch.object(aws_tools, '_get_boto_client') as client:
        result = aws_tools.aws_api_read('x', op, params)
    assert result['success'] is False
    assert 'secret' in result['error']
    client.assert_not_called()


@pytest.mark.parametrize('op,params', [
    ('get_parameter', {'Name': '/aws/service/ami'}),
    ('get_credential_report', {}),
    ('get_account_password_policy', {}),
    ('list_secrets', {}),
    ('describe_instances', {}),
])
def test_aws_api_read_still_allows_metadata(op, params):
    assert not aws_tools._aws_read_discloses_secret(op, params)


@pytest.mark.parametrize('op', [
    'storage_accounts.list_keys', 'registries.list_credentials',
    'managed_clusters.list_cluster_admin_credentials',
    'web_apps.list_publishing_credentials', 'web_apps.list_application_settings',
    'web_apps.list_connection_strings', 'storage_accounts.list_account_sas',
    'database_accounts.list_keys', 'redis.list_keys',
])
def test_azure_api_read_refuses_secret_reads(op):
    with patch.object(azure_tools, '_azure_execute') as execute:
        result = azure_tools.azure_api_read('storage', op, {})
    assert result['success'] is False
    execute.assert_not_called()


def test_azure_api_read_allows_plain_reads():
    for op in ('virtual_machines.list_all', 'storage_accounts.get_properties',
               'ssh_public_keys.list'):
        assert not azure_tools._is_azure_secret_read(op)


def test_k8s_secret_values_are_stripped():
    result = {'items': [{
        'metadata': {'name': 'db', 'annotations': {
            kubernetes_tools._LAST_APPLIED: '{"data":{"password":"c2VjcmV0"}}', 'team': 'x'}},
        'type': 'Opaque',
        'data': {'password': 'c2VjcmV0'},
        'string_data': {'token': 'plain'},
    }]}
    out = kubernetes_tools._without_secret_data(result)
    item = out['items'][0]
    assert item['data'] == {'password': '[REDACTED]'}
    assert item['string_data'] == {'token': '[REDACTED]'}
    assert item['metadata']['annotations'][kubernetes_tools._LAST_APPLIED] == '[REDACTED]'
    assert item['metadata']['annotations']['team'] == 'x'
    assert 'c2VjcmV0' not in str(out)

    single = kubernetes_tools._without_secret_data({'metadata': {}, 'data': {'k': 'v'}})
    assert single['data'] == {'k': '[REDACTED]'}


def test_failed_login_message_same_for_known_and_unknown_account():
    import inspect
    from routes import auth
    src = inspect.getsource(auth.login)
    assert 'attempts remaining' not in src
