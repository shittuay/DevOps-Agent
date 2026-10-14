"""Solo accounts confirm their own risky actions; organization members still need an approver.

Before this, every signup had role 'user', so a medium/high-risk action from chat or the
Claude.ai connector became an ApprovalRequest. A requester with no organization was only
visible to platform admins, so a solo customer's "stop my instance" waited on (and emailed)
the platform's own staff, who know nothing about the customer's account.

Also pins: the MCP approval gate fails closed, an approved run invalidates the read cache,
and /setup (which writes the server's Anthropic key) is admin-only.
"""
import pytest


def _make_user(email, role='user'):
    from models import User, db
    user = User(
        email=email,
        username=email.split('@')[0].replace('-', '_'),
        full_name=email,
        role=role,
        email_verified=True,
    )
    user.set_password('TestPassword123!')
    db.session.add(user)
    db.session.commit()
    return user


def _login(app, email):
    from flask import g
    g.pop('_login_user', None)
    c = app.test_client()
    resp = c.post('/login', data={'email': email, 'password': 'TestPassword123!'})
    assert resp.status_code == 302, f"login failed for {email}: {resp.status_code}"
    return c


@pytest.fixture
def people(app, db_session):
    from models import db, Organization, OrganizationMember, ApprovalRequest, AppNotification, User

    solo = _make_user('selfconf-solo@example.com')
    member = _make_user('selfconf-member@example.com')
    org_approver = _make_user('selfconf-approver@example.com', role='approver')
    stranger = _make_user('selfconf-stranger@example.com')
    admin = _make_user('selfconf-admin@example.com', role='admin')

    org = Organization(name='Self Confirm Org', slug='self-confirm-org-test', owner_id=member.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=member.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=org_approver.id, role='member', is_active=True),
    ])
    db.session.commit()

    yield {'solo': solo, 'member': member, 'org_approver': org_approver,
           'stranger': stranger, 'admin': admin, 'org': org}

    db.session.rollback()
    try:
        ids = [solo.id, member.id, org_approver.id, stranger.id, admin.id]
        ApprovalRequest.query.filter(ApprovalRequest.requester_id.in_(ids)).delete(synchronize_session=False)
        AppNotification.query.filter(AppNotification.user_id.in_(ids)).delete(synchronize_session=False)
        OrganizationMember.query.filter_by(organization_id=org.id).delete(synchronize_session=False)
        db.session.delete(Organization.query.get(org.id))
        for uid in ids:
            u = User.query.get(uid)
            if u:
                db.session.delete(u)
        db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def fake_execute(monkeypatch):
    calls = []

    def _fake(req):
        calls.append(req.id)
        return {'success': True, 'stopped': req.tool_input.get('instance_id')}

    from services import approval_service
    monkeypatch.setattr(approval_service, '_execute_tool', _fake)
    return calls


def _request_for(user):
    from services.approval_service import create_request
    return create_request(
        tool_name='terminate_ec2_instance',
        tool_input={'instance_id': 'i-0selfconfirm'},
        risk_level='high',
        risk_reason='This will terminate ec2 instance: instance_id=i-0selfconfirm',
        requester_id=user.id,
    )


def test_solo_request_is_self_confirmable_and_not_sent_to_platform_admins(people, monkeypatch):
    from services import approval_service
    from models import AppNotification

    notified = []
    monkeypatch.setattr(approval_service, '_notify_approvers', lambda req: notified.append(req.id))

    req = _request_for(people['solo'])
    assert approval_service.can_self_confirm(req)
    assert notified == [], "a solo request must not page the platform's approvers"
    reminder = AppNotification.query.filter_by(
        user_id=people['solo'].id, link='/approvals/mine').first()
    assert reminder is not None
    assert 'confirm' in approval_service.waiting_message(req).lower()


def test_org_request_still_goes_to_approvers(people, monkeypatch):
    from services import approval_service

    notified = []
    monkeypatch.setattr(approval_service, '_notify_approvers', lambda req: notified.append(req.id))
    req = _request_for(people['member'])
    assert not approval_service.can_self_confirm(req)
    assert notified == [req.id]
    assert 'approver' in approval_service.waiting_message(req).lower()


def test_solo_user_confirms_own_request(app, people, fake_execute):
    from models import ApprovalRequest

    req = _request_for(people['solo'])
    client = _login(app, people['solo'].email)

    status = client.get(f'/api/approvals/{req.id}/status').get_json()
    assert status['can_confirm'] is True

    resp = client.post(f'/api/approvals/{req.id}/confirm', json={})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['result']['success'] is True
    assert fake_execute == [req.id]

    stored = ApprovalRequest.query.get(req.id)
    assert stored.status == 'executed'
    assert stored.approver_id == people['solo'].id

    again = client.post(f'/api/approvals/{req.id}/confirm', json={})
    assert again.status_code == 400
    assert fake_execute == [req.id], "a request must never run twice"


def test_org_member_cannot_self_confirm(app, people, fake_execute):
    from models import ApprovalRequest

    req = _request_for(people['member'])
    client = _login(app, people['member'].email)

    assert client.get(f'/api/approvals/{req.id}/status').get_json()['can_confirm'] is False
    resp = client.post(f'/api/approvals/{req.id}/confirm', json={})
    assert resp.status_code == 400
    assert fake_execute == []
    assert ApprovalRequest.query.get(req.id).status == 'pending'


def test_org_approver_still_approves_member_request(app, people, fake_execute):
    req = _request_for(people['member'])
    client = _login(app, people['org_approver'].email)
    resp = client.post(f'/api/approvals/{req.id}/approve', json={})
    assert resp.status_code == 200, resp.get_json()
    assert fake_execute == [req.id]


def test_requester_can_cancel_but_others_cannot_touch(app, people, fake_execute):
    from models import ApprovalRequest

    req = _request_for(people['solo'])

    stranger = _login(app, people['stranger'].email)
    assert stranger.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 400
    assert stranger.post(f'/api/approvals/{req.id}/cancel', json={}).status_code == 400
    assert ApprovalRequest.query.get(req.id).status == 'pending'

    owner = _login(app, people['solo'].email)
    assert owner.post(f'/api/approvals/{req.id}/cancel', json={}).status_code == 200
    stored = ApprovalRequest.query.get(req.id)
    assert stored.status == 'rejected'
    assert fake_execute == []
    assert owner.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 400


def test_my_requests_lists_only_own_pending(app, people):
    mine = _request_for(people['solo'])
    _request_for(people['member'])

    client = _login(app, people['solo'].email)
    assert client.get('/approvals/mine').status_code == 200
    data = client.get('/api/approvals/mine').get_json()
    assert [r['id'] for r in data] == [mine.id]
    assert data[0]['can_confirm'] is True


def test_expired_request_cannot_be_confirmed(app, people, fake_execute):
    from datetime import timedelta
    from models import ApprovalRequest, db
    from src.utils.timeutils import utcnow

    req = _request_for(people['solo'])
    req.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()

    client = _login(app, people['solo'].email)
    assert client.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 400
    assert fake_execute == []
    assert ApprovalRequest.query.get(req.id).status == 'expired'


def test_approved_run_invalidates_read_cache(people, monkeypatch):
    from services import approval_service
    from services.tool_cache import READ_CACHE

    uid = people['solo'].id
    READ_CACHE.put(uid, 'describe_instances::{}', {'success': True, 'state': 'running'})
    assert READ_CACHE.get(uid, 'describe_instances::{}') is not None

    class _Agent:
        tools = {'terminate_ec2_instance': lambda **kw: {'success': True}}
        _current_user_id = None
        _current_conversation_id = None
        def _reset_turn_tool_state(self): pass
        def _set_cloud_user_context(self, uid): pass
        def _clear_cloud_user_context(self): pass
        def _record_tool_call(self, *a, **k): pass
        def _verify_and_annotate(self, name, inp, result): return result
        def _audit_infrastructure_change(self, *a, **k): pass

    import app as app_module
    monkeypatch.setattr(app_module, 'agent', _Agent())
    req = _request_for(people['solo'])
    approval_service._execute_tool(req)
    assert READ_CACHE.get(uid, 'describe_instances::{}') is None


class _ContextOnlyAgent:
    def _set_cloud_user_context(self, uid): pass
    def _clear_cloud_user_context(self): pass


def test_mcp_gate_fails_closed_when_request_cannot_be_filed(app, people, monkeypatch):
    from routes import mcp
    from services import approval_service
    import app as app_module

    monkeypatch.setattr(app_module, 'agent', _ContextOnlyAgent())

    def _boom(**kwargs):
        raise RuntimeError('database unavailable')

    monkeypatch.setattr(approval_service, 'create_request', _boom)
    ran = []
    monkeypatch.setattr(mcp, '_get_all_tools', lambda: ([], {
        'terminate_ec2_instance': {'handler': lambda **kw: ran.append(kw) or {'success': True}},
    }))

    with app.app_context():
        resp = mcp._handle_tools_call(1, {
            'name': 'terminate_ec2_instance',
            'arguments': {'instance_id': 'i-0selfconfirm'},
        }, people['solo'].id)

    assert ran == [], "a risky MCP call must not run when its approval request can't be filed"
    assert resp['result']['isError'] is True


def test_mcp_solo_request_points_user_at_confirmation(app, people, monkeypatch):
    from routes import mcp
    import app as app_module

    monkeypatch.setattr(app_module, 'agent', _ContextOnlyAgent())

    ran = []
    monkeypatch.setattr(mcp, '_get_all_tools', lambda: ([], {
        'terminate_ec2_instance': {'handler': lambda **kw: ran.append(kw) or {'success': True}},
    }))
    with app.app_context():
        resp = mcp._handle_tools_call(1, {
            'name': 'terminate_ec2_instance',
            'arguments': {'instance_id': 'i-0selfconfirm'},
        }, people['solo'].id)

    assert ran == []
    text = resp['result']['content'][0]['text']
    assert '/approvals/mine' in text


def test_setup_is_admin_only(app, people):
    user = _login(app, people['solo'].email)
    resp = user.post('/setup', json={'api_key': 'sk-ant-should-not-be-saved'})
    assert resp.status_code == 403

    admin = _login(app, people['admin'].email)
    assert admin.get('/setup').status_code == 200


def test_doctor_is_admin_only(app, people):
    user = _login(app, people['solo'].email)
    assert user.get('/doctor').status_code in (302, 403)

    admin = _login(app, people['admin'].email)
    resp = admin.get('/doctor')
    assert resp.status_code == 200
    assert b'sk-ant-' not in resp.data, "the diagnostics page must not show any part of the API key"
