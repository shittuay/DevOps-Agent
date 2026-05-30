"""Tests for SSO onboarding status — services/sso_onboarding.py."""

import os

import pytest
from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from models import db, Organization, OrganizationDomain, User  # noqa: E402
from services import sso_onboarding as ob  # noqa: E402
from services import sso_service  # noqa: E402


@pytest.fixture()
def app_ctx():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


# --------------------------------------------------------------------------- #
# is_provider_configured
# --------------------------------------------------------------------------- #

def test_provider_configured_oidc():
    assert ob.is_provider_configured({}) is False
    assert ob.is_provider_configured(
        {'provider': 'google', 'client_id': 'c', 'client_secret_encrypted': 'x'}) is True
    # generic OIDC also needs a discovery URL
    assert ob.is_provider_configured(
        {'provider': 'generic_oidc', 'client_id': 'c', 'client_secret_encrypted': 'x'}) is False
    assert ob.is_provider_configured(
        {'provider': 'generic_oidc', 'client_id': 'c', 'client_secret_encrypted': 'x',
         'metadata_url': 'https://i/.well-known/openid-configuration'}) is True
    # azure needs tenant_id
    assert ob.is_provider_configured(
        {'provider': 'azure', 'client_id': 'c', 'client_secret_encrypted': 'x'}) is False
    assert ob.is_provider_configured(
        {'provider': 'azure', 'client_id': 'c', 'client_secret_encrypted': 'x',
         'tenant_id': 't'}) is True


def test_provider_configured_saml():
    assert ob.is_provider_configured({'provider': 'saml', 'idp_sso_url': 'u'}) is False
    assert ob.is_provider_configured(
        {'provider': 'saml', 'idp_entity_id': 'e', 'idp_sso_url': 'u', 'idp_x509_cert': 'c'}) is True


# --------------------------------------------------------------------------- #
# get_onboarding_status progression
# --------------------------------------------------------------------------- #

def _org():
    o = Organization(name='Acme', slug='acme', owner_id=1)
    db.session.add(o)
    db.session.commit()
    return o


def test_status_empty_org(app_ctx):
    org = _org()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 0
    assert st['total'] == 5
    assert st['percent'] == 0
    assert st['all_done'] is False
    assert st['current'] == 'provider'
    assert st['next_action']['anchor'] == '#sso-config'


def test_status_progresses(app_ctx):
    org = _org()

    # 1. configure provider
    org.sso_config = {'provider': 'google', 'client_id': 'c', 'client_secret_encrypted': 'x'}
    db.session.commit()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 1 and st['current'] == 'domain'

    # 2. add a domain (unverified)
    d = OrganizationDomain(organization_id=org.id, domain='acme.com', verified=False)
    db.session.add(d)
    db.session.commit()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 2 and st['current'] == 'verify'

    # 3. verify the domain
    d.verified = True
    db.session.commit()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 3 and st['current'] == 'enable'

    # 4. enable SSO
    org.sso_enabled = True
    db.session.commit()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 4 and st['current'] == 'login'

    # 5. first member signs in via SSO
    u = User(email='a@acme.com', username='a', sso_organization_id=org.id, sso_provider='google')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    st = ob.get_onboarding_status(org)
    assert st['completed'] == 5
    assert st['all_done'] is True
    assert st['percent'] == 100
    assert st['current'] is None
    assert st['next_action'] is None
