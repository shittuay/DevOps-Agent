"""Regression: ComplianceService.get_policy()/get_compliance_report()/
get_framework() must be scoped to the owning user.

get_policy/get_compliance_report did a bare Model.query.get(id) with no
user_id filter, even though ComplianceService is always constructed with a
specific user_id (routes/compliance.py's toggle_policy/delete_policy/
download_report all do ComplianceService(current_user.id)). Any logged-in
user could toggle, delete, or download another user's compliance policy/
report by guessing/incrementing the integer id -- an IDOR. Fixed by filtering
by self.user_id in both getters (every real call site always sets user_id,
so this doesn't change behavior for any legitimate caller).

get_framework() had the identical gap and was missed in that same fix (found
by a later scheduled review) -- routes/compliance.py's framework_detail/
enable_framework call it with a guessed integer id from the URL, so a
logged-in user could read or re-enable another user's
ComplianceFrameworkModel row (compliance_score, is_enabled, settings JSON).
"""
import pytest


@pytest.fixture
def other_user(app, db_session):
    from models import User, db
    for existing in User.query.filter(
        (User.email == 'other@example.com') | (User.username == 'otheruser')
    ).all():
        db.session.delete(existing)
    db.session.commit()

    user = User(email='other@example.com', username='otheruser', full_name='Other User')
    user.set_password('OtherPassword123!')
    db.session.add(user)
    db.session.commit()
    yield user
    try:
        u = User.query.get(user.id)
        if u:
            db.session.delete(u)
            db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def victim_policy(test_user, db_session):
    from services.compliance_service import ComplianceService
    svc = ComplianceService(test_user.id)
    policy = svc.create_policy(test_user.id, 'Victim Policy', 'access_control', rules=[])
    yield policy
    from models import CompliancePolicy, db
    try:
        p = CompliancePolicy.query.get(policy.id)
        if p:
            db.session.delete(p)
            db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def victim_report(test_user, db_session):
    from models import ComplianceReport, db
    report = ComplianceReport(
        user_id=test_user.id, name='Victim Report', report_type='summary',
        framework='soc2', overall_score=90, controls_passed=9, controls_failed=1
    )
    db.session.add(report)
    db.session.commit()
    yield report
    try:
        r = ComplianceReport.query.get(report.id)
        if r:
            db.session.delete(r)
            db.session.commit()
    except Exception:
        db.session.rollback()


def test_get_policy_scoped_to_owner(other_user, victim_policy):
    from services.compliance_service import ComplianceService
    attacker_svc = ComplianceService(other_user.id)
    assert attacker_svc.get_policy(victim_policy.id) is None


def test_get_compliance_report_scoped_to_owner(other_user, victim_report):
    from services.compliance_service import ComplianceService
    attacker_svc = ComplianceService(other_user.id)
    assert attacker_svc.get_compliance_report(victim_report.id) is None


def test_delete_policy_blocked_for_non_owner(other_user, victim_policy):
    from services.compliance_service import ComplianceService
    from models import CompliancePolicy

    attacker_svc = ComplianceService(other_user.id)
    assert attacker_svc.delete_policy(victim_policy.id) is False
    assert CompliancePolicy.query.get(victim_policy.id) is not None


def test_toggle_policy_blocked_for_non_owner(other_user, victim_policy):
    from services.compliance_service import ComplianceService

    original_state = victim_policy.is_active
    attacker_svc = ComplianceService(other_user.id)
    assert attacker_svc.toggle_policy(victim_policy.id) is None

    from models import db
    db.session.refresh(victim_policy)
    assert victim_policy.is_active == original_state


def test_owner_can_still_manage_own_policy(test_user, victim_policy):
    from services.compliance_service import ComplianceService
    owner_svc = ComplianceService(test_user.id)
    assert owner_svc.get_policy(victim_policy.id) is not None
    assert owner_svc.toggle_policy(victim_policy.id) is not None


@pytest.fixture
def victim_framework(test_user, db_session):
    from models import ComplianceFrameworkModel, db
    framework = ComplianceFrameworkModel(
        user_id=test_user.id, name='soc2', display_name='SOC 2',
        is_enabled=True, compliance_score=87,
    )
    db.session.add(framework)
    db.session.commit()
    yield framework
    try:
        f = ComplianceFrameworkModel.query.get(framework.id)
        if f:
            db.session.delete(f)
            db.session.commit()
    except Exception:
        db.session.rollback()


def test_get_framework_scoped_to_owner(other_user, victim_framework):
    from services.compliance_service import ComplianceService
    attacker_svc = ComplianceService(other_user.id)
    assert attacker_svc.get_framework(victim_framework.id) is None


def test_owner_can_still_read_own_framework(test_user, victim_framework):
    from services.compliance_service import ComplianceService
    owner_svc = ComplianceService(test_user.id)
    result = owner_svc.get_framework(victim_framework.id)
    assert result is not None
    assert result.id == victim_framework.id
