"""An organization always keeps an owner (2026-11-23 scheduled review).

The only owner could demote or remove themselves through the Members page, leaving an
organization nobody could manage: only an owner can grant owner access, so it could never
get one back.
"""
import pytest


@pytest.fixture
def org(app, test_user, db_session):
    from models import db, User, Organization, OrganizationMember

    other = User(email='lastowner-other@example.com', username='lastownerother')
    other.set_password('TestPassword123!')
    db.session.add(other)
    db.session.commit()

    org = Organization(name='Owner Org', slug='last-owner-org-test', owner_id=test_user.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=test_user.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=other.id, role='admin', is_active=True),
    ])
    db.session.commit()

    yield org, other

    db.session.rollback()
    OrganizationMember.query.filter_by(organization_id=org.id).delete()
    Organization.query.filter_by(id=org.id).delete()
    User.query.filter_by(id=other.id).delete()
    db.session.commit()


def _role(org_id, user_id):
    from models import OrganizationMember
    m = OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()
    return m.role, m.is_active


def test_only_owner_cannot_demote_themselves(authenticated_client, test_user, org):
    org, _ = org
    authenticated_client.post(f'/organizations/{org.id}/members/{test_user.id}/role',
                              data={'role': 'member'})
    assert _role(org.id, test_user.id) == ('owner', True)


def test_only_owner_cannot_remove_themselves(authenticated_client, test_user, org):
    org, _ = org
    authenticated_client.post(f'/organizations/{org.id}/members/{test_user.id}/remove')
    assert _role(org.id, test_user.id) == ('owner', True)


def test_owner_can_step_down_once_another_owner_exists(authenticated_client, test_user, org):
    org, other = org
    authenticated_client.post(f'/organizations/{org.id}/members/{other.id}/role',
                              data={'role': 'owner'})
    assert _role(org.id, other.id) == ('owner', True)
    authenticated_client.post(f'/organizations/{org.id}/members/{test_user.id}/role',
                              data={'role': 'member'})
    assert _role(org.id, test_user.id) == ('member', True)


def test_service_refuses_last_owner_directly(app, test_user, org):
    from services.multi_tenancy import MultiTenancyService
    org, _ = org
    service = MultiTenancyService()
    assert service.is_last_owner(org.id, test_user.id)
    assert service.update_member_role(org.id, test_user.id, 'admin') is None
    assert service.remove_member(org.id, test_user.id) is False
    assert _role(org.id, test_user.id) == ('owner', True)
