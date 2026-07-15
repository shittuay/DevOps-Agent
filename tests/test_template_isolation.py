"""
Regression tests for the /api/templates/<id>/use IDOR fix.

use_template() previously fetched CommandTemplate by id with no ownership
check (unlike update_template/delete_template), letting any authenticated
user read another user's private saved command by guessing/incrementing the
template id.
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
        from models import CommandTemplate

        CommandTemplate.query.filter_by(user_id=user.id).delete()
        u = User.query.get(user.id)
        if u:
            db.session.delete(u)
        db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def make_template(db_session):
    """Create CommandTemplate rows and delete them before the owning user's
    fixture tears down — otherwise SQLAlchemy nulls the NOT NULL user_id FK
    on user delete and poisons the session for later tests."""
    from models import CommandTemplate, db

    created = []

    def _make(user_id, is_public=False):
        tpl = CommandTemplate(
            user_id=user_id,
            name='secret-runbook',
            command='aws sts get-caller-identity --profile prod',
            category='aws',
            is_public=is_public,
        )
        db.session.add(tpl)
        db.session.commit()
        created.append(tpl.id)
        return tpl

    yield _make

    try:
        for tpl_id in created:
            tpl = CommandTemplate.query.get(tpl_id)
            if tpl:
                db.session.delete(tpl)
        db.session.commit()
    except Exception:
        db.session.rollback()


def test_use_template_blocks_other_users_private_template(authenticated_client, other_user, make_template):
    tpl = make_template(other_user.id, is_public=False)

    resp = authenticated_client.post(f'/api/templates/{tpl.id}/use')

    assert resp.status_code == 403
    assert resp.get_json()['error'] == 'Unauthorized'


def test_use_template_allows_public_template(authenticated_client, other_user, make_template):
    tpl = make_template(other_user.id, is_public=True)

    resp = authenticated_client.post(f'/api/templates/{tpl.id}/use')

    assert resp.status_code == 200
    assert resp.get_json()['command'] == tpl.command


def test_use_template_allows_own_template(authenticated_client, test_user, make_template):
    tpl = make_template(test_user.id, is_public=False)

    resp = authenticated_client.post(f'/api/templates/{tpl.id}/use')

    assert resp.status_code == 200
    assert resp.get_json()['command'] == tpl.command
