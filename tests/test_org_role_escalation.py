"""Regression test for a privilege-escalation gap in org role management.

Found during a scheduled security review: POST /organizations/<org_id>/members/
<user_id>/role took `role` straight from the request body and handed it to
MultiTenancyService.update_member_role() with no allow-list and no check that
the caller was already an 'owner' — so any org 'admin' (gated in only by
org_admin_required, which accepts both 'owner' and 'admin') could grant
themselves (or anyone) 'owner', the only role with owner-only powers like org
deletion/billing (see user_has_org_permission(..., ['owner'])). Fixed by
validating `role` against the known role set and requiring the caller to
already be an owner before granting or changing owner access.
"""
import pytest


@pytest.fixture
def org_with_admin_and_member(app, test_user, db_session):
    from models import db, User, Organization, OrganizationMember

    owner = test_user

    admin_user = User(email='org-admin@example.com', username='orgadmin', full_name='Org Admin')
    admin_user.set_password('TestPassword123!')
    db.session.add(admin_user)

    other_member = User(email='org-member@example.com', username='orgmember', full_name='Org Member')
    other_member.set_password('TestPassword123!')
    db.session.add(other_member)
    db.session.commit()

    org = Organization(name='Test Org', slug='test-org-escalation', owner_id=owner.id)
    db.session.add(org)
    db.session.commit()

    owner_membership = OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner', is_active=True)
    admin_membership = OrganizationMember(organization_id=org.id, user_id=admin_user.id, role='admin', is_active=True)
    other_membership = OrganizationMember(organization_id=org.id, user_id=other_member.id, role='member', is_active=True)
    db.session.add_all([owner_membership, admin_membership, other_membership])
    db.session.commit()

    yield org, admin_user, other_member

    try:
        OrganizationMember.query.filter_by(organization_id=org.id).delete()
        Organization.query.filter_by(id=org.id).delete()
        User.query.filter(User.id.in_([admin_user.id, other_member.id])).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _login_as(client, email, password='TestPassword123!'):
    response = client.post('/login', data={'email': email, 'password': password})
    assert response.status_code == 302, f"Login failed with status {response.status_code}"
    return client


def test_org_admin_cannot_self_promote_to_owner(client, org_with_admin_and_member):
    from models import OrganizationMember

    org, admin_user, other_member = org_with_admin_and_member
    _login_as(client, 'org-admin@example.com')

    client.post(f'/organizations/{org.id}/members/{admin_user.id}/role', data={'role': 'owner'})

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=admin_user.id).first()
    assert membership.role == 'admin'


def test_org_admin_cannot_grant_owner_to_another_member(client, org_with_admin_and_member):
    from models import OrganizationMember

    org, admin_user, other_member = org_with_admin_and_member
    _login_as(client, 'org-admin@example.com')

    client.post(f'/organizations/{org.id}/members/{other_member.id}/role', data={'role': 'owner'})

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=other_member.id).first()
    assert membership.role == 'member'


def test_org_admin_can_still_change_non_owner_roles(client, org_with_admin_and_member):
    from models import OrganizationMember

    org, admin_user, other_member = org_with_admin_and_member
    _login_as(client, 'org-admin@example.com')

    client.post(f'/organizations/{org.id}/members/{other_member.id}/role', data={'role': 'billing'})

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=other_member.id).first()
    assert membership.role == 'billing'


def test_invalid_role_is_rejected(client, org_with_admin_and_member):
    from models import OrganizationMember

    org, admin_user, other_member = org_with_admin_and_member
    _login_as(client, 'org-admin@example.com')

    client.post(f'/organizations/{org.id}/members/{other_member.id}/role', data={'role': 'superadmin'})

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=other_member.id).first()
    assert membership.role == 'member'


def test_owner_can_grant_owner(client, org_with_admin_and_member, test_user):
    from models import OrganizationMember

    org, admin_user, other_member = org_with_admin_and_member
    _login_as(client, test_user.email)

    client.post(f'/organizations/{org.id}/members/{admin_user.id}/role', data={'role': 'owner'})

    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=admin_user.id).first()
    assert membership.role == 'owner'
