"""Regression test for an IDOR in the organizations team-view route.

Found during a scheduled security review: GET /organizations/<org_id>/teams/
<team_id> (view_team) computed `membership = service.get_membership(org_id,
current_user.id)` but never checked it before rendering — unlike the sibling
list_teams route, which redirects non-members away. Any @login_required user
who knew or guessed an org_id/team_id could view another organization's team
name, description, and full member roster. Fixed by adding the same
membership check list_teams already has.
"""
import pytest


@pytest.fixture
def org_with_team(app, test_user, db_session):
    from models import db, User, Organization, OrganizationMember, Team

    owner = test_user

    outsider = User(email='outsider@example.com', username='outsider', full_name='Outsider')
    outsider.set_password('TestPassword123!')
    db.session.add(outsider)
    db.session.commit()

    org = Organization(name='Team View Org', slug='team-view-org', owner_id=owner.id)
    db.session.add(org)
    db.session.commit()

    owner_membership = OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner', is_active=True)
    db.session.add(owner_membership)

    team = Team(organization_id=org.id, name='Secret Team', description='Sensitive team info')
    db.session.add(team)
    db.session.commit()

    yield org, team, outsider

    try:
        Team.query.filter_by(id=team.id).delete()
        OrganizationMember.query.filter_by(organization_id=org.id).delete()
        Organization.query.filter_by(id=org.id).delete()
        User.query.filter_by(id=outsider.id).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def _login_as(client, email, password='TestPassword123!'):
    response = client.post('/login', data={'email': email, 'password': password})
    assert response.status_code == 302, f"Login failed with status {response.status_code}"
    return client


def test_non_member_cannot_view_team(client, org_with_team):
    org, team, outsider = org_with_team
    _login_as(client, outsider.email)

    response = client.get(f'/organizations/{org.id}/teams/{team.id}', follow_redirects=False)

    assert response.status_code == 302
    assert '/organizations' in response.headers.get('Location', '')


def test_member_can_view_own_team(client, org_with_team, test_user):
    org, team, outsider = org_with_team
    _login_as(client, test_user.email)

    response = client.get(f'/organizations/{org.id}/teams/{team.id}', follow_redirects=False)

    # Owner is a member: must not be redirected away as a non-member.
    assert response.status_code == 200
