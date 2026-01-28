"""
Model Tests

Tests for database models.
"""

import pytest
from datetime import datetime, timedelta


class TestUserModel:
    """Tests for User model."""

    def test_create_user(self, app):
        """Test creating a user."""
        from models import User, db

        with app.app_context():
            user = User(
                email='model@test.com',
                username='modeltest',
                full_name='Model Test'
            )
            user.set_password('testpassword')
            db.session.add(user)
            db.session.commit()

            assert user.id is not None
            assert user.email == 'model@test.com'
            assert user.check_password('testpassword')

            # Cleanup
            db.session.delete(user)
            db.session.commit()

    def test_user_avatar_initials(self, app):
        """Test user avatar initials generation."""
        from models import User

        with app.app_context():
            user = User(email='test@test.com', username='test', full_name='John Doe')
            assert user.get_avatar_initials() == 'JD'

            user.full_name = 'Jane'
            assert user.get_avatar_initials() == 'J'

            user.full_name = None
            assert user.get_avatar_initials() == 'T'  # First letter of username

    def test_user_to_dict(self, app, test_user):
        """Test user serialization."""
        with app.app_context():
            data = test_user.to_dict()

            assert 'id' in data
            assert 'email' in data
            assert 'username' in data
            assert 'password_hash' not in data  # Should not expose password


class TestConversationModel:
    """Tests for Conversation model."""

    def test_create_conversation(self, app, test_user):
        """Test creating a conversation."""
        from models import Conversation, db
        import uuid

        with app.app_context():
            conv = Conversation(
                id=str(uuid.uuid4()),
                user_id=test_user.id,
                title='Test Conversation'
            )
            db.session.add(conv)
            db.session.commit()

            assert conv.id is not None
            assert conv.title == 'Test Conversation'
            assert conv.user_id == test_user.id

            # Cleanup
            db.session.delete(conv)
            db.session.commit()


class TestAPIKeyModel:
    """Tests for APIKey model."""

    def test_generate_key(self, app):
        """Test API key generation."""
        from models import APIKey

        with app.app_context():
            key = APIKey.generate_key()
            assert key.startswith('doa_live_')
            assert len(key) == 41  # doa_live_ (9) + 32 hex chars

    def test_hash_key(self, app):
        """Test API key hashing."""
        from models import APIKey

        with app.app_context():
            key = 'doa_live_test123'
            hash1 = APIKey.hash_key(key)
            hash2 = APIKey.hash_key(key)

            assert hash1 == hash2
            assert hash1 != key
            assert len(hash1) == 64  # SHA-256 hex

    def test_has_scope(self, app, test_api_key):
        """Test API key scope checking."""
        with app.app_context():
            api_key = test_api_key['model']

            assert api_key.has_scope('read')
            assert api_key.has_scope('write')
            assert api_key.has_scope('admin')

            api_key.scopes = ['read']
            assert api_key.has_scope('read')
            assert not api_key.has_scope('write')


class TestSubscriptionModel:
    """Tests for subscription models."""

    def test_subscription_credits(self, app, test_subscription):
        """Test subscription credit management."""
        with app.app_context():
            assert test_subscription.has_credits()
            assert test_subscription.credits_remaining == 100

            # Use a credit
            result = test_subscription.use_credit()
            assert result == True
            assert test_subscription.credits_remaining == 99
            assert test_subscription.credits_used_this_month == 1

    def test_subscription_no_credits(self, app, test_subscription):
        """Test subscription with no credits."""
        with app.app_context():
            test_subscription.credits_remaining = 0

            assert not test_subscription.has_credits()
            result = test_subscription.use_credit()
            assert result == False


class TestAuditLogModel:
    """Tests for AuditLog model."""

    def test_create_audit_log(self, app, test_user):
        """Test creating an audit log entry."""
        from models import AuditLog, db

        with app.app_context():
            log = AuditLog.log(
                action='test_action',
                category='auth',
                user_id=test_user.id,
                description='Test audit log entry'
            )

            assert log.id is not None
            assert log.action == 'test_action'
            assert log.action_category == 'auth'
            assert log.user_id == test_user.id

            # Cleanup
            db.session.delete(log)
            db.session.commit()

    def test_audit_log_to_dict(self, app, test_user):
        """Test audit log serialization."""
        from models import AuditLog, db

        with app.app_context():
            log = AuditLog.log(
                action='serialize_test',
                category='settings',
                user_id=test_user.id
            )

            data = log.to_dict()
            assert 'id' in data
            assert 'action' in data
            assert 'created_at' in data

            # Cleanup
            db.session.delete(log)
            db.session.commit()
