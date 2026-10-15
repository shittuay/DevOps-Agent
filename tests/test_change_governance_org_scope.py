"""Change governance must scope non-admin approvers to their own organization.

Previously, list_pending_approvals/approve_change/reject_change/rollback_change
in routes/changes.py operated with no tenant boundary: any user holding the
platform-wide role='approver' could see and act on every customer's pending
infrastructure changes, not just their own team's. Fixed by stamping
InfrastructureChange.organization_id from the requester's active organization
at creation time, and scoping every non-admin approver route to organizations
the approver is actually a member of. Admins remain unrestricted.
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
    # Flask-Login caches the loaded user on g._login_user; the app fixture
    # keeps one app context alive for the whole session, so g bleeds across
    # test_client() instances unless cleared before each login (see the
    # `client` fixture in conftest.py, which does the same).
    g.pop('_login_user', None)
    c = app.test_client()
    resp = c.post('/login', data={'email': email, 'password': 'TestPassword123!'})
    assert resp.status_code == 302, f"login failed for {email}: {resp.status_code}"
    return c


def _create_medium_risk_change(client, active_org_id=None):
    if active_org_id is not None:
        with client.session_transaction() as sess:
            sess['active_organization_id'] = active_org_id
    resp = client.post('/api/changes', json={
        'action_type': 'resize',
        'resource_type': 'ec2',
        'title': 'Resize web-01',
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['change']


@pytest.fixture
def org_governance_setup(app, db_session):
    from models import db, Organization, OrganizationMember, InfrastructureChange, User

    # The suite shares one database: clear anything an earlier run of this fixture left.
    db.session.rollback()
    emails = ['org-requester@example.com', 'org-approver@example.com',
              'outside-approver@example.com', 'gov-admin@example.com', 'org-plain-member@example.com']
    stale = [u.id for u in User.query.filter(User.email.in_(emails)).all()]
    old_org = Organization.query.filter_by(slug='acme-gov-scope-test').first()
    if old_org:
        OrganizationMember.query.filter_by(organization_id=old_org.id).delete(synchronize_session=False)
        Organization.query.filter_by(id=old_org.id).delete(synchronize_session=False)
    if stale:
        InfrastructureChange.query.filter(InfrastructureChange.user_id.in_(stale)).delete(synchronize_session=False)
        OrganizationMember.query.filter(OrganizationMember.user_id.in_(stale)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(stale)).delete(synchronize_session=False)
    db.session.commit()
    db.session.expunge_all()

    requester = _make_user(db_session, 'org-requester@example.com', role='user')
    org_approver = _make_user(db_session, 'org-approver@example.com', role='approver')
    outside_approver = _make_user(db_session, 'outside-approver@example.com', role='approver')
    admin = _make_user(db_session, 'gov-admin@example.com', role='admin')

    org = Organization(name='Acme', slug='acme-gov-scope-test', owner_id=requester.id)
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
        InfrastructureChange.query.filter_by(user_id=requester.id).delete(synchronize_session=False)
        OrganizationMember.query.filter_by(organization_id=org.id).delete(synchronize_session=False)
        db.session.delete(Organization.query.get(org.id))
        for user_id in (requester.id, org_approver.id, outside_approver.id, admin.id):
            u = User.query.get(user_id)
            if u:
                db.session.delete(u)
        db.session.commit()
    except Exception:
        db.session.rollback()
    db.session.expunge_all()  # drop stale objects so later tests don't touch deleted rows


def test_change_stamped_with_active_organization(app, org_governance_setup):
    setup = org_governance_setup
    client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(client, active_org_id=setup['org'].id)
    assert change['organization_id'] == setup['org'].id


def test_change_without_active_org_has_no_organization(app, org_governance_setup):
    client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(client, active_org_id=None)
    assert change['organization_id'] is None


def test_org_member_approver_sees_and_approves_pending_change(app, org_governance_setup):
    setup = org_governance_setup
    requester_client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(requester_client, active_org_id=setup['org'].id)

    approver_client = _login(app, 'org-approver@example.com')
    pending = approver_client.get('/api/changes/pending').get_json()
    assert change['id'] in [c['id'] for c in pending['pending']]

    resp = approver_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'ok'})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['change']['status'] == 'approved'


def test_outside_approver_cannot_see_or_act_on_foreign_org_change(app, org_governance_setup):
    setup = org_governance_setup
    requester_client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(requester_client, active_org_id=setup['org'].id)

    outside_client = _login(app, 'outside-approver@example.com')

    pending = outside_client.get('/api/changes/pending').get_json()
    assert change['id'] not in [c['id'] for c in pending['pending']]

    resp = outside_client.get(f"/api/changes/{change['id']}")
    assert resp.status_code == 403

    resp = outside_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'nope'})
    assert resp.status_code == 403

    resp = outside_client.post(f"/api/changes/{change['id']}/reject", json={'reason': 'nope'})
    assert resp.status_code == 403


def test_unstamped_change_is_still_reviewed_by_the_requesters_org(app, org_governance_setup):
    """Since 2026-10-14 visibility follows the requester's organizations (the same
    rule as agent requests), not the organization stamped from the session. A
    change filed without an active org is still reviewed by the requester's
    org-mate approver; outsiders still can't touch it."""
    setup = org_governance_setup
    requester_client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(requester_client, active_org_id=None)
    assert change['organization_id'] is None

    outside_client = _login(app, 'outside-approver@example.com')
    resp = outside_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'nope'})
    assert resp.status_code == 403

    org_approver_client = _login(app, 'org-approver@example.com')
    resp = org_approver_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'ok'})
    assert resp.status_code == 200, resp.get_json()


def test_admin_can_approve_unstamped_change(app, org_governance_setup):
    requester_client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(requester_client, active_org_id=None)

    admin_client = _login(app, 'gov-admin@example.com')
    resp = admin_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'ok'})
    assert resp.status_code == 200, resp.get_json()


def test_plain_org_member_cannot_execute_another_users_approved_change(app, org_governance_setup):
    """execute_change previously only checked org-membership (_change_visible_to_approver),
    not approver role, so any plain 'user'-role org member could execute (actually run)
    another user's already-approved change. Must require approver-or-admin, matching
    approve_change/reject_change's role gate.
    """
    from models import db, OrganizationMember

    setup = org_governance_setup
    requester_client = _login(app, 'org-requester@example.com')
    change = _create_medium_risk_change(requester_client, active_org_id=setup['org'].id)

    approver_client = _login(app, 'org-approver@example.com')
    resp = approver_client.post(f"/api/changes/{change['id']}/approve", json={'comment': 'ok'})
    assert resp.status_code == 200, resp.get_json()

    plain_member = _make_user(db_session=db.session, email='org-plain-member@example.com', role='user')
    db.session.add(OrganizationMember(
        organization_id=setup['org'].id, user_id=plain_member.id, role='member', is_active=True,
    ))
    db.session.commit()

    plain_client = _login(app, 'org-plain-member@example.com')
    resp = plain_client.post(f"/api/changes/{change['id']}/execute")
    assert resp.status_code == 403, resp.get_json()


def test_admin_sees_all_pending_regardless_of_organization(app, org_governance_setup):
    setup = org_governance_setup
    requester_client = _login(app, 'org-requester@example.com')
    org_change = _create_medium_risk_change(requester_client, active_org_id=setup['org'].id)
    solo_change = _create_medium_risk_change(requester_client, active_org_id=None)

    admin_client = _login(app, 'gov-admin@example.com')
    pending = admin_client.get('/api/changes/pending').get_json()
    ids = [c['id'] for c in pending['pending']]
    assert org_change['id'] in ids
    assert solo_change['id'] in ids
