"""Push notifications to the iPhone app for approval requests (services/push_service.py).

APNs is never contacted here: httpx.Client is replaced with a fake.
"""
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import g

from services import push_service as ps

PASSWORD = 'Password123!x'
TOKEN = 'ab' * 32


@pytest.fixture
def apns_env(monkeypatch):
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    monkeypatch.setenv('APNS_KEY', pem)
    monkeypatch.setenv('APNS_KEY_ID', 'KEY1234567')
    monkeypatch.setenv('APNS_TEAM_ID', 'TEAM123456')
    monkeypatch.setenv('APNS_BUNDLE_ID', 'io.devopsagent.app')
    ps._jwt_cache.clear()


class _Resp:
    def __init__(self, status, reason=None):
        self.status_code = status
        self._reason = reason

    def json(self):
        return {'reason': self._reason} if self._reason else {}


class _FakeClient:
    sent = []
    replies = {}

    def __init__(self, **kw):
        assert kw.get('http2') is True, 'APNs requires HTTP/2'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        _FakeClient.sent.append((url, json, headers))
        token = url.rsplit('/', 1)[-1]
        return _FakeClient.replies.get(token, _Resp(200))


@pytest.fixture
def fake_apns(monkeypatch):
    import httpx
    _FakeClient.sent, _FakeClient.replies = [], {}
    monkeypatch.setattr(httpx, 'Client', _FakeClient)
    return _FakeClient


def _user(db, User, tag):
    u = User(email=f'push-{tag}@example.com', username=f'push_{tag}', email_verified=True,
             onboarding_completed=True)
    u.set_password(PASSWORD)
    db.session.add(u)
    db.session.commit()
    return u


def test_token_validation():
    assert ps.valid_token(TOKEN)
    assert not ps.valid_token('short')
    assert not ps.valid_token('zz' * 32)
    assert not ps.valid_token('')


def test_not_configured_sends_nothing(app, db_session, monkeypatch, fake_apns):
    for k in ('APNS_KEY', 'APNS_KEY_ID', 'APNS_TEAM_ID', 'APNS_BUNDLE_ID', 'APNS_KEY_PATH'):
        monkeypatch.delenv(k, raising=False)
    assert not ps.is_configured()
    assert ps.send_now([1], ps.build_payload('t', 'b')) == 0
    assert fake_apns.sent == []


def test_send_and_remove_devices_apple_says_are_gone(app, db_session, apns_env, fake_apns):
    from models import PushDevice, User, db
    tag = uuid.uuid4().hex[:8]
    user = _user(db, User, tag)
    gone = 'cd' * 32
    db.session.add_all([PushDevice(user_id=user.id, token=TOKEN),
                        PushDevice(user_id=user.id, token=gone, environment='sandbox')])
    db.session.commit()
    fake_apns.replies[gone] = _Resp(410, 'Unregistered')

    assert ps.send_now([user.id], ps.build_payload('Title', 'Body', {'approval_id': 7})) == 1
    urls = [u for u, _, _ in fake_apns.sent]
    assert f'https://api.push.apple.com/3/device/{TOKEN}' in urls
    assert f'https://api.sandbox.push.apple.com/3/device/{gone}' in urls
    _, body, headers = fake_apns.sent[0]
    assert headers['apns-topic'] == 'io.devopsagent.app'
    assert headers['authorization'].startswith('bearer ')
    assert body['aps']['alert'] == {'title': 'Title', 'body': 'Body'} and body['approval_id'] == 7
    assert PushDevice.query.filter_by(token=gone).first() is None
    assert PushDevice.query.filter_by(token=TOKEN).first() is not None
    PushDevice.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()


def test_approval_notification_never_carries_tool_arguments(monkeypatch):
    captured = {}
    monkeypatch.setattr(ps, 'send_async', lambda ids, payload: captured.update(ids=ids, p=payload))

    class Req:
        id = 42
        tool_name = 'aws_api_write'
        risk_level = 'high'
        tool_input = {'params': {'Password': 'hunter2-secret'}}
        risk_reason = 'This will call rds create_db_instance: MasterUserPassword=hunter2-secret'
        requester = None
    ps.notify_approval(Req(), [5], self_confirm=True)
    text = repr(captured['p'])
    assert 'hunter2' not in text and 'aws_api_write' in text and 'high risk' in text
    assert captured['p']['link'] == '/approvals/mine' and captured['p']['approval_id'] == 42
    assert captured['p']['aps']['category'] == 'APPROVAL_REQUEST'


def test_filing_a_request_pushes_to_the_person_who_must_confirm(app, db_session, monkeypatch):
    from models import User, db
    from services import approval_service
    calls = []
    monkeypatch.setattr(ps, 'notify_approval', lambda req, ids, self_confirm: calls.append((list(ids), self_confirm)))
    user = _user(db, User, uuid.uuid4().hex[:8])
    req = approval_service.create_request('delete_vpc', {'vpc_id': 'vpc-1'}, 'high', 'Delete a VPC', user.id)
    assert calls and calls[0] == ([user.id], True)
    db.session.delete(req)
    db.session.delete(user)
    db.session.commit()


def _login(app, user):
    c = app.test_client()
    g.pop('_login_user', None)
    assert c.post('/login', data={'email': user.email, 'password': PASSWORD}).status_code == 302
    g.pop('_login_user', None)
    return c


def test_register_moves_a_token_to_whoever_signed_in_last(app, db_session):
    from models import PushDevice, User, db
    tag = uuid.uuid4().hex[:8]
    a, b = _user(db, User, tag), _user(db, User, tag + 'b')
    try:
        ca = _login(app, a)
        assert ca.post('/api/push/devices', json={'token': 'nope'}).status_code == 400
        assert ca.post('/api/push/devices', json={'token': TOKEN}).status_code == 200
        g.pop('_login_user', None)
        cb = _login(app, b)
        assert cb.post('/api/push/devices', json={'token': TOKEN, 'environment': 'sandbox'}).status_code == 200
        rows = PushDevice.query.filter_by(token=TOKEN).all()
        assert len(rows) == 1 and rows[0].user_id == b.id and rows[0].environment == 'sandbox'
        g.pop('_login_user', None)
        assert ca.delete('/api/push/devices', json={'token': TOKEN}).status_code == 200
        assert PushDevice.query.filter_by(token=TOKEN).count() == 1, "a can't remove b's device"
        g.pop('_login_user', None)
        assert cb.delete('/api/push/devices', json={'token': TOKEN}).status_code == 200
        assert PushDevice.query.filter_by(token=TOKEN).count() == 0
    finally:
        g.pop('_login_user', None)
        PushDevice.query.filter_by(token=TOKEN).delete()
        db.session.delete(a)
        db.session.delete(b)
        db.session.commit()


def test_account_deletion_removes_push_devices(app, db_session):
    from models import PushDevice, User, db
    from services.account_deletion import delete_account
    user = _user(db, User, uuid.uuid4().hex[:8])
    uid = user.id
    db.session.add(PushDevice(user_id=uid, token='ef' * 32))
    db.session.commit()
    delete_account(uid)
    assert PushDevice.query.filter_by(user_id=uid).count() == 0
