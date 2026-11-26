"""The generic read escape hatches run without a confirmation prompt, so they must not
return secret values (2026-11-17 scheduled review)."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.parametrize('service,operation,params', [
    ('secretsmanager', 'get_secret_value', {'SecretId': 'prod/db'}),
    ('SecretsManager', 'GET_SECRET_VALUE', {'SecretId': 'prod/db'}),
    ('secretsmanager', 'batch_get_secret_value', {}),
    ('ssm', 'get_parameter', {'Name': '/db/pw', 'WithDecryption': True}),
    ('ssm', 'get_parameters_by_path', {'Path': '/', 'WithDecryption': True}),
    ('ec2', 'get_password_data', {'InstanceId': 'i-1'}),
    ('sts', 'get_session_token', {}),
    ('ecr', 'get_authorization_token', {}),
    ('redshift', 'get_cluster_credentials', {}),
])
def test_aws_api_read_refuses_secret_reads(service, operation, params):
    from src.tools import aws_tools
    with patch.object(aws_tools, '_get_boto_client') as get_client:
        result = aws_tools.aws_api_read(service, operation, params)
    assert result['success'] is False
    assert 'console' in result['error']
    get_client.assert_not_called()


def test_aws_api_read_still_allows_metadata_reads():
    from src.tools import aws_tools
    client = MagicMock()
    client.get_parameter.return_value = {'Parameter': {'Name': '/app/region', 'Value': 'us-east-1'}}
    client.describe_secret.return_value = {'Name': 'prod/db'}
    with patch.object(aws_tools, '_get_boto_client', return_value=client):
        assert aws_tools.aws_api_read('ssm', 'get_parameter', {'Name': '/app/region'})['success']
        assert aws_tools.aws_api_read('secretsmanager', 'describe_secret', {'SecretId': 'x'})['success']


@pytest.mark.parametrize('op', [
    'storage_accounts.list_keys', 'storage_accounts.list_account_sas',
    'storage_accounts.list_service_sas', 'managed_clusters.list_cluster_admin_credentials',
])
def test_azure_api_read_refuses_key_reads(op):
    from src.tools import azure_tools
    with patch.object(azure_tools, '_azure_execute') as execute:
        result = azure_tools.azure_api_read('storage', op, {})
    assert result['success'] is False
    assert 'portal' in result['error']
    execute.assert_not_called()


def test_azure_api_read_still_allows_listing_accounts():
    from src.tools import azure_tools
    with patch.object(azure_tools, '_azure_execute', return_value=[{'name': 'acct'}]):
        assert azure_tools.azure_api_read('storage', 'storage_accounts.list', {})['success']


def test_k8s_api_read_redacts_secret_data():
    from src.tools import kubernetes_tools as k
    secret_list = MagicMock()
    secret_list.to_dict.return_value = {'items': [
        {'metadata': {'name': 'db'}, 'type': 'Opaque',
         'data': {'password': 'aHVudGVyMg=='}, 'string_data': None},
    ]}
    api = MagicMock()
    api.list_namespaced_secret.return_value = secret_list
    with patch.object(k, '_get_k8s_client'), patch.object(k, '_k8s_api_client'), \
            patch.object(k.client, 'CoreV1Api', return_value=api):
        result = k.k8s_api_read('core', 'list_namespaced_secret', {'namespace': 'default'})
    assert result['success']
    item = result['result']['items'][0]
    assert item['data'] == {'password': '[REDACTED]'}
    assert item['metadata']['name'] == 'db'
    assert 'aHVudGVyMg' not in str(result)


def test_k8s_api_read_redacts_single_secret():
    from src.tools import kubernetes_tools as k
    secret = MagicMock()
    secret.to_dict.return_value = {'metadata': {'name': 'tls'}, 'data': {'tls.key': 'LS0t'}}
    api = MagicMock()
    api.read_namespaced_secret.return_value = secret
    with patch.object(k, '_get_k8s_client'), patch.object(k, '_k8s_api_client'), \
            patch.object(k.client, 'CoreV1Api', return_value=api):
        result = k.k8s_api_read('core', 'read_namespaced_secret', {'name': 'tls', 'namespace': 'x'})
    assert result['result']['data'] == {'tls.key': '[REDACTED]'}
