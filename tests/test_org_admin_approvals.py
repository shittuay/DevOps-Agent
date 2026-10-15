"""Organization owners and admins approve their own team's risky agent actions.

Before this, only accounts holding the platform-wide 'approver' or 'admin' role could
approve, and only platform admins can grant that role, so a customer team needed the
DevOps Agent operators to set up its approvers. Now an organization's owners and admins
(OrganizationMember.role) can approve requests from members of that organization, and a
requester whose organization has nobody else who could approve confirms their own.
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
def teams(app, db_session):
    from models import (db, Organization, OrganizationMember, ApprovalRequest,
                        AppNotification, InfrastructureChange, User)

    owner = _make_user('orgappr-owner@example.com')
    admin = _make_user('orgappr-admin@example.com')
    member = _make_user('orgappr-member@example.com')
    member2 = _make_user('orgappr-member2@example.com')
    other_owner = _make_user('orgappr-other-owner@example.com')
    other_member = _make_user('orgappr-other-member@example.com')
    lone_owner = _make_user('orgappr-lone-owner@example.com')

    org = Organization(name='Team A', slug='orgappr-team-a', owner_id=owner.id)
    other = Organization(name='Team B', slug='orgappr-team-b', owner_id=other_owner.id)
    lone = Organization(name='Team Lone', slug='orgappr-team-lone', owner_id=lone_owner.id)
    db.session.add_all([org, other, lone])
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=admin.id, role='admin', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=member.id, role='member', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=member2.id, role='member', is_active=True),
        OrganizationMember(organization_id=other.id, user_id=other_owner.id, role='owner', is_active=True),
        OrganizationMember(organization_id=other.id, user_id=other_member.id, role='member', is_active=True),
        OrganizationMember(organization_id=lone.id, user_id=lone_owner.id, role='owner', is_active=True),
    ])
    db.session.commit()

    people = {'owner': owner, 'admin': admin, 'member': member, 'member2': member2,
              'other_owner': other_owner, 'other_member': other_member,
              'lone_owner': lone_owner, 'org': org}
    yield people

    db.session.rollback()
    try:
        ids = [u.id for k, u in people.items() if k != 'org']
        ApprovalRequest.query.filter(ApprovalRequest.requester_id.in_(ids)).delete(synchronize_session=False)
        AppNotification.query.filter(AppNotification.user_id.in_(ids)).delete(synchronize_session=False)
        InfrastructureChange.query.filter(InfrastructureChange.user_id.in_(ids)).delete(synchronize_session=False)
        for o in (org, other, lone):
            OrganizationMember.query.filter_by(organization_id=o.id).delete(synchronize_session=False)
            db.session.delete(Organization.query.get(o.id))
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
    from services import approval_service
    monkeypatch.setattr(approval_service, '_execute_tool',
                        lambda req: calls.append(req.id) or {'success': True})
    return calls


def _request_for(user):
    from services.approval_service import create_request
    return create_request(
        tool_name='manage_ec2_instance',
        tool_input={'instance_id': 'i-0orgappr', 'action': 'stop'},
        risk_level='medium',
        risk_reason='This will manage ec2 instance: instance_id=i-0orgappr',
        requester_id=user.id,
    )


def test_org_owner_and_admin_can_approve_member_request(app, teams, fake_execute):
    from services.approval_service import eligible_approver_ids, can_self_confirm

    req = _request_for(teams['member'])
    assert eligible_approver_ids(req) == {teams['owner'].id, teams['admin'].id}
    assert not can_self_confirm(req)

    owner = _login(app, teams['owner'].email)
    assert owner.get('/approvals').status_code == 200
    pending = owner.get('/api/approvals/pending').get_json()
    assert req.id in [r['id'] for r in pending if r['_type'] == 'agent']
    assert owner.get('/api/approvals/count').get_json()['count'] >= 1

    resp = owner.post(f'/api/approvals/{req.id}/approve', json={})
    assert resp.status_code == 200, resp.get_json()
    assert fake_execute == [req.id]


def test_org_admin_can_reject(app, teams, fake_execute):
    from models import ApprovalRequest
    req = _request_for(teams['member'])
    admin = _login(app, teams['admin'].email)
    assert admin.post(f'/api/approvals/{req.id}/reject', json={'note': 'not now'}).status_code == 200
    assert ApprovalRequest.query.get(req.id).status == 'rejected'
    assert fake_execute == []


def test_plain_member_cannot_approve_teammate(app, teams, fake_execute):
    req = _request_for(teams['member'])
    peer = _login(app, teams['member2'].email)
    assert peer.get('/api/approvals/pending').status_code == 403
    assert peer.post(f'/api/approvals/{req.id}/approve', json={}).status_code == 403
    assert fake_execute == []


def test_owner_of_another_org_cannot_approve(app, teams, fake_execute):
    req = _request_for(teams['member'])
    outsider = _login(app, teams['other_owner'].email)
    pending = outsider.get('/api/approvals/pending').get_json()
    assert req.id not in [r['id'] for r in pending]
    assert outsider.post(f'/api/approvals/{req.id}/approve', json={}).status_code == 400
    assert fake_execute == []


def test_owner_request_goes_to_the_other_admin(app, teams, fake_execute):
    from services.approval_service import eligible_approver_ids, can_self_confirm
    req = _request_for(teams['owner'])
    assert eligible_approver_ids(req) == {teams['admin'].id}
    assert not can_self_confirm(req)
    owner = _login(app, teams['owner'].email)
    assert owner.post(f'/api/approvals/{req.id}/approve', json={}).status_code == 400
    assert owner.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 400
    admin = _login(app, teams['admin'].email)
    assert admin.post(f'/api/approvals/{req.id}/approve', json={}).status_code == 200
    assert fake_execute == [req.id]


def test_sole_owner_confirms_own_request(app, teams, fake_execute):
    from services.approval_service import can_self_confirm
    req = _request_for(teams['lone_owner'])
    assert can_self_confirm(req), "nobody else in the org could approve, so the owner confirms"
    lone = _login(app, teams['lone_owner'].email)
    assert lone.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 200
    assert fake_execute == [req.id]


def test_org_admins_are_notified(teams, monkeypatch):
    from models import AppNotification
    _request_for(teams['member'])
    notified = {n.user_id for n in AppNotification.query.filter_by(link='/approvals').all()}
    assert {teams['owner'].id, teams['admin'].id} <= notified
    assert teams['member2'].id not in notified
    assert teams['other_owner'].id not in notified


def test_org_admin_reviews_change_requests_too(app, teams):
    """One queue since 2026-10-14: change requests follow the agent-request rules."""
    from models import InfrastructureChange, db
    change = InfrastructureChange(
        user_id=teams['member'].id,
        organization_id=teams['org'].id,
        action_type='delete',
        resource_type='ec2',
        resource_name='web-1',
        title='Delete web-1',
        status='pending',
    )
    db.session.add(change)
    db.session.commit()
    owner = _login(app, teams['owner'].email)
    pending = owner.get('/api/approvals/pending').get_json()
    assert [r['id'] for r in pending if r['_type'] == 'change'] == [change.id]
    assert owner.post(f'/api/changes/{change.id}/approve', json={}).status_code == 200

    other_owner = _login(app, teams['other_owner'].email)
    assert all(r['_type'] != 'change' for r in other_owner.get('/api/approvals/pending').get_json())


def test_history_is_scoped_to_the_admins_orgs(app, teams, fake_execute):
    from services.approval_service import cancel_own
    mine = _request_for(teams['member'])
    theirs = _request_for(teams['other_member'])
    cancel_own(mine.id, teams['member'].id)
    cancel_own(theirs.id, teams['other_member'].id)

    owner = _login(app, teams['owner'].email)
    ids = [r['id'] for r in owner.get('/api/approvals/history').get_json() if r.get('_type') != 'change']
    assert mine.id in ids
    assert theirs.id not in ids


def test_non_reviewer_is_sent_to_my_requests(app, teams):
    peer = _login(app, teams['member2'].email)
    resp = peer.get('/approvals')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/approvals/mine')
