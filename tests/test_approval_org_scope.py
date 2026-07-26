"""Agent-triggered approvals must scope non-admin approvers to their own organization.

Previously, routes/approvals.py and services/approval_service.py operated with no
tenant boundary at all for ApprovalRequest: any user holding the platform-wide
role='approver' could see, approve, and reject every organization's pending
high-risk tool-call requests, not just their own team's — a more consequential
instance of the InfrastructureChange gap fixed in test_change_governance_org_scope.py,
since approving here actually executes the underlying tool call. ApprovalRequest has
no organization_id column of its own, so visibility is derived from whether the
approver shares an active organization membership with the request's requester
(services/approval_service.is_visible_to_approver). Admins remain unrestricted.
"""
import pytest


def _make_user(db_session, email, role='user'):
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
def approval_org_setup(app, db_session):
    from models import db, Organization, OrganizationMember, ApprovalRequest, User

    requester = _make_user(db_session, 'appr-requester@example.com', role='user')
    org_approver = _make_user(db_session, 'appr-org-approver@example.com', role='approver')
    outside_approver = _make_user(db_session, 'appr-outside-approver@example.com', role='approver')
    admin = _make_user(db_session, 'appr-admin@example.com', role='admin')

    org = Organization(name='Acme Approvals', slug='acme-approval-scope-test', owner_id=requester.id)
    db.session.add(org)
    db.session.commit()

    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=requester.id, role='member', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=org_approver.id, role='member', is_active=True),
    ])
    db.session.commit()

    yield {
        'requester': requester,
        'org_approver': org_approver,
        'outside_approver': outside_approver,
        'admin': admin,
        'org': org,
    }

    db.session.rollback()
    try:
        ApprovalRequest.query.filter_by(requester_id=requester.id).delete(synchronize_session=False)
        OrganizationMember.query.filter_by(organization_id=org.id).delete(synchronize_session=False)
        db.session.delete(Organization.query.get(org.id))
        for user_id in (requester.id, org_approver.id, outside_approver.id, admin.id):
            u = User.query.get(user_id)
            if u:
                db.session.delete(u)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _create_pending_request(setup):
    from services.approval_service import create_request
    return create_request(
        tool_name='terminate_ec2_instance',
        tool_input={'instance_id': 'i-deadbeef'},
        risk_level='high',
        risk_reason='This will terminate: instance_id=i-deadbeef',
        requester_id=setup['requester'].id,
    )


def test_org_member_approver_sees_and_approves_pending_request(app, approval_org_setup):
    setup = approval_org_setup
    req = _create_pending_request(setup)

    approver_client = _login(app, 'appr-org-approver@example.com')
    pending = approver_client.get('/api/approvals/pending').get_json()
    assert req.id in [r['id'] for r in pending if r.get('_type') == 'agent']

    resp = approver_client.post(f'/api/approvals/{req.id}/approve', json={'note': 'ok'})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['success'] is True


def test_outside_approver_cannot_see_or_act_on_foreign_org_request(app, approval_org_setup):
    setup = approval_org_setup
    req = _create_pending_request(setup)

    outside_client = _login(app, 'appr-outside-approver@example.com')

    pending = outside_client.get('/api/approvals/pending').get_json()
    assert req.id not in [r['id'] for r in pending if r.get('_type') == 'agent']

    status_resp = outside_client.get(f'/api/approvals/{req.id}/status')
    assert status_resp.status_code == 403

    approve_resp = outside_client.post(f'/api/approvals/{req.id}/approve', json={'note': 'nope'})
    assert approve_resp.status_code == 400
    assert approve_resp.get_json()['success'] is False

    reject_resp = outside_client.post(f'/api/approvals/{req.id}/reject', json={'note': 'nope'})
    assert reject_resp.status_code == 400
    assert reject_resp.get_json()['success'] is False


def test_solo_request_without_org_requires_admin(app, approval_org_setup, db_session):
    """A requester with no active org membership at all is admin-only, same
    convention as the InfrastructureChange fix — there's no organization to
    scope against, so even an org-mate approver (of a *different* org) can't
    reach it, and only an admin can act."""
    from models import db, User

    solo_requester = _make_user(db_session, 'appr-solo-requester@example.com', role='user')
    from services.approval_service import create_request
    req = create_request(
        tool_name='terminate_ec2_instance',
        tool_input={'instance_id': 'i-solo'},
        risk_level='high',
        risk_reason='This will terminate: instance_id=i-solo',
        requester_id=solo_requester.id,
    )

    org_approver_client = _login(app, 'appr-org-approver@example.com')
    resp = org_approver_client.post(f'/api/approvals/{req.id}/approve', json={'note': 'nope'})
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False

    admin_client = _login(app, 'appr-admin@example.com')
    resp = admin_client.post(f'/api/approvals/{req.id}/approve', json={'note': 'ok'})
    assert resp.status_code == 200, resp.get_json()

    db.session.delete(User.query.get(solo_requester.id))
    db.session.commit()


def test_admin_sees_all_pending_regardless_of_organization(app, approval_org_setup):
    setup = approval_org_setup
    req = _create_pending_request(setup)

    admin_client = _login(app, 'appr-admin@example.com')
    pending = admin_client.get('/api/approvals/pending').get_json()
    assert req.id in [r['id'] for r in pending if r.get('_type') == 'agent']
