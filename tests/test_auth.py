"""
Authentication Tests

Tests for user registration, login, and authentication flows.
"""

import pytest


class TestRegistration:
    """Tests for user registration."""

    def test_signup_page_loads(self, client):
        """Test signup page loads correctly."""
        response = client.get('/signup')
        assert response.status_code == 200

    def test_successful_registration(self, client, app, db_session):
        """Test successful user registration."""
        from models import User, db

        response = client.post('/signup', data={
            'email': 'newuser@example.com',
            'username': 'newuser',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!',
            'full_name': 'New User'
        }, follow_redirects=True)

        assert response.status_code == 200

        user = User.query.filter_by(email='newuser@example.com').first()
        assert user is not None
        assert user.username == 'newuser'
        db.session.delete(user)
        db.session.commit()

    def test_registration_duplicate_email(self, client, test_user):
        """Test registration with existing email fails."""
        response = client.post('/signup', data={
            'email': 'test@example.com',
            'username': 'anotheruser',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!',
            'full_name': 'Another User'
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'already registered' in response.data.lower() or b'already' in response.data.lower()

    def test_registration_weak_password(self, client, app):
        """Test registration with weak password fails."""
        from models import User

        response = client.post('/signup', data={
            'email': 'weak@example.com',
            'username': 'weakuser',
            'password': '123',
            'confirm_password': '123'
        }, follow_redirects=True)

        # Verify user was NOT created regardless of response code
        with app.app_context():
            user = User.query.filter_by(email='weak@example.com').first()
            assert user is None

    def test_registration_missing_uppercase(self, client, app):
        """Test registration requires uppercase letter."""
        from models import User

        response = client.post('/signup', data={
            'email': 'noupper@example.com',
            'username': 'noupperuser',
            'password': 'securepass123!',
            'confirm_password': 'securepass123!'
        }, follow_redirects=True)

        # Verify user was NOT created
        with app.app_context():
            user = User.query.filter_by(email='noupper@example.com').first()
            assert user is None


class TestLogin:
    """Tests for user login."""

    def test_login_page_loads(self, client):
        """Test login page loads correctly (200 or 302 redirect to chat if session exists)."""
        response = client.get('/login')
        assert response.status_code in [200, 302]

    def test_successful_login(self, client, test_user):
        """Test successful login."""
        response = client.post('/login', data={
            'email': 'test@example.com',
            'password': 'TestPassword123!'
        }, follow_redirects=True)
        assert response.status_code == 200

    def test_login_wrong_password(self, client, test_user):
        """Test login with wrong password fails."""
        response = client.post('/login', data={
            'email': 'test@example.com',
            'password': 'WrongPassword123!'
        }, follow_redirects=True)
        assert response.status_code == 200
        assert b'Invalid' in response.data or b'invalid' in response.data

    def test_login_nonexistent_user(self, client):
        """Test login with nonexistent user fails."""
        response = client.post('/login', data={
            'email': 'nonexistent@example.com',
            'password': 'AnyPassword123!'
        }, follow_redirects=True)
        assert response.status_code == 200


class TestLogout:
    """Tests for user logout."""

    def test_logout(self, authenticated_client):
        """Test logout works correctly."""
        response = authenticated_client.get('/logout', follow_redirects=True)
        assert response.status_code == 200


class TestPasswordSecurity:
    """Tests for password security."""

    def test_password_hashing(self, app):
        """Test passwords are properly hashed."""
        from models import User

        with app.app_context():
            user = User(email='hash@test.com', username='hashtest')
            user.set_password('mypassword')

            assert user.password_hash != 'mypassword'
            assert user.check_password('mypassword')
            assert not user.check_password('wrongpassword')

    def test_account_lockout(self, app, test_user):
        """Test account locks after failed attempts."""
        with app.app_context():
            for _ in range(5):
                test_user.record_failed_login()

            assert test_user.is_locked()
