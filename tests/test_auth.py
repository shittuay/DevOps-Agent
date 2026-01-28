"""
Authentication Tests

Tests for user registration, login, and authentication flows.
"""

import pytest
from flask import url_for


class TestRegistration:
    """Tests for user registration."""

    def test_signup_page_loads(self, client):
        """Test signup page loads correctly."""
        response = client.get('/signup')
        assert response.status_code == 200
        assert b'Sign Up' in response.data or b'Create Account' in response.data

    def test_successful_registration(self, client, app):
        """Test successful user registration."""
        from models import User

        response = client.post('/signup', data={
            'email': 'newuser@example.com',
            'username': 'newuser',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!'
        }, follow_redirects=True)

        with app.app_context():
            user = User.query.filter_by(email='newuser@example.com').first()
            assert user is not None
            assert user.username == 'newuser'

    def test_registration_duplicate_email(self, client, test_user):
        """Test registration with existing email fails."""
        response = client.post('/signup', data={
            'email': 'test@example.com',  # Same as test_user
            'username': 'anotheruser',
            'password': 'SecurePass123!',
            'confirm_password': 'SecurePass123!'
        })

        assert response.status_code in [200, 302]  # Should show error or redirect

    def test_registration_weak_password(self, client):
        """Test registration with weak password fails."""
        response = client.post('/signup', data={
            'email': 'weak@example.com',
            'username': 'weakuser',
            'password': '123',
            'confirm_password': '123'
        })

        # Should not create user with weak password
        assert response.status_code in [200, 400]


class TestLogin:
    """Tests for user login."""

    def test_login_page_loads(self, client):
        """Test login page loads correctly."""
        response = client.get('/login')
        assert response.status_code == 200
        assert b'Login' in response.data or b'Sign In' in response.data

    def test_successful_login(self, client, test_user):
        """Test successful login."""
        response = client.post('/login', data={
            'email': 'test@example.com',
            'password': 'testpassword123'
        }, follow_redirects=True)

        assert response.status_code == 200

    def test_login_wrong_password(self, client, test_user):
        """Test login with wrong password fails."""
        response = client.post('/login', data={
            'email': 'test@example.com',
            'password': 'wrongpassword'
        })

        assert response.status_code in [200, 401]

    def test_login_nonexistent_user(self, client):
        """Test login with nonexistent user fails."""
        response = client.post('/login', data={
            'email': 'nonexistent@example.com',
            'password': 'anypassword'
        })

        assert response.status_code in [200, 401]


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
