"""Developer API resource endpoints and the webhook list address.

`/api-gateway/v1/resources` and `/v1/resources/<id>` read `name`, `provider` and
`metadata`, which InfrastructureResource does not have, so both returned 500 for
any user with a synced resource. The developer dashboard and Webhooks pages
called `/api-gateway/api/webhooks`, which did not exist (found 2026-10-14).
"""
KEY = 'doa_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'


def _resource(user, **kw):
    from models import InfrastructureResource, db
    r = InfrastructureResource(user_id=user.id, cloud_provider='aws', resource_type='ec2',
                               resource_id='i-0test', resource_name='web-1', region='us-east-1',
                               status='running', resource_metadata={'instance_type': 't3.micro'}, **kw)
    db.session.add(r)
    db.session.commit()
    return r


def test_list_resources(client, test_api_key, test_user):
    _resource(test_user)
    resp = client.get('/api-gateway/v1/resources', headers={'X-API-Key': KEY})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    [item] = resp.get_json()['resources']
    assert item['name'] == 'web-1'
    assert item['provider'] == 'aws'
    assert item['type'] == 'ec2'


def test_get_resource(client, test_api_key, test_user):
    r = _resource(test_user)
    resp = client.get(f'/api-gateway/v1/resources/{r.id}', headers={'X-API-Key': KEY})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_json()['resource']
    assert body['resource_id'] == 'i-0test'
    assert body['metadata'] == {'instance_type': 't3.micro'}


def test_other_users_resource_is_not_found(client, test_api_key, test_user, db_session):
    from models import User, db
    other = User(username='other-dev', email='other-dev@example.com')
    other.set_password('Another1Password!')
    db.session.add(other)
    db.session.commit()
    r = _resource(other)
    resp = client.get(f'/api-gateway/v1/resources/{r.id}', headers={'X-API-Key': KEY})
    assert resp.status_code == 404


def test_webhook_list_address_exists_and_hides_secret(authenticated_client, test_user):
    from models import WebhookEndpoint, db
    db.session.add(WebhookEndpoint(user_id=test_user.id, name='ci', url='https://example.com/hook',
                                   secret='s3cret-value', events=['resource.created']))
    db.session.commit()
    resp = authenticated_client.get('/api-gateway/api/webhooks')
    assert resp.status_code == 200
    [hook] = resp.get_json()['webhooks']
    assert hook['name'] == 'ci'
    assert 's3cret-value' not in resp.get_data(as_text=True)


def test_webhook_list_is_per_user(authenticated_client, test_user, db_session):
    from models import User, WebhookEndpoint, db
    other = User(username='other-hooks', email='other-hooks@example.com')
    other.set_password('Another1Password!')
    db.session.add(other)
    db.session.commit()
    db.session.add(WebhookEndpoint(user_id=other.id, name='theirs', url='https://example.com/x'))
    db.session.commit()
    assert authenticated_client.get('/api-gateway/api/webhooks').get_json()['webhooks'] == []
