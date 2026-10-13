"""
Authentication Tests

Tests for user registration, login, and authentication flows.
"""

from unittest.mock import MagicMock, patch

import pytest


class _ImmediateThread:
    """Stand-in for threading.Thread that runs its target synchronously on
    .start() instead of spawning a real thread — lets tests exercise the
    background closure's own logic deterministically."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


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

    def test_login_email_is_case_insensitive(self, client, test_user):
        """Mobile keyboards capitalize the first letter; that must not reject a valid login."""
        response = client.post('/login', data={
            'email': 'Test@Example.com',
            'password': 'TestPassword123!'
        })
        assert response.status_code == 302
        assert '/login' not in response.headers['Location']

    def test_login_matches_mixed_case_stored_email(self, client, test_user, db_session):
        """Accounts stored before signup lowercased emails still log in."""
        from models import db
        test_user.email = 'Test@Example.com'
        db.session.commit()
        response = client.post('/login', data={
            'email': 'test@example.com',
            'password': 'TestPassword123!'
        })
        assert response.status_code == 302
        assert '/login' not in response.headers['Location']

    def test_login_username_stays_case_sensitive(self, client, test_user):
        response = client.post('/login', data={
            'email': 'TestUser',
            'password': 'TestPassword123!'
        })
        assert response.status_code == 200
        assert b'Invalid' in response.data

    def test_login_nonexistent_user(self, client):
        """Test login with nonexistent user fails."""
        response = client.post('/login', data={
            'email': 'nonexistent@example.com',
            'password': 'AnyPassword123!'
        }, follow_redirects=True)
        assert response.status_code == 200


class TestLoginTimingSideChannel:
    """A nonexistent account and a wrong password must be indistinguishable
    by response time, not just error text — login() previously returned
    immediately for an unknown email/username, skipping User.check_password()
    (bcrypt, deliberately slow) entirely, while a wrong password on a real
    account paid that cost. Asserting on the mechanism (bcrypt always invoked)
    rather than wall-clock time, since real timing assertions are flaky under
    CI load.
    """

    def test_nonexistent_user_still_invokes_bcrypt(self, client):
        with patch('routes.auth.bcrypt.checkpw', return_value=False) as mock_checkpw:
            client.post('/login', data={
                'email': 'nonexistent@example.com',
                'password': 'AnyPassword123!'
            })

        mock_checkpw.assert_called_once()
        args = mock_checkpw.call_args.args
        assert args[0] == b'AnyPassword123!'
        assert args[1] == b'$2b$12$9kf93ejgP7rGjtdLIjO4neb2MCGNWpSDYDBFDRKjxcwn4BlHraYDm'

    def test_existing_user_wrong_password_invokes_bcrypt_against_real_hash(self, client, test_user):
        with patch('routes.auth.bcrypt.checkpw', return_value=False) as mock_checkpw:
            client.post('/login', data={
                'email': 'test@example.com',
                'password': 'WrongPassword123!'
            })

        mock_checkpw.assert_called_once()
        args = mock_checkpw.call_args.args
        assert args[0] == b'WrongPassword123!'
        assert args[1] == test_user.password_hash.encode('utf-8')

    def test_run_timing_safe_password_check_dummy_path_never_matches(self, app):
        from routes.auth import _run_timing_safe_password_check
        with app.app_context():
            assert _run_timing_safe_password_check(None, 'whatever-password') is False

    def test_run_timing_safe_password_check_real_user_path(self, app, test_user):
        from routes.auth import _run_timing_safe_password_check
        with app.app_context():
            assert _run_timing_safe_password_check(test_user, 'TestPassword123!') is True
            assert _run_timing_safe_password_check(test_user, 'WrongPassword123!') is False


class TestForgotPasswordTimingSideChannel:
    """The email dispatch for an existing account must not block the HTTP
    response — forgot_password() previously did a DB write plus a
    synchronous, network-variable email API call (up to a 10s timeout) only
    when the account existed, while a nonexistent email returned immediately.
    Both render the identical generic success message, so response *time*
    was the leak. Asserting on the mechanism (background thread dispatched,
    request itself does no DB write) rather than wall-clock timing, which
    would be flaky under CI load.
    """

    def test_existing_user_dispatches_background_thread(self, client, test_user):
        with patch('routes.auth.threading.Thread') as MockThread:
            response = client.post('/forgot-password', data={'email': 'test@example.com'})

        assert response.status_code == 200
        MockThread.assert_called_once()
        _, kwargs = MockThread.call_args
        assert kwargs['daemon'] is True
        assert callable(kwargs['target'])
        MockThread.return_value.start.assert_called_once()

    def test_existing_user_request_itself_does_no_db_write(self, client, test_user, db_session):
        """The token generation/DB write must happen in the background
        thread, not inline in the request — otherwise the timing gap
        this fix closes would just move from "email send" to "DB write".
        threading.Thread is mocked out entirely here, so its .start() is a
        no-op that never actually runs the closure — if the route wrote to
        the DB directly (not inside the closure), it would show up here."""
        with patch('routes.auth.threading.Thread'):
            client.post('/forgot-password', data={'email': 'test@example.com'})

        db_session.refresh(test_user)
        assert test_user.password_reset_token is None

    def test_nonexistent_user_does_not_dispatch_any_work(self, client):
        with patch('routes.auth.threading.Thread') as MockThread:
            response = client.post('/forgot-password', data={'email': 'nobody-here@example.com'})

        assert response.status_code == 200
        MockThread.assert_not_called()

    def test_both_cases_return_identical_success_message(self, client, test_user):
        with patch('routes.auth.threading.Thread'):
            existing_resp = client.post('/forgot-password', data={'email': 'test@example.com'}, follow_redirects=True)
        nonexistent_resp = client.post('/forgot-password', data={'email': 'nobody-here@example.com'}, follow_redirects=True)

        assert existing_resp.status_code == nonexistent_resp.status_code == 200
        assert b'If an account with that email exists' in existing_resp.data
        assert b'If an account with that email exists' in nonexistent_resp.data

    def test_dispatch_helper_generates_token_and_sends_email(self, app, test_user):
        """Runs the background closure's own logic synchronously (via
        _ImmediateThread) to verify token generation, persistence, and the
        email call all happen correctly — independent of the route test
        above, which only checks that dispatch was attempted.

        The closure's own `with flask_app.app_context()` pops (and tears
        down Flask-SQLAlchemy's scoped session) before this function
        continues, so `test_user` and the mock's captured argument may be
        detached by then — capture the plain id upfront and re-query fresh
        afterward rather than touching either ORM object post-dispatch."""
        from routes.auth import _dispatch_password_reset_email
        from models import db, User

        expected_user_id = test_user.id

        with app.test_request_context():
            with patch('routes.auth.threading.Thread', _ImmediateThread), \
                 patch('services.email_service.email_service.send_password_reset_email') as mock_send:
                _dispatch_password_reset_email(expected_user_id)

        mock_send.assert_called_once()

        # The commit happened on a different (nested-app-context) session —
        # this test's ambient session may still have `test_user` cached from
        # before the dispatch, so force a real re-read instead of trusting
        # the identity map.
        db.session.expire_all()
        refreshed = User.query.get(expected_user_id)
        assert refreshed.password_reset_token is not None
        assert refreshed.password_reset_expires is not None

    def test_dispatch_helper_handles_deleted_user_gracefully(self, app, db_session):
        """user_id captured at request time could be stale by the time the
        background thread runs (e.g. account deleted in between) — must not
        raise inside the thread."""
        from routes.auth import _dispatch_password_reset_email

        with app.test_request_context():
            with patch('routes.auth.threading.Thread', _ImmediateThread), \
                 patch('services.email_service.email_service.send_password_reset_email') as mock_send:
                _dispatch_password_reset_email(user_id=999999999)

        mock_send.assert_not_called()


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


class TestSmsMfaRemoved:
    """SMS codes were never delivered and were removed; existing SMS users must
    fall back to email codes rather than be locked out."""

    def test_sms_user_is_migrated_to_email_and_can_log_in(self, client, test_user, db_session):
        from unittest.mock import patch
        from models import db, User

        test_user.mfa_method = 'sms'
        test_user.phone_number = '+15555550100'
        test_user.phone_verified = True
        db.session.commit()

        sent = {}
        with patch('services.email_service.email_service.send_otp_email',
                   side_effect=lambda user, code: sent.setdefault('code', code) or True):
            resp = client.post('/login', data={
                'email': 'test@example.com', 'password': 'TestPassword123!',
            })

        assert resp.status_code == 302
        assert '/verify-2fa' in resp.headers['Location']
        assert 'code' in sent
        assert User.query.get(test_user.id).mfa_method == 'email'

        resp = client.post('/verify-2fa', data={'code': sent['code']})
        assert resp.status_code == 302
        assert '/verify-2fa' not in resp.headers['Location']
        assert '/login' not in resp.headers['Location']

    def test_sms_can_no_longer_be_chosen(self, authenticated_client):
        resp = authenticated_client.post('/api/mfa/set-method', json={'method': 'sms'})
        assert resp.status_code == 400
        assert 'SMS' in resp.get_json()['error']

    def test_phone_endpoints_are_gone(self, authenticated_client):
        resp = authenticated_client.post('/api/mfa/phone/add', json={'phone_number': '+15555550100'})
        assert resp.status_code == 404


class TestEmailMfaFlow:
    """The email-only paths left after SMS removal: resend, method activation,
    and the login-time send failure."""

    def _start_login(self, client, test_user, send_ok=True):
        from unittest.mock import patch
        from models import db
        test_user.mfa_method = 'email'
        db.session.commit()
        with patch('services.email_service.email_service.send_otp_email', return_value=send_ok):
            return client.post('/login', data={
                'email': 'test@example.com', 'password': 'TestPassword123!',
            })

    def test_email_send_failure_returns_to_login_and_clears_pending_state(self, client, test_user, db_session):
        resp = self._start_login(client, test_user, send_ok=False)
        assert resp.status_code == 200
        assert b'Failed to send verification email' in resp.data
        with client.session_transaction() as sess:
            assert '2fa_pending_user' not in sess

    def test_resend_sends_a_new_email_code(self, client, test_user, db_session):
        from datetime import timedelta
        from unittest.mock import patch
        from models import db, User
        from src.utils.timeutils import utcnow

        self._start_login(client, test_user)
        user = User.query.get(test_user.id)
        user.mfa_otp_sent_at = utcnow() - timedelta(minutes=2)
        db.session.commit()

        with patch('services.email_service.email_service.send_otp_email', return_value=True) as send:
            resp = client.post('/api/2fa/resend-otp')
        assert resp.status_code == 200
        assert resp.get_json()['message'] == 'Code resent via email.'
        send.assert_called_once()

    def test_resend_reports_email_failure(self, client, test_user, db_session):
        from datetime import timedelta
        from unittest.mock import patch
        from models import db, User
        from src.utils.timeutils import utcnow

        self._start_login(client, test_user)
        user = User.query.get(test_user.id)
        user.mfa_otp_sent_at = utcnow() - timedelta(minutes=2)
        db.session.commit()

        with patch('services.email_service.email_service.send_otp_email', return_value=False):
            resp = client.post('/api/2fa/resend-otp')
        assert resp.status_code == 500

    def test_resend_without_pending_session_is_rejected(self, client):
        resp = client.post('/api/2fa/resend-otp')
        assert resp.status_code == 400

    def test_activate_email_mfa(self, authenticated_client, test_user, db_session):
        from unittest.mock import patch
        from models import db, User

        test_user.email_verified = True
        db.session.commit()
        sent = {}
        with patch('services.email_service.email_service.send_otp_email',
                   side_effect=lambda user, code: sent.setdefault('code', code) or True):
            resp = authenticated_client.post('/api/mfa/set-method', json={'method': 'email'})
        assert resp.status_code == 200
        assert resp.get_json()['action'] == 'verify_otp'

        resp = authenticated_client.post('/api/mfa/verify-method',
                                         json={'method': 'email', 'code': sent['code']})
        assert resp.status_code == 200
        assert len(resp.get_json()['backup_codes']) > 0
        assert User.query.get(test_user.id).mfa_method == 'email'

    def test_verify_method_rejects_sms(self, authenticated_client):
        resp = authenticated_client.post('/api/mfa/verify-method', json={'method': 'sms', 'code': '123456'})
        assert resp.status_code == 400


class TestVerify2faPaths:
    """Behaviour of /verify-2fa's failure and fallback paths, pinned so the
    helper split (SonarCloud complexity) can't change what users see."""

    def _pending_totp(self, client, test_user):
        import pyotp
        from models import db
        secret = pyotp.random_base32()
        test_user.mfa_method = 'totp'
        test_user.two_factor_secret = secret
        db.session.commit()
        resp = client.post('/login', data={'email': 'test@example.com', 'password': 'TestPassword123!'})
        assert '/verify-2fa' in resp.headers['Location']
        return secret

    def test_get_renders_the_form(self, client, test_user, db_session):
        self._pending_totp(client, test_user)
        assert client.get('/verify-2fa').status_code == 200

    def test_no_pending_login_redirects_to_login(self, client):
        resp = client.get('/verify-2fa')
        assert resp.status_code == 302 and '/login' in resp.headers['Location']

    def test_expired_pending_login_says_so_and_clears_session(self, client, test_user, db_session):
        self._pending_totp(client, test_user)
        with client.session_transaction() as sess:
            sess['2fa_pending_time'] = '2000-01-01T00:00:00'
        resp = client.get('/verify-2fa')
        assert resp.status_code == 200 and b'timed out' in resp.data
        with client.session_transaction() as sess:
            assert '2fa_pending_user' not in sess

    def test_empty_code_is_rejected(self, client, test_user, db_session):
        self._pending_totp(client, test_user)
        resp = client.post('/verify-2fa', data={'code': ''})
        assert b'Please enter a verification code.' in resp.data

    def test_wrong_code_counts_down_then_locks(self, client, test_user, db_session):
        from models import User
        self._pending_totp(client, test_user)
        resp = client.post('/verify-2fa', data={'code': '000000'})
        assert b'Invalid code. 4 attempts remaining.' in resp.data
        for _ in range(4):
            resp = client.post('/verify-2fa', data={'code': '000000'})
        assert b'Account locked for 15 minutes.' in resp.data
        assert User.query.get(test_user.id).two_factor_locked_until is not None

        resp = client.post('/verify-2fa', data={'code': '000000'})
        assert b'Too many failed attempts. Try again in' in resp.data

    def test_expired_lock_is_cleared_and_valid_code_logs_in(self, client, test_user, db_session):
        import pyotp
        from datetime import timedelta
        from models import db
        from src.utils.timeutils import utcnow
        secret = self._pending_totp(client, test_user)
        test_user.two_factor_locked_until = utcnow() - timedelta(minutes=1)
        test_user.two_factor_attempts = 5
        db.session.commit()
        resp = client.post('/verify-2fa', data={'code': pyotp.TOTP(secret).now()})
        assert resp.status_code == 302 and '/verify-2fa' not in resp.headers['Location']

    def test_backup_code_logs_in_and_is_consumed(self, client, test_user, db_session):
        from models import db, User
        from services.two_factor_service import two_factor_service
        self._pending_totp(client, test_user)
        codes = two_factor_service.generate_backup_codes()
        test_user.backup_codes = [two_factor_service.hash_backup_code(c) for c in codes]
        db.session.commit()
        resp = client.post('/verify-2fa', data={'code': codes[0]})
        assert resp.status_code == 302 and '/verify-2fa' not in resp.headers['Location']
        assert len(User.query.get(test_user.id).backup_codes) == len(codes) - 1

    def test_safe_next_is_honoured(self, client, test_user, db_session):
        import pyotp
        from models import db
        secret = pyotp.random_base32()
        test_user.mfa_method = 'totp'
        test_user.two_factor_secret = secret
        db.session.commit()
        client.post('/login?next=/settings', data={'email': 'test@example.com', 'password': 'TestPassword123!'})
        resp = client.post('/verify-2fa', data={'code': pyotp.TOTP(secret).now()})
        assert resp.headers['Location'].endswith('/settings')
