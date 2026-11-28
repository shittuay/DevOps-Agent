"""An organization must keep at least one active owner (2026-11-28 scheduled review).

The only owner could demote or remove themselves through the Members page, leaving nobody
able to grant owner access, change another owner, or manage SSO.
"""
from tests.test_org_role_escalation import org_with_admin_and_member, _login_as  # noqa: F401


def _membership(org_id, user_id):
    from models import OrganizationMember
    return OrganizationMember.query.filter_by(organization_id=org_id, user_id=user_id).first()


def test_only_owner_cannot_demote_self(client, org_with_admin_and_member, test_user):
    org, _admin, _member = org_with_admin_and_member
    _login_as(client, test_user.email)
    client.post(f'/organizations/{org.id}/members/{test_user.id}/role', data={'role': 'member'})
    assert _membership(org.id, test_user.id).role == 'owner'


def test_only_owner_cannot_remove_self(client, org_with_admin_and_member, test_user):
    org, _admin, _member = org_with_admin_and_member
    _login_as(client, test_user.email)
    client.post(f'/organizations/{org.id}/members/{test_user.id}/remove')
    assert _membership(org.id, test_user.id).is_active


def test_owner_can_step_down_once_another_owner_exists(client, org_with_admin_and_member, test_user):
    org, admin_user, _member = org_with_admin_and_member
    _login_as(client, test_user.email)
    client.post(f'/organizations/{org.id}/members/{admin_user.id}/role', data={'role': 'owner'})
    client.post(f'/organizations/{org.id}/members/{test_user.id}/role', data={'role': 'admin'})
    assert _membership(org.id, test_user.id).role == 'admin'
    assert _membership(org.id, admin_user.id).role == 'owner'


def test_service_refuses_last_owner_directly(app, org_with_admin_and_member, test_user):
    from services.multi_tenancy import MultiTenancyService
    org, _admin, _member = org_with_admin_and_member
    service = MultiTenancyService()
    assert service.is_last_owner(org.id, test_user.id)
    assert service.update_member_role(org.id, test_user.id, 'viewer') is None
    assert service.remove_member(org.id, test_user.id) is False
    assert _membership(org.id, test_user.id).role == 'owner'
