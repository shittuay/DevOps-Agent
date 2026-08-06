"""Regression: view_team() must require the caller to be a member of the org.

routes/organizations.py's view_team fetched `membership =
service.get_membership(org_id, current_user.id)` but never checked it before
rendering the team's member list -- unlike the sibling view_organization/
list_members/list_teams routes in the same file, which all redirect with a
flash message when `membership` is falsy. It only validated that the team
belongs to the requested org_id. Any authenticated user, including one who
belongs to zero organizations, could browse
/organizations/<org_id>/teams/<team_id> for any org/team id pair and see
that org's team member list (names, roles) without ever being a member.
"""
import pytest


@pytest.fixture
def victim_org_and_team(app, db_session, test_user):
    """An org + team owned by test_user, with test_user as its only member."""
    from services.multi_tenancy import MultiTenancyService
    svc = MultiTenancyService()
    org = svc.create_organization(name='Victim Org', owner_id=test_user.id)
    svc.add_member(org.id, test_user.id, role='owner')
    team = svc.create_team(org.id, name='Victim Team')
    yield org, team

    from models import db, Organization, OrganizationMember, Team
    db.session.rollback()
    try:
        Team.query.filter_by(id=team.id).delete()
        OrganizationMember.query.filter_by(organization_id=org.id).delete()
        Organization.query.filter_by(id=org.id).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def outsider_client(client, db_session):
    """A second, distinct user who is not a member of any organization."""
    from models import User, db
    for existing in User.query.filter(
        (User.email == 'outsider@example.com') | (User.username == 'outsideruser')
    ).all():
        db.session.delete(existing)
    db.session.commit()

    user = User(email='outsider@example.com', username='outsideruser', full_name='Outsider')
    user.set_password('OutsiderPassword123!')
    db.session.add(user)
    db.session.commit()

    response = client.post('/login', data={
        'email': 'outsider@example.com',
        'password': 'OutsiderPassword123!'
    })
    assert response.status_code == 302

    yield client

    try:
        u = User.query.get(user.id)
        if u:
            db.session.delete(u)
            db.session.commit()
    except Exception:
        db.session.rollback()


def test_non_member_cannot_view_team(outsider_client, victim_org_and_team):
    org, team = victim_org_and_team
    resp = outsider_client.get(
        f'/organizations/{org.id}/teams/{team.id}', follow_redirects=False
    )
    assert resp.status_code in (302, 303), (
        f"expected a redirect for a non-member, got {resp.status_code}"
    )


def test_member_can_still_view_own_team(authenticated_client, victim_org_and_team):
    org, team = victim_org_and_team
    resp = authenticated_client.get(f'/organizations/{org.id}/teams/{team.id}')
    assert resp.status_code == 200
