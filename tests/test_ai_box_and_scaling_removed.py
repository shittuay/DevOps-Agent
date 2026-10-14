"""The AI Infrastructure plain-English box works, and Predictive Scaling is gone.

/ai/api/parse called a method the service never had (parse_natural_language), and the
pages sent a `query` field the route rejected, so the box always failed. Eight sibling
endpoints called methods that didn't exist either; /ai/api/analyze-drift returned
"No drift detected" without reading any account. The generated Terraform hardcoded an
old AMI id and printed invented monthly prices.

Predictive Scaling (/scaling) was removed (2026-10-14): nothing ever fed it metrics, so it
was always empty.
"""
import importlib

import pytest


def _parse(client, text, **extra):
    return client.post('/ai/api/parse', json={'query': text, **extra})


def test_box_generates_terraform_for_several_resources(authenticated_client):
    resp = _parse(authenticated_client, 'Create 3 small servers and a database named shop in us west')
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    tf = data['terraform']

    assert set(data['intent']['actions']) == {'create_server', 'create_database'}
    assert tf.count('resource "aws_instance"') == 3
    assert 'resource "aws_db_instance"' in tf
    assert 'region = "us-west-2"' in tf
    assert 'instance_type = "t3.micro"' in tf


def test_terraform_never_hardcodes_an_ami_or_password(authenticated_client):
    tf = _parse(authenticated_client, 'create a server and a database').get_json()['terraform']
    assert 'data "aws_ami" "ubuntu"' in tf
    assert 'owners      = ["099720109477"]' in tf, "Ubuntu images must come from Canonical's account"
    assert 'ami-' not in tf
    assert 'manage_master_user_password = true' in tf
    assert 'password ' not in tf.replace('manage_master_user_password', '')
    assert 'publicly_accessible         = false' in tf


def test_bucket_blocks_public_access(authenticated_client):
    tf = _parse(authenticated_client, 'create a bucket named logs').get_json()['terraform']
    assert 'resource "aws_s3_bucket_public_access_block"' in tf
    assert 'block_public_policy     = true' in tf


def test_no_invented_prices(authenticated_client):
    data = _parse(authenticated_client, 'create a large server').get_json()
    assert 'estimated_cost' not in data
    assert 'estimated_cost' not in data['spec']
    assert '$' not in data['terraform']


@pytest.mark.parametrize('body,status', [
    ({'query': ''}, 400),
    ({'query': 'tell me a joke'}, 422),
    ({'query': 'create a server', 'cloud_provider': 'azure'}, 422),
])
def test_bad_requests_get_a_clear_error(authenticated_client, body, status):
    resp = authenticated_client.post('/ai/api/parse', json=body)
    assert resp.status_code == status
    assert resp.get_json()['error']


def test_old_request_field_still_accepted(authenticated_client):
    resp = authenticated_client.post('/ai/api/parse', json={'request': 'create a vpc'})
    assert resp.status_code == 200
    assert 'resource "aws_vpc"' in resp.get_json()['terraform']


@pytest.mark.parametrize('path', [
    '/ai/api/generate-terraform', '/ai/api/generate-cloudformation', '/ai/api/estimate-cost',
    '/ai/api/validate', '/ai/api/deploy', '/ai/api/explain', '/ai/api/convert',
    '/ai/api/analyze-drift', '/ai/api/security-scan',
])
def test_broken_ai_endpoints_are_gone(authenticated_client, path):
    assert authenticated_client.post(path, json={}).status_code in (404, 405)


def test_provision_page_promises_only_what_it_does(authenticated_client):
    html = authenticated_client.get('/ai/provision').get_data(as_text=True)
    assert 'Estimated Monthly Cost' not in html
    assert 'deployInfra' not in html
    assert 'CloudFormation' not in html


def test_fake_execute_request_is_gone():
    from services.ai_infrastructure import AIInfrastructureService
    assert not hasattr(AIInfrastructureService, 'execute_request'), (
        "execute_request logged 'All resources provisioned successfully' without calling any cloud API"
    )


def test_scaling_route_is_gone(authenticated_client):
    assert authenticated_client.get('/scaling/').status_code == 404


@pytest.mark.parametrize('module', ['routes.scaling', 'services.predictive_scaling'])
def test_scaling_modules_are_gone(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)


@pytest.mark.parametrize('path', ['/chat', '/dashboard', '/ai/'])
def test_nothing_links_to_scaling(authenticated_client, path):
    resp = authenticated_client.get(path, follow_redirects=True)
    assert resp.status_code == 200
    assert "'/scaling'" not in resp.get_data(as_text=True)
    assert 'href="/scaling' not in resp.get_data(as_text=True)
