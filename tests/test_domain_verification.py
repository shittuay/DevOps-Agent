"""Tests for DNS TXT domain verification — services/domain_verification.py.

Self-contained minimal Flask + in-memory SQLite app; DNS is mocked.
"""

import os

import pytest
from flask import Flask

os.environ.setdefault('SECRET_KEY', 'test-secret-key')

from models import db, Organization, OrganizationDomain  # noqa: E402
from services import domain_verification as dv  # noqa: E402
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


def _domain(domain='acme.com', verified=False, token=None):
    org = Organization(name='Acme', slug='acme', owner_id=1, sso_enabled=True,
                       sso_provider='generic_oidc', sso_config={'provider': 'generic_oidc'})
    db.session.add(org)
    db.session.commit()
    row = OrganizationDomain(organization_id=org.id, domain=domain,
                             verified=verified, verification_token=token)
    db.session.add(row)
    db.session.commit()
    return org, row


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def test_challenge_host_and_value():
    assert dv.challenge_host('Acme.COM') == '_devops-agent-challenge.acme.com'
    assert dv.expected_txt_value('abc123') == 'devops-agent-verification=abc123'


def test_ensure_token_generates_and_persists(app_ctx):
    _, row = _domain(token=None)
    token = dv.ensure_token(row)
    assert token and len(token) >= 16
    # Stable across calls.
    assert dv.ensure_token(row) == token


def test_dns_instructions(app_ctx):
    _, row = _domain()
    info = dv.dns_instructions(row)
    assert info['host'] == '_devops-agent-challenge.acme.com'
    assert info['type'] == 'TXT'
    assert info['value'] == 'devops-agent-verification=' + row.verification_token


# --------------------------------------------------------------------------- #
# verify_domain
# --------------------------------------------------------------------------- #

def test_verify_success_with_prefixed_value(app_ctx, monkeypatch):
    _, row = _domain(token='tok123')
    monkeypatch.setattr(dv, '_resolve_txt',
                        lambda host: ['some-other-record', 'devops-agent-verification=tok123'])
    ok, msg = dv.verify_domain(row)
    assert ok and 'verified' in msg.lower()
    assert row.verified is True
    assert row.verified_at is not None


def test_verify_success_with_bare_token(app_ctx, monkeypatch):
    _, row = _domain(token='tok123')
    monkeypatch.setattr(dv, '_resolve_txt', lambda host: ['tok123'])
    ok, _ = dv.verify_domain(row)
    assert ok and row.verified is True


def test_verify_fails_on_mismatch(app_ctx, monkeypatch):
    _, row = _domain(token='tok123')
    monkeypatch.setattr(dv, '_resolve_txt', lambda host: ['devops-agent-verification=WRONG'])
    ok, msg = dv.verify_domain(row)
    assert not ok and row.verified is False
    assert 'did not match' in msg.lower()


def test_verify_handles_missing_record(app_ctx, monkeypatch):
    import dns.resolver
    _, row = _domain(token='tok123')

    def boom(host):
        raise dns.resolver.NXDOMAIN()
    monkeypatch.setattr(dv, '_resolve_txt', boom)
    ok, msg = dv.verify_domain(row)
    assert not ok and row.verified is False
    assert 'no txt record' in msg.lower()


def test_verify_handles_timeout(app_ctx, monkeypatch):
    import dns.exception
    _, row = _domain(token='tok123')

    def boom(host):
        raise dns.exception.Timeout()
    monkeypatch.setattr(dv, '_resolve_txt', boom)
    ok, msg = dv.verify_domain(row)
    assert not ok and 'timed out' in msg.lower()


# --------------------------------------------------------------------------- #
# Routing now requires a verified domain
# --------------------------------------------------------------------------- #

def test_resolve_requires_verified_domain(app_ctx):
    org, row = _domain(domain='acme.com', verified=False, token='t')
    assert sso_service.resolve_org_for_email('user@acme.com') is None

    row.verified = True
    db.session.commit()
    resolved = sso_service.resolve_org_for_email('user@acme.com')
    assert resolved is not None and resolved.id == org.id
