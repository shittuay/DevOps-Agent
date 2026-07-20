"""Regression: /compliance/api/run-check must validate framework_id, not 500.

The route passed request.json.get('framework_id') (None when omitted) straight
into run_compliance_check -> enable_framework -> None.upper(), returning a 500
with a raw traceback. It now returns 400 for a missing/unsupported framework.
"""
import pytest


@pytest.fixture
def compliance_cleanup(db_session):
    """Delete committed compliance rows before the owning user's fixture tears
    down. Otherwise deleting test_user nulls the NOT NULL
    compliance_frameworks.user_id FK, poisoning the shared session for the rest
    of the suite. Request this LAST in a test so it finalizes first."""
    yield
    from models import db, ComplianceFrameworkModel, ComplianceReport
    db.session.rollback()
    try:
        ComplianceReport.query.delete()
        ComplianceFrameworkModel.query.delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_run_check_missing_framework_returns_400(authenticated_client):
    resp = authenticated_client.post('/compliance/api/run-check', json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert 'framework_id' in body['error']
    assert 'soc2' in body['supported']


def test_run_check_unsupported_framework_returns_400(authenticated_client):
    resp = authenticated_client.post('/compliance/api/run-check',
                                     json={'framework_id': 'not_a_framework'})
    assert resp.status_code == 400
    assert 'Unsupported' in resp.get_json()['error']


def test_run_check_valid_framework_does_not_500(authenticated_client, compliance_cleanup):
    resp = authenticated_client.post('/compliance/api/run-check',
                                     json={'framework_id': 'soc2'})
    # No cloud creds in tests -> scanner logs a warning and returns an empty
    # report, but the request must succeed rather than error.
    assert resp.status_code == 200


def test_enable_framework_rejects_none():
    from services.compliance_service import ComplianceService
    import pytest
    svc = ComplianceService(user_id=1)
    with pytest.raises(ValueError):
        svc.enable_framework(1, None)
