"""Kubernetes tools reach the signed-in user's own EKS clusters, never the server's kubeconfig."""
import base64
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import boto3
import pytest
from kubernetes import client
from kubernetes.client.rest import ApiException

from src.tools import k8s_access
from src.tools import kubernetes_tools as kt
from src.tools.k8s_access import ClusterAccessError

CA_PEM = b'-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----\n'
ENDPOINT = 'https://ABCDEF0123456789.gr7.us-east-1.eks.amazonaws.com'


class FakePaginator:
    def __init__(self, names):
        self.names = names

    def paginate(self):
        return [{'clusters': self.names}]


class FakeEks:
    def __init__(self, names=('prod',), cluster=None):
        self.names = list(names)
        self.describe_calls = 0
        self.cluster = cluster or {
            'status': 'ACTIVE',
            'endpoint': ENDPOINT,
            'certificateAuthority': {'data': base64.b64encode(CA_PEM).decode()},
            'resourcesVpcConfig': {'endpointPublicAccess': True},
        }

    def get_paginator(self, name):
        assert name == 'list_clusters'
        return FakePaginator(self.names)

    def describe_cluster(self, name):
        self.describe_calls += 1
        return {'cluster': self.cluster}


def _real_sts(region='us-east-1', **kwargs):
    return boto3.client('sts', region_name=region, aws_access_key_id='AKIAEXAMPLE',
                        aws_secret_access_key='secret', **kwargs)


@pytest.fixture
def eks_user(monkeypatch):
    monkeypatch.delenv(k8s_access.LOCAL_KUBECONFIG_ENV, raising=False)
    k8s_access._cache.clear()
    eks = FakeEks()
    sts_calls = []

    def fake_boto(user_id, service, region, **kwargs):
        assert user_id == 7
        if service == 'eks':
            return eks
        if service == 'sts':
            sts_calls.append(kwargs)
            return _real_sts(region, **kwargs)
        raise AssertionError(service)

    monkeypatch.setattr(k8s_access, '_user_id', lambda: 7)
    monkeypatch.setattr(k8s_access, '_boto', fake_boto)
    monkeypatch.setattr(k8s_access, '_default_region', lambda region: region or 'us-east-1')
    yield eks, sts_calls
    k8s_access._cache.clear()


def test_parse_context_forms():
    assert k8s_access.parse_context(None) == (None, None)
    assert k8s_access.parse_context('prod') == (None, 'prod')
    assert k8s_access.parse_context('us-west-2/prod-1') == ('us-west-2', 'prod-1')
    assert k8s_access.parse_context(
        'arn:aws:eks:eu-west-1:123456789012:cluster/web') == ('eu-west-1', 'web')
    for bad in ('../etc', 'nope/prod', 'a b', 'https://evil.example'):
        with pytest.raises(ClusterAccessError):
            k8s_access.parse_context(bad)


def test_token_is_a_presigned_sts_url_that_signs_the_cluster_name():
    token = k8s_access.eks_token(_real_sts(endpoint_url='https://sts.us-east-1.amazonaws.com'), 'prod')
    assert token.startswith('k8s-aws-v1.')
    encoded = token[len('k8s-aws-v1.'):]
    url = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == 'sts.us-east-1.amazonaws.com'
    assert query['Action'] == ['GetCallerIdentity']
    assert 'x-k8s-aws-id' in query['X-Amz-SignedHeaders'][0].split(';')


def test_no_signed_in_user_fails_closed_without_reading_server_kubeconfig(monkeypatch):
    monkeypatch.delenv(k8s_access.LOCAL_KUBECONFIG_ENV, raising=False)
    monkeypatch.setattr(k8s_access, '_user_id', lambda: None)

    def forbidden(*args, **kwargs):
        raise AssertionError('server kubeconfig must not be read')

    monkeypatch.setattr(k8s_access.config, 'new_client_from_config', forbidden)
    monkeypatch.setattr(k8s_access.config, 'load_kube_config', forbidden)
    with pytest.raises(ClusterAccessError, match='K8S_USE_LOCAL_KUBECONFIG'):
        k8s_access.api_client(None)
    result = kt.get_pods()
    assert result['success'] is False and 'connected AWS account' in result['error']


def test_self_hosted_opt_in_uses_local_kubeconfig(monkeypatch):
    monkeypatch.setenv(k8s_access.LOCAL_KUBECONFIG_ENV, 'true')
    seen = {}

    def fake_new_client(context=None):
        seen['context'] = context
        return client.ApiClient(client.Configuration())

    monkeypatch.setattr(k8s_access.config, 'new_client_from_config', fake_new_client)
    k8s_access.api_client('kind-dev')
    assert seen['context'] == 'kind-dev'


def test_eks_client_uses_the_users_cluster_and_leaves_global_config_alone(eks_user):
    eks, sts_calls = eks_user
    default_host = client.Configuration.get_default_copy().host
    api = k8s_access.api_client(None)
    cfg = api.configuration
    assert cfg.host == ENDPOINT
    assert cfg.verify_ssl is True
    assert Path(cfg.ssl_ca_cert).read_bytes() == CA_PEM
    assert cfg.api_key['authorization'].startswith('k8s-aws-v1.')
    assert cfg.api_key_prefix['authorization'] == 'Bearer'
    assert sts_calls == [{'endpoint_url': 'https://sts.us-east-1.amazonaws.com'}]
    assert client.Configuration.get_default_copy().host == default_host

    k8s_access.api_client('prod')
    assert eks.describe_calls == 1, 'token and endpoint are cached between calls'


def test_cluster_choice_is_explicit_when_ambiguous(eks_user):
    eks, _ = eks_user
    eks.names = ['a', 'b']
    with pytest.raises(ClusterAccessError, match='2 EKS clusters in us-east-1: a, b'):
        k8s_access.api_client(None)
    eks.names = []
    with pytest.raises(ClusterAccessError, match='No EKS clusters found'):
        k8s_access.api_client(None)
    assert k8s_access.api_client('b').configuration.host == ENDPOINT


@pytest.mark.parametrize('change, message', [
    ({'resourcesVpcConfig': {'endpointPublicAccess': False}}, 'private API endpoint'),
    ({'endpoint': 'https://169.254.169.254'}, 'unexpected API endpoint'),
    ({'status': 'CREATING'}, 'CREATING'),
])
def test_unusable_clusters_are_refused(eks_user, change, message):
    eks, _ = eks_user
    eks.cluster.update(change)
    with pytest.raises(ClusterAccessError, match=message):
        k8s_access.api_client('prod')


def test_tools_bind_every_api_group_to_the_call_client(monkeypatch):
    api = client.ApiClient(client.Configuration())
    monkeypatch.setattr(kt.k8s_access, 'api_client', lambda context=None: api)
    v1, apps = kt._get_k8s_client('prod')
    assert v1.api_client is api and apps.api_client is api
    assert kt._k8s_api_client() is api


def test_source_never_uses_the_process_wide_kubernetes_config():
    source = Path(kt.__file__).read_text()
    assert 'load_kube_config(' not in source
    assert not re.search(r'\b(client|k8s_client)\.[A-Za-z0-9]+Api\(\)', source)
    assert 'ApiClient()' not in source
    assert 'getattr(client, api_cls_name)()' not in source


def test_thread_local_client_does_not_leak_between_threads(monkeypatch):
    clients = {}

    def make(context=None):
        return client.ApiClient(client.Configuration())

    monkeypatch.setattr(kt.k8s_access, 'api_client', make)

    def run(name):
        kt._get_k8s_client(name)
        clients[name] = kt._k8s_api_client()

    threads = [threading.Thread(target=run, args=(n,)) for n in ('a', 'b')]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert clients['a'] is not clients['b']


def test_refused_call_gets_an_access_entry_hint(monkeypatch):
    def unauthorized(context=None):
        raise ApiException(status=401, reason='Unauthorized')

    monkeypatch.setattr(kt, '_get_k8s_client', unauthorized)
    monkeypatch.setattr(k8s_access, 'local_kubeconfig_enabled', lambda: False)
    monkeypatch.setattr(k8s_access, '_user_id', lambda: 7)
    monkeypatch.setattr(k8s_access, 'resolve_cluster', lambda context: ('us-east-1', 'prod'))
    monkeypatch.setattr(k8s_access, '_principal_arn',
                        lambda user_id, region: 'arn:aws:iam::123456789012:role/DevOpsAgentRole')
    handler = next(t['handler'] for t in kt.get_tools() if t['name'] == 'get_pods')
    result = handler(namespace='default', context='prod')
    assert result['status_code'] == 401
    assert 'create_eks_access_entry' in result['hint']
    assert 'arn:aws:iam::123456789012:role/DevOpsAgentRole' in result['hint']
    assert 'AmazonEKSViewPolicy' in result['hint']


def test_every_context_parameter_explains_eks_clusters():
    for tool in kt.get_tools():
        prop = tool['input_schema'].get('properties', {}).get('context')
        if prop is not None:
            assert prop['description'] == k8s_access.CONTEXT_DESCRIPTION, tool['name']


def test_list_contexts_lists_eks_clusters(eks_user):
    eks, _ = eks_user
    eks.names = ['web', 'api']
    result = kt.list_contexts()
    assert result['source'] == 'eks'
    assert [c['name'] for c in result['contexts']] == ['us-east-1/api', 'us-east-1/web']
