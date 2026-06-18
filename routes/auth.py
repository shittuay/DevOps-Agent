"""
Authentication and MFA routes.
Extracted from app.py to reduce its size. All routes keep the same URL paths.
"""
import hashlib
import re
import secrets
import threading
from datetime import datetime, timedelta

from flask import (
    Blueprint, current_app, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from email_validator import EmailNotValidError, validate_email

from urllib.parse import urlparse

from extensions import limiter, security_logger
from models import db, SubscriptionTier, User, UserSubscription

auth_bp = Blueprint('auth', __name__)


def _is_safe_redirect(target: str) -> bool:
    """Reject absolute URLs and protocol-relative URLs to prevent open redirects."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    if test_url.scheme and test_url.scheme not in ('http', 'https'):
        return False
    if test_url.netloc and test_url.netloc != ref_url.netloc:
        return False
    if target.startswith('//'):
        return False
    return True


def _validate_password_strength(password: str) -> str | None:
    """Return an error string if password fails strength rules, else None."""
    if len(password) < 8:
        return 'Password must be at least 8 characters long'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one number'
    return None


def _check_csrf():
    """Validate CSRF token only when WTF_CSRF_ENABLED is True (skips in tests)."""
    if not current_app.config.get('WTF_CSRF_ENABLED', True):
        return None
    from flask_wtf.csrf import validate_csrf, ValidationError as CSRFValidationError
    try:
        validate_csrf(request.form.get('csrf_token'))
        return None
    except CSRFValidationError:
        return 'Invalid or expired session. Please refresh and try again.'


# ==========================================
# Core Auth Routes
# ==========================================

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """User login page with security features."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        csrf_error = _check_csrf()
        if csrf_error:
            return render_template('login.html', error=csrf_error), 400

        email_or_username = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        ip_address = request.remote_addr

        security_logger.info(f"Login attempt from IP: {ip_address} for user: {email_or_username}")

        if not email_or_username or not password:
            security_logger.warning(f"Failed login attempt from {ip_address}: Missing credentials")
            return render_template('login.html', error='Email/Username and password are required')

        user = User.query.filter(
            (User.email == email_or_username) | (User.username == email_or_username)
        ).first()

        if not user:
            security_logger.warning(f"Failed login attempt from {ip_address}: User not found - {email_or_username}")
            return render_template('login.html', error='Invalid email/username or password')

        from services import sso_service
        if sso_service.sso_login_required(user):
            security_logger.info(f"Password login blocked (SSO enforced) for {user.email}")
            return render_template('login.html',
                error='Your organization requires single sign-on. Please use "Sign in with SSO".')

        if user.is_locked():
            security_logger.warning(f"Login attempt for locked account: {user.email} from {ip_address}")
            return render_template('login.html', error='Account temporarily locked due to multiple failed login attempts. Try again in 15 minutes.')

        if user.check_password(password):
            if user.has_mfa_enabled():
                session['2fa_pending_user'] = user.id
                session['2fa_pending_time'] = datetime.utcnow().isoformat()
                _next = request.args.get('next', '')
                session['2fa_next'] = _next if _is_safe_redirect(_next) else ''
                session['2fa_method'] = user.mfa_method or 'totp'
                security_logger.info(f"MFA ({user.mfa_method}) required for {user.email} from {ip_address}")

                if user.mfa_method in ('email', 'sms'):
                    from services.two_factor_service import two_factor_service
                    code = two_factor_service.generate_otp()
                    user.set_mfa_otp(code)
                    db.session.commit()
                    if user.mfa_method == 'email':
                        from services.email_service import email_service
                        sent = email_service.send_otp_email(user, code)
                        if not sent:
                            session.pop('2fa_pending_user', None)
                            session.pop('2fa_pending_time', None)
                            session.pop('2fa_method', None)
                            return render_template('login.html', error='Failed to send verification email. Please try again.')
                    else:
                        from services.sms_service import sms_service
                        sent = sms_service.send_otp(user.phone_number, code)
                        if not sent:
                            session.pop('2fa_pending_user', None)
                            session.pop('2fa_pending_time', None)
                            session.pop('2fa_method', None)
                            return render_template('login.html', error='Failed to send SMS verification code. Please try again or switch to email MFA.')

                return redirect(url_for('.verify_2fa'))

            remember_me = request.form.get('remember') == 'on'
            session.clear()
            login_user(user, remember=remember_me)
            user.update_last_login(ip_address=ip_address)
            session.permanent = remember_me

            security_logger.info(f"Successful login: {user.email} from {ip_address}")

            next_page = request.args.get('next', '')
            if next_page and _is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(url_for('chat'))
        else:
            user.record_failed_login()
            attempts_remaining = max(0, 5 - user.failed_login_attempts)

            security_logger.warning(f"Failed login attempt for {user.email} from {ip_address}. Attempts remaining: {attempts_remaining}")

            if attempts_remaining == 0:
                return render_template('login.html', error='Account locked due to multiple failed login attempts. Try again in 15 minutes.')
            else:
                return render_template('login.html', error=f'Invalid email/username or password. {attempts_remaining} attempts remaining before account lockout.')

    return render_template('login.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def signup():
    """User registration page with input validation."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    # Preserve upgrade intent across the signup form POST
    tier_intent = request.args.get('tier', '') or request.form.get('tier_intent', '')

    if request.method == 'POST':
        csrf_error = _check_csrf()
        if csrf_error:
            return render_template('signup.html', error=csrf_error), 400

        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        ip_address = request.remote_addr

        security_logger.info(f"Signup attempt from IP: {ip_address} for email: {email}")

        if not email or not username or not password:
            return render_template('signup.html', error='Email, username, and password are required')

        try:
            valid = validate_email(email, check_deliverability=False)
            email = valid.email
        except EmailNotValidError as e:
            security_logger.warning(f"Invalid email format from {ip_address}: {email}")
            return render_template('signup.html', error=f'Invalid email address: {str(e)}')

        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            return render_template('signup.html', error='Username must be 3-20 characters long and contain only letters, numbers, and underscores')

        confirm_password = request.form.get('confirm_password', '')
        if password != confirm_password:
            return render_template('signup.html', error='Passwords do not match')

        pw_error = _validate_password_strength(password)
        if pw_error:
            return render_template('signup.html', error=pw_error)

        if User.query.filter_by(email=email).first():
            security_logger.warning(f"Signup attempt with existing email from {ip_address}: {email}")
            return render_template('signup.html', error='Email already registered')

        if User.query.filter_by(username=username).first():
            security_logger.warning(f"Signup attempt with existing username from {ip_address}: {username}")
            return render_template('signup.html', error='Username already taken')

        try:
            verification_token = secrets.token_urlsafe(32)
            hashed_verification_token = hashlib.sha256(verification_token.encode()).hexdigest()

            # First user ever = admin; every direct signup = admin of their own account.
            # Team members added via invite get user/approver role set by the inviting admin.
            user = User(
                email=email,
                username=username,
                full_name=full_name if full_name else None,
                last_login_ip=ip_address,
                email_verified=False,
                email_verification_token=hashed_verification_token,
                email_verification_sent_at=datetime.utcnow(),
                role='admin',
            )
            user.set_password(password)

            db.session.add(user)
            db.session.flush()  # get user.id without committing yet

            security_logger.info(f"New user registered: {email} from {ip_address}")

            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            if free_tier:
                from dateutil.relativedelta import relativedelta
                sub = UserSubscription(
                    user_id=user.id,
                    tier_id=free_tier.id,
                    credits_remaining=free_tier.monthly_credits,
                    current_period_start=datetime.utcnow(),
                    current_period_end=datetime.utcnow() + relativedelta(months=1),
                    last_reset_date=datetime.utcnow(),
                )
                db.session.add(sub)
            else:
                current_app.logger.error("Free tier not found in subscription_tiers — user registered without credits")

            db.session.commit()  # single commit: user + subscription together

            def _send_signup_emails(app, user_id, user_email, token):
                with app.app_context():
                    try:
                        from services.email_service import email_service
                        from models import User as _User, DripEmailLog, db as _db
                        _user = _User.query.get(user_id)
                        if _user:
                            email_service.send_verification_email(_user, token=token)
                            if user_email:
                                email_service.send_welcome_email(_user)
                                drip_log = DripEmailLog(user_id=user_id, drip_key='day_0_welcome', success=True)
                                _db.session.add(drip_log)
                                _db.session.commit()
                    except Exception as email_err:
                        current_app.logger.warning(f"Failed to send signup emails to {user_email}: {email_err}")

            threading.Thread(
                target=_send_signup_emails,
                args=(current_app._get_current_object(), user.id, user.email, verification_token),
                daemon=True,
            ).start()

            session.clear()
            login_user(user, remember=True)
            user.update_last_login(ip_address=ip_address)

            # If user signed up after clicking a pricing tier, send them straight to billing
            _valid_tiers = ('starter', 'professional', 'business')
            if tier_intent and tier_intent in _valid_tiers:
                from flask import url_for as _url_for
                return redirect(f'/billing?upgrade={tier_intent}')
            return redirect(url_for('chat'))
        except Exception as e:
            db.session.rollback()
            return render_template('signup.html', error=f'Error creating account: {str(e)}', tier_intent=tier_intent)

    return render_template('signup.html', tier_intent=tier_intent)


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout user."""
    logout_user()
    return redirect(url_for('.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password():
    """Request a password reset link via email."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        csrf_error = _check_csrf()
        if csrf_error:
            return render_template('forgot_password.html', error=csrf_error), 400

        email = request.form.get('email', '').strip().lower()
        ip_address = request.remote_addr

        if not email:
            return render_template('forgot_password.html', error='Please enter your email address.')

        success_msg = 'If an account with that email exists, we have sent a password reset link. Please check your inbox.'

        user = User.query.filter_by(email=email).first()
        if user:
            raw_token = secrets.token_urlsafe(32)
            hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()

            user.password_reset_token = hashed_token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()

            try:
                from services.email_service import email_service
                email_service.send_password_reset_email(user, token=raw_token)
                security_logger.info(f"Password reset email sent to {email} from {ip_address}")
            except Exception as e:
                current_app.logger.warning(f"Failed to send password reset email to {email}: {e}")
        else:
            security_logger.info(f"Password reset requested for non-existent email: {email} from {ip_address}")

        return render_template('forgot_password.html', success=success_msg)

    return render_template('forgot_password.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def reset_password():
    """Reset password using a tokenized link from email."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    token = request.args.get('token', '')
    user_id = request.args.get('user_id', '')

    if not token or not user_id:
        return render_template('reset_password.html', error='Invalid or missing reset link.', token_valid=False)

    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(id=user_id, password_reset_token=hashed_token).first()

    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        return render_template('reset_password.html', error='This reset link is invalid or has expired. Please request a new one.', token_valid=False)

    if request.method == 'POST':
        csrf_error = _check_csrf()
        if csrf_error:
            return render_template('reset_password.html', error=csrf_error, token_valid=True, token=token, user_id=user_id), 400

        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not password:
            return render_template('reset_password.html', error='Please enter a new password.', token_valid=True, token=token, user_id=user_id)

        if password != confirm_password:
            return render_template('reset_password.html', error='Passwords do not match.', token_valid=True, token=token, user_id=user_id)

        pw_error = _validate_password_strength(password)
        if pw_error:
            return render_template('reset_password.html', error=pw_error + '.', token_valid=True, token=token, user_id=user_id)

        user.set_password(password)
        user.password_reset_token = None
        user.password_reset_expires = None
        db.session.commit()

        security_logger.info(f"Password reset successfully for user {user.email}")
        return render_template('reset_password.html', success='Your password has been reset successfully. You can now sign in.', token_valid=False)

    return render_template('reset_password.html', token_valid=True, token=token, user_id=user_id)


@auth_bp.route('/verify-email')
@limiter.limit("20 per hour")
def verify_email():
    """Verify user email address via tokenized link."""
    token = request.args.get('token', '')
    user_id = request.args.get('user_id', '')

    if not token or not user_id:
        return render_template('login.html', error='Invalid verification link.')

    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(id=user_id, email_verification_token=hashed_token).first()

    if not user:
        return render_template('login.html', error='Invalid or expired verification link.')

    if user.email_verification_sent_at and (datetime.utcnow() - user.email_verification_sent_at).total_seconds() > 86400:
        return render_template('login.html', error='Verification link has expired. Please request a new one.')

    user.email_verified = True
    user.email_verification_token = None
    db.session.commit()

    security_logger.info(f"Email verified for user {user.email}")

    if current_user.is_authenticated and current_user.id == user.id:
        return redirect(url_for('chat'))

    return render_template('login.html', error=None, success='Your email has been verified. Please sign in.')


@auth_bp.route('/resend-verification', methods=['GET', 'POST'])
@login_required
@limiter.limit("3 per hour", exempt_when=lambda: request.method == 'GET')
def resend_verification():
    """GET: render the resend-verification page.
    POST: send a new verification email (rate-limited to 3/hr).
    """
    if request.method == 'GET':
        if current_user.email_verified:
            return redirect(url_for('index'))
        return render_template('resend_verification.html', user=current_user)

    user = current_user

    if user.email_verified:
        return jsonify({'success': False, 'message': 'Email is already verified.'}), 400

    raw_token = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()

    user.email_verification_token = hashed_token
    user.email_verification_sent_at = datetime.utcnow()
    db.session.commit()

    def _resend_email(app, user_id, user_email, token):
        with app.app_context():
            try:
                from services.email_service import email_service
                from models import User as _User
                _user = _User.query.get(user_id)
                if _user:
                    email_service.send_verification_email(_user, token=token)
                    current_app.logger.info(f"Verification email resent to {user_email}")
            except Exception as e:
                current_app.logger.warning(f"Failed to resend verification email to {user_email}: {e}")

    threading.Thread(
        target=_resend_email,
        args=(current_app._get_current_object(), user.id, user.email, raw_token),
        daemon=True,
    ).start()
    return jsonify({'success': True, 'message': 'Verification email sent. Please check your inbox.'})


# ==========================================
# Two-Factor Authentication Routes
# ==========================================

@auth_bp.route('/verify-2fa', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_2fa():
    """Verify MFA code after password authentication (supports TOTP, email OTP, SMS OTP)."""
    from services.two_factor_service import two_factor_service

    pending_user_id = session.get('2fa_pending_user')
    pending_time = session.get('2fa_pending_time')

    if not pending_user_id or not pending_time:
        return redirect(url_for('.login'))

    pending_dt = datetime.fromisoformat(pending_time)
    if datetime.utcnow() - pending_dt > timedelta(minutes=5):
        session.pop('2fa_pending_user', None)
        session.pop('2fa_pending_time', None)
        session.pop('2fa_next', None)
        session.pop('2fa_method', None)
        return redirect(url_for('.login'))

    user = User.query.get(pending_user_id)
    if not user:
        session.pop('2fa_pending_user', None)
        session.pop('2fa_pending_time', None)
        session.pop('2fa_next', None)
        session.pop('2fa_method', None)
        return redirect(url_for('.login'))

    mfa_method = session.get('2fa_method', user.mfa_method or 'totp')

    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        ip_address = request.remote_addr

        if not code:
            return render_template('verify_2fa.html', mfa_method=mfa_method,
                                   error='Please enter a verification code.')

        if user.two_factor_locked_until and datetime.utcnow() < user.two_factor_locked_until:
            remaining = int((user.two_factor_locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            return render_template('verify_2fa.html', mfa_method=mfa_method,
                                   error=f'Too many failed attempts. Try again in {remaining} minutes.')

        if user.two_factor_locked_until and datetime.utcnow() >= user.two_factor_locked_until:
            user.two_factor_locked_until = None
            user.two_factor_attempts = 0

        verified = False

        if mfa_method == 'totp':
            verified = two_factor_service.verify_totp(user.two_factor_secret, code)
        elif mfa_method in ('email', 'sms'):
            verified = user.verify_mfa_otp(code)
            if verified:
                user.clear_mfa_otp()

        if not verified and user.backup_codes:
            is_backup_valid, matched_hash = two_factor_service.verify_backup_code(
                code, user.backup_codes
            )
            if is_backup_valid:
                verified = True
                user.backup_codes = [h for h in user.backup_codes if h != matched_hash]
                if mfa_method in ('email', 'sms'):
                    user.clear_mfa_otp()

        if verified:
            user.two_factor_attempts = 0
            db.session.commit()

            next_page = session.get('2fa_next', '')
            session.clear()
            login_user(user, remember=True)
            user.update_last_login(ip_address=ip_address)
            session.permanent = True

            security_logger.info(f"MFA ({mfa_method}) verified for {user.email} from {ip_address}")
            if next_page and _is_safe_redirect(next_page):
                return redirect(next_page)
            return redirect(url_for('chat'))
        else:
            user.two_factor_attempts = (user.two_factor_attempts or 0) + 1
            if user.two_factor_attempts >= 5:
                user.two_factor_locked_until = datetime.utcnow() + timedelta(minutes=15)
                security_logger.warning(f"MFA locked for {user.email} from {ip_address}")
            db.session.commit()

            attempts_remaining = max(0, 5 - (user.two_factor_attempts or 0))
            security_logger.warning(f"Failed MFA for {user.email} from {ip_address}. Remaining: {attempts_remaining}")

            if attempts_remaining == 0:
                return render_template('verify_2fa.html', mfa_method=mfa_method,
                                       error='Too many failed attempts. Account locked for 15 minutes.')
            return render_template('verify_2fa.html', mfa_method=mfa_method,
                                   error=f'Invalid code. {attempts_remaining} attempts remaining.')

    return render_template('verify_2fa.html', mfa_method=mfa_method)


@auth_bp.route('/request-mfa-reset', methods=['POST'])
def request_mfa_reset():
    """Send MFA reset link to user's email. Called from verify-2fa page."""
    pending_user_id = session.get('2fa_pending_user')
    if not pending_user_id:
        return redirect(url_for('.login'))

    user = User.query.get(pending_user_id)
    if not user:
        return redirect(url_for('.login'))

    import secrets as _secrets
    from datetime import timedelta
    token = _secrets.token_urlsafe(32)
    user.mfa_reset_token = hashlib.sha256(token.encode()).hexdigest()
    user.mfa_reset_expires = datetime.utcnow() + timedelta(minutes=30)
    db.session.commit()

    from services.email_service import email_service
    email_service.send_mfa_reset_email(user, token)

    return render_template('login.html',
        success='A reset link has been sent to your email address. It expires in 30 minutes.')


@auth_bp.route('/reset-mfa', methods=['GET'])
def reset_mfa():
    """Disable MFA via emailed token and log the user in."""
    token = request.args.get('token', '')
    user_id = request.args.get('user_id', '')

    if not token or not user_id:
        return render_template('login.html', error='Invalid reset link.')

    user = User.query.get(user_id)
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    if not user or user.mfa_reset_token != hashed_token:
        return render_template('login.html', error='Invalid or expired reset link.')

    if datetime.utcnow() > user.mfa_reset_expires:
        user.mfa_reset_token = None
        user.mfa_reset_expires = None
        db.session.commit()
        return render_template('login.html', error='Reset link has expired. Please try again.')

    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.mfa_method = 'none'
    user.mfa_otp_hash = None
    user.mfa_otp_expires = None
    user.mfa_reset_token = None
    user.mfa_reset_expires = None
    db.session.commit()

    session.clear()
    login_user(user)
    security_logger.info(f"MFA reset and login for {user.email} via email token")
    return redirect(url_for('chat'))


@auth_bp.route('/setup-2fa')
@login_required
def setup_2fa_page():
    """Render the 2FA setup page."""
    return render_template('setup_2fa.html', user=current_user)


@auth_bp.route('/api/2fa/setup', methods=['POST'])
@login_required
def api_2fa_setup():
    """Generate 2FA secret and QR code."""
    from services.two_factor_service import two_factor_service

    if current_user.mfa_method == 'totp' and current_user.two_factor_enabled:
        return jsonify({'error': 'TOTP is already enabled'}), 400

    secret = two_factor_service.generate_secret()
    qr_code = two_factor_service.generate_qr_code(secret, current_user.email)

    current_user.two_factor_secret = secret
    db.session.commit()

    return jsonify({
        'success': True,
        'secret': secret,
        'qr_code': qr_code
    })


@auth_bp.route('/api/2fa/verify-setup', methods=['POST'])
@login_required
def api_2fa_verify_setup():
    """Verify TOTP code to complete 2FA setup."""
    from services.two_factor_service import two_factor_service

    data = request.get_json()
    if not data or not data.get('code'):
        return jsonify({'error': 'Verification code is required'}), 400

    code = data['code'].strip()

    if not current_user.two_factor_secret:
        return jsonify({'error': 'Please start 2FA setup first'}), 400

    if current_user.mfa_method == 'totp' and current_user.two_factor_enabled:
        return jsonify({'error': 'TOTP is already enabled'}), 400

    if two_factor_service.verify_totp(current_user.two_factor_secret, code):
        current_user.two_factor_enabled = True
        current_user.mfa_method = 'totp'
        current_user.two_factor_verified_at = datetime.utcnow()
        current_user.two_factor_attempts = 0
        current_user.email_verified = True  # TOTP setup proves account ownership

        backup_codes = two_factor_service.generate_backup_codes()
        current_user.backup_codes = [
            two_factor_service.hash_backup_code(c) for c in backup_codes
        ]
        db.session.commit()

        security_logger.info(f"2FA (TOTP) enabled for {current_user.email}")

        return jsonify({
            'success': True,
            'backup_codes': backup_codes
        })
    else:
        return jsonify({'error': 'Invalid verification code. Please try again.'}), 400


@auth_bp.route('/api/2fa/disable', methods=['POST'])
@login_required
def api_2fa_disable():
    """Disable 2FA (requires password confirmation)."""
    data = request.get_json()
    if not data or not data.get('password'):
        return jsonify({'error': 'Password is required to disable 2FA'}), 400

    if not current_user.check_password(data['password']):
        return jsonify({'error': 'Incorrect password'}), 403

    current_user.two_factor_enabled = False
    current_user.mfa_method = 'none'
    current_user.two_factor_secret = None
    current_user.backup_codes = None
    current_user.two_factor_verified_at = None
    current_user.two_factor_attempts = 0
    current_user.two_factor_locked_until = None
    current_user.mfa_otp_hash = None
    current_user.mfa_otp_expires = None
    current_user.mfa_otp_sent_at = None
    db.session.commit()

    security_logger.info(f"MFA disabled for {current_user.email}")

    return jsonify({'success': True, 'message': '2FA has been disabled.'})


@auth_bp.route('/api/2fa/regenerate-backup-codes', methods=['POST'])
@login_required
def api_2fa_regenerate_backup_codes():
    """Generate new backup codes (invalidates old ones)."""
    from services.two_factor_service import two_factor_service

    if not current_user.has_mfa_enabled():
        return jsonify({'error': 'MFA is not enabled'}), 400

    data = request.get_json()
    if not data or not data.get('password'):
        return jsonify({'error': 'Password is required'}), 400

    if not current_user.check_password(data['password']):
        return jsonify({'error': 'Incorrect password'}), 403

    backup_codes = two_factor_service.generate_backup_codes()
    current_user.backup_codes = [
        two_factor_service.hash_backup_code(c) for c in backup_codes
    ]
    db.session.commit()

    security_logger.info(f"Backup codes regenerated for {current_user.email}")

    return jsonify({
        'success': True,
        'backup_codes': backup_codes
    })


# ==========================================
# Multi-Method MFA Routes
# ==========================================

@auth_bp.route('/api/mfa/set-method', methods=['POST'])
@login_required
def api_mfa_set_method():
    """Choose an MFA method (email, sms, totp). Sends verification OTP for email/sms."""
    from services.two_factor_service import two_factor_service

    data = request.get_json()
    method = (data or {}).get('method', '').strip().lower()

    if method not in ('email', 'sms', 'totp'):
        return jsonify({'error': 'Invalid method. Choose email, sms, or totp.'}), 400

    if method == 'totp':
        return jsonify({'success': True, 'method': 'totp', 'action': 'totp_setup'})

    if method == 'email':
        if not current_user.email_verified:
            return jsonify({'error': 'Please verify your email address first (check Settings).'}), 400
        code = two_factor_service.generate_otp()
        current_user.set_mfa_otp(code)
        db.session.commit()
        from services.email_service import email_service
        sent = email_service.send_otp_email(current_user, code)
        if not sent:
            return jsonify({'error': 'Failed to send verification email. Please try again.'}), 500
        return jsonify({'success': True, 'method': 'email', 'action': 'verify_otp'})

    if method == 'sms':
        if not current_user.phone_number or not current_user.phone_verified:
            return jsonify({'error': 'Please add and verify a phone number first.', 'needs_phone': True}), 400
        code = two_factor_service.generate_otp()
        current_user.set_mfa_otp(code)
        db.session.commit()
        from services.sms_service import sms_service
        sent = sms_service.send_otp(current_user.phone_number, code)
        if not sent:
            return jsonify({'error': 'Failed to send SMS. Check your phone number or try again later.'}), 500
        return jsonify({'success': True, 'method': 'sms', 'action': 'verify_otp'})


@auth_bp.route('/api/mfa/verify-method', methods=['POST'])
@login_required
def api_mfa_verify_method():
    """Confirm OTP to activate email or SMS MFA. Generates backup codes."""
    from services.two_factor_service import two_factor_service

    data = request.get_json()
    code = (data or {}).get('code', '').strip()
    method = (data or {}).get('method', '').strip().lower()

    if not code or method not in ('email', 'sms'):
        return jsonify({'error': 'Code and method are required.'}), 400

    if not current_user.verify_mfa_otp(code):
        return jsonify({'error': 'Invalid or expired code. Please try again.'}), 400

    current_user.clear_mfa_otp()
    current_user.mfa_method = method
    current_user.two_factor_enabled = True
    current_user.two_factor_verified_at = datetime.utcnow()
    current_user.two_factor_attempts = 0
    current_user.email_verified = True  # MFA setup proves account ownership

    backup_codes = two_factor_service.generate_backup_codes()
    current_user.backup_codes = [
        two_factor_service.hash_backup_code(c) for c in backup_codes
    ]
    db.session.commit()

    security_logger.info(f"MFA ({method}) enabled for {current_user.email}")
    return jsonify({'success': True, 'backup_codes': backup_codes})


@auth_bp.route('/api/mfa/phone/add', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def api_mfa_phone_add():
    """Add a phone number and send verification SMS."""
    from services.two_factor_service import two_factor_service
    from services.sms_service import sms_service

    data = request.get_json()
    phone = (data or {}).get('phone_number', '').strip()

    if not phone:
        return jsonify({'error': 'Phone number is required.'}), 400

    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        return jsonify({'error': 'Invalid phone number. Use E.164 format (e.g. +12125551234).'}), 400

    current_user.phone_number = phone
    current_user.phone_verified = False

    code = two_factor_service.generate_otp()
    current_user.set_mfa_otp(code)
    db.session.commit()

    sent = sms_service.send_otp(phone, code)
    if not sent:
        return jsonify({'error': 'Failed to send SMS verification code. Check your phone number and try again.'}), 500
    return jsonify({'success': True, 'message': 'Verification code sent to your phone.'})


@auth_bp.route('/api/mfa/phone/verify', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def api_mfa_phone_verify():
    """Verify phone ownership via OTP."""
    data = request.get_json()
    code = (data or {}).get('code', '').strip()

    if not code:
        return jsonify({'error': 'Verification code is required.'}), 400

    if not current_user.verify_mfa_otp(code):
        return jsonify({'error': 'Invalid or expired code.'}), 400

    current_user.phone_verified = True
    current_user.clear_mfa_otp()
    db.session.commit()

    return jsonify({'success': True, 'message': 'Phone number verified.'})


@auth_bp.route('/api/2fa/resend-otp', methods=['POST'])
@limiter.limit("3 per 5 minutes")
def api_2fa_resend_otp():
    """Resend email/SMS OTP during login flow (60s cooldown)."""
    from services.two_factor_service import two_factor_service

    pending_user_id = session.get('2fa_pending_user')
    mfa_method = session.get('2fa_method')

    if not pending_user_id or mfa_method not in ('email', 'sms'):
        return jsonify({'error': 'No pending MFA session.'}), 400

    user = User.query.get(pending_user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 400

    if not user.can_resend_otp():
        return jsonify({'error': 'Please wait 60 seconds before resending.'}), 429

    code = two_factor_service.generate_otp()
    user.set_mfa_otp(code)
    db.session.commit()

    if mfa_method == 'email':
        from services.email_service import email_service
        sent = email_service.send_otp_email(user, code)
        if not sent:
            return jsonify({'error': 'Failed to send verification email. Please try again.'}), 500
    else:
        from services.sms_service import sms_service
        sent = sms_service.send_otp(user.phone_number, code)
        if not sent:
            return jsonify({'error': 'Failed to send SMS. Please try again.'}), 500

    return jsonify({'success': True, 'message': f'Code resent via {mfa_method}.'})
