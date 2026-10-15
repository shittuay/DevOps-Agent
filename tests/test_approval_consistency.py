"""One approval model for every way of running a risky tool.

- Approvers and admins used to run any risky action instantly. Their high-risk calls
  (delete, terminate, destroy, secret disclosure) now wait for their own explicit
  confirmation; their medium-risk calls still run directly.
- The developer API (/api-gateway/v1/execute) and /api/v1/tools/execute let the caller
  confirm their own risky calls (a confirm_token round trip, or "confirm": true),
  regardless of organization. They now follow the chat rules: a request is filed, and
  only a caller who could confirm it in chat can confirm it over the API. Confirmed runs
  go through the approval service, so they're verified and audited.
"""
import pytest


def _make_user(email, role='user'):
    from models import User, db
    user = User(email=email, username=email.split('@')[0].replace('-', '_'),
                full_name=email, role=role, email_verified=True)
    user.set_password('TestPassword123!')
    db.session.add(user)
    db.session.commit()
    return user


class _Req:
    def __init__(self, requester_id):
        self.requester_id = requester_id


class _FakeAgent:
    """Stands in for app.agent inside approval_service._execute_tool."""

    def __init__(self, names):
        self.calls = []
        self.tools = {n: self._make(n) for n in names}
        self._current_user_id = None
        self._current_conversation_id = None

    def _make(self, name):
        def _h(**kw):
            self.calls.append((name, kw))
            return {'success': True, 'tool': name}
        return _h

    def _reset_turn_tool_state(self): pass
    def _set_cloud_user_context(self, uid): pass
    def _clear_cloud_user_context(self): pass
    def _record_tool_call(self, *a, **k): pass
    def _verify_and_annotate(self, name, inp, result): return result
    def _audit_infrastructure_change(self, *a, **k): pass


@pytest.fixture
def people(app, db_session):
    from models import (db, Organization, OrganizationMember, ApprovalRequest,
                        AppNotification, User, APIKey, UserSubscription, SubscriptionTier, UsageLog)

    approver = _make_user('consist-approver@example.com', role='approver')
    approver2 = _make_user('consist-approver2@example.com', role='approver')
    solo = _make_user('consist-solo@example.com')
    owner = _make_user('consist-owner@example.com')
    member = _make_user('consist-member@example.com')

    org = Organization(name='Consist Org', slug='consist-org-test', owner_id=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=member.id, role='member', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=approver.id, role='member', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=approver2.id, role='member', is_active=True),
    ])
    tier = SubscriptionTier.query.filter_by(name='professional').first()
    if not tier:
        tier = SubscriptionTier(name='professional', display_name='Professional',
                                monthly_price=99, monthly_credits=1000)
        db.session.add(tier)
        db.session.commit()
    keys = {}
    for u in (solo, member):
        from datetime import timedelta
        from src.utils.timeutils import utcnow
        db.session.add(UserSubscription(user_id=u.id, tier_id=tier.id, credits_remaining=50,
                                        current_period_end=utcnow() + timedelta(days=20)))
        k, plain = APIKey.create_for_user(u.id, 'consist', ['read', 'write'])
        db.session.add(k)
        keys[u.id] = plain
    db.session.commit()

    yield {'approver': approver, 'approver2': approver2, 'solo': solo, 'owner': owner,
           'member': member, 'org': org, 'keys': keys}

    db.session.rollback()
    try:
        ids = [approver.id, approver2.id, solo.id, owner.id, member.id]
        ApprovalRequest.query.filter(ApprovalRequest.requester_id.in_(ids)).delete(synchronize_session=False)
        AppNotification.query.filter(AppNotification.user_id.in_(ids)).delete(synchronize_session=False)
        UsageLog.query.filter(UsageLog.user_id.in_(ids)).delete(synchronize_session=False)
        APIKey.query.filter(APIKey.user_id.in_(ids)).delete(synchronize_session=False)
        UserSubscription.query.filter(UserSubscription.user_id.in_(ids)).delete(synchronize_session=False)
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
def fake_agent(monkeypatch):
    import app as app_module
    agent = _FakeAgent(['manage_ec2_instance', 'delete_vpc', 'execute_command'])
    monkeypatch.setattr(app_module, 'agent', agent)
    return agent


# --- approvers and admins -------------------------------------------------

def test_needs_approval_matrix(people):
    from services.approval_service import needs_approval
    for risk in ('medium', 'high', 'critical'):
        assert needs_approval(people['solo'], risk)
    assert not needs_approval(people['approver'], 'medium')
    assert needs_approval(people['approver'], 'high')
    assert needs_approval(people['approver'], 'critical')
    admin = type('U', (), {'role': 'admin'})()
    assert not needs_approval(admin, 'medium') and needs_approval(admin, 'high')
    assert needs_approval(None, 'medium')


def test_approver_high_risk_is_their_own_confirmation(people, monkeypatch):
    from services import approval_service
    from services.approval_service import create_request, can_self_confirm, can_approve
    from models import AppNotification

    notified = []
    monkeypatch.setattr(approval_service, '_notify_approvers', lambda r: notified.append(r.id))
    req = create_request(tool_name='delete_vpc', tool_input={'vpc_id': 'vpc-1'},
                         risk_level='high', risk_reason='This will delete vpc',
                         requester_id=people['approver'].id)
    assert can_self_confirm(req)
    assert not can_approve(req, people['approver2']), "nobody else reviews an approver's own confirmation"
    assert not can_approve(req, people['owner'])
    assert notified == []
    assert AppNotification.query.filter_by(user_id=people['approver'].id,
                                           link='/approvals/mine').first() is not None


def test_approver_confirms_own_high_risk_in_chat_flow(app, people, fake_agent):
    from flask import g
    from services.approval_service import create_request
    req = create_request(tool_name='delete_vpc', tool_input={'vpc_id': 'vpc-1'},
                         risk_level='high', risk_reason='This will delete vpc',
                         requester_id=people['approver'].id)
    g.pop('_login_user', None)
    c = app.test_client()
    assert c.post('/login', data={'email': people['approver'].email,
                                  'password': 'TestPassword123!'}).status_code == 302
    assert c.get(f'/api/approvals/{req.id}/status').get_json()['can_confirm'] is True
    assert c.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 200
    assert fake_agent.calls == [('delete_vpc', {'vpc_id': 'vpc-1'})]


def test_chat_and_mcp_use_needs_approval():
    """All four gates must ask the same question, not a role check of their own."""
    import inspect
    from src.agent import core
    from routes import mcp
    src = inspect.getsource(core)
    assert src.count('needs_approval(') == 3
    assert "role in ('approver', 'admin')" not in src
    assert "role not in ('approver', 'admin')" not in src
    assert 'needs_approval(' in inspect.getsource(mcp._handle_tools_call)


# --- /api/v1/tools/execute -------------------------------------------------

def _v1(client, key, tool, params, **extra):
    return client.post('/api/v1/tools/execute', json={'tool': tool, 'params': params, **extra},
                       headers={'X-API-Key': key})


@pytest.fixture
def v1_agent(app, fake_agent):
    prev = app.config.get('DEVOPS_AGENT')
    app.config['DEVOPS_AGENT'] = fake_agent
    yield fake_agent
    app.config['DEVOPS_AGENT'] = prev


def test_v1_solo_user_files_then_confirms(app, people, v1_agent):
    client = app.test_client()
    key = people['keys'][people['solo'].id]
    params = {'action': 'stop', 'instance_id': 'i-1'}

    first = _v1(client, key, 'manage_ec2_instance', params)
    assert first.status_code == 202
    body = first.get_json()
    assert body['can_confirm'] is True
    assert v1_agent.calls == []

    run = _v1(client, key, 'manage_ec2_instance', params, approval_id=body['approval_id'])
    assert run.status_code == 200, run.get_json()
    assert run.get_json()['status'] == 'executed'
    assert v1_agent.calls == [('manage_ec2_instance', params)]

    again = _v1(client, key, 'manage_ec2_instance', params, approval_id=body['approval_id'])
    assert again.status_code == 200
    assert len(v1_agent.calls) == 1, "re-sending must report the result, not run it again"


def test_v1_approval_id_must_match_the_call(app, people, v1_agent):
    client = app.test_client()
    key = people['keys'][people['solo'].id]
    first = _v1(client, key, 'manage_ec2_instance', {'action': 'stop', 'instance_id': 'i-1'}).get_json()
    swapped = _v1(client, key, 'manage_ec2_instance', {'action': 'terminate', 'instance_id': 'i-1'},
                  approval_id=first['approval_id'])
    assert swapped.status_code == 400
    assert v1_agent.calls == []


def test_v1_cannot_use_someone_elses_approval(app, people, v1_agent):
    client = app.test_client()
    params = {'action': 'stop', 'instance_id': 'i-1'}
    mine = _v1(client, people['keys'][people['solo'].id], 'manage_ec2_instance', params).get_json()
    other = _v1(client, people['keys'][people['member'].id], 'manage_ec2_instance', params,
                approval_id=mine['approval_id'])
    assert other.status_code == 404
    assert v1_agent.calls == []


def test_v1_org_member_waits_for_owner(app, people, v1_agent):
    from flask import g
    client = app.test_client()
    key = people['keys'][people['member'].id]
    params = {'vpc_id': 'vpc-9'}

    first = _v1(client, key, 'delete_vpc', params)
    assert first.status_code == 202
    body = first.get_json()
    assert body['can_confirm'] is False

    still = _v1(client, key, 'delete_vpc', params, approval_id=body['approval_id'])
    assert still.status_code == 202
    assert v1_agent.calls == []

    g.pop('_login_user', None)
    owner = app.test_client()
    assert owner.post('/login', data={'email': people['owner'].email,
                                      'password': 'TestPassword123!'}).status_code == 302
    assert owner.post(f"/api/approvals/{body['approval_id']}/approve", json={}).status_code == 200
    assert v1_agent.calls == [('delete_vpc', params)]

    done = _v1(client, key, 'delete_vpc', params, approval_id=body['approval_id'])
    assert done.status_code == 200
    assert done.get_json()['status'] == 'executed'
    assert len(v1_agent.calls) == 1


# --- developer API (/api-gateway/v1/execute) --------------------------------

def _gw(client, key, tool, params, **extra):
    return client.post('/api-gateway/v1/execute', json={'tool': tool, 'params': params, **extra},
                       headers={'X-API-Key': key})


def test_gateway_follows_the_same_rules(app, people, fake_agent):
    from models import UserSubscription
    client = app.test_client()
    params = {'action': 'stop', 'instance_id': 'i-2'}

    # Org member: waits for an owner; the old confirm_token round trip is gone.
    member_key = people['keys'][people['member'].id]
    first = _gw(client, member_key, 'manage_ec2_instance', params)
    assert first.status_code == 202, first.get_json()
    assert first.get_json()['can_confirm'] is False
    assert 'confirm_token' not in first.get_json()
    assert _gw(client, member_key, 'manage_ec2_instance', params,
               approval_id=first.get_json()['approval_id']).status_code == 202
    assert fake_agent.calls == []

    # Solo user: confirms by re-sending with the approval_id; one credit is spent on the run.
    solo_key = people['keys'][people['solo'].id]
    before = UserSubscription.query.filter_by(user_id=people['solo'].id).first().credits_remaining
    filed = _gw(client, solo_key, 'manage_ec2_instance', params).get_json()
    assert filed['can_confirm'] is True
    run = _gw(client, solo_key, 'manage_ec2_instance', params, approval_id=filed['approval_id'])
    assert run.status_code == 200, run.get_json()
    assert fake_agent.calls == [('manage_ec2_instance', params)]
    after = UserSubscription.query.filter_by(user_id=people['solo'].id).first().credits_remaining
    assert after == before - 1


def test_gateway_fails_closed_when_safety_check_breaks(app, people, fake_agent, monkeypatch):
    from src.agent import safety

    def _boom(self, *a, **k):
        raise RuntimeError('validator down')

    monkeypatch.setattr(safety.SafetyValidator, 'validate_tool_call', _boom)
    resp = _gw(app.test_client(), people['keys'][people['solo'].id],
               'manage_ec2_instance', {'action': 'terminate', 'instance_id': 'i-3'})
    assert resp.status_code == 503
    assert fake_agent.calls == []
