"""The developer API and MCP enforce a key's scopes and IP allow-list.

Before 2026-10-22 /api-gateway/v1's key check only looked the key up: a key created
with scopes=['read'], or used from an address outside its allow-list, could still
call /v1/execute and /v1/agent, and MCP took the same shortcut. Both also accepted
the key in the URL (?api_key=), where it lands in access logs.
"""
from types import SimpleNamespace

import pytest

from services.api_key_service import key_allows, key_grants, key_ip_allowed


def _key(*scopes, ips=None):
    return SimpleNamespace(scopes=list(scopes), allowed_ips=ips or [])


def test_scope_grants():
    assert key_grants(_key('read')) == {'read'}
    assert key_allows(_key('agent'), 'agent') and key_allows(_key('agent'), 'execute')
    assert not key_allows(_key('write'), 'agent') and key_allows(_key('write'), 'execute')
    assert key_allows(_key('admin'), 'agent')
    assert key_allows(_key('read:resources'), 'read')
    assert not key_allows(_key('read:resources'), 'execute')
    assert not key_allows(_key('anything-else'), 'read')
    assert not key_allows(_key(), 'read')


def test_ip_allow_list():
    assert key_ip_allowed(_key('read'), None)
    assert key_ip_allowed(_key('read', ips=['10.0.0.1']), '10.0.0.1')
    assert not key_ip_allowed(_key('read', ips=['10.0.0.1']), '10.0.0.2')
    assert not key_ip_allowed(_key('read', ips=['10.0.0.1']), None)


@pytest.fixture
def make_key(app, test_user, db_session):
    from models import APIKey, db
    made = []

    def _make(scopes, ips=None, suffix='a'):
        plain = f'doa_scope_test_{suffix}_{"x" * 24}'
        row = APIKey(user_id=test_user.id, name=f'scope {suffix}', key_prefix=plain[:8],
                     key_hash=APIKey.hash_key(plain), scopes=scopes, allowed_ips=ips or [])
        db.session.add(row)
        db.session.commit()
        made.append(row.id)
        return plain

    yield _make
    for key_id in made:
        row = APIKey.query.get(key_id)
        if row:
            db.session.delete(row)
    db.session.commit()


def test_read_key_cannot_execute_or_chat(client, make_key):
    key = make_key(['read'], suffix='r')
    h = {'X-API-Key': key}
    assert client.get('/api-gateway/v1/tools', headers=h).status_code != 403
    for path in ('/api-gateway/v1/execute', '/api-gateway/v1/agent', '/api-gateway/v1/agent/stream'):
        resp = client.post(path, headers=h, json={'tool': 'list_ec2_instances', 'message': 'hi'})
        assert resp.status_code == 403, (path, resp.status_code)


def test_key_outside_its_ip_allow_list_is_refused(client, make_key):
    key = make_key(['admin'], ips=['203.0.113.9'], suffix='ip')
    resp = client.get('/api-gateway/v1/tools', headers={'X-API-Key': key},
                      environ_base={'REMOTE_ADDR': '198.51.100.1'})
    assert resp.status_code == 403


def test_key_in_the_url_is_refused(client, make_key):
    key = make_key(['admin'], suffix='q')
    resp = client.get(f'/api-gateway/v1/tools?api_key={key}')
    assert resp.status_code == 401
    assert 'header' in resp.get_json()['error']


def test_bearer_header_works(client, make_key):
    key = make_key(['admin'], suffix='b')
    resp = client.get('/api-gateway/v1/tools', headers={'Authorization': f'Bearer {key}'})
    assert resp.status_code not in (401, 403)


def test_mcp_refuses_read_keys_and_url_keys(app, make_key):
    from routes import mcp
    read_key = make_key(['read'], suffix='mr')
    agent_key = make_key(['agent'], suffix='ma')
    with app.test_request_context('/mcp', headers={'Authorization': f'Bearer {read_key}'}):
        assert mcp._authenticate() is None
    with app.test_request_context(f'/mcp?api_key={agent_key}'):
        assert mcp._authenticate() is None
    with app.test_request_context('/mcp', headers={'Authorization': f'Bearer {agent_key}'}):
        assert mcp._authenticate() is not None


def test_every_gateway_key_route_names_a_capability():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'routes' / 'api_gateway.py').read_text()
    assert '@api_key_required\n' not in src
    assert "request.args.get('api_key')" in src  # only to explain the refusal
    assert "or request.args.get('api_key')" not in src
