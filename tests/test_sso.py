"""Tests for organization SSO (OIDC) — services/sso_service.py.

Self-contained: builds a minimal Flask + in-memory SQLite app importing only
`models` and `sso_service`, so it runs without the full app's cloud SDK deps.
"""

import os

import pytest
from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key')  # Fernet key derivation fallback

from models import db, User, Organization, OrganizationMember, OrganizationDomain  # noqa: E402
from services import sso_service  # noqa: E402


@pytest.fixture()
def sso_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _make_org(provider='generic_oidc', enabled=True, with_secret=True, domains=('acme.com',)):
    config = {
        'provider': provider,
        'client_id': 'client123',
        'metadata_url': 'https://idp.test/.well-known/openid-configuration',
        'default_role': 'member',
        'allowed_domains': list(domains),
    }
    if with_secret:
        config['client_secret_encrypted'] = sso_service.encrypt_secret('s3cr3t')
    org = Organization(name='Acme', slug='acme', owner_id=1,
                        sso_enabled=enabled, sso_provider=provider, sso_config=config)
    db.session.add(org)
    db.session.commit()
    for d in domains:
        db.session.add(OrganizationDomain(organization_id=org.id, domain=d, verified=True))
    db.session.commit()
    return org


def _identity(email='alice@acme.com', verified=True, sub='idp-sub-1', provider='generic_oidc'):
    return sso_service.Identity(subject=sub, email=email, email_verified=verified,
                                name='Alice', provider=provider)


# --------------------------------------------------------------------------- #
# Secret encryption
# --------------------------------------------------------------------------- #

def test_encrypt_roundtrip():
    token = sso_service.encrypt_secret('hunter2')
    assert token and token != 'hunter2'
    assert sso_service.decrypt_secret(token) == 'hunter2'
    assert sso_service.encrypt_secret('') == ''
    assert sso_service.decrypt_secret('') == ''


def test_decrypt_garbage_returns_empty():
    assert sso_service.decrypt_secret('not-a-valid-token') == ''


# --------------------------------------------------------------------------- #
# Admin config save / read
# --------------------------------------------------------------------------- #

def test_save_config_encrypts_secret(sso_app):
    org = Organization(name='Acme', slug='acme', owner_id=1)
    db.session.add(org)
    db.session.commit()

    ok, err = sso_service.save_config(org.id, {
        'provider': 'generic_oidc', 'client_id': 'cid', 'client_secret': 'topsecret',
        'metadata_url': 'https://idp.test/.well-known/openid-configuration',
        'enabled': 'on',
    })
    assert ok and err is None

    db.session.refresh(org)
    assert org.sso_enabled is True
    assert org.sso_provider == 'generic_oidc'
    assert org.sso_config['client_secret_encrypted'] != 'topsecret'
    assert sso_service.decrypt_secret(org.sso_config['client_secret_encrypted']) == 'topsecret'


def test_add_and_remove_domain(sso_app):
    org = Organization(name='Acme', slug='acme', owner_id=1)
    db.session.add(org)
    db.session.commit()

    ok, err = sso_service.add_domain(org.id, '  ACME.com ')
    assert ok and err is None
    row = OrganizationDomain.query.filter_by(organization_id=org.id).one()
    assert row.domain == 'acme.com'
    assert row.verified is False
    assert row.verification_token  # token issued for DNS challenge

    # Duplicate within the org is rejected.
    ok, err = sso_service.add_domain(org.id, 'acme.com')
    assert not ok and 'already added' in err.lower()

    # Invalid format rejected.
    ok, err = sso_service.add_domain(org.id, 'not a domain')
    assert not ok and 'valid domain' in err.lower()

    assert sso_service.remove_domain(org.id, row.id) is True
    assert OrganizationDomain.query.filter_by(organization_id=org.id).count() == 0


def test_add_domain_rejects_claim_by_other_org(sso_app):
    org1 = Organization(name='A', slug='a', owner_id=1)
    org2 = Organization(name='B', slug='b', owner_id=1)
    db.session.add_all([org1, org2])
    db.session.commit()
    assert sso_service.add_domain(org1.id, 'shared.com')[0] is True
    ok, err = sso_service.add_domain(org2.id, 'shared.com')
    assert not ok and 'another organization' in err.lower()


def test_save_config_requires_secret_first_time(sso_app):
    org = Organization(name='Acme', slug='acme', owner_id=1)
    db.session.add(org)
    db.session.commit()
    ok, err = sso_service.save_config(org.id, {
        'provider': 'google', 'client_id': 'cid', 'client_secret': '', 'enabled': 'on'})
    assert not ok and 'secret' in err.lower()


def test_save_config_keeps_secret_on_blank(sso_app):
    org = _make_org()
    original = org.sso_config['client_secret_encrypted']
    ok, err = sso_service.save_config(org.id, {
        'provider': 'generic_oidc', 'client_id': 'client123', 'client_secret': '',
        'metadata_url': 'https://idp.test/.well-known/openid-configuration',
        'domains': 'acme.com', 'enabled': 'on'})
    assert ok, err
    db.session.refresh(org)
    assert org.sso_config['client_secret_encrypted'] == original


def test_save_config_rejects_unknown_provider(sso_app):
    org = Organization(name='Acme', slug='acme', owner_id=1)
    db.session.add(org)
    db.session.commit()
    ok, err = sso_service.save_config(org.id, {'provider': 'ldap', 'client_id': 'x'})
    assert not ok and 'provider' in err.lower()


def test_get_admin_config_hides_secret(sso_app):
    org = _make_org()
    cfg = sso_service.get_admin_config(org)
    assert 'client_secret_encrypted' not in cfg
    assert cfg['has_secret'] is True
    assert cfg['provider'] == 'generic_oidc'
    assert cfg['enabled'] is True


# --------------------------------------------------------------------------- #
# Domain-based org resolution
# --------------------------------------------------------------------------- #

def test_resolve_org_for_email(sso_app):
    org = _make_org(domains=('acme.com',))
    assert sso_service.resolve_org_for_email('bob@acme.com').id == org.id
    assert sso_service.resolve_org_for_email('bob@ACME.com').id == org.id
    assert sso_service.resolve_org_for_email('bob@other.com') is None
    assert sso_service.resolve_org_for_email('garbage') is None


def test_resolve_org_skips_disabled(sso_app):
    _make_org(enabled=False)
    assert sso_service.resolve_org_for_email('bob@acme.com') is None


# --------------------------------------------------------------------------- #
# JIT provisioning
# --------------------------------------------------------------------------- #

def test_provision_creates_user_and_membership(sso_app):
    org = _make_org()
    user, created = sso_service.find_or_provision_user(org, _identity())
    assert created is True
    assert user.email == 'alice@acme.com'
    assert user.email_verified is True
    assert user.sso_provider == 'generic_oidc'
    assert user.sso_subject == 'idp-sub-1'
    assert user.sso_organization_id == org.id
    assert not user.check_password('')  # password is unusable/random
    assert OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).count() == 1


def test_provision_is_idempotent(sso_app):
    org = _make_org()
    u1, c1 = sso_service.find_or_provision_user(org, _identity())
    u2, c2 = sso_service.find_or_provision_user(org, _identity())
    assert u1.id == u2.id
    assert c1 is True and c2 is False
    assert OrganizationMember.query.filter_by(organization_id=org.id, user_id=u1.id).count() == 1


def test_provision_unverified_email_raises(sso_app):
    org = _make_org()
    with pytest.raises(sso_service.SSOError):
        sso_service.find_or_provision_user(org, _identity(verified=False))


def test_provision_links_existing_user(sso_app):
    org = _make_org()
    existing = User(email='alice@acme.com', username='alice', full_name='Alice')
    existing.set_password('oldpassword')
    db.session.add(existing)
    db.session.commit()

    user, created = sso_service.find_or_provision_user(org, _identity())
    assert created is False
    assert user.id == existing.id
    assert user.sso_provider == 'generic_oidc'
    assert user.check_password('oldpassword')  # existing password preserved
    assert OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).count() == 1


# --------------------------------------------------------------------------- #
# Provider endpoints + authorization URL
# --------------------------------------------------------------------------- #

def test_github_endpoints_and_auth_url(sso_app):
    config = {'provider': 'github', 'client_id': 'ghid',
              'client_secret_encrypted': sso_service.encrypt_secret('ghsecret')}
    ep = sso_service.get_provider_endpoints(config)
    assert ep['type'] == 'oauth2'
    assert 'github.com/login/oauth/authorize' in ep['authorization_endpoint']

    url = sso_service.build_authorization_url(config, 'https://app.test/cb', 'STATE1', 'NONCE1')
    assert 'client_id=ghid' in url
    assert 'state=STATE1' in url
    assert 'redirect_uri=https%3A%2F%2Fapp.test%2Fcb' in url
    assert 'nonce=' not in url  # OAuth2 (not OIDC) -> no nonce


def test_endpoints_missing_credentials_raises(sso_app):
    with pytest.raises(sso_service.SSOError):
        sso_service.get_provider_endpoints({'provider': 'google', 'client_id': 'x'})


def test_unsupported_provider_raises(sso_app):
    with pytest.raises(sso_service.SSOError):
        sso_service.get_provider_endpoints({'provider': 'ldap'})


# --------------------------------------------------------------------------- #
# Full callback flows (mocked network)
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_handle_callback_github(sso_app, monkeypatch):
    config = {'provider': 'github', 'client_id': 'ghid',
              'client_secret_encrypted': sso_service.encrypt_secret('ghsecret')}

    monkeypatch.setattr(sso_service.requests, 'post',
                        lambda *a, **k: _Resp({'access_token': 'gho_token'}))

    def fake_get(url, *a, **k):
        if url.endswith('/user/emails'):
            return _Resp([{'email': 'dev@acme.com', 'primary': True, 'verified': True}])
        if url.endswith('/user'):
            return _Resp({'id': 42, 'login': 'dev', 'name': 'Dev User'})
        return _Resp({}, 404)
    monkeypatch.setattr(sso_service.requests, 'get', fake_get)

    identity = sso_service.handle_callback(config, 'code', 'https://app.test/cb', 'n')
    assert identity.provider == 'github'
    assert identity.subject == '42'
    assert identity.email == 'dev@acme.com'
    assert identity.email_verified is True


def _signed_oidc(monkeypatch, nonce_in_token='NONCE1'):
    """Set up a mocked OIDC IdP with a real signed id_token; returns the config."""
    from joserfc import jwt
    from joserfc.jwk import RSAKey

    key = RSAKey.generate_key(2048, parameters={'kid': 'k1'})
    pub_jwks = {'keys': [key.as_dict(private=False)]}
    claims = {
        'iss': 'https://idp.test', 'aud': 'client123', 'sub': 'oidc-sub-9',
        'exp': 9999999999, 'email': 'carol@acme.com', 'email_verified': True,
        'name': 'Carol', 'nonce': nonce_in_token,
    }
    id_token = jwt.encode({'alg': 'RS256', 'kid': 'k1'}, claims, key)

    monkeypatch.setattr(sso_service, '_discover', lambda url: {
        'authorization_endpoint': 'https://idp.test/auth',
        'token_endpoint': 'https://idp.test/token',
        'userinfo_endpoint': 'https://idp.test/userinfo',
        'jwks_uri': 'https://idp.test/jwks',
        'issuer': 'https://idp.test',
    })
    monkeypatch.setattr(sso_service.requests, 'post',
                        lambda *a, **k: _Resp({'id_token': id_token, 'access_token': 'at'}))

    def fake_get(url, *a, **k):
        if url == 'https://idp.test/jwks':
            return _Resp(pub_jwks)
        return _Resp({})  # userinfo
    monkeypatch.setattr(sso_service.requests, 'get', fake_get)

    return {'provider': 'generic_oidc', 'client_id': 'client123',
            'client_secret_encrypted': sso_service.encrypt_secret('s3cr3t'),
            'metadata_url': 'https://idp.test/.well-known/openid-configuration'}


def test_handle_callback_oidc_signed_token(sso_app, monkeypatch):
    config = _signed_oidc(monkeypatch, nonce_in_token='NONCE1')
    identity = sso_service.handle_callback(config, 'code', 'https://app.test/cb', 'NONCE1')
    assert identity.subject == 'oidc-sub-9'
    assert identity.email == 'carol@acme.com'
    assert identity.email_verified is True
    assert identity.name == 'Carol'


def test_handle_callback_oidc_nonce_mismatch_raises(sso_app, monkeypatch):
    config = _signed_oidc(monkeypatch, nonce_in_token='NONCE1')
    with pytest.raises(sso_service.SSOError):
        sso_service.handle_callback(config, 'code', 'https://app.test/cb', 'WRONG')
