"""Approved-action results are stored and shown redacted; new keys are a one-time download.

Before 2026-10-22 an approved create_ec2_keypair or get_secret_value saved its raw
result to ApprovalRequest.execution_result and into the chat as JSON, and every
reviewer's page returned it through to_dict(). The secret detector also matched only
a private key's BEGIN line, and none of its labelled patterns matched JSON's quoted
form ("SecretAccessKey": "..."), so redaction would not have caught it either.
"""
import json
import os

import pytest

from services.secret_detector import redact_secrets, redact_structure
from tests.test_approval_self_confirm import _login, people  # noqa: F401

PEM = ('-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEAuniquebodyline1\nuniquebodyline2zzzz\n'
       '-----END RSA PRIVATE KEY-----')
AWS_SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'


def test_private_key_body_is_redacted():
    out = redact_secrets(f"key: {PEM} done")
    assert 'uniquebodyline' not in out
    assert out.endswith(' done')


def test_unterminated_private_key_is_redacted_to_the_end():
    out = redact_secrets(PEM.split('-----END')[0])
    assert 'uniquebodyline' not in out


def test_json_quoted_labels_are_redacted():
    text = json.dumps({'SecretAccessKey': AWS_SECRET, 'db_password': 'hunter2hunter2',
                       'client_secret': 'a' * 32})
    out = redact_secrets(text)
    assert AWS_SECRET not in out and 'hunter2hunter2' not in out and 'a' * 32 not in out


def test_overlapping_matches_do_not_corrupt_text():
    out = redact_secrets('postgres://user:password=abcdefghij@host/db')
    assert 'abcdefghij' not in out and out.endswith('@host/db')


def test_redact_structure_masks_credential_fields_but_not_names():
    out = redact_structure({
        'secret_access_key': AWS_SECRET, 'private_key': PEM, 'secret_name': 'prod-db',
        'NextToken': 'abc', 'items': [{'Password': 'x'}],
    })
    assert out['secret_access_key'] == '[REDACTED]'
    assert out['private_key'] == '[REDACTED]'
    assert out['secret_name'] == 'prod-db'
    assert out['NextToken'] == 'abc'
    assert out['items'][0]['Password'] == '[REDACTED]'


def _keypair_result():
    return {'success': True, 'key_name': 'k1', 'private_key': PEM,
            'message': 'Key pair k1 created',
            'download_file': {'filename': 'k1.pem', 'content': PEM,
                              'content_type': 'application/x-pem-file'}}


def test_stored_result_keeps_the_key_out_and_offers_a_download():
    from services.approval_service import stored_result
    safe, download = stored_result('create_ec2_keypair', _keypair_result(), 7)
    assert 'uniquebodyline' not in json.dumps(safe)
    assert safe['download_file'] == {'filename': 'k1.pem', 'ready_for_download': True}
    assert download['content'] == PEM and download['filename'] == 'k1.pem'


def test_stored_result_for_a_secret_value_tool_withholds_the_value():
    from services.approval_service import stored_result
    safe, download = stored_result('get_secret_value', {
        'success': True, 'secret_name': 'api', 'value': 'plain-text-value-123'}, 3)
    assert 'plain-text-value-123' not in json.dumps(safe)
    assert 'plain-text-value-123' in download['content']


def test_ordinary_results_have_no_download():
    from services.approval_service import stored_result
    safe, download = stored_result('terminate_ec2_instance', {'success': True, 'message': 'ok'}, 1)
    assert download is None and safe == {'success': True, 'message': 'ok'}


@pytest.fixture
def keypair_tool(monkeypatch):
    from services import approval_service
    if not os.environ.get('CREDENTIAL_ENCRYPTION_KEY'):
        monkeypatch.setenv('SECRET_KEY', os.environ.get('SECRET_KEY') or 'test-secret-key')
    monkeypatch.setattr(approval_service, '_execute_tool', lambda req: _keypair_result())


def _keypair_request(user):
    from services.approval_service import create_request
    return create_request(tool_name='create_ec2_keypair', tool_input={'key_name': 'k1'},
                          risk_level='high', risk_reason='This will create a key pair',
                          requester_id=user.id)


def test_confirmed_keypair_is_redacted_everywhere_and_downloads_once(app, people, keypair_tool):
    from models import ApprovalRequest, ChatMessage
    user = people['solo']
    req = _keypair_request(user)
    client = _login(app, user.email)

    assert client.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 200
    row = ApprovalRequest.query.get(req.id)
    assert row.status == 'executed'
    assert 'uniquebodyline' not in json.dumps(row.execution_result)
    assert row.download_payload and 'uniquebodyline' not in row.download_payload  # encrypted
    for m in ChatMessage.query.filter_by(user_id=user.id).all():
        assert 'uniquebodyline' not in (m.content or '')

    status = client.get(f'/api/approvals/{req.id}/status').get_json()
    assert 'uniquebodyline' not in json.dumps(status)
    assert status['can_download'] is True

    first = client.get(status['download_url'])
    assert first.status_code == 200 and b'uniquebodyline1' in first.data
    assert 'attachment' in first.headers['Content-Disposition']
    assert client.get(status['download_url']).status_code == 404


def test_only_the_requester_can_download(app, people, keypair_tool):
    req = _keypair_request(people['solo'])
    _login(app, people['solo'].email).post(f'/api/approvals/{req.id}/confirm', json={})
    other = _login(app, people['stranger'].email)
    assert other.get(f'/api/approvals/{req.id}/download').status_code == 404


def test_to_dict_masks_credentials_in_tool_input(app, people):
    from services.approval_service import create_request
    req = create_request(tool_name='create_secret', tool_input={'name': 'db', 'secret_value': 'p@ss-123456'},
                         risk_level='medium', risk_reason='r', requester_id=people['solo'].id)
    d = req.to_dict()
    assert d['tool_input']['secret_value'] == '[REDACTED]'
    assert req.tool_input['secret_value'] == 'p@ss-123456'  # the stored call still runs as asked


def test_change_rows_store_a_redacted_result():
    from src.agent.core import _stored_change_result
    out = _stored_change_result('create_ec2_keypair', _keypair_result())
    assert 'uniquebodyline' not in json.dumps(out)
    out = _stored_change_result('create_iam_access_key', {
        'success': True, 'secret_access_key': AWS_SECRET, 'message': 'created'})
    assert AWS_SECRET not in json.dumps(out)
