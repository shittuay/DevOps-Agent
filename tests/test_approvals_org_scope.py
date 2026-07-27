"""Regression: routes/approvals.py's get_pending()/get_count()/get_history()
leaked every organization's InfrastructureChange records to any platform-role
'approver', instead of scoping to the approver's own organization(s) the way
routes/changes.py's list_pending_approvals() already does (via
_user_active_org_ids()/_change_visible_to_approver()). InfrastructureChange
carries an organization_id specifically to scope non-admin approver
visibility (see models.py's docstring on that column) -- routes/approvals.py
was never given the same treatment as routes/changes.py, even though it reads
the same model.

ApprovalRequest (the "agent tool-call approval" side of these endpoints) has
no organization_id and is intentionally platform-wide for any approver, so
these tests only assert on the InfrastructureChange leak.
"""
import pytest


@pytest.fixture
def approver_user(app, db_session):
    from models import User, db
    for existing in User.query.filter(
        (User.email == 'approver@example.com') | (User.username == 'approveruser')
    ).all():
        db.session.delete(existing)
    db.session.commit()

    user = User(email='approver@example.com', username='approveruser',
                full_name='Approver User', role='approver')
    user.set_password('ApproverPassword123!')
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
def approver_client(client, approver_user):
    response = client.post('/login', data={
        'email': 'approver@example.com',
        'password': 'ApproverPassword123!'
    })
    assert response.status_code == 302
    return client


@pytest.fixture
def two_orgs_with_pending_changes(app, db_session, approver_user, test_user):
    from models import Organization, OrganizationMember, InfrastructureChange, db

    org_mine = Organization(name='My Org', slug='my-org-approvals-test', owner_id=approver_user.id)
    org_other = Organization(name='Other Org', slug='other-org-approvals-test', owner_id=test_user.id)
    db.session.add_all([org_mine, org_other])
    db.session.commit()

    db.session.add(OrganizationMember(
        organization_id=org_mine.id, user_id=approver_user.id, role='admin', is_active=True
    ))
    db.session.commit()

    change_mine = InfrastructureChange(
        user_id=test_user.id, organization_id=org_mine.id,
        action_type='stop', resource_type='ec2', title='Stop instance (my org)',
        status='pending'
    )
    change_other = InfrastructureChange(
        user_id=test_user.id, organization_id=org_other.id,
        action_type='terminate', resource_type='ec2', title='Terminate instance (other org)',
        status='pending'
    )
    db.session.add_all([change_mine, change_other])
    db.session.commit()

    yield {'mine': change_mine, 'other': change_other}

    try:
        InfrastructureChange.query.filter(
            InfrastructureChange.id.in_([change_mine.id, change_other.id])
        ).delete(synchronize_session=False)
        OrganizationMember.query.filter_by(organization_id=org_mine.id).delete()
        Organization.query.filter(
            Organization.id.in_([org_mine.id, org_other.id])
        ).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_pending_hides_other_orgs_change(approver_client, two_orgs_with_pending_changes):
    resp = approver_client.get('/api/approvals/pending')
    assert resp.status_code == 200
    ids = [item['id'] for item in resp.get_json() if item.get('_type') == 'change']
    assert two_orgs_with_pending_changes['mine'].id in ids
    assert two_orgs_with_pending_changes['other'].id not in ids


def test_count_excludes_other_orgs_change(approver_client, two_orgs_with_pending_changes):
    resp = approver_client.get('/api/approvals/count')
    assert resp.status_code == 200
    # Only the approver's own org's pending change should be counted.
    assert resp.get_json()['count'] == 1


def test_history_hides_other_orgs_change(approver_client, two_orgs_with_pending_changes, db_session):
    from models import InfrastructureChange, db
    two_orgs_with_pending_changes['mine'].status = 'approved'
    two_orgs_with_pending_changes['other'].status = 'approved'
    db.session.commit()

    resp = approver_client.get('/api/approvals/history')
    assert resp.status_code == 200
    ids = [item['id'] for item in resp.get_json() if item.get('_type') == 'change']
    assert two_orgs_with_pending_changes['mine'].id in ids
    assert two_orgs_with_pending_changes['other'].id not in ids
