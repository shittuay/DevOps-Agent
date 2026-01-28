"""
Pytest Configuration and Fixtures

Provides shared fixtures for all tests.
"""

import os
import pytest
import tempfile
from datetime import datetime

# Set test environment before importing app
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = 'true'


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    from app import app as flask_app
    from models import db

    # Use a temporary database
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SECRET_KEY': 'test-secret-key',
        'ANTHROPIC_API_KEY': 'test-api-key'
    })

    # Create tables
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.drop_all()

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture(scope='function')
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(scope='function')
def db_session(app):
    """Create database session for tests."""
    from models import db

    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()

        yield db.session

        transaction.rollback()
        connection.close()


@pytest.fixture
def test_user(app, db_session):
    """Create a test user."""
    from models import User, db

    with app.app_context():
        user = User(
            email='test@example.com',
            username='testuser',
            full_name='Test User'
        )
        user.set_password('testpassword123')
        db.session.add(user)
        db.session.commit()

        yield user

        # Cleanup
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def authenticated_client(client, test_user):
    """Create authenticated test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
        sess['_fresh'] = True

    return client


@pytest.fixture
def test_api_key(app, test_user, db_session):
    """Create a test API key."""
    from models import APIKey, db

    with app.app_context():
        key = 'doa_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
        api_key = APIKey(
            user_id=test_user.id,
            name='Test API Key',
            key_prefix='doa_test_a1',
            key_hash=APIKey.hash_key(key),
            scopes=['read', 'write', 'admin']
        )
        db.session.add(api_key)
        db.session.commit()

        yield {'model': api_key, 'key': key}

        # Cleanup
        db.session.delete(api_key)
        db.session.commit()


@pytest.fixture
def api_headers(test_api_key):
    """Headers for API requests."""
    return {
        'Authorization': f'Bearer {test_api_key["key"]}',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def test_subscription(app, test_user, db_session):
    """Create a test subscription."""
    from models import SubscriptionTier, UserSubscription, db

    with app.app_context():
        # Create tier if not exists
        tier = SubscriptionTier.query.filter_by(name='test_tier').first()
        if not tier:
            tier = SubscriptionTier(
                name='test_tier',
                display_name='Test Tier',
                monthly_price=0,
                monthly_credits=100
            )
            db.session.add(tier)
            db.session.commit()

        subscription = UserSubscription(
            user_id=test_user.id,
            tier_id=tier.id,
            credits_remaining=100
        )
        db.session.add(subscription)
        db.session.commit()

        yield subscription

        # Cleanup
        db.session.delete(subscription)
        db.session.commit()
