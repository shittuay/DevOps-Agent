"""One developer API (2026-10-14).

/api-gateway/v1 now serves everything /api/v1 offered that it didn't, with the same
handlers and key check. /api/v1 keeps working until its Sunset date and says so on
every response.
"""
KEY = 'doa_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
H = {'X-API-Key': KEY}


def test_every_parity_route_is_registered(app):
    from routes.api_gateway import V1_PARITY_ROUTES
    rules = {(r.rule, m) for r in app.url_map.iter_rules() for m in r.methods}
    for path, method, *_ in V1_PARITY_ROUTES:
        assert ('/api-gateway' + path, method) in rules, path


def test_me_and_preferences(client, test_api_key, test_user):
    me = client.get('/api-gateway/v1/me', headers=H)
    assert me.status_code == 200, me.get_data(as_text=True)[:300]
    assert client.get('/api-gateway/v1/me/preferences', headers=H).status_code == 200


def test_conversation_lifecycle(client, test_api_key, test_user):
    created = client.post('/api-gateway/v1/conversations', headers=H, json={'title': 'x'})
    assert created.status_code in (200, 201), created.get_data(as_text=True)[:300]
    body = created.get_json()
    cid = (body.get('conversation') or body).get('id')
    assert client.get(f'/api-gateway/v1/conversations/{cid}', headers=H).status_code == 200
    assert client.delete(f'/api-gateway/v1/conversations/{cid}', headers=H).status_code in (200, 204)


def test_key_is_required(client):
    assert client.get('/api-gateway/v1/me').status_code == 401


def test_openapi_lists_real_routes(client):
    spec = client.get('/api-gateway/v1/openapi.json').get_json()
    assert spec['servers'] == [{'url': '/api-gateway/v1'}]
    for path in ('/me', '/conversations/{conversation_id}', '/agent', '/execute', '/security/findings'):
        assert path in spec['paths'], path
    assert 'delete' in spec['paths']['/conversations/{conversation_id}']


def test_api_v1_is_marked_deprecated(client, test_api_key):
    resp = client.get('/api/v1/auth/me', headers=H)
    assert resp.headers['Deprecation'] == 'true'
    assert resp.headers['Sunset'].endswith('GMT')
    assert '</api-gateway/v1/me>; rel="successor-version"' in resp.headers['Link']
    other = client.get('/api/v1/resources', headers=H)
    assert '</api-gateway/v1/resources>' in other.headers['Link']
