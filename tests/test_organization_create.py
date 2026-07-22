"""Regression: creating an organization must never 500 / insert a NULL owner.

The route-smoke suite caught POST /organizations/create returning 5xx: an empty
or owner-less request reached the insert and violated the NOT NULL owner_id /
name columns, which raised inside the request and left the DB session in a
PendingRollback state (poisoning later tests). create_organization now refuses
invalid input and the route returns a clean 400.
"""
import pytest


@pytest.fixture
def org_cleanup(db_session):
    """Remove committed orgs before the owning user tears down, so a NOT NULL
    owner_id FK is never nulled on user delete (which would poison the session)."""
    yield
    from models import db, Organization, OrganizationMember
    db.session.rollback()
    try:
        OrganizationMember.query.delete()
        Organization.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_create_organization_rejects_missing_owner(app, db_session):
    from services.multi_tenancy import MultiTenancyService
    from models import Organization
    svc = MultiTenancyService()
    assert svc.create_organization(name='Acme', owner_id=None) is None
    assert svc.create_organization(name='   ', owner_id=1) is None
    assert Organization.query.count() == 0
    # Session must still be usable (no failed-insert PendingRollback).
    assert Organization.query.filter_by(owner_id=None).count() == 0


def test_create_org_route_empty_body_is_4xx_not_500(authenticated_client, org_cleanup):
    resp = authenticated_client.post('/organizations/create', data={})
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}"


def test_create_org_route_valid_body_succeeds(authenticated_client, org_cleanup):
    resp = authenticated_client.post('/organizations/create',
                                     data={'name': 'My Org'}, follow_redirects=False)
    assert resp.status_code in (302, 303)  # redirect to the new org
