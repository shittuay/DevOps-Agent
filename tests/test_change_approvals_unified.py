"""Change requests use the same approval rules as agent requests (2026-10-14).

Before: only the platform 'approver' role could approve a change request, and only
platform admins can grant that role, so a customer team couldn't approve its own
changes and a solo user's high-risk change could never be approved at all.
"""
import uuid

import pytest


def _user(name, role='user'):
    from models import User, db
    tag = uuid.uuid4().hex[:8]
    u = User(email=f'{name}-{tag}@example.com', username=f'{name}_{tag}'.replace('-', '_'), role=role)
    u.set_password('Password123!x')
    db.session.add(u)
    db.session.commit()
    return u


class _Client:
    """A test client that clears Flask-Login's cached user (g._login_user) before each
    request: the app fixture keeps one app context alive, so it would otherwise act
    as whichever user logged in last."""
    def __init__(self, app, email):
        self._c = app.test_client()
        assert self.post('/login', data={'email': email, 'password': 'Password123!x'}).status_code == 302

    def _do(self, method, *a, **kw):
        from flask import g
        g.pop('_login_user', None)
        return getattr(self._c, method)(*a, **kw)

    def get(self, *a, **kw):
        return self._do('get', *a, **kw)

    def post(self, *a, **kw):
        return self._do('post', *a, **kw)


def _login(app, email):
    return _Client(app, email)


def _change(user, risk='high'):
    from models import InfrastructureChange, db
    c = InfrastructureChange(user_id=user.id, action_type='delete', resource_type='ec2',
                             resource_name='web-1', title='Delete web-1', status='pending',
                             change_details={'risk_level': risk})
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def team(app, db_session):
    from models import Organization, OrganizationMember, db
    owner = _user('cu-owner')
    member = _user('cu-member')
    peer = _user('cu-peer')
    solo = _user('cu-solo')
    org = Organization(name='CU', slug=f'cu-org-{uuid.uuid4().hex[:8]}', owner_id=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=member.id, role='member', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=peer.id, role='member', is_active=True),
    ])
    db.session.commit()
    people = {'owner': owner, 'member': member, 'peer': peer, 'solo': solo}
    yield people

    # The suite shares one database: leave nothing behind for tests that count rows.
    from models import InfrastructureChange, User
    ids = [u.id for u in people.values()]
    db.session.rollback()
    InfrastructureChange.query.filter(InfrastructureChange.user_id.in_(ids)).delete(synchronize_session=False)
    OrganizationMember.query.filter_by(organization_id=org.id).delete(synchronize_session=False)
    Organization.query.filter_by(id=org.id).delete(synchronize_session=False)
    User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    db.session.expunge_all()


def test_solo_user_confirms_their_own_high_risk_change(app, team):
    c = _change(team['solo'])
    client = _login(app, team['solo'].email)
    mine = client.get('/api/approvals/mine').get_json()
    [row] = [r for r in mine if r['_type'] == 'change']
    assert row['id'] == c.id and row['can_confirm'] is True
    assert client.post(f'/api/changes/{c.id}/approve', json={}).status_code == 200


def test_member_waits_for_owner_and_peer_cannot_approve(app, team):
    c = _change(team['member'])
    member = _login(app, team['member'].email)
    [row] = [r for r in member.get('/api/approvals/mine').get_json() if r['_type'] == 'change']
    assert row['can_confirm'] is False
    assert member.post(f'/api/changes/{c.id}/approve', json={}).status_code == 403
    assert _login(app, team['peer'].email).post(f'/api/changes/{c.id}/approve', json={}).status_code == 403
    assert _login(app, team['owner'].email).post(f'/api/changes/{c.id}/approve', json={}).status_code == 200


def test_requester_can_always_cancel(app, team):
    c = _change(team['member'])
    resp = _login(app, team['member'].email).post(f'/api/changes/{c.id}/reject',
                                                  json={'reason': 'Cancelled by requester'})
    assert resp.status_code == 200 and resp.get_json()['change']['status'] == 'rejected'


def test_owner_sees_team_changes_in_lists(app, team):
    c = _change(team['member'])
    owner = _login(app, team['owner'].email)
    assert c.id in [x['id'] for x in owner.get('/api/changes').get_json()['changes']]
    assert c.id in [x['id'] for x in owner.get('/api/changes/pending').get_json()['pending']]
    assert owner.get(f'/api/changes/{c.id}').status_code == 200
    outsider = _login(app, team['solo'].email)
    assert outsider.get(f'/api/changes/{c.id}').status_code == 403
    assert c.id not in [x['id'] for x in outsider.get('/api/changes').get_json()['changes']]


def test_plain_member_cannot_run_a_teammates_approved_change(app, team):
    from models import db
    c = _change(team['member'])
    c.status = 'approved'
    db.session.commit()
    assert _login(app, team['peer'].email).post(f'/api/changes/{c.id}/execute').status_code == 403
