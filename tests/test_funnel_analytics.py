"""Funnel analytics: distinct-user counts per milestone.

These lock in the behaviour that makes the numbers trustworthy at low volume:
counting distinct *users* rather than rows, and treating a second calendar day
as the retention signal rather than a second conversation.
"""

from datetime import datetime, timedelta

import pytest

from models import (
    db, User, Conversation, ChatMessage, UserCloudCredential, CheckoutAttempt,
)
from services.funnel_analytics import (
    get_funnel, get_checkout_summary, get_checkout_attempts, STAGE_ORDER,
)


def _stage(funnel, key):
    for s in funnel['stages']:
        if s['key'] == key:
            return s
    raise AssertionError(f'stage {key} missing from funnel')


@pytest.fixture
def clean_funnel_data(app, db_session):
    """Remove rows that would otherwise leak between funnel assertions."""
    CheckoutAttempt.query.delete()
    ChatMessage.query.delete()
    Conversation.query.delete()
    UserCloudCredential.query.delete()
    db.session.commit()
    yield
    CheckoutAttempt.query.delete()
    ChatMessage.query.delete()
    Conversation.query.delete()
    UserCloudCredential.query.delete()
    db.session.commit()


def _make_conversation(user, cid='conv-funnel-1'):
    conv = Conversation(id=cid, user_id=user.id, title='t')
    db.session.add(conv)
    db.session.commit()
    return conv


def _add_message(user, conv, when, role='user', content='hi'):
    msg = ChatMessage(
        user_id=user.id, conversation_id=conv.id,
        role=role, content=content, timestamp=when,
    )
    db.session.add(msg)
    db.session.commit()
    return msg


class TestFunnelShape:
    def test_all_stages_present_and_ordered(self, app, clean_funnel_data):
        funnel = get_funnel()
        assert [s['key'] for s in funnel['stages']] == STAGE_ORDER

    def test_empty_database_does_not_divide_by_zero(self, app, db_session, clean_funnel_data):
        User.query.delete()
        db.session.commit()
        funnel = get_funnel()
        assert funnel['signed_up'] == 0
        for s in funnel['stages']:
            assert s['count'] == 0
            assert s['pct_of_signups'] == 0.0


class TestStageCounting:
    def test_signup_counts_once(self, app, test_user, clean_funnel_data):
        assert get_funnel()['signed_up'] >= 1

    def test_message_stage_counts_users_not_messages(self, app, test_user, clean_funnel_data):
        """Forty messages from one user is one user, not forty.

        This is the distinction that separates 'nobody came' from 'one person
        loved it', and it is invisible in a raw message count.
        """
        conv = _make_conversation(test_user)
        base = datetime(2026, 8, 1, 12, 0, 0)
        for i in range(40):
            _add_message(test_user, conv, base + timedelta(minutes=i))

        assert _stage(get_funnel(), 'sent_first_message')['count'] == 1

    def test_assistant_messages_do_not_count_as_user_activity(self, app, test_user, clean_funnel_data):
        conv = _make_conversation(test_user)
        _add_message(test_user, conv, datetime(2026, 8, 1, 12, 0), role='assistant')

        assert _stage(get_funnel(), 'sent_first_message')['count'] == 0

    def test_returned_requires_two_distinct_days(self, app, test_user, clean_funnel_data):
        """Two chats in one sitting is one session, not a return visit."""
        conv = _make_conversation(test_user)
        _add_message(test_user, conv, datetime(2026, 8, 1, 9, 0))
        _add_message(test_user, conv, datetime(2026, 8, 1, 23, 0))

        assert _stage(get_funnel(), 'returned')['count'] == 0

        _add_message(test_user, conv, datetime(2026, 8, 2, 9, 0))
        assert _stage(get_funnel(), 'returned')['count'] == 1

    def test_cloud_credential_stage(self, app, test_user, clean_funnel_data):
        assert _stage(get_funnel(), 'connected_cloud')['count'] == 0

        cred = UserCloudCredential(
            user_id=test_user.id, cloud_provider='aws',
            credentials_encrypted='x', is_active=True,
        )
        db.session.add(cred)
        db.session.commit()

        assert _stage(get_funnel(), 'connected_cloud')['count'] == 1


class TestCheckoutStage:
    def test_created_attempt_reaches_checkout_but_is_not_paid(self, app, test_user, clean_funnel_data):
        db.session.add(CheckoutAttempt(
            user_id=test_user.id, product_type='subscription',
            product_key='starter', currency='USD', status='created',
        ))
        db.session.commit()

        funnel = get_funnel()
        assert _stage(funnel, 'reached_checkout')['count'] == 1
        assert _stage(funnel, 'paid')['count'] == 0

    def test_failed_attempt_still_counts_as_reaching_checkout(self, app, test_user, clean_funnel_data):
        """A user blocked by a bad API key tried to pay. That must stay visible."""
        db.session.add(CheckoutAttempt(
            user_id=test_user.id, product_type='subscription',
            product_key='starter', currency='USD', status='failed',
            error_message='Invalid API Key provided',
        ))
        db.session.commit()

        funnel = get_funnel()
        assert _stage(funnel, 'reached_checkout')['count'] == 1
        assert _stage(funnel, 'paid')['count'] == 0
        assert get_checkout_summary()['failed'] == 1

    def test_completed_attempt_counts_as_paid(self, app, test_user, clean_funnel_data):
        db.session.add(CheckoutAttempt(
            user_id=test_user.id, product_type='subscription',
            product_key='starter', currency='USD', status='completed',
            completed_at=datetime.utcnow(),
        ))
        db.session.commit()

        assert _stage(get_funnel(), 'paid')['count'] == 1

    def test_repeat_attempts_count_one_user(self, app, test_user, clean_funnel_data):
        for _ in range(5):
            db.session.add(CheckoutAttempt(
                user_id=test_user.id, product_type='credit_pack',
                product_key='pack_100', currency='NGN', status='failed',
            ))
        db.session.commit()

        assert _stage(get_funnel(), 'reached_checkout')['count'] == 1
        assert get_checkout_summary()['failed'] == 5

    def test_checkout_attempts_listing_includes_error(self, app, test_user, clean_funnel_data):
        db.session.add(CheckoutAttempt(
            user_id=test_user.id, product_type='subscription',
            product_key='starter', currency='USD', status='failed',
            error_message='Invalid API Key provided',
        ))
        db.session.commit()

        rows = get_checkout_attempts(limit=5)
        assert rows
        assert rows[0]['error_message'] == 'Invalid API Key provided'
        assert rows[0]['user_email'] == test_user.email


class TestCohortWindow:
    def test_old_signup_excluded_from_recent_window(self, app, db_session, clean_funnel_data):
        old = User(email='old@example.com', username='olduser')
        old.set_password('TestPassword123!')
        old.created_at = datetime.utcnow() - timedelta(days=120)
        db.session.add(old)
        db.session.commit()

        try:
            all_time = get_funnel()['signed_up']
            last_7 = get_funnel(days=7)['signed_up']
            assert all_time >= 1
            assert last_7 < all_time
        finally:
            db.session.delete(old)
            db.session.commit()

    def test_empty_cohort_yields_zero_not_everything(self, app, test_user, clean_funnel_data):
        """An empty cohort must filter to nothing rather than fall through unfiltered."""
        conv = _make_conversation(test_user)
        _add_message(test_user, conv, datetime.utcnow())

        User.query.update({User.created_at: datetime.utcnow() - timedelta(days=365)})
        db.session.commit()

        funnel = get_funnel(days=1)
        assert funnel['signed_up'] == 0
        assert _stage(funnel, 'sent_first_message')['count'] == 0


class TestBiggestDrop:
    def test_identifies_the_stage_that_loses_most_users(self, app, db_session, clean_funnel_data):
        users = []
        for i in range(4):
            u = User(email=f'drop{i}@example.com', username=f'dropuser{i}')
            u.set_password('TestPassword123!')
            u.email_verified = True
            db.session.add(u)
            users.append(u)
        db.session.commit()

        # Only one of the four ever sends a message: the cliff is verified -> message.
        conv = Conversation(id='conv-drop', user_id=users[0].id, title='t')
        db.session.add(conv)
        db.session.commit()
        db.session.add(ChatMessage(
            user_id=users[0].id, conversation_id=conv.id,
            role='user', content='hi', timestamp=datetime.utcnow(),
        ))
        db.session.commit()

        try:
            drop = get_funnel()['biggest_drop']
            assert drop is not None
            assert drop['lost'] >= 1
        finally:
            ChatMessage.query.delete()
            Conversation.query.delete()
            for u in users:
                db.session.delete(u)
            db.session.commit()
