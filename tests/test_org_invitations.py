"""Organization invitations (2026-11-15 scheduled review).

Before: create_invitation inserted an OrganizationMember with user_id=None into a NOT NULL
column, so every "Invite Member" raised IntegrityError (500) and no email was ever sent.
The accept route joined on a plain GET, any signed-in account could use any token (the
invitee's email was never stored), tokens never expired, and the role was not checked, so
an org admin could invite someone straight in as 'owner'. The Members page's Remove button
sent the membership id where the route expects a user id, and "Change Role" called a
function that didn't exist.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest

PASSWORD = 'TestPassword123!'


@pytest.fixture
def org_setup(app, test_user, db_session):
    from models import db, User, Organization, OrganizationMember, OrganizationInvitation

    admin = User(email='inv-admin@example.com', username='invadmin', full_name='Inv Admin')
    invitee = User(email='invitee@example.com', username='invitee', email_verified=True)
    stranger = User(email='stranger@example.com', username='stranger', email_verified=True)
    for u in (admin, invitee, stranger):
        u.set_password(PASSWORD)
        db.session.add(u)
    db.session.commit()

    org = Organization(name='Invite Org', slug='invite-org-test', owner_id=test_user.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=test_user.id, role='owner', is_active=True),
        OrganizationMember(organization_id=org.id, user_id=admin.id, role='admin', is_active=True),
    ])
    db.session.commit()

    yield org, admin, invitee, stranger

    db.session.rollback()
    OrganizationInvitation.query.filter_by(organization_id=org.id).delete()
    OrganizationMember.query.filter_by(organization_id=org.id).delete()
    Organization.query.filter_by(id=org.id).delete()
    User.query.filter(User.id.in_([admin.id, invitee.id, stranger.id])).delete(synchronize_session=False)
    db.session.commit()


def _login(client, email):
    resp = client.post('/login', data={'email': email, 'password': PASSWORD})
    assert resp.status_code == 302
    return client


def _invite(client, org, email='invitee@example.com', role='member'):
    sent = {}

    def fake_send(self, to_email, org_name, inviter_name, role_, link, days):
        sent['to'], sent['link'] = to_email, link
        return True

    with patch('services.email_service.EmailService.send_org_invitation_email', fake_send):
        resp = client.post(f'/organizations/{org.id}/invite', data={'email': email, 'role': role})
    return resp, sent


def _token(link):
    return link.rsplit('/', 1)[1]


def test_invite_creates_invitation_and_emails_link(client, org_setup):
    from models import OrganizationInvitation
    org, admin, invitee, _ = org_setup
    _login(client, admin.email)
    resp, sent = _invite(client, org, email='  Invitee@Example.com ')
    assert resp.status_code == 302
    assert sent['to'] == 'invitee@example.com'
    inv = OrganizationInvitation.query.filter_by(organization_id=org.id).one()
    assert inv.email == 'invitee@example.com'
    assert inv.token_hash != _token(sent['link'])  # only the hash is stored
    assert len(inv.token_hash) == 64


def test_admin_cannot_invite_as_owner(client, org_setup):
    from models import OrganizationInvitation
    org, admin, _, _ = org_setup
    _login(client, admin.email)
    _invite(client, org, role='owner')
    assert OrganizationInvitation.query.filter_by(organization_id=org.id).count() == 0


def test_get_does_not_join(client, org_setup):
    from services.multi_tenancy import MultiTenancyService
    org, admin, invitee, _ = org_setup
    _login(client, admin.email)
    _, sent = _invite(client, org)
    client.get('/logout')
    _login(client, invitee.email)
    resp = client.get(f'/organizations/invitation/{_token(sent["link"])}')
    assert resp.status_code == 200
    assert b'Accept invitation' in resp.data
    assert MultiTenancyService().get_membership(org.id, invitee.id) is None


def test_invitee_accepts_once_with_invited_role(client, org_setup):
    from services.multi_tenancy import MultiTenancyService
    org, admin, invitee, _ = org_setup
    _login(client, admin.email)
    _, sent = _invite(client, org, role='viewer')
    client.get('/logout')
    _login(client, invitee.email)
    token = _token(sent['link'])
    resp = client.post(f'/organizations/invitation/{token}')
    assert resp.status_code == 302
    membership = MultiTenancyService().get_membership(org.id, invitee.id)
    assert membership is not None and membership.role == 'viewer'
    # Single use.
    assert client.post(f'/organizations/invitation/{token}').status_code == 400


def test_other_account_cannot_use_the_link(client, org_setup):
    from services.multi_tenancy import MultiTenancyService
    org, admin, _, stranger = org_setup
    _login(client, admin.email)
    _, sent = _invite(client, org)
    client.get('/logout')
    _login(client, stranger.email)
    resp = client.post(f'/organizations/invitation/{_token(sent["link"])}')
    assert resp.status_code == 400
    assert MultiTenancyService().get_membership(org.id, stranger.id) is None


def test_unverified_email_cannot_accept(client, org_setup, db_session):
    from models import db
    from services.multi_tenancy import MultiTenancyService
    org, admin, invitee, _ = org_setup
    invitee.email_verified = False
    db.session.commit()
    _login(client, admin.email)
    _, sent = _invite(client, org)
    client.get('/logout')
    _login(client, invitee.email)
    assert client.post(f'/organizations/invitation/{_token(sent["link"])}').status_code == 400
    assert MultiTenancyService().get_membership(org.id, invitee.id) is None


def test_expired_and_revoked_links_fail(client, org_setup):
    from models import db, OrganizationInvitation
    from services.multi_tenancy import MultiTenancyService
    org, admin, invitee, _ = org_setup
    _login(client, admin.email)
    _, sent = _invite(client, org)
    inv = OrganizationInvitation.query.filter_by(organization_id=org.id).one()
    inv.expires_at = inv.created_at - timedelta(seconds=1)
    db.session.commit()
    assert MultiTenancyService().get_invitation_by_token(_token(sent['link'])) is None

    _, sent2 = _invite(client, org)
    live = MultiTenancyService().get_invitation_by_token(_token(sent2['link']))
    assert live is not None
    client.post(f'/organizations/{org.id}/invitations/{live.id}/revoke')
    assert MultiTenancyService().get_invitation_by_token(_token(sent2['link'])) is None


def test_reinvite_replaces_old_link(client, org_setup):
    from services.multi_tenancy import MultiTenancyService
    org, admin, _, _ = org_setup
    _login(client, admin.email)
    _, first = _invite(client, org)
    _, second = _invite(client, org)
    svc = MultiTenancyService()
    assert svc.get_invitation_by_token(_token(first['link'])) is None
    assert svc.get_invitation_by_token(_token(second['link'])) is not None


def test_email_failure_shows_link_instead_of_500(client, org_setup):
    from models import OrganizationInvitation
    org, admin, _, _ = org_setup
    _login(client, admin.email)
    with patch('services.email_service.EmailService.send_org_invitation_email', return_value=False):
        resp = client.post(f'/organizations/{org.id}/invite',
                           data={'email': 'invitee@example.com', 'role': 'member'},
                           follow_redirects=True)
    assert resp.status_code == 200
    assert b'/organizations/invitation/' in resp.data
    assert OrganizationInvitation.query.filter_by(organization_id=org.id).count() == 1


def test_members_page_forms_post_user_ids_with_csrf(client, org_setup, test_user):
    org, admin, _, _ = org_setup
    _login(client, test_user.email)
    html = client.get(f'/organizations/{org.id}/members').data.decode()
    assert f'/organizations/{org.id}/members/{admin.id}/remove' in html
    assert f'/organizations/{org.id}/members/{admin.id}/role' in html
    assert 'changeRole(' not in html and 'removeMember(' not in html
    assert html.count('name="csrf_token"') >= 3


def test_invitation_email_escapes_names():
    from services.email_service import EmailService
    captured = {}
    with patch.object(EmailService, 'send_email',
                      lambda self, to, subj, html, text=None: captured.setdefault('html', html) or True):
        EmailService().send_org_invitation_email(
            'a@b.io', '<script>x</script>', '<img src=x>', 'member', 'https://h/x', 7)
    assert '<script>' not in captured['html'] and '<img src=x>' not in captured['html']


def test_totp_setup_does_not_mark_email_verified(authenticated_client, test_user, db_session):
    import pyotp
    test_user.email_verified = False
    test_user.two_factor_secret = pyotp.random_base32()
    test_user.two_factor_enabled = False
    db_session.commit()
    code = pyotp.TOTP(test_user.two_factor_secret).now()
    resp = authenticated_client.post('/api/2fa/verify-setup', json={'code': code})
    assert resp.status_code == 200, resp.get_json()
    db_session.refresh(test_user)
    assert test_user.two_factor_enabled is True
    assert not test_user.email_verified
