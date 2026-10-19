"""
Pytest Configuration and Fixtures

Provides shared fixtures for all tests.
Uses SQLite in-memory with StaticPool so all connections share the same DB,
preventing the isolation issue where test-client requests see an empty DB.
"""

import os
import pytest

# Set test environment before importing app
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = 'true'
# Force SQLite in-memory for tests — overrides any external DATABASE_URL
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

# Diagnostic scripts (not real pytest suites): they make live AWS/Stripe API
# calls and use print()/return instead of assertions, so pytest would collect
# their test_*-prefixed helpers and report trivial passes. Run them directly
# (e.g. `python tests/test_stripe.py`) — exclude them from collection here.
collect_ignore = [
    'test_stripe.py',
    'test_secrets_manager.py',
]


@pytest.fixture(scope='session')
def app():
    """Create application for testing with a shared in-memory SQLite database."""
    from app import app as flask_app
    from models import db
    from sqlalchemy.pool import StaticPool

    flask_app.config.update({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key',
        'ANTHROPIC_API_KEY': 'test-api-key',
        'RATELIMIT_ENABLED': False,
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'connect_args': {'check_same_thread': False},
            'poolclass': StaticPool,
        },
    })

    from app import limiter
    limiter.enabled = False

    ctx = flask_app.app_context()
    ctx.push()
    db.create_all()

    yield flask_app

    db.session.remove()
    db.drop_all()
    ctx.pop()


@pytest.fixture(scope='function')
def client(app):
    """Create test client with clean auth state."""
    from flask import g
    # Flask-Login caches the user on g._login_user (persistent app context).
    # Clear it so a new client starts unauthenticated.
    g.pop('_login_user', None)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess.clear()
    return c


@pytest.fixture(scope='function')
def db_session(app):
    """Yield the current db session; rollback uncommitted changes after each test."""
    from models import db
    yield db.session
    db.session.rollback()
    db.session.expire_all()


@pytest.fixture
def test_user(app, db_session):
    """Create a test user, cleaning up any leftover from previous runs."""
    from models import User, db

    # Clean up both by email AND username to avoid unique constraint errors
    for existing in User.query.filter(
        (User.email == 'test@example.com') | (User.username == 'testuser')
    ).all():
        db.session.delete(existing)
    db.session.commit()

    user = User(
        email='test@example.com',
        username='testuser',
        full_name='Test User'
    )
    user.set_password('TestPassword123!')
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
def authenticated_client(client, test_user):
    """Create authenticated test client by logging in via the actual login route."""
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPassword123!'
    })
    assert response.status_code == 302, f"Login failed with status {response.status_code}"
    return client


@pytest.fixture
def test_api_key(app, test_user, db_session):
    """Create a test API key."""
    from models import APIKey, db

    key = 'doa_test_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
    api_key = APIKey(
        user_id=test_user.id,
        name='Test API Key',
        key_prefix=key[:8],
        key_hash=APIKey.hash_key(key),
        scopes=['read', 'write', 'admin']
    )
    db.session.add(api_key)
    db.session.commit()

    yield {'model': api_key, 'key': key}

    try:
        k = APIKey.query.get(api_key.id)
        if k:
            db.session.delete(k)
            db.session.commit()
    except Exception:
        db.session.rollback()


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

    try:
        s = UserSubscription.query.get(subscription.id)
        if s:
            db.session.delete(s)
            db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture(autouse=True)
def _approval_runs_inline(monkeypatch):
    """Approved actions run on a background thread in production; run them inline in tests.

    The suite shares one in-memory SQLite connection, so a real second thread
    writing to it would be flaky. tests/test_approval_background_run.py covers
    the deferred behaviour by capturing the job instead of running it.
    """
    try:
        from services import approval_service
    except Exception:
        return

    def _inline(fn):
        fn()
        _expire_approval_rows()  # the job wrote through its own session

    monkeypatch.setattr(approval_service, '_start_background', _inline)


def _expire_approval_rows():
    """Reload ApprovalRequest rows a background job changed through its own session.

    Only these: expire_all() on the suite's shared session would also expire
    leftovers from earlier tests whose rows were since bulk-deleted.
    """
    from models import db, ApprovalRequest
    for obj in list(db.session.identity_map.values()):
        if isinstance(obj, ApprovalRequest):
            db.session.expire(obj)
