"""Self-serve account deletion (Settings > Profile). Apple requires it in any app that lets
people create an account (App Store guideline 5.1.1(v)), and there was none.

The models have no ON DELETE rules, so these tests turn SQLite's foreign-key checks on: a
missed child table fails here the way it would on Postgres.
"""
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from flask import g
from sqlalchemy import event, text

from src.utils.timeutils import utcnow

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = 'Password123!x'


def _user(db, User, tag, **kw):
    u = User(email=f'del-{tag}@example.com', username=f'del_{tag}', email_verified=True, **kw)
    u.set_password(PASSWORD)
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def fk_checks(app):
    from models import db
    with app.app_context():
        db.session.commit()  # the pragma is ignored inside an open transaction
        db.session.execute(text('PRAGMA foreign_keys=ON'))
        assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
        yield
        db.session.commit()
        db.session.execute(text('PRAGMA foreign_keys=OFF'))


def _populate(db, owner, other):
    from models import (ApprovalRequest, ChatMessage, Conversation, Organization,
                        OrganizationMember, UsageLog)
    conv = Conversation(id=uuid.uuid4().hex[:20], user_id=owner.id)
    db.session.add(conv)
    db.session.flush()
    db.session.add(ChatMessage(user_id=owner.id, conversation_id=conv.id, role='user', content='hi'))
    db.session.add(UsageLog(user_id=owner.id, conversation_id=conv.id, action_type='message'))
    org = Organization(name='Solo', slug=f'solo-{uuid.uuid4().hex[:8]}', owner_id=owner.id)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner'))
    mine = ApprovalRequest(requester_id=owner.id, tool_name='delete_vpc', risk_level='high',
                           risk_reason='x', expires_at=utcnow() + timedelta(hours=1))
    theirs = ApprovalRequest(requester_id=other.id, approver_id=owner.id, tool_name='delete_vpc',
                             risk_level='high', risk_reason='x', status='approved',
                             expires_at=utcnow() + timedelta(hours=1))
    db.session.add_all([mine, theirs])
    db.session.commit()
    return conv.id, org.id, mine.id, theirs.id


def test_deletes_everything_the_user_owns_and_keeps_other_users_rows(app, db_session, fk_checks):
    from models import (ApprovalRequest, ChatMessage, Conversation, Organization, UsageLog,
                        User, db)
    from services.account_deletion import delete_account
    tag = uuid.uuid4().hex[:8]
    owner, other = _user(db, User, tag), _user(db, User, tag + 'b')
    conv_id, org_id, mine_id, theirs_id = _populate(db, owner, other)
    owner_id, other_id = owner.id, other.id

    delete_account(owner_id)

    assert db.session.get(User, owner_id) is None
    assert db.session.get(Conversation, conv_id) is None
    assert ChatMessage.query.filter_by(conversation_id=conv_id).count() == 0
    assert UsageLog.query.filter_by(user_id=owner_id).count() == 0
    assert db.session.get(Organization, org_id) is None, 'a team only they belonged to goes too'
    assert db.session.get(ApprovalRequest, mine_id) is None
    kept = db.session.get(ApprovalRequest, theirs_id)
    assert kept is not None and kept.approver_id is None, "another user's request survives"
    assert db.session.get(User, other_id) is not None
    db.session.delete(kept)
    db.session.delete(db.session.get(User, other_id))
    db.session.commit()


def test_refuses_while_they_own_a_team_with_other_members(app, db_session):
    from models import Organization, OrganizationMember, User, db
    from services.account_deletion import AccountDeletionBlocked, delete_account
    tag = uuid.uuid4().hex[:8]
    owner, member = _user(db, User, tag), _user(db, User, tag + 'm')
    org = Organization(name='Team', slug=f'team-{tag}', owner_id=owner.id)
    db.session.add(org)
    db.session.flush()
    db.session.add_all([OrganizationMember(organization_id=org.id, user_id=owner.id, role='owner'),
                        OrganizationMember(organization_id=org.id, user_id=member.id, role='member')])
    db.session.commit()
    with pytest.raises(AccountDeletionBlocked, match='Team'):
        delete_account(owner.id)
    assert db.session.get(User, owner.id) is not None
    OrganizationMember.query.filter_by(organization_id=org.id).delete()
    db.session.delete(org)
    db.session.delete(member)
    db.session.delete(owner)
    db.session.commit()


def test_paid_plan_is_cancelled_first_and_a_failed_cancel_keeps_the_account(app, db_session, monkeypatch):
    from models import SubscriptionTier, User, UserSubscription, db
    from services.account_deletion import AccountDeletionBlocked, delete_account
    import stripe_integration
    tag = uuid.uuid4().hex[:8]
    tier = SubscriptionTier.query.first() or SubscriptionTier(name=f't{tag}', display_name='T',
                                                              monthly_credits=1)
    db.session.add(tier)
    db.session.commit()
    user = _user(db, User, tag)
    db.session.add(UserSubscription(user_id=user.id, tier_id=tier.id,
                                    stripe_subscription_id=f'sub_{tag}'))
    db.session.commit()

    calls = []
    monkeypatch.setattr(stripe_integration.StripePaymentService, 'cancel_subscription',
                        staticmethod(lambda sid: calls.append(sid) or {'success': False}))
    user_id = user.id
    with pytest.raises(AccountDeletionBlocked, match='paid plan'):
        delete_account(user_id)
    assert db.session.get(User, user_id) is not None

    monkeypatch.setattr(stripe_integration.StripePaymentService, 'cancel_subscription',
                        staticmethod(lambda sid: calls.append(sid) or {'success': True}))
    delete_account(user_id)
    assert calls == [f'sub_{tag}', f'sub_{tag}']
    assert db.session.get(User, user_id) is None


def _login(app, user):
    c = app.test_client()
    g.pop('_login_user', None)
    assert c.post('/login', data={'email': user.email, 'password': PASSWORD}).status_code == 302
    g.pop('_login_user', None)
    return c


def test_route_needs_password_and_the_word_delete(app, db_session):
    from models import User, db
    user = _user(db, User, uuid.uuid4().hex[:8])
    user_id = user.id
    c = _login(app, user)
    try:
        assert c.post('/api/account/delete', json={'password': PASSWORD}).status_code == 400
        assert c.post('/api/account/delete', json={'confirm': 'DELETE', 'password': 'nope'}).status_code == 403
        assert db.session.get(User, user_id) is not None
        resp = c.post('/api/account/delete', json={'confirm': 'DELETE', 'password': PASSWORD})
        assert resp.status_code == 200 and resp.get_json()['success']
        assert db.session.get(User, user_id) is None
        g.pop('_login_user', None)
        assert c.get('/settings').status_code in (302, 401), 'signed out afterwards'
    finally:
        g.pop('_login_user', None)


def test_platform_admin_cannot_delete_themselves_here(app, db_session):
    from models import User, db
    from services.account_deletion import blocking_reason
    admin = _user(db, User, uuid.uuid4().hex[:8], role='admin')
    assert 'admin' in blocking_reason(admin)
    db.session.delete(admin)
    db.session.commit()


def test_settings_page_has_the_delete_box():
    html = (ROOT / 'templates' / 'settings.html').read_text()
    assert 'id="deleteAccountBox"' in html and "/api/account/delete" in html


def test_admin_delete_user_uses_the_fk_walking_delete(app, db_session, fk_checks):
    from models import Conversation, User, db
    tag = uuid.uuid4().hex[:8]
    admin = _user(db, User, tag + 'a', role='admin')
    target = _user(db, User, tag + 't')
    target_id, admin_id = target.id, admin.id
    db.session.add(Conversation(id=uuid.uuid4().hex[:20], user_id=target_id))
    db.session.commit()
    c = _login(app, admin)
    try:
        r = c.post(f'/admin/users/{target_id}/delete', json={})
        assert r.status_code == 200, r.get_data(as_text=True)[:300]
        assert db.session.get(User, target_id) is None
    finally:
        g.pop('_login_user', None)
        db.session.delete(db.session.get(User, admin_id))
        db.session.commit()
