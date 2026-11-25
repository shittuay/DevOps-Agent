"""The *_api_read escape hatches run without confirmation, so they must refuse
operations that return secret values or mint credentials (2026-11-16 review)."""
from unittest.mock import patch

import pytest

from src.tools import aws_tools, azure_tools, kubernetes_tools


@pytest.mark.parametrize('service,operation,params', [
    ('secretsmanager', 'get_secret_value', {'SecretId': 'x'}),
    ('SecretsManager', 'GET_SECRET_VALUE', {'SecretId': 'x'}),
    ('sts', 'get_session_token', {}),
    ('ecr', 'get_authorization_token', {}),
    ('redshift', 'get_cluster_credentials', {}),
    ('ec2', 'get_password_data', {'InstanceId': 'i-1'}),
    ('lightsail', 'get_instance_access_details', {}),
    ('appsync', 'list_api_keys', {'apiId': 'a'}),
    ('ssm', 'get_parameter', {'Name': 'p', 'WithDecryption': True}),
    ('ssm', 'get_parameters_by_path', {'Path': '/', 'WithDecryption': True}),
    ('apigateway', 'get_api_keys', {'includeValues': True}),
    ('glue', 'get_connection', {'Name': 'c'}),
])
def test_aws_read_refuses_secret_operations(service, operation, params):
    with patch.object(aws_tools, '_get_boto_client') as get_client:
        result = aws_tools.aws_api_read(service, operation, params)
    assert result['success'] is False
    assert result['error_code'] == 'SecretDisclosureRefused'
    get_client.assert_not_called()


@pytest.mark.parametrize('service,operation,params', [
    ('ssm', 'get_parameter', {'Name': 'p'}),
    ('glue', 'get_connection', {'Name': 'c', 'HidePassword': True}),
    ('secretsmanager', 'list_secrets', {}),
    ('kms', 'list_keys', {}),
    ('iam', 'list_access_keys', {}),
    ('ec2', 'describe_instances', {}),
])
def test_aws_read_allows_metadata(service, operation, params):
    assert aws_tools._secret_read_refusal(service, operation, params) is None


@pytest.mark.parametrize('op', [
    'storage_accounts.list_keys',
    'managed_clusters.list_cluster_admin_credentials',
    'managed_clusters.get_access_profile',
    'web_apps.list_application_settings',
    'web_apps.begin_list_publishing_credentials',
    'web_apps.list_connection_strings',
    'registries.list_credentials',
    'database_accounts.list_keys',
    'storage_accounts.list_account_sas',
])
def test_azure_read_refuses_secret_operations(op):
    with patch.object(azure_tools, '_azure_execute') as execute:
        result = azure_tools.azure_api_read('storage', op, {})
    assert result['success'] is False
    assert result['error_code'] == 'SecretDisclosureRefused'
    execute.assert_not_called()


@pytest.mark.parametrize('op', [
    'virtual_machines.list_all', 'storage_accounts.get_properties',
    'ssh_public_keys.list', 'vaults.list_by_resource_group',
])
def test_azure_read_allows_metadata(op):
    assert not azure_tools._is_azure_secret_read(op)


@pytest.mark.parametrize('method,params', [
    ('read_namespaced_secret', {'name': 's', 'namespace': 'default'}),
    ('list_namespaced_secret', {'namespace': 'default'}),
    ('list_secret_for_all_namespaces', {}),
    ('list_cluster_custom_object', {'plural': 'secrets'}),
])
def test_k8s_read_refuses_secrets(method, params):
    with patch.object(kubernetes_tools, '_get_k8s_client') as get_client:
        result = kubernetes_tools.k8s_api_read('core', method, params)
    assert result['success'] is False
    assert result['error_code'] == 'SecretDisclosureRefused'
    get_client.assert_not_called()


def test_k8s_read_allows_other_reads():
    assert not kubernetes_tools._is_k8s_secret_read('list_namespaced_config_map', {})
    assert not kubernetes_tools._is_k8s_secret_read('list_namespaced_pod', {})
