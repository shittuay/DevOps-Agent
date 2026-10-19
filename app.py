"""
Flask Web Interface for DevOps Agent with API Key Configuration and Authentication
"""
import hmac
from html import escape as html_escape
import os
import sys

# --- Early secrets initialization (before any module reads os.environ) ---
_flask_env = os.environ.get('FLASK_ENV', 'development')
_use_aws = os.environ.get('USE_AWS_SECRETS', '').lower() == 'true'
_secrets_loaded = False
if _flask_env == 'production' or _use_aws:
    from services.secrets_manager import init_secrets
    _secrets_loaded = init_secrets()
    if not _secrets_loaded:
        # Fall back to .env file if AWS Secrets Manager failed
        print("WARNING: AWS Secrets Manager failed, falling back to .env file")
        from dotenv import load_dotenv
        for _env_path in ['config/.env', '.env']:
            if os.path.exists(_env_path):
                load_dotenv(_env_path)
                break
elif _flask_env != 'testing':
    from dotenv import load_dotenv
    # config/.env is authoritative — override=True ensures it always wins over shell env vars
    if os.path.exists('config/.env'):
        load_dotenv('config/.env', override=True)
    elif os.path.exists('.env'):
        load_dotenv('.env', override=True)
# FLASK_ENV=='testing' (set by tests/conftest.py before importing this module) intentionally
# skips both branches above — dotenv files must never override the forced in-memory SQLite
# DATABASE_URL, or the test suite's db.create_all()/drop_all() lifecycle runs against whatever
# real database happens to be configured in .env / config/.env.
# --- End early secrets initialization ---

# --- Startup validation: fail fast if critical Stripe config is missing/wrong ---
def _validate_stripe_config():
    required = {
        'STRIPE_SECRET_KEY': 'sk_live_ or sk_test_',
        'STRIPE_WEBHOOK_SECRET': 'whsec_',
        'STRIPE_PRICE_STARTER': 'price_',
        'STRIPE_PRICE_PROFESSIONAL': 'price_',
        'STRIPE_PRICE_BUSINESS': 'price_',
        'STRIPE_PRICE_PACK_100': 'price_',
    }
    errors = []
    for var, prefix in required.items():
        val = os.environ.get(var, '')
        if not val:
            errors.append(f"  MISSING: {var}")
        elif not val.startswith(prefix.split(' ')[0]):
            errors.append(f"  WRONG FORMAT: {var}={val[:30]}... (expected prefix: {prefix})")
    if errors:
        print("\n[STARTUP ERROR] Stripe config invalid — check config/.env:\n" + "\n".join(errors))
        print(f"  STRIPE_PRICE_STARTER currently={os.environ.get('STRIPE_PRICE_STARTER', 'NOT SET')}")
        print(f"  STRIPE_PRICE_PROFESSIONAL currently={os.environ.get('STRIPE_PRICE_PROFESSIONAL', 'NOT SET')}")
        print(f"  STRIPE_PRICE_BUSINESS currently={os.environ.get('STRIPE_PRICE_BUSINESS', 'NOT SET')}\n")

_validate_stripe_config()
# --- End startup validation ---

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response, send_file, g, stream_with_context
from werkzeug.exceptions import HTTPException
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets
import hashlib
import logging
import re
from email_validator import validate_email, EmailNotValidError
from services.email_service import email_service
from services.status_service import status_service
from services.credit_service import CreditService
from models import InfrastructureResource, CostOptimization, SecurityFinding, Alert

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.agent import DevOpsAgent
from src.utils import setup_logging, get_logger

# Module-level logger — used as fallback before app-level logger is configured
logger = get_logger(__name__)
from src.tools import (
    command_tools,
    aws_tools,
    azure_tools,
    gcp_tools,
    kubernetes_tools,
    git_tools,
    github_tools,
    docker_tools,
    cicd_tools,
    pentest_tools,
    terraform_tools,
    sonarqube_tools,
    nexus_tools,
    monitoring_tools,
    ansible_tools,
    alerting_tools,
    devops_operations_tools,
    verification_tools
)

# Import database models
from models import (
    db, User, ChatMessage, Conversation, UserPreferences, CommandTemplate,
    ResponseFeedback, SubscriptionTier, UserSubscription, CreditPurchase, UsageLog,
    LearningSession, PaymentWebhookEvent, NGNPriceConfig, ConversionEvent, AppNotification,
    CrisisIncident
)


app = Flask(__name__)

# How often /api/chat pads its response with a whitespace keep-alive byte
# while a long-running agent turn is still in progress — see the 524 incident
# entry in CLAUDE_RUNBOOK.md. Module-level so tests can shrink it instead of
# waiting out a real interval.
CHAT_KEEPALIVE_INTERVAL_SECONDS = 15

# Hard ceiling on how long /api/chat holds the HTTP request open waiting for an
# agent turn. MUST stay comfortably below gunicorn's --timeout: the keep-alive
# above commits a 200 to the client as soon as the first whitespace byte goes
# out, so if the arbiter kills the worker mid-turn the browser receives a 200
# whose body is nothing but whitespace and `response.json()` throws
# "Unexpected end of JSON input" — see CLAUDE_RUNBOOK.md's workflow-turn entry.
# On expiry the request returns a real JSON body while the turn keeps running
# in the background and persists itself (see _finalize_turn).
CHAT_MAX_TURN_SECONDS = int(os.environ.get('CHAT_MAX_TURN_SECONDS', '840'))

# At or below this many credits, chat responses carry a `low_credit_warning`
# so the UI can warn the user before they spend their next credit (Execution
# Integrity rule 5). The existing one-time email fires only at exactly 5.
LOW_CREDIT_THRESHOLD = 5


def _low_credit_warning(credits_remaining):
    """A `low_credit_warning` payload when the balance is running low, else None."""
    if credits_remaining is None or credits_remaining > LOW_CREDIT_THRESHOLD:
        return None
    if credits_remaining <= 0:
        return None  # the exhausted path has its own upgrade pitch
    return {
        'credits_remaining': credits_remaining,
        'message': (
            f"You have {credits_remaining} credit{'s' if credits_remaining != 1 else ''} "
            f"left. Each message costs 1 — top up to keep going."
        ),
    }

# Trust proxy headers (Cloudflare → nginx → Flask).
# Without this, Talisman sees HTTP and redirects Stripe webhooks, losing the body + signature.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Error tracking — captures unhandled exceptions to Sentry in production.
# Set SENTRY_DSN env var to enable. Safe no-op if not configured or SDK not installed.
_sentry_dsn = os.environ.get('SENTRY_DSN')
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[FlaskIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
    except ImportError:
        print("Warning: SENTRY_DSN set but sentry-sdk not installed. Run: pip install sentry-sdk[flask]")

# Initialize security features
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter.errors import RateLimitExceeded
from flask_talisman import Talisman

# Import shared extension instances (limiter + security_logger live in extensions.py
# so blueprints can import them without circular imports)
from extensions import limiter, security_logger

# CSRF Protection
csrf = CSRFProtect(app)
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit for CSRF tokens
app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # Automatic check off; _enforce_csrf_on_form_submissions() below does it

# Flask-WTF's automatic check is disabled above because the JSON surfaces of
# this app (/api/*, the MCP transport, the developer REST gateway, and the
# HMAC-signed inbound webhook receiver) send no CSRF token. The promised
# replacement — per-endpoint `@csrf.protect` — was never written. Four auth
# routes do check by hand via routes/auth.py's `_check_csrf()` (/login,
# /signup, /forgot-password, /reset-password), and those four are the ONLY
# form endpoints that were ever validated. Every other form-encoded POST —
# /profile, the organization create/invite/settings forms, compliance policy
# and evidence, API key and webhook creation — rendered no token and checked
# none.
#
# What needs protecting is narrower than "every POST". A cross-origin page
# cannot send `Content-Type: application/json` without a CORS preflight it has
# no way to satisfy, so the JSON endpoints are not the exposed surface.
# Form-encoded and multipart submissions ARE "simple requests" that any page
# can make with the victim's cookies attached, so those are enforced here.
#
# The four hand-written `_check_csrf()` calls are left in place: this hook
# preempts them, but their inline error message is the only feedback those
# pages can give, since none of the four auth templates render flashes.
#
# This mirrors Flask-WTF's own `csrf_protect` hook (flask_wtf/csrf.py) so that
# `csrf.exempt(...)` keeps working; it reads that extension's private exemption
# sets, which is why requirements.txt pins flask-wtf exactly. Revisit if that
# pin moves.
_CSRF_FORM_MIMETYPES = frozenset({
    'application/x-www-form-urlencoded',
    'multipart/form-data',
})


@app.before_request
def _enforce_csrf_on_form_submissions():
    """Validate the CSRF token on cookie-authenticated form submissions."""
    if not app.config.get('WTF_CSRF_ENABLED', True):
        return
    if request.method not in app.config['WTF_CSRF_METHODS']:
        return
    if (request.mimetype or '').lower() not in _CSRF_FORM_MIMETYPES:
        return
    if not request.endpoint:
        return
    if app.blueprints.get(request.blueprint) in csrf._exempt_blueprints:
        return
    view = app.view_functions.get(request.endpoint)
    if view is not None and f'{view.__module__}.{view.__name__}' in csrf._exempt_views:
        return
    csrf.protect()

# Bind limiter to this app instance
limiter.init_app(app)

_is_production = os.environ.get('FLASK_ENV') == 'production'
Talisman(app,
    force_https=_is_production,
    strict_transport_security=_is_production,
    strict_transport_security_max_age=31536000,
    content_security_policy={
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'", "https://js.stripe.com", "https://cdn.jsdelivr.net"],
        'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com"],
        'img-src': ["'self'", "data:", "https:"],
        'font-src': ["'self'", "data:", "https://fonts.gstatic.com", "https://cdn.jsdelivr.net"],
        'connect-src': ["'self'", "https://api.stripe.com"],
        'frame-src': ["'self'", "https://js.stripe.com", "https://hooks.stripe.com"],
        'base-uri': "'self'",
        'form-action': ["'self'", "https://claude.ai"],
        'object-src': "'none'",
    },
)

# security_logger and limiter are now imported from extensions.py above
os.makedirs('logs', exist_ok=True)

# Session configuration
# Check environment variable first (for production), then load or generate persistent secret key
app.secret_key = os.environ.get('SECRET_KEY')

if not app.secret_key:
    # Local development: use file-based secret key
    secret_key_file = os.path.join(os.path.dirname(__file__), 'instance', 'secret_key')
    os.makedirs(os.path.dirname(secret_key_file), exist_ok=True)

    if os.path.exists(secret_key_file):
        with open(secret_key_file, 'r') as f:
            app.secret_key = f.read().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        with open(secret_key_file, 'w') as f:
            f.write(app.secret_key)

# Use default Flask sessions (signed cookies) instead of filesystem to prevent session sharing
# app.config['SESSION_TYPE'] = 'filesystem'  # REMOVED - caused session sharing between users
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours in seconds
app.config['SESSION_COOKIE_SECURE'] = _is_production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_DURATION'] = 2592000  # 30 days
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = _is_production
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'

# Database configuration
# PostgreSQL for both local dev and production
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    # The local-dev fallback below carries a well-known password (it matches
    # docker-compose.yml's dev database). Falling back to it in production would
    # either fail obscurely or, worse, connect to some unintended local database,
    # so refuse instead of guessing.
    if os.environ.get('FLASK_ENV') == 'production' or os.environ.get('USE_AWS_SECRETS') == 'true':
        raise RuntimeError(
            "DATABASE_URL is not set. It is required in production - refusing to "
            "fall back to the local development database."
        )
    database_url = (
        f"postgresql://{os.environ.get('DEV_DB_USER', 'devops')}"
        f":{os.environ.get('DEV_DB_PASSWORD', 'devops_local')}"
        f"@{os.environ.get('DEV_DB_HOST', 'localhost')}:5432/devops_agent"
    )
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
import re as _re
_db_url_safe = _re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', database_url)
print(f"[DB] Connecting to: {_db_url_safe}")
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
if database_url.startswith('sqlite'):
    # An in-memory SQLite database lives on its one connection (Flask-SQLAlchemy
    # uses a StaticPool for it). Recycling that connection after 300s silently
    # replaces the database with a new, empty one; the test suite runs about
    # five minutes, so every test after that point saw "no such table".
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
from routes.auth import auth_bp
app.register_blueprint(auth_bp)
from routes.approvals import approvals_bp
app.register_blueprint(approvals_bp)
from routes.billing import billing_bp
app.register_blueprint(billing_bp)

from routes.admin import admin_bp
app.register_blueprint(admin_bp)

# Register drift detection blueprint for infrastructure drift detection
from routes.drift import drift_bp
app.register_blueprint(drift_bp)


# Register AI Infrastructure blueprint
from routes.ai_infrastructure import ai_infrastructure_bp
app.register_blueprint(ai_infrastructure_bp)

# Register Analytics blueprint
from routes.analytics import analytics_bp
app.register_blueprint(analytics_bp)

# Register API Gateway blueprint
from routes.api_gateway import api_gateway_bp
app.register_blueprint(api_gateway_bp)

# Register Organizations blueprint
from routes.organizations import organizations_bp
app.register_blueprint(organizations_bp)

# Register SSO (OIDC) authentication blueprint
from routes.sso_auth import sso_auth_bp
app.register_blueprint(sso_auth_bp)

# Register Change Governance blueprint
from routes.changes import changes_bp
app.register_blueprint(changes_bp)

from routes.curriculum import curriculum_bp
app.register_blueprint(curriculum_bp)

from routes.metrics import metrics_bp
app.register_blueprint(metrics_bp)
from services import metrics_service
metrics_service.init_app(app)

# Pre-built workflow templates
from routes.workflows import workflows_bp
app.register_blueprint(workflows_bp)

from routes.artifacts import artifacts_bp
app.register_blueprint(artifacts_bp)
csrf.exempt(artifacts_bp)

from routes.skills import skills_bp
app.register_blueprint(skills_bp)

from routes.integrations import integrations_bp
app.register_blueprint(integrations_bp)

# Load built-in skills at import time — gunicorn never runs the __main__ block,
# so loading there left the Skills feature empty in production. Passing `app`
# is required: the engine's list/context methods no-op without an app handle.
try:
    from services.skills_engine import get_skills_engine as _get_skills_engine
    _get_skills_engine(app).load_skills_from_disk(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skills'))
except Exception as _skills_load_err:
    print(f"Skills loading warning: {_skills_load_err}")

# MCP server (Model Context Protocol — remote tool access for Claude Desktop)
from routes.mcp import (mcp_bp, mcp_oauth_alias_bp, mcp_base_url,
                        OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)
app.register_blueprint(mcp_bp)
csrf.exempt(mcp_bp)  # MCP clients send raw JSON, not form posts
# Root-level OAuth path aliases (/authorize, /token, /register) for clients
# that probe origin-default paths instead of the advertised endpoints.
app.register_blueprint(mcp_oauth_alias_bp)
csrf.exempt(mcp_oauth_alias_bp)

# Base URL for MCP OAuth metadata — derived per-request from the host so the
# issuer matches whichever host the connector uses (apex or mcp. subdomain).
_mcp_base_url = mcp_base_url

@app.route('/.well-known/oauth-authorization-server')
@app.route('/.well-known/oauth-authorization-server/mcp')
@app.route('/.well-known/oauth-authorization-server/mcp/')
def oauth_authorization_server_metadata():
    """OAuth 2.0 Authorization Server Metadata (RFC 8414, incl. path-variant probes)."""
    base = _mcp_base_url()
    resp = jsonify({
        'issuer':                                base,
        'authorization_endpoint':                f'{base}/mcp/oauth/authorize',
        'token_endpoint':                        f'{base}/mcp/oauth/token',
        'registration_endpoint':                 f'{base}/mcp/oauth/register',
        'response_types_supported':              ['code'],
        'grant_types_supported':                 ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported':      ['S256'],
        'token_endpoint_auth_methods_supported': ['client_secret_post', 'client_secret_basic', 'none'],
        'scopes_supported':                      ['mcp'],
        'authorization_response_iss_parameter_supported': True,
    })
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route('/.well-known/oauth-protected-resource')
@app.route('/.well-known/oauth-protected-resource/mcp')
@app.route('/.well-known/oauth-protected-resource/mcp/')
def oauth_protected_resource_metadata():
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    The advertised resource MUST match the URL the client is configured with,
    or strict clients (claude.ai connectors) discard their freshly issued
    tokens as resource-mismatched. The /mcp-suffixed document describes the
    /mcp resource; the root document describes the origin root (the MCP
    streamable transport is also served at POST / for root-configured clients).
    """
    base = _mcp_base_url()
    wants_mcp_path = request.path.rstrip('/').endswith('/mcp')
    resp = jsonify({
        'resource':                 f'{base}/mcp' if wants_mcp_path else base,
        'authorization_servers':    [base],
        'bearer_methods_supported': ['header', 'query'],
        'scopes_supported':         ['mcp'],
    })
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

# Register REST API v1 blueprint (CLI + programmatic access)
from api import api_bp
app.register_blueprint(api_bp)
csrf.exempt(api_bp)


# Initialise status service (public status page + Brevo subscriber broadcasts)
status_service.set_app(app)
status_service.set_email_service(email_service)

# RBAC context processor - makes RBAC helpers available in all templates
from services.rbac import RBACContext, get_user_role, user_has_permission, Permission
from services.rbac import admin_required as _admin_required

@app.context_processor
def inject_rbac():
    """Inject RBAC context into all templates."""
    if current_user.is_authenticated:
        return {
            'rbac': RBACContext(current_user),
            'user_role': get_user_role(current_user),
            'Permission': Permission
        }
    return {
        'rbac': None,
        'user_role': None,
        'Permission': Permission
    }

# Ensure proper database session cleanup
@app.teardown_appcontext
def shutdown_session(exception=None):
    """Remove database sessions at the end of the request or when the application shuts down."""
    if exception:
        db.session.rollback()
    try:
        db.session.remove()
    except Exception:
        pass


# Ensure clean transaction state before each request (no query overhead)
@app.before_request
def ensure_clean_transaction():
    """Roll back any leftover failed transaction without issuing a query."""
    try:
        if db.session.is_active and db.session.dirty:
            db.session.rollback()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

@app.errorhandler(RateLimitExceeded)
def handle_rate_limit(e):
    """Return a clean 429 response instead of letting it bubble up as 500."""
    limit = getattr(e, 'description', str(e))
    if request.path.startswith('/api/') or request.path.startswith('/chat'):
        return jsonify({'error': f'Rate limit exceeded. {limit}'}), 429
    # Both branches must carry the status explicitly: render_template() alone
    # returns a bare string, which Flask serves as 200 - so adding a 429.html
    # would have quietly turned every rate-limited response into a success.
    if _template_exists('429.html'):
        return render_template('429.html', limit=limit), 429
    return f'<h1>429 Too Many Requests</h1><p>{limit}</p>', 429


def _template_exists(name):
    from flask import current_app
    import os
    return os.path.exists(os.path.join(current_app.template_folder, name))


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Turn a rejected form submission into a re-try, not a bare 400 page.

    _enforce_csrf_on_form_submissions() only ever fires on form-encoded posts,
    so the caller is a browser rendering one of our own pages: send them back to
    it with a flash rather than Flask-WTF's default error document. The wording
    stays generic because a failure here is far more often a stale session than
    an actual forged request.

    The referrer is validated before it is used as the redirect target: on a
    genuinely forged request it points at the attacker's page, and bouncing the
    victim straight back to it would make this handler an open redirect.
    """
    from routes.auth import _is_safe_redirect

    security_logger.warning(
        f"CSRF rejected: {request.method} {request.path} from {request.remote_addr} ({e.description})"
    )
    flash('Your session expired. Please refresh the page and try again.', 'error')
    referrer = request.referrer
    target = referrer if referrer and _is_safe_redirect(referrer) else url_for('index')
    return redirect(target), 303


@app.errorhandler(405)
def handle_method_not_allowed(e):
    """Return 405 instead of letting it bubble up as 500."""
    if request.path.startswith('/api/') or request.path.startswith('/chat'):
        return jsonify({'error': 'Method not allowed'}), 405
    return render_template('404.html'), 405


# Error handler for database errors
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle uncaught exceptions and ensure database rollback."""
    # Rollback database session on error
    try:
        db.session.rollback()
    except Exception:
        pass

    # Log the error to both Flask logger and stderr for visibility
    import traceback as _tb
    print(f"\n{'='*60}\n500 ERROR on {request.method} {request.path}\n{'='*60}", flush=True)
    _tb.print_exc()
    print(f"{'='*60}\n", flush=True)
    app.logger.error(f"Unhandled exception: {str(e)}", exc_info=True)

    # For PostgreSQL transaction errors, provide helpful message
    if 'InFailedSqlTransaction' in str(e) or 'current transaction is aborted' in str(e):
        return jsonify({
            'error': 'A database error occurred. Please try again.',
            'details': 'The previous operation encountered an issue. Your request has been reset.'
        }), 500

    # For database-specific errors, provide helpful message
    if 'database is locked' in str(e).lower():
        return jsonify({
            'error': 'Database is temporarily busy. Please try again in a moment.',
            'details': 'The system is processing another request. This usually resolves quickly.'
        }), 503

    # For stripe/billing endpoints, show actual error for debugging
    if request.path.startswith('/api/stripe') or request.path.startswith('/api/subscription') or request.path.startswith('/api/credits'):
        return jsonify({'error': str(e), 'path': request.path}), 500

    # For other errors in API endpoints, return JSON
    if request.path.startswith('/api/') or request.path.startswith('/chat'):
        return jsonify({'error': 'An internal error occurred. Please try again.'}), 500

    # For page requests, render error template — only show details in dev mode
    if os.environ.get('FLASK_ENV') == 'development':
        import traceback as _tb2
        error_detail = f"{type(e).__name__}: {str(e)}"
        error_traceback = _tb2.format_exc()
    else:
        error_detail = 'An unexpected error occurred.'
        error_traceback = ''
    return render_template('500.html', error_detail=error_detail, error_traceback=error_traceback), 500


# Enforce 2FA setup for all authenticated users
_2FA_EXEMPT_ROUTES = {
    'auth.login', 'auth.signup', 'auth.logout', 'static', 'auth.verify_2fa', 'auth.setup_2fa_page',
    'auth.api_2fa_setup', 'auth.api_2fa_verify_setup', 'page_not_found', 'handle_exception',
    'ensure_clean_transaction', 'onboarding_page', 'complete_onboarding',
    'update_onboarding_step',
    'auth.api_mfa_set_method', 'auth.api_mfa_verify_method', 'auth.api_mfa_phone_add',
    'auth.api_mfa_phone_verify', 'auth.api_2fa_resend_otp',
    # Email verification routes must also be exempt — otherwise new users loop between
    # "setup 2FA" and "verify email" before they can do either
    'auth.verify_email', 'auth.resend_verification',
    'auth.forgot_password', 'auth.reset_password',
    'register_redirect', 'usage_policy', 'privacy_policy', 'docs',
    'status_page', 'status_unsubscribe', 'api_status_health',
}

_ONBOARDING_OK_ROUTES = {
    'onboarding_page', 'complete_onboarding', 'update_onboarding_step',
    'onboarding_scan',
    'aws_config', 'azure_config', 'gcp_config',
}


@app.before_request
def _remember_signup_source():
    """Note where a visitor came from (utm_source/ref, or the referring site) so
    signup can save it; first visit wins. See services/signup_source.py."""
    if request.method != 'GET' or current_user.is_authenticated:
        return
    if request.endpoint and request.endpoint.startswith('static'):
        return
    try:
        from services.signup_source import remember
        remember(session, request.args, request.referrer)
    except Exception:
        pass


@app.before_request
def enforce_two_factor():
    """Require all logged-in users to set up 2FA before accessing the app."""
    if app.config.get('TESTING'):
        return
    if not current_user.is_authenticated:
        return
    if request.endpoint in _2FA_EXEMPT_ROUTES:
        return
    if request.endpoint and request.endpoint.startswith('static'):
        return
    if not current_user.has_mfa_enabled():
        if request.path.startswith('/api/'):
            return jsonify({'error': '2FA setup required', 'mfa_required': True}), 403
        return redirect(url_for('auth.setup_2fa_page'))
    # Redirect to onboarding if not completed (after 2FA is set up)
    if not getattr(current_user, 'onboarding_completed', True):
        if request.endpoint and request.endpoint not in _ONBOARDING_OK_ROUTES:
            # API calls during onboarding should get JSON, not a redirect
            if request.path.startswith('/api/'):
                return jsonify({'error': 'onboarding_required'}), 403
            return redirect(url_for('onboarding_page'))


# Routes that do NOT require email verification (auth pages, email verify flow, static)
_EMAIL_VERIFY_EXEMPT_ROUTES = {
    'auth.login', 'auth.signup', 'auth.logout', 'auth.verify_email', 'auth.resend_verification',
    'auth.forgot_password', 'auth.reset_password', 'static', 'page_not_found',
    'handle_exception', 'ensure_clean_transaction', 'register_redirect',
    'usage_policy', 'privacy_policy', 'docs',
    'status_page', 'status_unsubscribe', 'api_status_health',
    # 2FA setup routes must also be exempt — otherwise new users loop between
    # "verify email" and "setup 2FA" before they can do either
    'auth.setup_2fa_page', 'auth.verify_2fa', 'auth.api_2fa_setup', 'auth.api_2fa_verify_setup',
    'auth.api_mfa_set_method', 'auth.api_mfa_verify_method', 'auth.api_mfa_phone_add',
    'auth.api_mfa_phone_verify', 'auth.api_2fa_resend_otp',
}

@app.before_request
def enforce_email_verification():
    """Require all logged-in users to verify their email before accessing the app."""
    if app.config.get('TESTING'):
        return
    if not current_user.is_authenticated:
        return
    if request.endpoint in _EMAIL_VERIFY_EXEMPT_ROUTES:
        return
    if request.endpoint and request.endpoint.startswith('static'):
        return
    # Users who have set up TOTP have already proven account ownership — exempt them
    if getattr(current_user, 'two_factor_enabled', False):
        return
    if not getattr(current_user, 'email_verified', True):
        # API routes get JSON; page routes get a redirect
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Email verification required', 'email_unverified': True}), 403
        return redirect(url_for('auth.resend_verification'))


@app.route('/register')
def register_redirect():
    """Permanent redirect from /register to /signup."""
    return redirect(url_for('auth.signup'), 308)


@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('404.html'), 404


# Global agent instance
agent = None
config_manager = None

# Temporary storage for file downloads (token -> {file_data, expires_at})
# Downloads expire after 5 minutes for security
download_storage = {}

def check_api_key_configured():
    """Check if API key is configured in environment, .env file, or AWS Secrets Manager."""
    # First check environment variable (for production)
    env_api_key = os.environ.get('ANTHROPIC_API_KEY')
    if env_api_key and env_api_key.startswith('sk-ant-'):
        return True

    # Try AWS Secrets Manager (for IAM role-based access)
    try:
        from src.config.config_manager import get_secret_from_aws
        aws_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
        secret_value = get_secret_from_aws('ANTHROPIC_API_KEY', aws_region)
        if secret_value and secret_value.startswith('sk-ant-'):
            # Set it in environment for subsequent checks
            os.environ['ANTHROPIC_API_KEY'] = secret_value
            return True
    except Exception:
        pass

    # Fall back to .env file (for local development)
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return False

    with open(env_path, 'r') as f:
        content = f.read()
        return 'ANTHROPIC_API_KEY=' in content and 'your_anthropic_api_key_here' not in content

def save_api_key(api_key):
    """Save API key to .env file."""
    env_path = os.path.join('config', '.env')

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add ANTHROPIC_API_KEY
    found = False
    for i, line in enumerate(lines):
        if line.startswith('ANTHROPIC_API_KEY='):
            lines[i] = f'ANTHROPIC_API_KEY={api_key}\n'
            found = True
            break

    if not found:
        lines.insert(0, f'ANTHROPIC_API_KEY={api_key}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def save_aws_credentials(access_key, secret_key, region='us-east-1'):
    """Save AWS credentials to .env file."""
    env_path = os.path.join('config', '.env')

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add AWS credentials
    credentials = {
        'AWS_ACCESS_KEY_ID': access_key,
        'AWS_SECRET_ACCESS_KEY': secret_key,
        'AWS_DEFAULT_REGION': region
    }

    for key, value in credentials.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break

        if not found:
            lines.append(f'{key}={value}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def save_azure_credentials(subscription_id, tenant_id, client_id, client_secret, location='eastus'):
    """Save Azure credentials to .env file."""
    env_path = os.path.join('config', '.env')

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add Azure credentials
    credentials = {
        'AZURE_SUBSCRIPTION_ID': subscription_id,
        'AZURE_TENANT_ID': tenant_id,
        'AZURE_CLIENT_ID': client_id,
        'AZURE_CLIENT_SECRET': client_secret,
        'AZURE_DEFAULT_LOCATION': location
    }

    for key, value in credentials.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break

        if not found:
            lines.append(f'{key}={value}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def save_gcp_credentials(project_id, credentials_json, region='us-central1', zone='us-central1-a'):
    """Save GCP credentials to .env file."""
    env_path = os.path.join('config', '.env')

    # Save service account JSON if provided
    if credentials_json:
        creds_path = os.path.join('config', 'gcp-service-account.json')
        with open(creds_path, 'w') as f:
            f.write(credentials_json)

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add GCP credentials
    credentials = {
        'GCP_PROJECT_ID': project_id,
        'GOOGLE_APPLICATION_CREDENTIALS': os.path.abspath(os.path.join('config', 'gcp-service-account.json')),
        'GCP_DEFAULT_REGION': region,
        'GCP_DEFAULT_ZONE': zone
    }

    for key, value in credentials.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break

        if not found:
            lines.append(f'{key}={value}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def get_aws_config_status():
    """Check if AWS credentials are configured."""
    # First check environment variables (for production)
    env_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    env_region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')

    if env_access_key and env_access_key.startswith('AKIA'):
        # Credentials found in environment
        access_key_masked = env_access_key[:4] + '****' + env_access_key[-4:] if len(env_access_key) > 8 else env_access_key
        return {
            'configured': True,
            'access_key': access_key_masked,
            'region': env_region
        }

    # Fall back to .env file (for local development)
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return {
            'configured': False,
            'access_key': None,
            'region': 'us-east-1'
        }

    with open(env_path, 'r') as f:
        content = f.read()

    # Check if AWS credentials exist and are not placeholder values
    has_access_key = 'AWS_ACCESS_KEY_ID=' in content and 'your_aws_access_key' not in content

    # Extract region if available
    region = None
    for line in content.split('\n'):
        if line.startswith('AWS_DEFAULT_REGION='):
            region = line.split('=', 1)[1].strip()
            break

    # Extract masked access key for display
    access_key_masked = None
    if has_access_key:
        for line in content.split('\n'):
            if line.startswith('AWS_ACCESS_KEY_ID='):
                key = line.split('=', 1)[1].strip()
                if key and len(key) > 8:
                    access_key_masked = key[:4] + '****' + key[-4:]
                break

    return {
        'configured': has_access_key,
        'access_key': access_key_masked,
        'region': region or 'us-east-1'
    }

def get_azure_config_status():
    """Check if Azure credentials are configured."""
    # First check environment variables
    env_subscription_id = os.environ.get('AZURE_SUBSCRIPTION_ID')
    env_location = os.environ.get('AZURE_DEFAULT_LOCATION', 'eastus')

    if env_subscription_id and len(env_subscription_id) > 10:
        subscription_masked = env_subscription_id[:8] + '****' + env_subscription_id[-4:]
        return {
            'configured': True,
            'subscription_id': subscription_masked,
            'location': env_location
        }

    # Fall back to .env file
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return {
            'configured': False,
            'subscription_id': None,
            'location': 'eastus'
        }

    with open(env_path, 'r') as f:
        content = f.read()

    # Check if Azure credentials exist
    has_subscription = 'AZURE_SUBSCRIPTION_ID=' in content and 'your_azure_subscription' not in content

    # Extract location if available
    location = None
    for line in content.split('\n'):
        if line.startswith('AZURE_DEFAULT_LOCATION='):
            location = line.split('=', 1)[1].strip()
            break

    # Extract masked subscription ID
    subscription_masked = None
    if has_subscription:
        for line in content.split('\n'):
            if line.startswith('AZURE_SUBSCRIPTION_ID='):
                sub_id = line.split('=', 1)[1].strip()
                if sub_id and len(sub_id) > 12:
                    subscription_masked = sub_id[:8] + '****' + sub_id[-4:]
                break

    return {
        'configured': has_subscription,
        'subscription_id': subscription_masked,
        'location': location or 'eastus'
    }

def get_gcp_config_status():
    """Check if GCP credentials are configured."""
    # First check environment variables
    env_project_id = os.environ.get('GCP_PROJECT_ID')
    env_region = os.environ.get('GCP_DEFAULT_REGION', 'us-central1')
    env_creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

    if env_project_id and len(env_project_id) > 0:
        has_creds_file = env_creds_path and os.path.exists(env_creds_path)
        return {
            'configured': True,
            'project_id': env_project_id,
            'region': env_region,
            'has_credentials_file': has_creds_file
        }

    # Fall back to .env file
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return {
            'configured': False,
            'project_id': None,
            'region': 'us-central1',
            'has_credentials_file': False
        }

    with open(env_path, 'r') as f:
        content = f.read()

    # Check if GCP credentials exist
    has_project = 'GCP_PROJECT_ID=' in content and 'your_gcp_project' not in content

    # Extract region if available
    region = None
    for line in content.split('\n'):
        if line.startswith('GCP_DEFAULT_REGION='):
            region = line.split('=', 1)[1].strip()
            break

    # Extract project ID
    project_id = None
    if has_project:
        for line in content.split('\n'):
            if line.startswith('GCP_PROJECT_ID='):
                project_id = line.split('=', 1)[1].strip()
                break

    # Check if credentials file exists
    creds_path = os.path.join('config', 'gcp-service-account.json')
    has_creds_file = os.path.exists(creds_path)

    return {
        'configured': has_project and has_creds_file,
        'project_id': project_id,
        'region': region or 'us-central1',
        'has_credentials_file': has_creds_file
    }

def initialize_agent():
    """Initialize the DevOps Agent.

    Idempotent: if the agent is already built and attached to app.config, this
    is a no-op. Safe to call at module import (so every gunicorn worker has the
    agent for the /api/v1 REST endpoints) and again lazily from chat routes.
    """
    global agent, config_manager

    # Already initialized on this worker — don't rebuild the tool registry.
    if agent is not None and app.config.get('DEVOPS_AGENT') is not None:
        return True, None

    try:
        # Load configuration
        config_manager = ConfigManager()

        # Setup logging
        setup_logging(
            log_file=config_manager.log_file,
            log_level=config_manager.log_level,
            console_output=False,  # Disable console output for web
            json_format=config_manager.get('logging.format') == 'json'
        )

        logger.info("Initializing DevOps Agent for web interface")

        # Create agent
        agent = DevOpsAgent(config_manager)

        # Register tools
        agent.register_tools_from_module(command_tools)
        agent.register_tools_from_module(verification_tools)  # http_check / tcp_check — always available
        if config_manager.aws_enabled:
            agent.register_tools_from_module(aws_tools)
        # Always enable GCP and Azure tools
        agent.register_tools_from_module(gcp_tools)
        agent.register_tools_from_module(azure_tools)
        if config_manager.k8s_enabled:
            agent.register_tools_from_module(kubernetes_tools)
        agent.register_tools_from_module(git_tools)
        agent.register_tools_from_module(github_tools)
        agent.register_tools_from_module(docker_tools)
        if config_manager.jenkins_enabled or config_manager.github_enabled:
            agent.register_tools_from_module(cicd_tools)

        # Register Terraform tools if enabled
        if config_manager.get('terraform.enabled', True):
            agent.register_tools_from_module(terraform_tools)
            logger.info("Terraform tools enabled")

        # Register Monitoring tools (Prometheus, Grafana, Datadog)
        if config_manager.get('monitoring.enabled', True):
            agent.register_tools_from_module(monitoring_tools)
            logger.info("Monitoring tools enabled (Prometheus, Grafana, Datadog)")

        # Register Ansible tools if enabled
        if config_manager.get('ansible.enabled', True):
            agent.register_tools_from_module(ansible_tools)
            logger.info("Ansible tools enabled")

        # Register Alerting tools (PagerDuty, OpsGenie) if enabled
        if config_manager.get('alerting.enabled', True):
            agent.register_tools_from_module(alerting_tools)
            logger.info("Alerting tools enabled (PagerDuty, OpsGenie)")

        # Register Penetration Testing tools if enabled
        if config_manager.get('pentest.enabled', False):
            agent.register_tools_from_module(pentest_tools)
            logger.info("Penetration testing tools enabled - ensure authorized usage")

        # Register SonarQube tools if enabled
        if config_manager.get('sonarqube.enabled', True):
            agent.register_tools_from_module(sonarqube_tools)
            logger.info("SonarQube tools enabled")

        # Register Nexus Repository tools if enabled
        if config_manager.get('nexus.enabled', True):
            agent.register_tools_from_module(nexus_tools)
            logger.info("Nexus Repository tools enabled")

        # Register DevOps operations tools (cost analysis, change governance, compliance)
        agent.register_tools_from_module(devops_operations_tools)
        logger.info("DevOps operations tools enabled (cost, changes, compliance)")

        logger.info(f"Agent initialized with {len(agent.list_available_tools())} tools")

        # Store agent on app.config so API v1 endpoints can access it
        app.config['DEVOPS_AGENT'] = agent

        return True, None

    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Learning Mode system prompt augmentation
# ---------------------------------------------------------------------------
LEARNING_MODE_CONTEXT = """
LEARNING MODE IS ACTIVE. You are both a senior DevOps engineer AND a patient teacher. You are building engineers, not just infrastructure.

NARRATION MANDATE: Narrate every action in plain English as you work — what you're doing, why you're doing it, and what it means. Never execute silently. Every tool call, every decision, every result gets explained.

CORE TEACHING PHILOSOPHY:
- Check the user's proficiency level provided in context. If a domain score is 0-15, assume ZERO prior knowledge and explain from absolute first principles.
- Always teach the "why" before the "how". Never just run a command — explain what it does and why it matters.
- Use real-world analogies to make abstract concepts concrete.
- Define every acronym the first time you use it (e.g., "IAM — Identity and Access Management").
- Never rush. Learning is the goal, not efficiency.

FOR BRAND NEW LEARNERS (proficiency 0-15 in any domain):
- Start with a plain-language paragraph explaining the concept before running any tools.
- Use analogies: "An EC2 instance is like renting a computer in Amazon's data center. You pick how powerful it should be, you install your own software, and you pay by the hour."
- Explain what DevOps IS if they ask. Connect cloud tools to real business scenarios.
- If a user says "I don't know where to start" or "I'm completely new", respond warmly with:
  1. A 30-second overview of the DevOps landscape: Cloud → Linux → Networking → Containers → Orchestration → CI/CD → IaC
  2. A recommendation to start with AWS basics
  3. A specific first action: "Let's start by exploring your sandbox. Try asking: show me my EC2 instances"

STRUCTURED TEACHING FORMAT — use this for every tool interaction:

### What We're Doing
[1-2 sentences: the goal in plain English — no jargon]

### Before Running: [Tool Name]
[Why this tool? What will it show? What should we expect to see?]

### Results Explained
[Plain-language breakdown of every important field in the output. Don't assume they know what any term means.]

### Key Takeaway
[2-4 bullet points the learner should remember from this interaction]

> **Try Next:** [One specific follow-up they can do right now to deepen their understanding]

TEACHING GUIDELINES BY PROFICIENCY LEVEL:
- 0-30 (beginner): explain everything, define all acronyms, use analogies, name common beginner mistakes, add "In real life..." context
- 31-60 (intermediate): focus on why, mention tradeoffs and alternatives, introduce best practices and security considerations
- 61-100 (advanced): focus on edge cases, performance optimization, cost efficiency, production-grade patterns

CURRICULUM PROGRESSION — suggest this order to absolute beginners:
1. AWS Foundations: EC2 → S3 → IAM → VPC → Security Groups → RDS → Lambda
2. Kubernetes Basics: Pods → Deployments → Services → Debugging
3. CI/CD: GitHub Actions → pipelines → automated testing
4. Infrastructure as Code: Terraform basics
5. DevOps Culture: monitoring, incident response, SRE concepts

TOOL TEACHING NOTES — use these when the user invokes these tools:

Jenkins:
- Jenkins is an open-source automation server. Think of it as a robot that watches your code repository and automatically builds, tests, and deploys your software whenever you push changes.
- A "job" is a task Jenkins knows how to do (e.g., "build and test the backend").
- A "build" is one specific run of a job — like one attempt to build the software.
- "Blue" color = passing, "Red" = failing, "Yellow" = unstable (some tests failed).
- The build queue is where jobs wait when all executor slots (workers) are busy.
- Nodes/agents are additional machines Jenkins uses to run builds in parallel.

GitHub Actions:
- GitHub Actions is CI/CD built directly into GitHub. No separate server needed.
- A "workflow" is a YAML file in .github/workflows/ that defines automation steps.
- A "run" is one execution of a workflow — triggered by a push, PR, schedule, or manually.
- "Self-hosted runners" are your own machines registered to run jobs (vs. GitHub's cloud runners).
- Secrets are encrypted environment variables — GitHub never exposes their values, only names.
- Environments (staging, production) add approval gates and environment-specific secrets.
- Billable minutes only apply to private repos using GitHub-hosted runners.

Docker:
- Docker packages software into "containers" — isolated environments with everything the app needs to run.
- Think of a container as a shipping container: same contents, runs identically anywhere.
- An "image" is the blueprint; a "container" is a running instance of that image.
- Docker Hub / registries store images so teams can share and deploy them.
- docker build → docker push → docker pull → docker run is the typical workflow.

Terraform:
- Terraform lets you describe infrastructure as code (IaC) — instead of clicking in AWS console, you write .tf files.
- "terraform plan" shows what WOULD change — always run this before apply.
- "terraform apply" actually creates/updates real infrastructure — changes have real costs.
- "terraform destroy" deletes everything Terraform manages in that directory.
- State file (terraform.tfstate) tracks what Terraform created — treat it like a database, never edit manually.
- Workspaces let you manage multiple environments (dev/staging/prod) from the same config.
- "terraform import" lets you bring existing infrastructure under Terraform management.

SonarQube:
- SonarQube is a code quality and security scanner. It reads your source code and finds bugs, vulnerabilities, and "code smells" (bad patterns that aren't bugs yet but will cause problems).
- A "quality gate" is a pass/fail threshold — e.g., "no new critical vulnerabilities allowed".
- "Issues" are individual findings: bugs (will break), vulnerabilities (security risk), code smells (maintainability).
- The analysis history shows trends — is code quality improving or degrading over time?
- Projects are repositories or codebases registered for scanning.

Nexus Repository Manager:
- Nexus is a repository manager — a private storage location for software packages (Maven JARs, npm packages, Docker images, Python wheels, etc.).
- Teams use Nexus so they don't download dependencies from the public internet on every build (faster, more reliable, audit trail).
- A "hosted" repository stores your own artifacts. A "proxy" repository caches public registry packages. A "group" combines multiple repos into one URL.
- Components are the actual packages (e.g., myapp-1.2.3.jar). Assets are the individual files within a component.
- Cleanup tasks automatically delete old or unused artifacts to save disk space.

Self-hosted LLMs (GPU instances, vLLM, EKS GPU nodes):
- Calling a hosted model API (Anthropic, OpenAI) needs no GPU of your own — the provider runs the GPUs and bills per token. Self-hosting means running an open-weight model (Llama, Qwen, Mistral) on GPUs you pay for by the hour.
- Teams self-host for data privacy/compliance (data never leaves their account), cost at high steady volume, customization (fine-tuning), and control (no rate limits or vendor model retirements). At low or bursty volume, an API is usually cheaper and simpler.
- GPU memory (VRAM) is the constraint: model weights need roughly 2 bytes per parameter at 16-bit precision, so a 7B model is about 15 GB before any working memory. A g5.xlarge has one NVIDIA A10G with 24 GB.
- vLLM is an inference server: it loads the model onto the GPU and exposes an OpenAI-compatible HTTP API, so existing OpenAI-style clients work by changing only base_url and api_key. It reserves most of the GPU memory up front for its KV cache, which is what lets it batch many requests at once — that batching is the main reason self-hosting can be cost-effective.
- The AWS Deep Learning Base GPU AMI (find_ami distro "dlami-gpu") already has the NVIDIA driver, Docker and the NVIDIA container toolkit, so a container can use the GPU with --gpus all and no driver installation.
- GPU capacity is gated by a vCPU-based Service Quota ("Running On-Demand G and VT instances"), which is often 0 on new accounts — the most common first failure.
- On Kubernetes, a GPU node also needs the NVIDIA device plugin, which advertises nvidia.com/gpu to the scheduler; a pod requests a GPU with resources.limits nvidia.com/gpu: 1. Without the plugin, GPU pods stay Pending forever.
- Each cloud gates GPUs differently: AWS uses a vCPU quota per instance family, Azure a vCPU quota per VM family (e.g. NCASv3_T4) shown by compute usage, and GCP a GPU-count quota per region plus a global one (NVIDIA_L4_GPUS, GPUS_ALL_REGIONS).
- Drivers arrive differently too: AWS's Deep Learning AMI ships them, Azure installs them with the NvidiaGpuDriverLinux VM extension, and GCP's Deep Learning VM installs them on first boot when metadata install-nvidia-driver is True.
- On-prem, the NVIDIA driver and container toolkit are installed on each GPU host by whoever runs the hardware; Kubernetes only sees GPUs once the device plugin (or the NVIDIA GPU Operator) is running. Air-gapped clusters must pre-stage model weights because they cannot download from Hugging Face.
- Older GPUs such as the T4 lack bfloat16, so vLLM needs --dtype half on them.
- GPU instances are expensive and bill while idle. Always tell the learner exactly how to tear down what was created.

Keep answers complete and thorough — teaching takes as many words as it needs to be clear.
"""

SANDBOX_MODE_ADDENDUM = """
SANDBOX MODE IS ACTIVE. All tool results are SIMULATED — no real cloud infrastructure is affected.

SANDBOX TEACHING APPROACH:
- Begin simulated results with "[SANDBOX]" so learners know this is practice data
- After each result, add: "In a real AWS/Azure/GCP account, this would show YOUR actual resources with your real IPs, names, and configurations"
- Explain what would be DIFFERENT in production: real costs, eventual consistency, IAM permissions required, risk of mistakes
- Actively encourage experimentation: "Nothing can break here. Try deleting that instance, creating a new VPC, changing security group rules — learn by doing!"
- When a user runs a destructive action (delete/terminate), execute it AND explain: "In a real environment, you'd want to double-check this and possibly create a snapshot first. In sandbox, practicing this workflow is exactly right."
- When real-world cost matters, say it is an estimate and point to the provider's pricing page. Never quote a price as fact.
- Mention real-world permissions: "To run this in real AWS, your IAM user would need the ec2:DescribeInstances permission"

FIRST STEPS — the user may be brand new to DevOps:
- If they ask what you can do, what tools you have, or how to start, do NOT list tools or categories. Offer three short practice missions in plain words (for example: launch a small web server and take it down again; find what is wasting money in an account; fix an app that keeps crashing) and ask which one to start. If they already picked one, start it right away.
- ONE STEP PER REPLY. For a mission or any "walk me through" / "step by step" request: explain the next step in plain words, do only that step (at most one tool call that changes something), show what happened, then stop and ask "Ready for the next step?". Never do the next step, and never clean up, in the same reply. Only run several steps at once if the user asks you to.
- Before doing a step, say what you are about to do and why, in one or two sentences.
- Use plain words. Explain any DevOps term the first time it appears.

DEBUGGING SCENARIOS — if user wants to practice troubleshooting, suggest:
- "Simulate a pod in CrashLoopBackOff" — Kubernetes debugging workflow
- "Simulate a security group blocking web traffic" — network troubleshooting
- "Simulate a disk full node" — disk pressure and pod eviction
- "Simulate high CPU on EC2" — performance investigation
- "Simulate OOMKilled pod" — memory limit tuning
- "Simulate database connection refused" — security group + networking debug
"""

SANDBOX_CLOUD_ACCESS = (
    "CLOUD ACCESS: SANDBOX. Every AWS, Azure, GCP and Kubernetes tool returns simulated "
    "practice data, so use any of them freely. Never tell the user to add cloud credentials "
    "or that tools will fail: nothing real is connected and nothing needs to be."
)


def _swarm_agents_for(model_config, prefs, sandbox_active):
    """How many Kimi swarm helpers this turn may use.

    None in sandbox: a swarm splits a multi-step request and finishes it in one reply,
    while sandbox is for learners walking through one step at a time.
    """
    if sandbox_active:
        return 0
    if prefs is not None and not getattr(prefs, 'swarm_enabled', True):
        return 0
    return getattr(model_config, 'swarm_max_agents', 0)


def _cloud_access_context(user_id, sandbox_active):
    """What the agent may assume about cloud access for this turn.

    In sandbox every provider is simulated, so the real-credentials status (which says
    "NOT configured, do not call these tools") would contradict sandbox and the agent
    would tell a new user to go add credentials instead of letting them practise.
    """
    if sandbox_active:
        return SANDBOX_CLOUD_ACCESS
    try:
        from services.credential_service import get_user_configured_providers
        configured = get_user_configured_providers(user_id)
    except Exception:
        return None
    configured_list = [p.upper() for p, v in configured.items() if v]
    not_configured = [p.upper() for p, v in configured.items() if not v]
    cred_status = f"CLOUD CREDENTIALS STATUS: Configured and ready: {', '.join(configured_list) if configured_list else 'none'}."
    if not_configured:
        cred_status += (
            f" NOT configured: {', '.join(not_configured)}."
            f" Do NOT call {'/'.join(not_configured)} tools — they will fail."
            f" If the user asks for {'/'.join(not_configured)} operations, tell them to add credentials in Settings > Cloud Credentials first."
            + (f" You CAN and SHOULD use {', '.join(configured_list)} tools freely." if configured_list else "")
        )
    return cred_status


# ---------------------------------------------------------------------------
# Structured learning curriculum (used by /api/learning/paths)
# ---------------------------------------------------------------------------
LEARNING_CURRICULUM = {
    'devops_fundamentals': {
        'title': 'DevOps Fundamentals',
        'description': 'Start here if you are brand new to DevOps. Learn what it is, why it matters, and where to begin.',
        'level': 'beginner',
        'estimated_hours': 4,
        'icon': 'compass',
        'modules': [
            {
                'id': 'what_is_devops',
                'title': 'What is DevOps?',
                'starter_prompt': 'I am completely new to DevOps and cloud. Can you explain what DevOps is, why companies use it, what a DevOps engineer does day to day, and how I should start learning? Assume I know nothing.',
                'topics': ['DevOps culture', 'CI/CD concept', 'infrastructure as code', 'monitoring', 'career path'],
            },
            {
                'id': 'devops_toolchain',
                'title': 'The DevOps Toolchain',
                'starter_prompt': 'Walk me through the tools a DevOps engineer uses from writing code all the way to deploying it to production. Explain each tool and why it is used.',
                'topics': ['Git', 'Docker', 'Kubernetes', 'Terraform', 'CI/CD pipelines', 'monitoring tools'],
            },
            {
                'id': 'linux_basics',
                'title': 'Linux for DevOps',
                'starter_prompt': 'What Linux commands do I absolutely need to know as a DevOps engineer? Start from the very basics — file navigation, permissions, processes — and tell me why each one matters.',
                'topics': ['bash shell', 'file system navigation', 'file permissions', 'processes', 'SSH', 'networking commands'],
            },
        ]
    },
    'aws_foundations': {
        'title': 'AWS Foundations',
        'description': 'Learn Amazon Web Services from scratch — the world\'s most popular cloud platform.',
        'level': 'beginner',
        'estimated_hours': 10,
        'icon': 'cloud',
        'modules': [
            {
                'id': 'cloud_intro',
                'title': 'What is Cloud Computing?',
                'starter_prompt': 'Explain cloud computing to me like I have never heard of it before. What is AWS, what is a region, what is an availability zone, and why do companies use cloud instead of buying their own servers?',
                'topics': ['cloud computing', 'AWS overview', 'regions', 'availability zones', 'shared responsibility model'],
            },
            {
                'id': 'ec2_intro',
                'title': 'EC2 — Your First Virtual Server',
                'starter_prompt': 'Teach me about EC2 instances from scratch. What are they, how do you choose an instance type, what is an AMI, and can you show me what running EC2 instances look like in the sandbox?',
                'topics': ['EC2 instances', 'instance types', 'AMIs', 'key pairs', 'SSH access', 'instance states'],
            },
            {
                'id': 's3_intro',
                'title': 'S3 — Cloud Object Storage',
                'starter_prompt': 'I want to understand S3 storage. What is it, what is the difference between a bucket and an object, when would I store things in S3 versus on an EC2 disk, and can we explore it in the sandbox?',
                'topics': ['S3 buckets', 'objects and keys', 'storage classes', 'versioning', 'static website hosting', 'lifecycle policies'],
            },
            {
                'id': 'iam_intro',
                'title': 'IAM — Security and Permissions',
                'starter_prompt': 'Explain AWS IAM to me. I know it stands for Identity and Access Management but I do not understand users, groups, roles, and policies. Walk me through it step by step with examples.',
                'topics': ['IAM users', 'IAM groups', 'IAM roles', 'policies', 'least privilege principle', 'MFA'],
            },
            {
                'id': 'vpc_intro',
                'title': 'VPC and Networking',
                'starter_prompt': 'I want to understand AWS networking. What is a VPC, what are subnets, what is the difference between public and private subnets, and why does it matter where I put my EC2 instance?',
                'topics': ['VPC', 'subnets', 'route tables', 'internet gateway', 'NAT gateway', 'CIDR notation'],
            },
            {
                'id': 'security_groups',
                'title': 'Security Groups — Firewall Rules',
                'starter_prompt': 'Explain security groups to me. How do they work, how are inbound and outbound rules different, and can we look at some security groups in the sandbox and understand what they are allowing?',
                'topics': ['security groups', 'inbound rules', 'outbound rules', 'ports', 'protocols', 'CIDR blocks'],
            },
            {
                'id': 'rds_intro',
                'title': 'RDS — Managed Databases',
                'starter_prompt': 'What is RDS and why would I use it instead of just installing PostgreSQL directly on my EC2 instance? What does AWS manage for me, and what do I still manage myself?',
                'topics': ['RDS', 'managed databases', 'Multi-AZ', 'read replicas', 'automated backups', 'database security'],
            },
            {
                'id': 'lambda_intro',
                'title': 'Lambda — Serverless Computing',
                'starter_prompt': 'I keep hearing the word serverless. What is AWS Lambda, how is it completely different from EC2, when should I use it, and what does serverless actually mean — there are still servers, right?',
                'topics': ['Lambda', 'serverless', 'event-driven architecture', 'triggers', 'cold starts', 'pricing model'],
            },
        ]
    },
    'kubernetes_basics': {
        'title': 'Kubernetes Basics',
        'description': 'Master container orchestration — run apps reliably at any scale.',
        'level': 'intermediate',
        'estimated_hours': 12,
        'prerequisite': 'Basic understanding of Docker containers recommended',
        'icon': 'grid',
        'modules': [
            {
                'id': 'k8s_intro',
                'title': 'What is Kubernetes?',
                'starter_prompt': 'I know what Docker containers are but I do not understand why I need Kubernetes. What problem does it solve, and what would go wrong if I just ran Docker containers directly on servers?',
                'topics': ['container orchestration', 'Kubernetes architecture', 'control plane', 'worker nodes', 'etcd'],
            },
            {
                'id': 'pods',
                'title': 'Pods — The Atomic Unit',
                'starter_prompt': 'Explain Kubernetes Pods to me. What exactly is a pod, how is it different from a container, and when would you put multiple containers in the same pod? Show me some pods in the sandbox.',
                'topics': ['pods', 'containers vs pods', 'multi-container pods', 'pod lifecycle', 'pod IP addresses'],
            },
            {
                'id': 'deployments',
                'title': 'Deployments — Reliable Updates',
                'starter_prompt': 'What is a Kubernetes Deployment and why is it better than running pods directly? How do rolling updates work, and how do I roll back if a deployment breaks production?',
                'topics': ['deployments', 'replica sets', 'rolling updates', 'rollbacks', 'deployment strategies'],
            },
            {
                'id': 'services_networking',
                'title': 'Services — Kubernetes Networking',
                'starter_prompt': 'How does networking work in Kubernetes? How do pods find each other, what is a Service, and how does traffic from the internet reach my application inside the cluster?',
                'topics': ['services', 'ClusterIP', 'NodePort', 'LoadBalancer', 'Ingress', 'DNS in Kubernetes'],
            },
            {
                'id': 'k8s_debugging',
                'title': 'Debugging in Kubernetes',
                'starter_prompt': 'Simulate a pod that is failing with CrashLoopBackOff so I can practice the debugging workflow. Teach me step by step how you would diagnose and fix a broken pod in production.',
                'topics': ['kubectl logs', 'describe pod', 'CrashLoopBackOff', 'OOMKilled', 'ImagePullBackOff', 'events'],
            },
            {
                'id': 'config_secrets',
                'title': 'ConfigMaps and Secrets',
                'starter_prompt': 'How do I manage configuration and secrets in Kubernetes? What is the difference between a ConfigMap and a Secret, and why should I not hardcode environment variables in my Docker image?',
                'topics': ['ConfigMaps', 'Secrets', 'environment variables', 'volume mounts', 'secret management'],
            },
        ]
    },
    'cicd_pipelines': {
        'title': 'CI/CD Pipelines',
        'description': 'Automate testing and deployment so every code change ships safely and fast.',
        'level': 'intermediate',
        'estimated_hours': 8,
        'prerequisite': 'Comfortable with Git and basic cloud concepts',
        'icon': 'git-merge',
        'modules': [
            {
                'id': 'cicd_concepts',
                'title': 'CI/CD Concepts',
                'starter_prompt': 'Explain CI/CD to me from scratch. What is Continuous Integration vs Continuous Delivery vs Continuous Deployment? Why do teams use it, and what does a typical pipeline look like?',
                'topics': ['CI/CD concepts', 'build pipelines', 'automated testing', 'deployment stages', 'trunk-based development'],
            },
            {
                'id': 'github_actions',
                'title': 'GitHub Actions',
                'starter_prompt': 'Teach me GitHub Actions. How do I create a workflow that runs my tests automatically when I push code, and then deploys to AWS if the tests pass? Walk me through writing the YAML.',
                'topics': ['GitHub Actions', 'workflows', 'jobs', 'steps', 'runners', 'secrets', 'artifacts'],
            },
        ]
    },
    'infrastructure_as_code': {
        'title': 'Infrastructure as Code',
        'description': 'Manage cloud resources with code instead of clicking around consoles.',
        'level': 'intermediate',
        'estimated_hours': 10,
        'prerequisite': 'Working knowledge of at least one cloud provider',
        'icon': 'code',
        'modules': [
            {
                'id': 'iac_concepts',
                'title': 'What is Infrastructure as Code?',
                'starter_prompt': 'What is Infrastructure as Code and why is everyone talking about Terraform? What is wrong with just clicking around in the AWS console, and how does writing infrastructure in code files solve those problems?',
                'topics': ['IaC concepts', 'declarative vs imperative', 'idempotency', 'version control for infrastructure', 'Terraform overview'],
            },
            {
                'id': 'terraform_basics',
                'title': 'Terraform Basics',
                'starter_prompt': 'Walk me through the core concepts of Terraform. What is a provider, a resource, a variable, an output, and a state file? How does terraform plan and terraform apply work?',
                'topics': ['Terraform HCL', 'providers', 'resources', 'variables', 'outputs', 'state file', 'plan and apply'],
            },
        ]
    },
    'monitoring_observability': {
        'title': 'Monitoring and Observability',
        'description': 'Know when things go wrong before your users do.',
        'level': 'intermediate',
        'estimated_hours': 6,
        'icon': 'activity',
        'modules': [
            {
                'id': 'monitoring_concepts',
                'title': 'Monitoring, Logging, and Tracing',
                'starter_prompt': 'Explain the three pillars of observability: metrics, logs, and traces. What is the difference between them, which tools are used for each, and how do they help me understand what my application is doing?',
                'topics': ['metrics', 'logs', 'distributed tracing', 'CloudWatch', 'Prometheus', 'Grafana', 'alerting'],
            },
        ]
    },
}


def _track_conversion(user_id: int, event_type: str, metadata: dict = None) -> None:
    """Fire-and-forget conversion funnel event. Silently ignores errors."""
    try:
        db.session.add(ConversionEvent(
            user_id=user_id,
            event_type=event_type,
            event_metadata=metadata or {},
        ))
        db.session.flush()
    except Exception:
        pass


@app.route('/')
def index():
    """Show landing page for unauthenticated users, chat for authenticated."""
    if not current_user.is_authenticated:
        return render_template('landing.html')
    return redirect(url_for('chat'))


@app.route('/chat')
@login_required
def chat():
    """Render the main chat interface or setup page."""
    if not check_api_key_configured():
        return render_template('setup.html')

    # Redirect new users who haven't connected any cloud credentials yet
    if not current_user.onboarding_completed:
        from models import UserCloudCredential
        has_creds = UserCloudCredential.query.filter_by(
            user_id=current_user.id, is_active=True
        ).first()
        if not has_creds:
            return redirect(url_for('onboarding_page'))

    if 'conversation_id' not in session:
        session['conversation_id'] = secrets.token_hex(8)

    subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
    if not subscription:
        free_tier = SubscriptionTier.query.filter_by(name='free').first()
        if free_tier:
            from dateutil.relativedelta import relativedelta
            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=free_tier.id,
                credits_remaining=free_tier.monthly_credits,
                current_period_start=utcnow(),
                current_period_end=utcnow() + relativedelta(months=1),
                last_reset_date=utcnow(),
            )
            db.session.add(subscription)
            db.session.commit()

    credits = subscription.credits_remaining if subscription else 0
    first_message = request.args.get('first_message', '')
    return render_template('index.html', user=current_user, initial_credits=credits,
                           first_message=first_message)


@app.route('/dashboard')
@login_required
def dashboard():
    """Infrastructure dashboard with real-time monitoring."""
    return render_template('dashboard_live.html', user=current_user)


@app.route('/infrastructure/map')
@login_required
def infrastructure_map():
    return render_template('infrastructure/map.html', user=current_user)


@app.route('/api/infrastructure/topology')
@login_required
def api_infrastructure_topology():
    resources = InfrastructureResource.query.filter_by(user_id=current_user.id).all()

    # Build a lookup: resource_id → node id (str(r.id))
    rid_to_node_id = {r.resource_id: str(r.id) for r in resources}

    nodes = []
    edges = []
    seen_vpcs = {}
    seen_clusters = {}

    for r in resources:
        meta = r.resource_metadata or {}
        node = {
            'id': str(r.id),
            'label': r.resource_name or r.resource_id,
            'sub': r.resource_id,
            'type': r.resource_type,
            'provider': r.cloud_provider,
            'region': r.region,
            'status': r.status,
            'cost': r.monthly_cost,
        }
        nodes.append(node)

        # VPC → EC2 edges
        vpc_id = meta.get('vpc_id')
        if vpc_id:
            if vpc_id not in seen_vpcs:
                seen_vpcs[vpc_id] = f'vpc_{vpc_id}'
                nodes.append({'id': f'vpc_{vpc_id}', 'label': vpc_id[:20], 'sub': vpc_id,
                               'type': 'vpc', 'provider': 'aws', 'group': True, 'status': 'active'})
            edges.append({'source': f'vpc_{vpc_id}', 'target': str(r.id), 'label': 'contains'})

        # EBS → EC2 edges
        attached_to = meta.get('attached_to')
        if attached_to and attached_to in rid_to_node_id:
            edges.append({'source': str(r.id), 'target': rid_to_node_id[attached_to], 'label': 'attached'})

        # Elastic IP → EC2 edges
        eip_instance = meta.get('instance_id')
        if eip_instance and eip_instance in rid_to_node_id:
            edges.append({'source': str(r.id), 'target': rid_to_node_id[eip_instance], 'label': 'assigned'})

        # K8s cluster grouping
        cluster = meta.get('cluster_name') or meta.get('cluster')
        if cluster and r.cloud_provider == 'kubernetes':
            if cluster not in seen_clusters:
                seen_clusters[cluster] = f'cluster_{cluster}'
                nodes.append({'id': f'cluster_{cluster}', 'label': cluster, 'sub': cluster,
                               'type': 'cluster', 'provider': 'kubernetes', 'group': True,
                               'region': r.region, 'status': 'active'})
            edges.append({'source': f'cluster_{cluster}', 'target': str(r.id), 'label': 'contains'})

    return jsonify({'nodes': nodes, 'edges': edges})


@app.route('/workflows')
@login_required
def workflows_page():
    """Pre-built workflow templates."""
    return render_template('workflows.html', user=current_user)


@app.route('/changes')
@login_required
def changes_page():
    """Change governance and approval workflows."""
    return render_template('changes.html', user=current_user)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Profile now lives in Settings; this keeps old links and the profile form working."""
    if request.method == 'POST':
        try:
            current_user.full_name = (request.form.get('full_name', '').strip() or None)
            current_user.bio = (request.form.get('bio', '').strip() or None)
            color = request.form.get('avatar_color', '').strip()
            if re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                current_user.avatar_color = color
            theme = request.form.get('theme', '')
            if theme in ('light', 'dark'):
                current_user.theme = theme
            db.session.commit()
            return redirect('/settings?saved=profile#profile')
        except Exception:
            db.session.rollback()
            logger.exception('Profile update failed')
            return redirect('/settings?error=profile#profile')
    return redirect('/settings#profile')


@app.route('/doctor')
@login_required
@_admin_required
def doctor_page():
    """Platform diagnostics (database, keys, disk, packages). Admin only: it
    describes the server, not the signed-in user's account."""
    from services.doctor import run_diagnostics
    results = run_diagnostics(app=app, db=db, agent=agent)
    return render_template('doctor.html', results=results, user=current_user)


PLATFORM_AWS_ACCOUNT_ID = os.environ.get('PLATFORM_AWS_ACCOUNT_ID', '188046727805')
# Public quick-create template; its trust policy names PLATFORM_AWS_ACCOUNT_ID, so the
# two must move together (docs/aws-account-migration.md).
CF_TEMPLATE_URL = os.environ.get(
    'CF_TEMPLATE_URL', 'https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json')


@app.route('/onboarding', methods=['GET'])
@login_required
def onboarding_page():
    """Onboarding wizard for new users."""
    return render_template('onboarding.html', user=current_user,
                           platform_aws_account_id=PLATFORM_AWS_ACCOUNT_ID,
                           cf_template_url=CF_TEMPLATE_URL)


@app.route('/api/onboarding/complete', methods=['POST'])
@login_required
def complete_onboarding():
    """Mark onboarding as completed."""
    data = request.get_json() or {}
    current_user.onboarding_completed = True
    current_user.onboarding_step = data.get('step', 0)
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/onboarding/step', methods=['POST'])
@login_required
def update_onboarding_step():
    """Update the current onboarding step."""
    data = request.get_json() or {}
    step = data.get('step', 0)
    current_user.onboarding_step = step
    db.session.commit()
    return jsonify({'success': True, 'step': step})


@app.route('/api/onboarding/scan', methods=['POST'])
@login_required
def onboarding_scan():
    """
    Trigger a first-time infrastructure discovery scan.

    Called after the user connects their first cloud credential in the
    onboarding wizard. Runs sync_user_infrastructure() synchronously so
    results are available immediately on the wizard's results step.

    Returns a summary: resource counts, estimated monthly cost, cost
    optimization count, security finding count.
    """
    try:
        from services.infrastructure_sync import sync_user_infrastructure
        from models import InfrastructureResource, CostOptimization, SecurityFinding

        sync_result = sync_user_infrastructure(current_user.id)

        # Build a summary for the wizard results step
        resources = InfrastructureResource.query.filter_by(
            user_id=current_user.id
        ).all()

        resource_by_type = {}
        for r in resources:
            resource_by_type[r.resource_type] = resource_by_type.get(r.resource_type, 0) + 1

        cost_findings = CostOptimization.query.filter_by(
            user_id=current_user.id,
            status='pending'
        ).count()
        potential_savings = db.session.query(
            db.func.sum(CostOptimization.potential_monthly_savings)
        ).filter_by(user_id=current_user.id, status='pending').scalar() or 0.0

        security_findings = SecurityFinding.query.filter_by(
            user_id=current_user.id,
            status='open'
        ).count()
        critical_findings = SecurityFinding.query.filter_by(
            user_id=current_user.id,
            status='open',
            severity='critical'
        ).count()

        return jsonify({
            'success': True,
            'total_resources': sync_result.get('total_resources', 0),
            'monthly_cost': round(sync_result.get('total_cost', 0.0), 2),
            'resource_breakdown': resource_by_type,
            'cost_findings': cost_findings,
            'potential_savings': round(float(potential_savings), 2),
            'security_findings': security_findings,
            'critical_findings': critical_findings,
            'providers': {
                'aws': sync_result.get('aws', {}).get('synced', 0),
                'azure': sync_result.get('azure', {}).get('synced', 0),
                'gcp': sync_result.get('gcp', {}).get('synced', 0),
            }
        })

    except Exception as e:
        logger.error(f"Onboarding scan failed for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/setup', methods=['GET', 'POST'])
@login_required
@_admin_required
def setup():
    """Platform API key configuration. Admin only: the key is written into the
    server's config/.env and re-initializes the shared agent for every user."""
    if request.method == 'POST':
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request'}), 400
        api_key = data.get('api_key', '').strip()
        if len(api_key) > 200:
            return jsonify({'error': 'Invalid API key'}), 400

        if not api_key:
            return jsonify({'error': 'API key is required'}), 400

        if not api_key.startswith('sk-ant-'):
            return jsonify({'error': 'Invalid Anthropic API key format'}), 400

        try:
            # Save API key
            save_api_key(api_key)

            # Try to initialize agent
            success, error = initialize_agent()

            if not success:
                return jsonify({'error': f'Failed to initialize agent: {error}'}), 500

            return jsonify({'success': True, 'message': 'API key configured successfully'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return render_template('setup.html')


@app.route('/settings')
@login_required
def settings():
    """Settings page for AWS and other configurations."""
    return render_template('settings.html', user=current_user,
                           platform_aws_account_id=PLATFORM_AWS_ACCOUNT_ID,
                           cf_template_url=CF_TEMPLATE_URL)


@app.route('/settings/skills')
@login_required
def settings_skills():
    """Skills now live in a Settings tab."""
    return redirect('/settings#skills')


@app.route('/docs')
def docs():
    """Documentation page - Public access."""
    return render_template('docs.html')


@app.route('/developers')
def developers():
    """Public API reference page - no auth required."""
    return render_template('developers.html')


@app.route('/usage-policy')
def usage_policy():
    """Usage Policy (Terms of Service) page - Public access."""
    return render_template('usage-policy.html')


# ---------------------------------------------------------------------------
# Status page
# ---------------------------------------------------------------------------

@app.route('/status')
def status_page():
    """Public status page — no login required. Checks are cached (status_service.CACHE_SECONDS)."""
    services = status_service.check_health()
    overall = status_service.get_overall_status(services)
    return render_template('status.html', services=services, overall=overall,
                           checked_at=status_service.checked_at())


@app.route('/status/unsubscribe/<token>')
def status_unsubscribe(token):
    """Unsubscribe from status-page emails (sign-ups were removed 2026-10-14; old links still work)."""
    ok, email = status_service.unsubscribe(token)
    services = status_service.check_health()
    return render_template('status.html',
        services=services,
        overall=status_service.get_overall_status(services),
        checked_at=status_service.checked_at(),
        flash_msg='You have been unsubscribed.' if ok else 'Invalid unsubscribe link.',
        flash_type='success' if ok else 'error',
    )


@app.route('/email/unsubscribe')
def email_unsubscribe():
    """Unsubscribe from onboarding and weekly digest emails (unauthenticated, HMAC-verified)."""
    from services.drip_email_service import verify_unsubscribe_token
    user_id = request.args.get('user_id', type=int)
    token = request.args.get('token', '')
    if not user_id or not token or not verify_unsubscribe_token(user_id, token):
        return '<html><body style="background:#0f1117;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><h2>Invalid link</h2><p style="color:#94a3b8">This unsubscribe link is invalid or expired.</p></div></body></html>', 400
    user = User.query.get(user_id)
    if user:
        user.email_opt_out = True
        db.session.commit()
    return '<html><body style="background:#0f1117;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="text-align:center"><h2>Unsubscribed</h2><p style="color:#94a3b8">You will no longer receive onboarding or weekly digest emails from DevOps Agent. Budget alerts you set up are not affected.</p></div></body></html>'


@app.route('/api/status/health')
def api_status_health():
    """JSON health check for external monitors (e.g. UptimeRobot)."""
    services = status_service.check_health()
    overall = status_service.get_overall_status(services)
    code = 200 if overall == 'operational' else 503
    checked = status_service.checked_at()
    return jsonify({'status': overall, 'services': services,
                    'checked_at': checked.isoformat() + 'Z' if checked else None,
                    'ts': utcnow().isoformat()}), code


@app.route('/api/notifications')
@login_required
def get_notifications():
    notifs = AppNotification.query.filter_by(user_id=current_user.id).order_by(AppNotification.created_at.desc()).limit(50).all()
    unread = AppNotification.query.filter_by(user_id=current_user.id, read=False).count()
    return jsonify({'notifications': [n.to_dict() for n in notifs], 'unread': unread})


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    data = request.get_json(silent=True) or {}
    notif_id = data.get('id')
    if notif_id:
        notif = AppNotification.query.filter_by(id=notif_id, user_id=current_user.id).first()
        if notif:
            notif.read = True
    else:
        AppNotification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/notifications', methods=['DELETE'])
@login_required
def clear_notifications():
    AppNotification.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'success': True})


@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page - Public access."""
    return render_template('privacy-policy.html')


@app.route('/about')
def about():
    """About page - Explains all features."""
    return render_template('about.html')


@app.route('/security')
def security_page():
    """Public security/trust page - credential handling, policies, guardrails."""
    return render_template('security.html')


@app.route('/api/aws-config', methods=['GET', 'POST', 'DELETE'])
@app.route('/api/aws/config', methods=['GET', 'POST', 'DELETE'])
@login_required
def aws_config():
    """Handle AWS configuration - per-user credential storage."""
    from services.credential_service import (
        save_user_aws_credentials,
        get_user_aws_credentials,
        delete_user_cloud_credentials
    )
    from models import UserCloudCredential

    if request.method == 'GET':
        # Get user's AWS credential status
        cred = UserCloudCredential.query.filter_by(
            user_id=current_user.id,
            cloud_provider='aws'
        ).first()

        if cred and cred.is_active:
            credentials = cred.get_credentials()
            result = {
                'configured': True,
                'region': cred.default_region,
                'verification_status': cred.verification_status,
                'last_verified': cred.last_verified.isoformat() if cred.last_verified else None
            }
            if credentials.get('role_arn'):
                result['auth_mode'] = 'role_arn'
                result['role_arn'] = credentials['role_arn']
                result['has_external_id'] = bool(credentials.get('external_id'))
                result['self_grant'] = bool(credentials.get('self_grant'))
            else:
                result['auth_mode'] = 'access_key'
                access_key = credentials.get('access_key', '')
                result['access_key'] = access_key[:8] + '****' if len(access_key) > 8 else '****'
            return jsonify(result)
        return jsonify({'configured': False})

    if request.method == 'DELETE':
        # Delete user's AWS credentials
        success, message = delete_user_cloud_credentials(current_user.id, 'aws')
        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    # POST - Save AWS credentials for this user
    # Check tier limits (only for new credentials, not updates)
    from services.tier_enforcement import check_resource_limit
    existing = UserCloudCredential.query.filter_by(user_id=current_user.id, cloud_provider='aws').first()
    if not existing:
        allowed, current, limit = check_resource_limit(current_user.id, 'cloud_accounts')
        if not allowed:
            return jsonify({'error': f'Cloud account limit reached ({limit}). Upgrade your plan for more.', 'upgrade_url': '/billing'}), 403

    try:
        data = request.get_json() or {}
        region = (data.get('region') or 'us-east-1').strip()

        success, message = save_user_aws_credentials(
            user_id=current_user.id,
            access_key=(data.get('access_key') or data.get('access_key_id') or '').strip(),
            secret_key=(data.get('secret_key') or data.get('secret_access_key') or '').strip(),
            role_arn=(data.get('role_arn') or '').strip(),
            external_id=(data.get('external_id') or '').strip(),
            region=region
        )

        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/aws/test', methods=['GET'])
@login_required
def test_aws_connection():
    """Test AWS connection using saved credentials."""
    try:
        from services.credential_service import get_user_boto_client
        sts = get_user_boto_client(current_user.id, 'sts')
        identity = sts.get_caller_identity()
        return jsonify({
            'success': True,
            'message': f"Connected as {identity.get('Arn', 'unknown')}",
            'account': identity.get('Account'),
            'arn': identity.get('Arn')
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 502


@app.route('/api/aws/self-grant', methods=['PUT'])
@login_required
def aws_self_grant():
    """Turn on/off letting the agent add owner-approved permissions to its own role."""
    from services.credential_service import set_aws_self_grant
    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('enabled'), bool):
        return jsonify({'error': 'enabled must be true or false'}), 400
    ok, message = set_aws_self_grant(current_user.id, data['enabled'])
    if ok:
        return jsonify({'success': True, 'self_grant': data['enabled'], 'message': message})
    return jsonify({'error': message}), 400


@app.route('/api/aws/policy-check', methods=['GET'])
@login_required
def aws_policy_check():
    """Check whether the connected IAM role predates the 2026-07-24 policy fixes."""
    from services.credential_service import check_aws_policy_freshness
    return jsonify(check_aws_policy_freshness(current_user.id))


@app.route('/api/azure/test', methods=['GET'])
@login_required
def test_azure_connection():
    """Test Azure connection using saved credentials."""
    from models import UserCloudCredential
    cred = UserCloudCredential.query.filter_by(
        user_id=current_user.id,
        cloud_provider='azure'
    ).first()
    if not cred or not cred.is_active:
        return jsonify({'success': False, 'error': 'No Azure credentials configured'})
    try:
        creds = cred.get_credentials()
        from azure.identity import ClientSecretCredential
        from azure.mgmt.resource import SubscriptionClient
        credential = ClientSecretCredential(
            tenant_id=creds.get('tenant_id'),
            client_id=creds.get('client_id'),
            client_secret=creds.get('client_secret')
        )
        sub_client = SubscriptionClient(credential)
        subscriptions = list(sub_client.subscriptions.list())
        return jsonify({'success': True, 'message': f'Azure credentials are valid ({len(subscriptions)} subscription(s) accessible)'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/gcp/test', methods=['GET'])
@login_required
def test_gcp_connection():
    """Test GCP connection using saved credentials."""
    from models import UserCloudCredential
    cred = UserCloudCredential.query.filter_by(
        user_id=current_user.id,
        cloud_provider='gcp'
    ).first()
    if not cred or not cred.is_active:
        return jsonify({'success': False, 'error': 'No GCP credentials configured'})
    try:
        creds = cred.get_credentials()
        import json
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        credentials_json = creds.get('service_account_json', '')
        if isinstance(credentials_json, str):
            sa_info = json.loads(credentials_json)
        else:
            sa_info = credentials_json
        google_creds = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        project_id = creds.get('project_id') or sa_info.get('project_id')
        service = build('cloudresourcemanager', 'v1', credentials=google_creds)
        service.projects().get(projectId=project_id).execute()
        return jsonify({'success': True, 'message': f'GCP credentials are valid (project: {project_id})'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/azure-config', methods=['GET', 'POST', 'DELETE'])
@app.route('/api/azure/config', methods=['GET', 'POST', 'DELETE'])
@login_required
def azure_config():
    """Handle Azure configuration - per-user credential storage."""
    from services.credential_service import (
        save_user_azure_credentials,
        delete_user_cloud_credentials
    )
    from models import UserCloudCredential

    if request.method == 'GET':
        # Get user's Azure credential status
        cred = UserCloudCredential.query.filter_by(
            user_id=current_user.id,
            cloud_provider='azure'
        ).first()

        if cred and cred.is_active:
            creds = cred.get_credentials()
            return jsonify({
                'configured': True,
                'subscription_id': creds.get('subscription_id'),
                'location': cred.default_region,
                'verification_status': cred.verification_status,
                'last_verified': cred.last_verified.isoformat() if cred.last_verified else None
            })
        return jsonify({'configured': False})

    if request.method == 'DELETE':
        # Delete user's Azure credentials
        success, message = delete_user_cloud_credentials(current_user.id, 'azure')
        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    # POST - Save Azure credentials for this user
    from services.tier_enforcement import check_resource_limit
    existing = UserCloudCredential.query.filter_by(user_id=current_user.id, cloud_provider='azure').first()
    if not existing:
        allowed, current, limit = check_resource_limit(current_user.id, 'cloud_accounts')
        if not allowed:
            return jsonify({'error': f'Cloud account limit reached ({limit}). Upgrade your plan for more.', 'upgrade_url': '/billing'}), 403

    try:
        data = request.get_json() or {}
        subscription_id = data.get('subscription_id', '').strip()
        tenant_id = data.get('tenant_id', '').strip()
        client_id = data.get('client_id', '').strip()
        client_secret = data.get('client_secret', '').strip()
        location = data.get('location', 'eastus').strip()

        success, message = save_user_azure_credentials(
            user_id=current_user.id,
            subscription_id=subscription_id,
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            location=location
        )

        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gcp-config', methods=['GET', 'POST', 'DELETE'])
@app.route('/api/gcp/config', methods=['GET', 'POST', 'DELETE'])
@login_required
def gcp_config():
    """Handle GCP configuration - per-user credential storage."""
    from services.credential_service import (
        save_user_gcp_credentials,
        delete_user_cloud_credentials
    )
    from models import UserCloudCredential

    if request.method == 'GET':
        # Get user's GCP credential status
        cred = UserCloudCredential.query.filter_by(
            user_id=current_user.id,
            cloud_provider='gcp'
        ).first()

        if cred and cred.is_active:
            creds = cred.get_credentials()
            return jsonify({
                'configured': True,
                'project_id': creds.get('project_id'),
                'region': cred.default_region,
                'zone': cred.default_zone,
                'verification_status': cred.verification_status,
                'last_verified': cred.last_verified.isoformat() if cred.last_verified else None
            })
        return jsonify({'configured': False})

    if request.method == 'DELETE':
        # Delete user's GCP credentials
        success, message = delete_user_cloud_credentials(current_user.id, 'gcp')
        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    # POST - Save GCP credentials for this user
    from services.tier_enforcement import check_resource_limit
    existing = UserCloudCredential.query.filter_by(user_id=current_user.id, cloud_provider='gcp').first()
    if not existing:
        allowed, current, limit = check_resource_limit(current_user.id, 'cloud_accounts')
        if not allowed:
            return jsonify({'error': f'Cloud account limit reached ({limit}). Upgrade your plan for more.', 'upgrade_url': '/billing'}), 403

    try:
        data = request.get_json() or {}
        project_id = data.get('project_id', '').strip()
        credentials_json = data.get('credentials_json', '').strip()
        region = data.get('region', 'us-central1').strip()
        zone = data.get('zone', 'us-central1-a').strip()

        success, message = save_user_gcp_credentials(
            user_id=current_user.id,
            project_id=project_id,
            service_account_json=credentials_json,
            region=region,
            zone=zone
        )

        if success:
            return jsonify({'success': True, 'message': message})
        return jsonify({'error': message}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/cloud-credentials', methods=['GET'])
@login_required
def get_cloud_credentials_status():
    """Get status of all cloud credentials for the current user."""
    from services.credential_service import get_user_configured_providers
    from models import UserCloudCredential

    providers = get_user_configured_providers(current_user.id)

    # Get detailed status for each provider
    result = {}
    for provider in ['aws', 'azure', 'gcp']:
        cred = UserCloudCredential.query.filter_by(
            user_id=current_user.id,
            cloud_provider=provider
        ).first()

        if cred:
            result[provider] = {
                'configured': cred.is_active and cred.verification_status == 'valid',
                'verification_status': cred.verification_status,
                'default_region': cred.default_region,
                'last_verified': cred.last_verified.isoformat() if cred.last_verified else None
            }
        else:
            result[provider] = {
                'configured': False,
                'verification_status': None,
                'default_region': None,
                'last_verified': None
            }

    return jsonify(result)


def _validate_webhook_url(webhook_url: str, channel_type: str) -> str | None:
    """Return an error string if the URL fails SSRF/validation checks, else None."""
    from src.utils.network_safety import assert_safe_external_webhook_url, UnsafeUrlError

    if not webhook_url.startswith('https://'):
        return 'Webhook URL must use HTTPS'

    if channel_type == 'slack' and 'hooks.slack.com' not in webhook_url:
        return (
            'Slack webhook URL must come from hooks.slack.com — '
            'go to your Slack workspace → Apps → Incoming Webhooks to generate one'
        )

    try:
        assert_safe_external_webhook_url(webhook_url)
    except UnsafeUrlError as e:
        return str(e)

    return None


@app.route('/api/notification-channels', methods=['GET', 'POST'])
@login_required
def notification_channels():
    """Manage user notification channels."""
    from models import UserNotificationChannel

    if request.method == 'GET':
        channels = UserNotificationChannel.query.filter_by(user_id=current_user.id).all()
        return jsonify({'channels': [c.to_dict() for c in channels]})

    data = request.get_json()
    channel_type = data.get('channel_type', 'slack')
    name = data.get('name', '').strip()
    webhook_url = data.get('webhook_url', '').strip()

    if not name or not webhook_url:
        return jsonify({'error': 'Name and webhook URL are required'}), 400

    url_error = _validate_webhook_url(webhook_url, channel_type)
    if url_error:
        return jsonify({'error': url_error}), 400

    channel = UserNotificationChannel(
        user_id=current_user.id,
        channel_type=channel_type,
        name=name,
        webhook_url=webhook_url,
        notify_changes=data.get('notify_changes', True),
        notify_security=data.get('notify_security', True),
        notify_cost=data.get('notify_cost', True),
        notify_incidents=data.get('notify_incidents', True),
    )
    db.session.add(channel)
    db.session.commit()

    return jsonify({'success': True, 'channel': channel.to_dict()}), 201


@app.route('/api/notification-channels/<int:channel_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_notification_channel(channel_id):
    """Update or delete a notification channel."""
    from models import UserNotificationChannel
    channel = UserNotificationChannel.query.get_or_404(channel_id)
    if channel.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if request.method == 'DELETE':
        db.session.delete(channel)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json()
    if 'is_active' in data:
        channel.is_active = data['is_active']
    if 'notify_changes' in data:
        channel.notify_changes = data['notify_changes']
    if 'notify_security' in data:
        channel.notify_security = data['notify_security']
    if 'notify_cost' in data:
        channel.notify_cost = data['notify_cost']
    if 'notify_incidents' in data:
        channel.notify_incidents = data['notify_incidents']
    if 'webhook_url' in data:
        url_error = _validate_webhook_url(data['webhook_url'], channel.channel_type)
        if url_error:
            return jsonify({'error': url_error}), 400
        channel.webhook_url = data['webhook_url']

    db.session.commit()
    return jsonify({'success': True, 'channel': channel.to_dict()})


@app.route('/api/notification-channels/<int:channel_id>/test', methods=['POST'])
@login_required
def test_notification_channel(channel_id):
    """Send a test notification to a channel."""
    from models import UserNotificationChannel
    from services.notification_service import SlackClient, Notification, NotificationPriority

    channel = UserNotificationChannel.query.get_or_404(channel_id)
    if channel.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if not channel.is_active:
        return jsonify({'success': False, 'error': 'Channel is disabled'}), 400

    notification = Notification(
        title='Test Notification from DevOps Agent',
        message='Your Slack integration is working correctly. You will receive alerts here for cost findings, security scans, and infrastructure analysis.',
        priority=NotificationPriority.NORMAL,
        fields={'Source': 'DevOps Agent', 'Type': 'Connection Test'},
    )

    try:
        if channel.channel_type != 'slack':
            return jsonify({'success': False, 'error': f"Channel type '{channel.channel_type}' not supported for test"}), 400

        # Call Slack directly so we can surface the response status in the UI.
        # webhook_url is user-configured (UserNotificationChannel) — an arbitrary
        # EXTERNAL endpoint, not the self-hosted-internal-tool trust model
        # assert_safe_url's default policy is designed for, so use the stricter
        # validator (also blocks RFC1918) that also gates SlackClient/TeamsClient
        # in services/notification_service.py and api_gateway.py's webhooks-out.
        from src.utils.network_safety import safe_request, assert_safe_external_webhook_url
        payload = {
            'text': notification.title,
            'blocks': notification.to_slack_blocks(),
        }
        resp = safe_request(
            'POST',
            channel.webhook_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10,
            validator=assert_safe_external_webhook_url,
        )
        # Truncated, like every other webhook-test response body in this app —
        # this endpoint is owner-only, but the body is still attacker-influenced
        # (the response of whatever host webhook_url points at), so don't let it
        # become an unbounded SSRF response oracle.
        slack_body = resp.text.strip()[:500]
        if resp.status_code == 200 and slack_body == 'ok':
            return jsonify({'success': True, 'message': 'Test notification sent'})
        return jsonify({
            'success': False,
            'error': f"Slack returned: HTTP {resp.status_code} — {slack_body}",
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/budget-alerts', methods=['GET', 'POST'])
@login_required
def budget_alerts():
    """Manage budget alert thresholds."""
    from models import BudgetAlert

    if request.method == 'GET':
        alerts = BudgetAlert.query.filter_by(user_id=current_user.id).all()
        return jsonify({'alerts': [a.to_dict() for a in alerts]})

    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()[:100]
    try:
        threshold = float(data.get('threshold_amount', 0))
    except (TypeError, ValueError):
        threshold = 0
    period = data.get('period', 'monthly')

    if not name or threshold <= 0:
        return jsonify({'error': 'Name and positive threshold amount are required'}), 400
    if period not in ('monthly', 'weekly', 'daily'):
        return jsonify({'error': 'Period must be monthly, weekly or daily'}), 400

    alert = BudgetAlert(
        user_id=current_user.id,
        name=name,
        threshold_amount=threshold,
        period=period,
    )
    db.session.add(alert)
    db.session.commit()

    return jsonify({'success': True, 'alert': alert.to_dict()}), 201


@app.route('/api/budget-alerts/<int:alert_id>', methods=['PUT', 'DELETE'])
@login_required
def manage_budget_alert(alert_id):
    """Update or delete a budget alert."""
    from models import BudgetAlert
    alert = BudgetAlert.query.get_or_404(alert_id)
    if alert.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if request.method == 'DELETE':
        db.session.delete(alert)
        db.session.commit()
        return jsonify({'success': True})

    data = request.get_json()
    if 'is_active' in data:
        alert.is_active = data['is_active']
    if 'threshold_amount' in data:
        alert.threshold_amount = data['threshold_amount']
    if 'name' in data:
        alert.name = data['name']

    db.session.commit()
    return jsonify({'success': True, 'alert': alert.to_dict()})


# ============================================
# Free-tier Groq chat helpers (no tool use)
# ============================================

# Import chat helpers from shared service (also used by API v1)
from services.chat_service import (
    FREE_TIER_SYSTEM_PROMPT,
    is_anthropic_error as _is_anthropic_error,
    fallback_failure_message as _fallback_failure_message,
    process_free_tier_chat as _process_free_tier_chat,
    stream_free_tier_chat as _stream_free_tier_chat,
    generate_upgrade_pitch as _generate_upgrade_pitch,
    ensure_non_empty_response as _ensure_non_empty_response,
)


def _chat_rate_limit() -> str:
    """Return the rate limit string for the current user's subscription tier."""
    if not current_user.is_authenticated:
        return "10 per hour"
    sub = UserSubscription.query.filter_by(user_id=current_user.id).first()
    tier = sub.tier.name if (sub and sub.tier) else 'free'
    return {
        'free': '10 per hour',
        'starter': '60 per hour',
        'professional': '200 per hour',
        'business': '1000 per hour',
    }.get(tier, '10 per hour')


@app.route('/api/reset-streaming', methods=['POST'])
@login_required
def reset_streaming_locks():
    """Emergency reset: clears all stuck is_streaming=True locks for the current user."""
    try:
        from sqlalchemy import update as _sa_update
        result = db.session.execute(
            _sa_update(Conversation).where(
                Conversation.user_id == current_user.id,
                Conversation.is_streaming == True  # noqa: E712
            ).values(is_streaming=False, updated_at=utcnow())
        )
        db.session.commit()
        return jsonify({'success': True, 'reset': result.rowcount,
                        'message': f'Cleared {result.rowcount} stuck streaming lock(s).'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/run-migration', methods=['POST'])
@login_required
def run_db_migration():
    """Run schema migration: creates missing tables and adds missing columns. Safe to re-run."""
    from sqlalchemy import inspect as _inspect, text as _text
    _COLUMN_TYPE_MAP = {
        'Boolean': 'BOOLEAN', 'Integer': 'INTEGER', 'String': 'VARCHAR(255)',
        'Text': 'TEXT', 'DateTime': 'TIMESTAMP', 'Float': 'FLOAT', 'JSON': 'JSONB',
    }
    def _sql_type(col):
        tn = type(col.type).__name__
        if tn == 'String' and getattr(col.type, 'length', None):
            return f'VARCHAR({col.type.length})'
        return _COLUMN_TYPE_MAP.get(tn, 'TEXT')
    def _default_clause(col):
        if col.default and col.default.is_scalar:
            v = col.default.arg
            if isinstance(v, bool): return ' DEFAULT ' + ('TRUE' if v else 'FALSE')
            if isinstance(v, int): return f' DEFAULT {v}'
        if not col.nullable:
            tn = type(col.type).__name__
            if tn == 'Boolean': return ' DEFAULT FALSE'
            if tn == 'Integer': return ' DEFAULT 0'
        return ''
    try:
        db.create_all()
        inspector = _inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        added = []
        for mapper in db.Model.registry.mappers:
            cls = mapper.class_
            table = getattr(cls, '__tablename__', None)
            if not table or table not in existing_tables:
                continue
            db_cols = {c['name'] for c in inspector.get_columns(table)}
            missing = [c for c in cls.__table__.columns if c.key not in db_cols]
            if not missing:
                continue
            with db.engine.connect() as conn:
                for col in missing:
                    sql = f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col.key} {_sql_type(col)}{_default_clause(col)}'
                    conn.execute(_text(sql))
                    added.append(f'{table}.{col.key}')
                conn.commit()
        return jsonify({'success': True, 'added': added,
                        'message': f'Migration complete. {len(added)} column(s) added: {", ".join(added) or "none (all up to date)"}.'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/add-credits', methods=['POST'])
@login_required
def admin_add_credits():
    """One-time admin endpoint: add credits to any user by email. Owner-only."""
    OWNER_EMAIL = 'yabiolashittu@gmail.com'
    if current_user.email != OWNER_EMAIL:
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json() or {}
    target_email = data.get('email', '').strip()
    amount = int(data.get('amount', 0))
    if not target_email or amount <= 0:
        return jsonify({'error': 'email and amount required'}), 400
    target = User.query.filter_by(email=target_email).first()
    if not target:
        return jsonify({'error': f'User not found: {target_email}'}), 404
    sub = UserSubscription.query.filter_by(user_id=target.id).first()
    if not sub:
        return jsonify({'error': f'No subscription for {target_email}'}), 404
    old = CreditService.balance(target.id)
    new_bal = CreditService.grant(target.id, amount)
    return jsonify({
        'success': True,
        'email': target_email,
        'credits_before': old,
        'credits_after': new_bal,
        'tier': sub.tier.name if sub.tier else 'unknown'
    })


def _record_tool_usage(*, user_id, conversation_id, ai_model, primary_row,
                        primary_tool, tool_calls, tools_used, turn_success):
    """Emit the per-tool ``UsageLog`` rows for a finished chat turn.

    Shared by ``/api/chat`` and ``/api/chat/stream``. Each row carries the
    tool's OWN outcome — ``usage_logs.success`` on a per-tool row used to be the
    turn-completion flag, which is what produced the false "unwanted RDS
    instance" alarm (CLAUDE_RUNBOOK.md, 2026-09-02). A tool the model guessed
    that progressive selection never sent is written as ``tool_not_offered`` so
    a recurrence of that day's misrouting is visible from one DB query.

    ``primary_row`` is the already-created turn row; its ``success`` /
    ``error_message`` are corrected in place if the primary tool actually
    failed. Returns the list of extra rows to add to the session.

    Falls back to one turn-flagged row per distinct executed tool when the
    structured ``tool_calls`` log is unavailable (e.g. the Groq no-tools
    fallback path).
    """
    rows = []
    seen = {primary_tool} if primary_tool else set()

    if tool_calls:
        outcome = {}  # tool -> (success, error, status); any failure wins
        for tc in tool_calls:
            name = tc.get('tool')
            if not name:
                continue
            ok = bool(tc.get('success'))
            if name not in outcome or (outcome[name][0] and not ok):
                outcome[name] = (ok, tc.get('error') or None, tc.get('status'))

        if primary_tool in outcome and not outcome[primary_tool][0] and primary_row.success:
            primary_row.success = False
            primary_row.error_message = primary_row.error_message or outcome[primary_tool][1]

        for name, (ok, err, status) in outcome.items():
            if name in seen:
                continue
            seen.add(name)
            rows.append(UsageLog(
                user_id=user_id,
                conversation_id=conversation_id,
                action_type='tool_not_offered' if status == 'not_offered' else 'tool_use',
                tool_name=name,
                credits_used=0,
                success=ok,
                error_message=None if ok else err,
                ai_model=ai_model,
            ))
    else:
        for name in tools_used[1:]:
            rows.append(UsageLog(
                user_id=user_id,
                conversation_id=conversation_id,
                action_type='tool_use',
                tool_name=name,
                credits_used=0,
                success=turn_success,
                ai_model=ai_model,
            ))
    return rows


@app.route('/api/chat', methods=['POST'])
@login_required
@limiter.limit(_chat_rate_limit, key_func=lambda: str(current_user.id))
def api_chat():
    """Handle chat messages."""
    if agent is None:
        # Try to initialize the agent
        if check_api_key_configured():
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Failed to initialize agent: {error}'}), 503
        else:
            return jsonify({'error': 'Agent not initialized. Please configure API key.'}), 503

    try:
        from services.input_sanitizer import sanitize_input, sanitize_output, validate_message
        from services.secret_detector import redact_secrets
        from src.agent.guardrails import screen_message

        data = request.get_json()
        message = sanitize_input(data.get('message', ''))

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Check if user is blocked due to repeated policy violations
        if current_user.is_guardrail_blocked():
            return jsonify({'error': 'Your account has been temporarily restricted due to repeated policy violations. Please contact support.'}), 403

        # Validate message content (length + injection patterns)
        is_valid, validation_reason = validate_message(message)
        if not is_valid:
            current_user.record_guardrail_violation()
            db.session.commit()
            return jsonify({'error': validation_reason}), 400

        # Haiku harmlessness screen
        guardrail_result = screen_message(message)
        if guardrail_result.blocked:
            # CRISIS DETECTION — separate from policy violations
            if guardrail_result.is_crisis:
                from services.crisis_resources import get_crisis_resources, get_user_country_from_request
                from models import CrisisIncident

                country_code = get_user_country_from_request(request)
                resources = get_crisis_resources(country_code)

                # Log the crisis incident for audit trail + support team
                crisis_incident = CrisisIncident(
                    user_id=current_user.id,
                    conversation_id=data.get('conversation_id'),
                    message_snippet=message[:500],
                    severity=guardrail_result.crisis_severity,
                    crisis_keywords=guardrail_result.crisis_keywords or {},
                    action='banner_shown',
                    resources_provided=resources,
                    user_country=country_code,
                    user_ip=request.remote_addr,
                    user_agent=request.headers.get('User-Agent', '')[:500],
                )
                db.session.add(crisis_incident)
                db.session.commit()
                logger.warning(f"Crisis incident logged. user_id={current_user.id} severity={guardrail_result.crisis_severity}")

                # Return crisis response (not error) — frontend shows banner instead of error
                return jsonify({
                    'crisis_response': True,
                    'message': 'If you\'re in crisis, please reach out for help.',
                    'resources': resources,
                    'incident_id': crisis_incident.id,
                }), 200

            # Regular policy violation
            current_user.record_guardrail_violation()
            db.session.commit()
            return jsonify({
                'error': 'Message blocked by content policy. Repeated violations may result in account suspension.'
            }), 400

        # Check user subscription and credits
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            # Create free tier subscription for new user
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            if not free_tier:
                return jsonify({'error': 'Subscription system not initialized. Please contact support.'}), 500

            from dateutil.relativedelta import relativedelta
            now = utcnow()
            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=free_tier.id,
                credits_remaining=free_tier.monthly_credits,
                current_period_start=now,
                current_period_end=now + relativedelta(months=1),
                last_reset_date=now,
            )
            db.session.add(subscription)
            db.session.commit()
            _track_conversion(current_user.id, 'trial_start', {'credits': free_tier.monthly_credits})

        # Monthly refill for every tier, free included (free = 20 credits a month).
        tier_name = subscription.tier.name if subscription.tier else 'free'
        subscription.refresh_credits_if_due()

        # Guard: if user has 0 credits but has never used any, their subscription
        # was mis-initialized (e.g. free tier had monthly_credits=0 at signup time).
        # Repair silently so they get their proper trial credits.
        subscription.repair_if_never_used()

        # Check if user has credits
        if not subscription.has_credits():
            if tier_name == 'free':
                _track_conversion(current_user.id, 'credit_exhaustion', {'tier': 'free'})
                _track_conversion(current_user.id, 'upgrade_cta_shown', {'source': 'api_chat'})
                db.session.commit()
                # Free-tier exhausted: return upgrade pitch as a normal response
                return jsonify({
                    'response': _generate_upgrade_pitch(subscription.current_period_end),
                    'credits_remaining': 0,
                    'trial_ended': True,
                })
            return jsonify({
                'error': 'insufficient_credits',
                'message': 'You have run out of credits. Please upgrade your plan or purchase more credits.',
                'credits_remaining': 0,
                'tier': subscription.tier.to_dict() if subscription.tier else None
            }), 402  # Payment Required

        # Resolve AI model for user's subscription tier with user preference
        from services.model_router import resolve_model_with_preference
        tier_name = subscription.tier.name if subscription.tier else 'free'
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        preferred_provider = prefs.preferred_model_provider if prefs else None
        model_config = resolve_model_with_preference(tier_name, preferred_provider)

        # Get or create conversation ID
        conversation_id = session.get('conversation_id')
        is_first_message = False
        if not conversation_id:
            conversation_id = secrets.token_hex(8)
            session['conversation_id'] = conversation_id
            is_first_message = True

            # Create new conversation record with temporary title
            conversation = Conversation(
                id=conversation_id,
                user_id=current_user.id,
                title='New Chat'
            )
            db.session.add(conversation)
        else:
            # Update conversation timestamp - MUST filter by user_id for security
            conversation = Conversation.query.filter_by(
                id=conversation_id,
                user_id=current_user.id
            ).first()
            if conversation:
                conversation.updated_at = utcnow()
                # Check if this is the first message (title still default)
                if conversation.title == 'New Chat':
                    is_first_message = True
            else:
                # Conversation doesn't exist, create a new one
                conversation_id = secrets.token_hex(8)
                session['conversation_id'] = conversation_id
                is_first_message = True
                conversation = Conversation(
                    id=conversation_id,
                    user_id=current_user.id,
                    title='New Chat'
                )
                db.session.add(conversation)

        # Load prior messages BEFORE adding the new message to avoid autoflush
        # including the pending insert in the SELECT result
        prior_messages = ChatMessage.query.filter_by(
            user_id=current_user.id,
            conversation_id=conversation_id
        ).order_by(ChatMessage.timestamp).all()

        conversation_history = [
            {'role': msg.role, 'content': msg.content}
            for msg in prior_messages
        ]

        # Save user message and update conversation preview
        user_message = ChatMessage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            role='user',
            content=message
        )
        db.session.add(user_message)
        if conversation and not getattr(conversation, '_preview_set', False):
            conversation.preview = message[:200]
            conversation._preview_set = True
        db.session.commit()  # Persist before agent processes — prevents message loss on crash

        # Get user preferences for personalized context
        preferences_context = None
        sandbox_active = False
        if prefs:
            preferences_context = prefs.get_context_for_prompt()
            if prefs.learning_mode:
                preferences_context = (preferences_context or '') + '\n\n' + LEARNING_MODE_CONTEXT
            # Sandbox is independent of learning mode — enabling it alone must
            # simulate every tool (the safety promise "nothing touches real infra").
            if prefs.sandbox_mode:
                preferences_context = (preferences_context or '') + '\n' + SANDBOX_MODE_ADDENDUM
                sandbox_active = True

        # Inject relevant memory context
        try:
            from services.memory_service import get_context_for_conversation
            memory_ctx = get_context_for_conversation(db, current_user.id, message)
            if memory_ctx:
                preferences_context = (preferences_context or '') + '\n\n' + memory_ctx
        except Exception:
            pass

        # Tell the agent which clouds it can use (sandbox: all of them, simulated)
        _cred_ctx = _cloud_access_context(current_user.id, sandbox_active)
        if _cred_ctx:
            preferences_context = (preferences_context or '') + '\n\n' + _cred_ctx

        # Build trial context for free-tier users
        trial_context = None
        if tier_name == 'free':
            credits_left = CreditService.balance(current_user.id)
            trial_context = (
                f"PLAN CONTEXT: This user is on the Free plan with {credits_left} of their 20 monthly credits left; they refill each month. "
                "They are experiencing the full DevOps agent with real tool execution. "
            )
            if credits_left <= 5:
                trial_context += (
                    "Their credits are running low. Naturally weave in a brief mention that they can "
                    "upgrade to the Starter plan ($29/month) for 200 credits a month, or wait for next month's refill. "
                    "Do NOT make this the focus -- still answer their question fully first."
                )

        # Inject mode prompt. Tool narrowing is NOT done here: passing a
        # tools_override (even a full-list one) makes core._maybe_select_tools
        # early-return, which silently disabled progressive tool loading on
        # every chat turn — scope_tools() documents that it ignores max_tools
        # and returns all ~742 tools reordered. Kimi then picked nmap_port_scan
        # 150 times for "create an ec2 instance" and never once called
        # create_ec2_instance. Pass max_tools instead and let the agent's own
        # category-based selection narrow the set (~50 tools for that message).
        # See CLAUDE_RUNBOOK.md 2026-09-02.
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory,
            SANDBOX_SYSTEM_PROMPT, REAL_AGENT_SYSTEM_PROMPT,
        )
        _factory = DevOpsAgentSessionFactory()
        if sandbox_active:
            _session = _factory.create_sandbox_session()
            preferences_context = (preferences_context or '') + '\n\n' + SANDBOX_SYSTEM_PROMPT
        else:
            _session = _factory.create_real_agent_session(None)
            preferences_context = (preferences_context or '') + '\n\n' + REAL_AGENT_SYSTEM_PROMPT.format(
                cloud_provider='configured providers',
                user_tier=tier_name,
                session_id=_session.session_id,
            )

        # Resolve values the agent call needs while still in the main request
        # context, so the background thread below never touches a
        # SQLAlchemy-session-bound object or Flask-Login's current_user proxy
        # from a different thread (same rule as _dispatch_password_reset_email
        # in routes/auth.py).
        _user_id = current_user.id
        _swarm_max_agents = _swarm_agents_for(model_config, prefs, sandbox_active)

        # Process message — route based on provider. The actual call runs in
        # a background thread while this request streams whitespace
        # keep-alive bytes below, so Cloudflare's ~100s idle-connection
        # timeout never fires on a legitimately long swarm/tool-loop turn —
        # see CLAUDE_RUNBOOK.md's 524 incident entry. The frontend still just
        # awaits the full JSON body (response.json() ignores insignificant
        # leading whitespace per the JSON spec).
        #
        # That thread owns the turn end to end: it runs the agent AND records
        # the result (_finalize_turn). The request generator only relays the
        # body. Two reasons it has to be that way — the agent's per-request
        # state is threading.local()-backed so only this thread can read it,
        # and the turn must still be persisted when the HTTP response is cut
        # short (client gone, CHAT_MAX_TURN_SECONDS reached), because by then
        # its tools may already have changed real cloud infrastructure.
        _agent_result = {}

        def _finalize_turn():
            """Record the finished turn and build the JSON body for the client.

            Called from the worker thread (see _run_agent_call), not the request
            thread, so that the assistant message, usage log and credit
            deduction all happen even when the client is no longer listening —
            a turn whose tools already changed real cloud infrastructure must
            never vanish without a trace just because the HTTP response died.

            Every ORM object is re-queried by id: the request thread's session
            and Flask-Login's `current_user` proxy must not be touched from
            here (same rule as _dispatch_password_reset_email in routes/auth.py).
            """
            response = _agent_result.get('response', 'Error: no response was generated')
            success = _agent_result.get('success', False)
            error_msg = _agent_result.get('error_msg')
            _tools_used = _agent_result.get('tools_used') or []
            _pending_download = _agent_result.get('pending_download')
            _model = model_config

            _user = User.query.get(_user_id)
            _conversation = Conversation.query.filter_by(
                id=conversation_id, user_id=_user_id
            ).first()
            _subscription = UserSubscription.query.filter_by(user_id=_user_id).first()

            # Auto-fallback: if primary provider returned an error string, retry with Groq
            _primary_error_snippet = response[:120] if response else ''
            if _model.provider in ('anthropic', 'kimi') and _is_anthropic_error(response):
                try:
                    from services.model_router import ModelConfig
                    response = _process_free_tier_chat(message, conversation_history, preferences_context)
                    fallback_note = "Claude" if _model.provider == 'anthropic' else "Kimi"
                    response += f"\n\n---\n*Note: {fallback_note} is temporarily unavailable (`{_primary_error_snippet}`). This response was generated by Llama 3.3 (Groq) without tool execution. Your cloud operations will resume when the primary model is back online.*"
                    _model = ModelConfig(
                        provider='groq', model='llama-3.3-70b-versatile',
                        display_name='Llama 3.3 70B (Fallback)', supports_tools=False,
                    )
                    success = True
                    error_msg = None
                except Exception:
                    pass  # Keep the original error response

            # Log usage — capture which tools were actually executed this turn
            _primary_tool = _tools_used[0] if _tools_used else None
            usage_log = UsageLog(
                user_id=_user_id,
                conversation_id=conversation_id,
                action_type='tool_use' if _tools_used else 'agent_message',
                tool_name=_primary_tool,
                credits_used=1,
                success=success,
                error_message=error_msg,
                ai_model=_model.model
            )
            db.session.add(usage_log)
            for _row in _record_tool_usage(
                user_id=_user_id, conversation_id=conversation_id, ai_model=_model.model,
                primary_row=usage_log, primary_tool=_primary_tool,
                tool_calls=_agent_result.get('tool_calls') or [],
                tools_used=_tools_used, turn_success=success,
            ):
                db.session.add(_row)

            # Track first-ever tool use for conversion funnel
            if _tools_used and success:
                prior_tool_use = UsageLog.query.filter_by(
                    user_id=_user_id, action_type='tool_use'
                ).filter(UsageLog.id != usage_log.id).first()
                if not prior_tool_use:
                    _track_conversion(_user_id, 'first_tool_use', {'tool': _primary_tool})

            # Sanitize and redact secrets from response
            response = sanitize_output(response)
            response = redact_secrets(response)

            # See services/chat_service.ensure_non_empty_response's docstring —
            # every ChatMessage(role='assistant', ...) save point must route through it.
            response = _ensure_non_empty_response(response)

            # Save assistant response
            assistant_message = ChatMessage(
                user_id=_user_id,
                conversation_id=conversation_id,
                role='assistant',
                content=response
            )
            db.session.add(assistant_message)

            # Update conversation title based on first message
            if is_first_message and _conversation:
                # Generate title from user's first message (max 50 chars)
                title = message.strip()
                if len(title) > 50:
                    title = title[:47] + '...'
                _conversation.title = title

            # Deduct credit AFTER successful response (not before)
            new_bal = None
            if success:
                new_bal = CreditService.deduct(_user_id, commit=False)

            db.session.commit()

            # Fire low-credit warning email at exactly 5 credits remaining (once per threshold)
            if success and new_bal == 5 and _user and _user.email:
                try:
                    from services.email_service import email_service as _es
                    threading.Thread(
                        target=_es.send_credit_low_warning, args=(_user, new_bal), daemon=True
                    ).start()
                except Exception:
                    pass

            # Auto-extract memorable facts from the conversation
            try:
                from services.memory_service import auto_extract_memories
                auto_extract_memories(db, _user_id, message, response)
            except Exception:
                pass

            # Check if there's a pending download from the agent
            download_url = None
            download_token = None
            if _pending_download:
                # Generate a secure token
                download_token = secrets.token_urlsafe(32)

                # Store the download with expiration (5 minutes)
                download_storage[download_token] = {
                    'filename': _pending_download.get('filename'),
                    'content': _pending_download.get('content'),
                    'content_type': _pending_download.get('content_type', 'application/octet-stream'),
                    'user_id': _user_id,
                    'expires_at': utcnow() + timedelta(minutes=5)
                }

                # Build download URL
                download_url = f'/api/download/{download_token}'

                logger.info(f"Download ready for user {_user_id}: {download_storage[download_token]['filename']}")

            _bal = CreditService.balance(_user_id)
            response_data = {
                'response': response,
                'timestamp': datetime.now().isoformat(),
                'credits_remaining': _bal,
                'credits_used_this_month': _subscription.credits_used_this_month if _subscription else 0,
                'conversation_title': _conversation.title if _conversation else None,
                'model_info': {
                    'provider': _model.provider,
                    'model': _model.model,
                    'display_name': _model.display_name,
                    'supports_tools': _model.supports_tools,
                }
            }
            _lcw = _low_credit_warning(_bal)
            if _lcw:
                response_data['low_credit_warning'] = _lcw

            # Add download URL if available
            if download_url:
                response_data['download_url'] = download_url
                response_data['download_filename'] = download_storage[download_token]['filename']

            # Risky actions filed for approval this turn: the page shows a confirm card
            # for each, as the streaming path does with its approval_required event.
            if _agent_result.get('approvals'):
                response_data['approvals'] = _agent_result['approvals']

            return response_data

        def _run_agent_call():
            # This runs on a brand-new OS thread (not a greenlet-friendly
            # context-copy) — Flask's app/request context from the request
            # thread is NOT visible here. agent.process_message_isolated goes
            # on to do real DB work (per-user cloud credential lookups in
            # credential_service.py, skills_engine's UserSkillActivation
            # query, etc.), all of which require an active app context or
            # raise "Working outside of application context." Without this
            # push, that RuntimeError gets caught by the except below and
            # silently reported as a generic agent error on every tool call.
            try:
                with app.app_context():
                    if model_config.provider == 'kimi':
                        resp = agent.process_message_isolated(
                            user_message=message,
                            conversation_history=conversation_history,
                            user_preferences_context=preferences_context,
                            user_id=_user_id,
                            model_override=model_config.model,
                            trial_context=trial_context,
                            sandbox_mode=sandbox_active,
                            provider='kimi',
                            max_tools=model_config.max_tools,
                            trust_tool_results=model_config.trust_tool_results,
                            swarm_max_agents=_swarm_max_agents,
                        )
                    elif model_config.provider == 'anthropic':
                        resp = agent.process_message_isolated(
                            user_message=message,
                            conversation_history=conversation_history,
                            user_preferences_context=preferences_context,
                            user_id=_user_id,
                            model_override=model_config.model,
                            trial_context=trial_context,
                            sandbox_mode=sandbox_active,
                            max_tools=model_config.max_tools,
                            trust_tool_results=model_config.trust_tool_results,
                        )
                    else:
                        resp = _process_free_tier_chat(message, conversation_history, preferences_context)
                _agent_result['response'] = resp
                _agent_result['success'] = True
                _agent_result['error_msg'] = None
            except Exception as agent_error:
                _agent_result['response'] = f"Error processing request: {str(agent_error)}"
                _agent_result['success'] = False
                _agent_result['error_msg'] = str(agent_error)

            # Capture the agent's per-request state HERE, on the thread that
            # actually ran the turn. `last_tools_used` and `pending_download`
            # are threading.local()-backed (_greenlet_local_property in
            # src/agent/core.py), so the request thread only ever sees its own
            # empty defaults for them.
            try:
                _agent_result['tools_used'] = list(agent.last_tools_used or [])
            except Exception:
                _agent_result['tools_used'] = []
            try:
                # Per-call record (name + real per-tool outcome), including tools
                # the model guessed that were never offered — see core._record_tool_call.
                _agent_result['tool_calls'] = list(getattr(agent, 'last_tool_calls', []) or [])
            except Exception:
                _agent_result['tool_calls'] = []
            try:
                _agent_result['pending_download'] = agent.pending_download
                agent.pending_download = None
            except Exception:
                _agent_result['pending_download'] = None
            try:
                _agent_result['approvals'] = list(getattr(agent, '_filed_approvals', []) or [])
            except Exception:
                _agent_result['approvals'] = []

            # Persist the turn from this thread as well, so it survives the
            # client disconnecting or the response being closed out early by
            # CHAT_MAX_TURN_SECONDS.
            try:
                with app.app_context():
                    _agent_result['response_data'] = _finalize_turn()
            except Exception as finalize_error:
                # No explicit rollback needed here: shutdown_session()
                # (teardown_appcontext, below) already rolled back the
                # session that raised when the `with` block above popped
                # its context — a fresh app_context() here would only get a
                # brand-new, already-clean scoped session.
                logger.error(f"Error finishing chat response: {str(finalize_error)}", exc_info=True)
                _agent_result['response_data'] = {'error': str(finalize_error)}

        import threading
        _worker = threading.Thread(target=_run_agent_call, daemon=True)
        _worker.start()

        def _generate_chat_response():
            import json
            import time

            # Keep-alive: pad with a whitespace byte every
            # CHAT_KEEPALIVE_INTERVAL_SECONDS while the agent call is still
            # running, and stop at CHAT_MAX_TURN_SECONDS. The deadline is the
            # point of this loop: the 200 was already committed with the first
            # whitespace byte, so a worker killed mid-turn by gunicorn's
            # --timeout leaves the client holding a 200 whose body is nothing
            # but whitespace, which is where "Unexpected end of JSON input"
            # came from. Returning early guarantees a parseable body while the
            # turn carries on in the background and persists itself.
            _deadline = time.monotonic() + CHAT_MAX_TURN_SECONDS
            while _worker.is_alive():
                _worker.join(timeout=CHAT_KEEPALIVE_INTERVAL_SECONDS)
                if not _worker.is_alive():
                    break
                if time.monotonic() >= _deadline:
                    logger.warning(
                        "Chat turn exceeded CHAT_MAX_TURN_SECONDS (%ss) for user %s, "
                        "conversation %s — closing the response early; the turn "
                        "continues in the background.",
                        CHAT_MAX_TURN_SECONDS, _user_id, conversation_id,
                    )
                    try:
                        _balance = CreditService.balance(_user_id)
                    except Exception:
                        _balance = None
                    _minutes = max(1, CHAT_MAX_TURN_SECONDS // 60)
                    yield json.dumps({
                        'response': (
                            f"This task has been running for over {_minutes} minutes and is "
                            "still going, so I've stopped holding the connection open. The "
                            "work is still running on the server and its result will be saved "
                            "to this conversation automatically — reopen this chat in a few "
                            "minutes to see it.\n\nAnything the task already changed in your "
                            "cloud account has taken effect."
                        ),
                        'still_running': True,
                        'timestamp': datetime.now().isoformat(),
                        'credits_remaining': _balance,
                    })
                    return
                yield ' '

            # _finalize_turn already ran on the worker thread — everything is
            # persisted by this point, all that is left is handing the body over.
            response_data = _agent_result.get('response_data')
            if response_data is None:
                response_data = {'error': 'The agent turn ended without producing a result.'}
            yield json.dumps(response_data)

        return app.response_class(
            stream_with_context(_generate_chat_response()),
            mimetype='application/json',
            headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'}
        )

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing chat message: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat/stream', methods=['POST'])
@login_required
@limiter.limit(_chat_rate_limit, key_func=lambda: str(current_user.id))
def api_chat_stream():
    """Handle chat messages with Server-Sent Events streaming."""
    if agent is None:
        if check_api_key_configured():
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Failed to initialize agent: {error}'}), 503
        else:
            return jsonify({'error': 'Agent not initialized. Please configure API key.'}), 503

    try:
        from services.input_sanitizer import sanitize_input, sanitize_output, validate_message
        from services.secret_detector import redact_secrets
        from src.agent.guardrails import screen_message

        data = request.get_json()
        message = sanitize_input(data.get('message', ''))

        # Handle file attachments (images as base64 dataURL, text files as plaintext)
        attachments = data.get('attachments', []) or []
        if attachments:
            parts = []
            for att in attachments[:5]:
                name = att.get('name', 'file')
                is_image = att.get('is_image', False)
                raw_data = att.get('data', '')
                if is_image and raw_data.startswith('data:'):
                    header, _, _ = raw_data.partition(',')
                    media_type = header.replace('data:', '').replace(';base64', '') or 'image/png'
                    parts.append(f'[Attached image: {name} ({media_type})]')
                elif not is_image and raw_data:
                    preview = raw_data[:3000] + ('...(truncated)' if len(raw_data) > 3000 else '')
                    parts.append(f'[Attached file: {name}]\n```\n{preview}\n```')
            if parts:
                message = (message + '\n\n' + '\n\n'.join(parts)).strip()

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Check if user is blocked due to repeated policy violations
        if current_user.is_guardrail_blocked():
            return jsonify({'error': 'Your account has been temporarily restricted due to repeated policy violations. Please contact support.'}), 403

        # Validate message content (length + injection patterns)
        is_valid, validation_reason = validate_message(message)
        if not is_valid:
            current_user.record_guardrail_violation()
            db.session.commit()
            return jsonify({'error': validation_reason}), 400

        # Haiku harmlessness screen
        guardrail_result = screen_message(message)
        if guardrail_result.blocked:
            # CRISIS DETECTION — separate from policy violations
            if guardrail_result.is_crisis:
                from services.crisis_resources import get_crisis_resources, get_user_country_from_request
                from models import CrisisIncident
                import json as _json_crisis

                country_code = get_user_country_from_request(request)
                resources = get_crisis_resources(country_code)

                # Log the crisis incident for audit trail + support team
                crisis_incident = CrisisIncident(
                    user_id=current_user.id,
                    conversation_id=data.get('conversation_id'),
                    message_snippet=message[:500],
                    severity=guardrail_result.crisis_severity,
                    crisis_keywords=guardrail_result.crisis_keywords or {},
                    action='banner_shown',
                    resources_provided=resources,
                    user_country=country_code,
                    user_ip=request.remote_addr,
                    user_agent=request.headers.get('User-Agent', '')[:500],
                )
                db.session.add(crisis_incident)
                db.session.commit()
                logger.warning(f"Crisis incident logged. user_id={current_user.id} severity={guardrail_result.crisis_severity}")

                # Return crisis response as SSE stream
                def generate_crisis_response():
                    yield f"data: {_json_crisis.dumps({'type': 'crisis', 'resources': resources, 'incident_id': crisis_incident.id})}\n\n"
                    yield f"data: {_json_crisis.dumps({'type': 'done'})}\n\n"

                return app.response_class(
                    generate_crisis_response(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
                )

            # Regular policy violation
            current_user.record_guardrail_violation()
            db.session.commit()
            return jsonify({
                'error': 'Message blocked by content policy. Repeated violations may result in account suspension.'
            }), 400

        # Check credits
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
        if not subscription:
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            if not free_tier:
                return jsonify({'error': 'Subscription system not initialized.'}), 500
            from dateutil.relativedelta import relativedelta
            now = utcnow()
            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=free_tier.id,
                credits_remaining=free_tier.monthly_credits,
                current_period_start=now,
                current_period_end=now + relativedelta(months=1),
                last_reset_date=now,
            )
            db.session.add(subscription)
            db.session.commit()

        # Monthly refill for every tier, free included (free = 20 credits a month).
        tier_name = subscription.tier.name if subscription.tier else 'free'
        subscription.refresh_credits_if_due()

        subscription.repair_if_never_used()

        if not subscription.has_credits():
            if tier_name == 'free':
                # Free-tier exhausted: stream the upgrade pitch as SSE
                import json as _json_stream
                pitch = _generate_upgrade_pitch(subscription.current_period_end)
                def generate_pitch():
                    yield f"data: {_json_stream.dumps({'type': 'chunk', 'content': pitch})}\n\n"
                    yield f"data: {_json_stream.dumps({'type': 'done', 'credits_remaining': 0, 'trial_ended': True})}\n\n"
                return app.response_class(
                    generate_pitch(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
                )
            return jsonify({'error': 'insufficient_credits'}), 402

        # Credit deduction moved into generate() after successful AI response

        # Resolve AI model for user's subscription tier with user preference
        from services.model_router import resolve_model_with_preference
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        preferred_provider = prefs.preferred_model_provider if prefs else None
        model_config = resolve_model_with_preference(tier_name, preferred_provider)

        # Get or create conversation
        conversation_id = session.get('conversation_id')
        is_first_message = False
        if not conversation_id:
            conversation_id = secrets.token_hex(8)
            session['conversation_id'] = conversation_id
            is_first_message = True
            conversation = Conversation(
                id=conversation_id,
                user_id=current_user.id,
                title='New Chat'
            )
            db.session.add(conversation)
        else:
            conversation = Conversation.query.filter_by(
                id=conversation_id,
                user_id=current_user.id
            ).first()
            if conversation:
                conversation.updated_at = utcnow()
                if conversation.title == 'New Chat':
                    is_first_message = True
            else:
                conversation_id = secrets.token_hex(8)
                session['conversation_id'] = conversation_id
                is_first_message = True
                conversation = Conversation(
                    id=conversation_id,
                    user_id=current_user.id,
                    title='New Chat'
                )
                db.session.add(conversation)

        # In-flight guard: atomic UPDATE — only sets is_streaming=True if it was False.
        # updated_at is explicitly stamped when the lock is acquired so stale detection is accurate.
        from sqlalchemy import update as _sa_update
        _now = utcnow()
        _stale_threshold = _now - timedelta(seconds=90)
        if conversation:
            # Stale lock recovery: if is_streaming=True but the lock was acquired >90s ago,
            # the stream crashed before the finally-block could clear it — safe to override.
            if conversation.is_streaming and conversation.updated_at and conversation.updated_at < _stale_threshold:
                db.session.execute(
                    _sa_update(Conversation).where(
                        Conversation.id == conversation.id
                    ).values(is_streaming=False, updated_at=_now)
                )
                db.session.commit()
                db.session.refresh(conversation)
            _guard_result = db.session.execute(
                _sa_update(Conversation).where(
                    Conversation.id == conversation.id,
                    Conversation.is_streaming == False  # noqa: E712
                ).values(is_streaming=True, updated_at=_now)
            )
            db.session.commit()
            if _guard_result.rowcount == 0:
                return jsonify({'error': 'Another request is already streaming for this conversation.'}), 409
            # Refresh so the in-memory object reflects the DB state
            db.session.refresh(conversation)
        else:
            db.session.commit()

        # Load prior messages — use explicit columns to avoid crashing on
        # tool_trace/page_context if the migration hasn't run yet.
        prior_messages = db.session.query(
            ChatMessage.role, ChatMessage.content
        ).filter(
            ChatMessage.user_id == current_user.id,
            ChatMessage.conversation_id == conversation_id
        ).order_by(ChatMessage.timestamp).all()

        conversation_history = [
            {'role': msg.role, 'content': msg.content}
            for msg in prior_messages
        ]

        # Save user message and update conversation preview
        from sqlalchemy import text as _text_sql
        try:
            user_msg = ChatMessage(
                user_id=current_user.id,
                conversation_id=conversation_id,
                role='user',
                content=message
            )
            db.session.add(user_msg)
            db.session.flush()
        except Exception:
            # Columns not yet migrated — insert using raw SQL with only the base columns
            db.session.rollback()
            db.session.execute(_text_sql(
                "INSERT INTO chat_messages (user_id, conversation_id, role, content, timestamp) "
                "VALUES (:uid, :cid, 'user', :content, :ts)"
            ), {'uid': current_user.id, 'cid': conversation_id,
                'content': message, 'ts': utcnow()})
        if conversation and not getattr(conversation, '_preview_set', False):
            conversation.preview = message[:200]
            conversation._preview_set = True
        db.session.commit()  # Persist before agent processes — prevents message loss on crash

        preferences_context = prefs.get_context_for_prompt() if prefs else None
        sandbox_active = False
        if prefs and prefs.learning_mode:
            preferences_context = (preferences_context or '') + '\n\n' + LEARNING_MODE_CONTEXT
        # Sandbox is independent of learning mode — enabling it alone must
        # simulate every tool (the safety promise "nothing touches real infra").
        if prefs and prefs.sandbox_mode:
            preferences_context = (preferences_context or '') + '\n' + SANDBOX_MODE_ADDENDUM
            sandbox_active = True

        # Inject page and resource context (sent by frontend when user is on a specific page/resource)
        _page_ctx = data.get('page_context', '')
        _resource_ctx = data.get('resource_context', '')
        if _page_ctx:
            preferences_context = (preferences_context or '') + \
                f'\n\nCURRENT PAGE CONTEXT: User is viewing {_page_ctx}.'
        if _resource_ctx:
            preferences_context = (preferences_context or '') + \
                f'\nFOCUSED RESOURCE: {_resource_ctx}'

        # Inject skills context (trigger-matched built-in skills + learned infrastructure summary)
        try:
            from services.skills_engine import get_skills_engine as _get_se
            _skills_ctx = _get_se().get_active_skills_context(current_user.id, message)
            if _skills_ctx:
                preferences_context = (preferences_context or '') + _skills_ctx
        except Exception:
            pass

        # Tell the agent which clouds it can use (sandbox: all of them, simulated)
        _cred_ctx = _cloud_access_context(current_user.id, sandbox_active)
        if _cred_ctx:
            preferences_context = (preferences_context or '') + '\n\n' + _cred_ctx

        # Build trial context for free-tier users
        uid = current_user.id
        trial_context = None
        if tier_name == 'free':
            credits_left = CreditService.balance(uid)
            trial_context = (
                f"PLAN CONTEXT: This user is on the Free plan with {credits_left} of their 20 monthly credits left; they refill each month. "
                "They are experiencing the full DevOps agent with real tool execution. "
            )
            if credits_left <= 5:
                trial_context += (
                    "Their credits are running low. Naturally weave in a brief mention that they can "
                    "upgrade to the Starter plan ($29/month) for 200 credits a month, or wait for next month's refill. "
                    "Do NOT make this the focus -- still answer their question fully first."
                )

        # Inject mode prompt. Tool narrowing happens inside the agent via
        # max_tools — see the matching comment on the non-streaming path above.
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory as _SessionFactory,
            SANDBOX_SYSTEM_PROMPT as _SANDBOX_PROMPT, REAL_AGENT_SYSTEM_PROMPT as _REAL_PROMPT,
        )
        _sfactory = _SessionFactory()
        if sandbox_active:
            _ssession = _sfactory.create_sandbox_session()
            preferences_context = (preferences_context or '') + '\n\n' + _SANDBOX_PROMPT
        else:
            _ssession = _sfactory.create_real_agent_session(None)
            preferences_context = (preferences_context or '') + '\n\n' + _REAL_PROMPT.format(
                cloud_provider='configured providers',
                user_tier=tier_name,
                session_id=_ssession.session_id,
            )

        # Capture variables for the generator closure
        cid = conversation_id
        is_first = is_first_message
        conv = conversation
        sub = subscription
        msg_text = message
        mc = model_config
        tc = trial_context
        sb = sandbox_active
        _stream_max_tools = model_config.max_tools
        _stream_trust = model_config.trust_tool_results
        # Read prefs here: inside generate() the request session is gone and
        # touching the ORM object raises DetachedInstanceError.
        _stream_swarm_agents = _swarm_agents_for(model_config, prefs, sandbox_active)

        db.session.commit()

        def generate():
            import json as _json
            from services.model_router import ModelConfig as _ModelConfig
            import logging as _logging
            _log = _logging.getLogger('stream_debug')
            _groq_fallback_mc = _ModelConfig(
                provider='groq', model='llama-3.3-70b-versatile',
                display_name='Llama 3.3 70B (Fallback)', supports_tools=False,
            )
            full_response = []
            actual_mc = mc
            _primary_error = ''
            from services.secret_detector import StreamingRedactor
            _secret_redactor = StreamingRedactor()

            # Tool event queue — callbacks fire synchronously inside the generator
            _tool_events = []
            _tool_events_log = []  # persistent log for DB storage (not drained)
            def _tool_cb(event_type, tool_name, data):
                ev = {'type': event_type, 'tool': tool_name,
                      'success': data.get('success', True)}
                _tool_events.append(ev)
                _tool_events_log.append(ev)
            agent.set_tool_event_callback(_tool_cb)

            def _drain_tool_events():
                while _tool_events:
                    ev = _tool_events.pop(0)
                    yield f"data: {_json.dumps(ev)}\n\n"
            _log.debug(f"stream: tier={getattr(mc, 'provider', '?')}, model={getattr(mc, 'model', '?')}")
            try:
                if mc.provider not in ('anthropic', 'kimi'):
                    stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                else:
                    try:
                        _provider_arg = 'kimi' if mc.provider == 'kimi' else None
                        stream_source = agent.process_message_streaming(
                            user_message=msg_text,
                            conversation_history=conversation_history,
                            user_preferences_context=preferences_context,
                            user_id=uid,
                            conversation_id=cid,
                            model_override=mc.model,
                            trial_context=tc,
                            sandbox_mode=sb,
                            provider=_provider_arg,
                            max_tools=_stream_max_tools,
                            trust_tool_results=_stream_trust,
                            swarm_max_agents=_stream_swarm_agents,
                        )
                        # Collect initial chunks to detect agent-swallowed errors
                        # The agent catches Anthropic exceptions and yields error text
                        _approval_sentinel = '\x00APPROVAL_REQUIRED\x00'
                        initial_buf = []
                        _approval_from_buf = None
                        _buf_exhausted = True
                        for _c in stream_source:
                            if isinstance(_c, str) and _c.startswith(_approval_sentinel):
                                _approval_from_buf = _c
                                _buf_exhausted = False
                                break
                            initial_buf.append(_c)
                            combined = ''.join(initial_buf)
                            if _is_anthropic_error(combined):
                                actual_mc = _groq_fallback_mc
                                _primary_error = combined
                                app.logger.warning('Chat: %s failed, using the backup model: %s',
                                                   mc.provider, redact_secrets(combined)[:300])
                                stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                                _buf_exhausted = False
                                break
                            if len(combined) > 20 or not combined.startswith(('\u274c', 'Error', 'API', '{')):
                                yield from _drain_tool_events()
                                for buf_chunk in initial_buf:
                                    full_response.append(buf_chunk)
                                    _safe = _secret_redactor.feed(buf_chunk)
                                    if _safe:
                                        yield f"data: {_json.dumps({'type': 'chunk', 'content': _safe})}\n\n"
                                _buf_exhausted = False
                                break
                        if _approval_from_buf:
                            payload = _json.loads(_approval_from_buf[len(_approval_sentinel):])
                            yield f"data: {_json.dumps({'type': 'approval_required', **payload})}\n\n"
                            with app.app_context():
                                try:
                                    c = Conversation.query.filter_by(id=cid, user_id=uid).first()
                                    if c:
                                        c.is_streaming = False
                                    db.session.commit()
                                except Exception:
                                    pass
                            yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': CreditService.balance(uid), 'approval_pending': True})}\n\n"
                            return
                        elif _buf_exhausted:
                            # Generator exhausted during initial check
                            combined = ''.join(initial_buf)
                            if _is_anthropic_error(combined):
                                actual_mc = _groq_fallback_mc
                                _primary_error = combined
                                app.logger.warning('Chat: %s failed, using the backup model: %s',
                                                   mc.provider, redact_secrets(combined)[:300])
                                stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                            else:
                                for buf_chunk in initial_buf:
                                    full_response.append(buf_chunk)
                                    _safe = _secret_redactor.feed(buf_chunk)
                                    if _safe:
                                        yield f"data: {_json.dumps({'type': 'chunk', 'content': _safe})}\n\n"
                                stream_source = iter([])  # already consumed
                    except Exception as _primary_exc:
                        # Actual exception (not swallowed by agent) — fallback to Groq
                        actual_mc = _groq_fallback_mc
                        _primary_error = str(_primary_exc)
                        app.logger.warning('Chat: %s raised, using the backup model: %s',
                                           mc.provider, redact_secrets(_primary_error)[:300])
                        stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)

                _approval_sentinel = '\x00APPROVAL_REQUIRED\x00'
                for chunk in stream_source:
                    if isinstance(chunk, str) and chunk.startswith(_approval_sentinel):
                        payload = _json.loads(chunk[len(_approval_sentinel):])
                        yield f"data: {_json.dumps({'type': 'approval_required', **payload})}\n\n"
                        with app.app_context():
                            try:
                                c = Conversation.query.filter_by(id=cid, user_id=uid).first()
                                if c:
                                    c.is_streaming = False
                                db.session.commit()
                            except Exception:
                                pass
                        yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': CreditService.balance(uid), 'approval_pending': True})}\n\n"
                        return
                    yield from _drain_tool_events()
                    full_response.append(chunk)
                    _safe = _secret_redactor.feed(chunk)
                    if _safe:
                        yield f"data: {_json.dumps({'type': 'chunk', 'content': _safe})}\n\n"
                yield from _drain_tool_events()

                # Flush whatever tail the redactor is still holding back so it
                # isn't lost — see StreamingRedactor's docstring for why chunks
                # are buffered rather than redacted one at a time.
                _safe = _secret_redactor.flush()
                if _safe:
                    yield f"data: {_json.dumps({'type': 'chunk', 'content': _safe})}\n\n"

                # Append fallback note if we switched providers
                if actual_mc.provider != mc.provider:
                    _fn = "Claude" if mc.provider == 'anthropic' else "Kimi"
                    _err_hint = (''.join(initial_buf))[:120] if 'initial_buf' in dir() else ''
                    fallback_msg = f"\n\n---\n*Note: {_fn} is temporarily unavailable (`{_err_hint}`). This response was generated by Llama 3.3 (Groq) without tool execution.*"
                    full_response.append(fallback_msg)
                    yield f"data: {_json.dumps({'type': 'chunk', 'content': fallback_msg})}\n\n"

                # Assemble full response for DB storage
                complete = ''.join(full_response)
                complete = sanitize_output(complete)
                complete = redact_secrets(complete)

                # See services/chat_service.ensure_non_empty_response's docstring —
                # every ChatMessage(role='assistant', ...) save point must route through it.
                complete = _ensure_non_empty_response(complete)

                # Save assistant response in app context
                # Capture all tool events for the trace (accumulated in _tool_events_log)
                with app.app_context():
                    # no_autoflush: prevent any SELECT from triggering an implicit INSERT
                    # before we've had a chance to test if the new columns exist.
                    with db.session.no_autoflush:
                        try:
                            assistant_msg = ChatMessage(
                                user_id=uid,
                                conversation_id=cid,
                                role='assistant',
                                content=complete,
                                tool_trace=_tool_events_log if _tool_events_log else None,
                                page_context=_page_ctx[:100] if _page_ctx else None,
                            )
                            db.session.add(assistant_msg)
                            db.session.flush()
                        except Exception:
                            # Columns not yet migrated — save without new fields
                            db.session.rollback()
                            assistant_msg = ChatMessage(
                                user_id=uid,
                                conversation_id=cid,
                                role='assistant',
                                content=complete,
                            )
                            db.session.add(assistant_msg)

                    _stream_tools = getattr(agent, 'last_tools_used', [])
                    _stream_primary = _stream_tools[0] if _stream_tools else None
                    usage_log = UsageLog(
                        user_id=uid,
                        conversation_id=cid,
                        action_type='tool_use' if _stream_tools else 'agent_message',
                        tool_name=_stream_primary,
                        credits_used=1,
                        success=True,
                        error_message=None,
                        ai_model=actual_mc.model
                    )
                    db.session.add(usage_log)

                    # The Kimi streaming tier writes no tool_trace, so these
                    # per-tool rows are the only per-tool signal it produces.
                    for _row in _record_tool_usage(
                        user_id=uid, conversation_id=cid, ai_model=actual_mc.model,
                        primary_row=usage_log, primary_tool=_stream_primary,
                        tool_calls=list(getattr(agent, 'last_tool_calls', []) or []),
                        tools_used=_stream_tools, turn_success=True,
                    ):
                        db.session.add(_row)

                    # Update conversation: title (first message) + clear streaming flag
                    c = Conversation.query.filter_by(id=cid, user_id=uid).first()
                    if c:
                        if is_first:
                            title = msg_text.strip()
                            c.title = title[:47] + '...' if len(title) > 50 else title
                        c.is_streaming = False

                    # Deduct credit AFTER successful response (not before)
                    remaining = CreditService.deduct(uid, commit=False)

                    db.session.commit()

                    # Fire low-credit warning email at exactly 5 credits remaining
                    if remaining == 5:
                        try:
                            import threading as _threading
                            from services.email_service import email_service as _es2
                            _user_obj = User.query.get(uid)
                            if _user_obj and _user_obj.email:
                                _threading.Thread(
                                    target=_es2.send_credit_low_warning, args=(_user_obj, remaining), daemon=True
                                ).start()
                        except Exception:
                            pass

                _done_evt = {'type': 'done', 'credits_remaining': remaining, 'model_info': {'provider': actual_mc.provider, 'model': actual_mc.model, 'display_name': actual_mc.display_name, 'supports_tools': actual_mc.supports_tools}}
                _lcw = _low_credit_warning(remaining)
                if _lcw:
                    _done_evt['low_credit_warning'] = _lcw
                yield f"data: {_json.dumps(_done_evt)}\n\n"

            except (BrokenPipeError, GeneratorExit, ConnectionResetError):
                # Client disconnected mid-stream — silently clean up, do not try to yield
                with app.app_context():
                    db.session.rollback()
            except _json.JSONDecodeError as e:
                logger.error(f"Malformed JSON from AI provider in stream for user {uid}: {e}")
                with app.app_context():
                    db.session.rollback()
                try:
                    yield f"data: {_json.dumps({'type': 'error', 'content': 'The AI returned an unreadable response. Please try again.'})}\n\n"
                except (BrokenPipeError, GeneratorExit, ConnectionResetError):
                    pass
            except Exception as e:
                # Report the REAL balance here, not a hardcoded 0. This handler
                # fires for any unrelated failure (a provider timeout, a tool
                # crash, a malformed response) — none of which mean the user's
                # credits are exhausted. The frontend's `credits_remaining === 0`
                # check (templates/index.html) treats that value as "trial
                # ended": it disables the message input/send button and shows
                # an upgrade banner, with no way to dismiss it short of a page
                # reload. A user with real credits left got permanently locked
                # out of chat by an unrelated transient error. See
                # CLAUDE_RUNBOOK.md's 2026-09-02 entry.
                with app.app_context():
                    db.session.rollback()
                    try:
                        _real_balance = CreditService.balance(uid)
                    except Exception:
                        _real_balance = None
                app.logger.error('Chat stream failed (%s): %s', actual_mc.provider, redact_secrets(str(e))[:300])
                if actual_mc is _groq_fallback_mc:
                    _err_text = _fallback_failure_message(mc.provider, _primary_error)
                else:
                    _err_text = 'Something went wrong while answering. Nothing was changed. Please try again.'
                try:
                    yield f"data: {_json.dumps({'type': 'error', 'content': _err_text})}\n\n"
                    # Always send done so the frontend doesn't hang waiting for stream close.
                    # Omit credits_remaining entirely if the balance lookup itself
                    # failed — the frontend already treats "undefined" as "leave the
                    # current display alone" (see the `!== undefined` checks), which
                    # is strictly safer here than guessing a number.
                    _done_payload = {'type': 'done', 'error': True}
                    if _real_balance is not None:
                        _done_payload['credits_remaining'] = _real_balance
                    yield f"data: {_json.dumps(_done_payload)}\n\n"
                except (BrokenPipeError, GeneratorExit, ConnectionResetError):
                    pass
            finally:
                # Clear tool event callback
                agent.set_tool_event_callback(None)
                # Safety net: clear is_streaming even if an error occurred before the success path
                try:
                    with app.app_context():
                        c = Conversation.query.filter_by(id=cid, user_id=uid).first()
                        if c and c.is_streaming:
                            c.is_streaming = False
                            db.session.commit()
                except Exception:
                    pass

        return app.response_class(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    except Exception as e:
        db.session.rollback()
        # Always clear the streaming flag if it was set before the error occurred
        try:
            if conversation:
                conversation.is_streaming = False
                db.session.commit()
        except Exception:
            pass
        logger.error(f"Error in streaming chat: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/model/health', methods=['GET'])
@login_required
def model_health():
    """Return health status of all AI providers."""
    from services.model_failover import get_provider_health
    health = get_provider_health()
    # Mask API key presence without exposing values
    import os as _os
    keys = {
        'ANTHROPIC_API_KEY': bool(_os.environ.get('ANTHROPIC_API_KEY')),
        'MOONSHOT_API_KEY': bool(_os.environ.get('MOONSHOT_API_KEY')),
        'GROQ_API_KEY': bool(_os.environ.get('GROQ_API_KEY')),
    }
    return jsonify({'providers': health, 'keys_present': keys})


@app.route('/api/model/health/reset', methods=['POST'])
@login_required
def reset_model_health():
    """Reset health tracking for all AI providers — forces retry on next request."""
    from services.model_failover import _provider_status
    for name in _provider_status:
        _provider_status[name]['healthy'] = True
        _provider_status[name]['failures'] = 0
        _provider_status[name]['last_failure'] = 0
    return jsonify({'success': True, 'message': 'All provider health states reset'})


@app.route('/api/model/switch', methods=['POST'])
@login_required
def switch_model():
    """Switch the user's preferred AI model provider."""
    try:
        data = request.get_json()
        provider = data.get('provider')

        if provider not in ('anthropic', 'kimi', None):
            return jsonify({'error': 'Invalid provider. Must be "anthropic", "kimi", or null.'}), 400

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)

        prefs.preferred_model_provider = provider
        db.session.commit()

        # Resolve what the effective model is now
        from services.model_router import resolve_model_with_preference
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
        tier_name = subscription.tier.name if subscription and subscription.tier else 'free'
        model_config = resolve_model_with_preference(tier_name, provider)

        return jsonify({
            'success': True,
            'provider': model_config.provider,
            'model': model_config.model,
            'display_name': model_config.display_name,
            'supports_tools': model_config.supports_tools,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/model/current', methods=['GET'])
@login_required
def get_current_model():
    """Get the user's current model configuration."""
    try:
        from services.model_router import resolve_model_with_preference
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        preferred = prefs.preferred_model_provider if prefs else None

        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
        tier_name = subscription.tier.name if subscription and subscription.tier else 'free'
        model_config = resolve_model_with_preference(tier_name, preferred)

        return jsonify({
            'provider': model_config.provider,
            'model': model_config.model,
            'display_name': model_config.display_name,
            'supports_tools': model_config.supports_tools,
            'preferred_provider': preferred,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def cleanup_expired_downloads():
    """Remove expired download tokens from storage."""
    now = utcnow()
    expired_tokens = [token for token, data in download_storage.items()
                      if data['expires_at'] < now]
    for token in expired_tokens:
        del download_storage[token]


@app.route('/api/download/<token>', methods=['GET'])
@login_required
def download_file(token):
    """Download a file using a temporary token."""
    try:
        # Clean up expired downloads
        cleanup_expired_downloads()

        # Check if token exists
        if token not in download_storage:
            return jsonify({'error': 'Invalid or expired download token'}), 404

        download_data = download_storage[token]

        # Verify it belongs to current user
        if download_data['user_id'] != current_user.id:
            security_logger.warning(f"Unauthorized download attempt by user {current_user.id} for token {token}")
            return jsonify({'error': 'Unauthorized'}), 403

        # Get file data
        filename = download_data['filename']
        content = download_data['content']
        content_type = download_data.get('content_type', 'application/octet-stream')

        # Delete token after use (one-time download)
        del download_storage[token]

        # Create response
        response = make_response(content)
        response.headers['Content-Type'] = content_type
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['X-Download-Success'] = 'true'

        logger.info(f"User {current_user.id} downloaded file: {filename}")

        return response

    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/summary', methods=['GET'])
@login_required
def get_dashboard_summary():
    """Get dashboard summary data."""
    try:
        from services.infrastructure_sync import get_dashboard_summary
        summary = get_dashboard_summary(current_user.id)
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/health-score', methods=['GET'])
@login_required
def get_health_score():
    """Return infrastructure health grade and breakdown for the current user."""
    try:
        from services.health_score import calculate_health_score
        result = calculate_health_score(current_user.id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Health score error for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/costs', methods=['GET'])
@login_required
def get_cost_data():
    """Get cost data from AWS Cost Explorer, with DB fallback."""
    try:
        from services.cost_explorer import get_actual_costs, get_cost_forecast
        days = request.args.get('days', 30, type=int)
        days = max(1, min(days, 365))
        costs = get_actual_costs(current_user.id, days=days)
        forecast = get_cost_forecast(current_user.id)
        costs['forecast'] = forecast
        return jsonify(costs)
    except Exception:
        # Fallback: aggregate cost data from synced resources (lightweight query)
        rows = db.session.query(
            InfrastructureResource.resource_type,
            db.func.sum(InfrastructureResource.monthly_cost)
        ).filter_by(user_id=current_user.id).group_by(
            InfrastructureResource.resource_type
        ).all()
        service_costs = {(r[0] or 'other'): float(r[1] or 0) for r in rows}
        total = sum(service_costs.values())
        return jsonify({
            'total_cost': round(total, 2),
            'services': [{'service': k, 'cost': round(v, 2)} for k, v in sorted(service_costs.items(), key=lambda x: -x[1])],
            'daily_trend': [],
            # No forecast without billing data; this used to be the estimate x 1.05.
            'forecast': {'forecast_total': None},
            # List-price estimates from the last sync, not what AWS billed.
            'source': 'estimate'
        })


@app.route('/api/dashboard/utilization/<int:resource_db_id>', methods=['GET'])
@login_required
def get_resource_utilization(resource_db_id):
    """Get real CloudWatch utilization metrics for a resource."""
    resource = InfrastructureResource.query.get(resource_db_id)
    if resource is None:
        return jsonify({'error': 'Resource not found'}), 404
    if resource.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        from services.cost_explorer import get_instance_utilization, get_rds_utilization

        days = request.args.get('days', 14, type=int)

        if resource.resource_type == 'ec2':
            data = get_instance_utilization(current_user.id, resource.resource_id, days=days)
        elif resource.resource_type == 'rds':
            db_id = (resource.resource_metadata or {}).get('db_instance_identifier', resource.resource_id)
            data = get_rds_utilization(current_user.id, db_id, days=days)
        else:
            return jsonify({'error': 'Utilization metrics not available for this resource type'}), 400

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/dashboard/sync', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def sync_infrastructure():
    """Queue an async infrastructure sync for the current user."""
    try:
        from tasks.cloud_tasks import sync_user_infrastructure_task
        task = sync_user_infrastructure_task.delay(current_user.id)
        return jsonify({'task_id': task.id, 'status': 'queued'})
    except Exception as e:
        # Celery/Redis unavailable — run synchronously
        app.logger.warning(f"Celery unavailable, running sync inline for user {current_user.id}: {e}")
        try:
            from services.infrastructure_sync import sync_user_infrastructure
            result = sync_user_infrastructure(current_user.id)
            return jsonify({
                'status': 'complete',
                'success': True,
                'total_resources': result.get('total_resources', 0),
                'total_savings': result.get('total_savings', 0),
            })
        except Exception as sync_err:
            app.logger.error(f"Inline sync failed for user {current_user.id}: {sync_err}")
            return jsonify({'success': False, 'error': str(sync_err)}), 500


@app.route('/api/dashboard/sync/status/<task_id>', methods=['GET'])
@login_required
def sync_status(task_id):
    """Poll the status of a queued infrastructure sync task."""
    try:
        from celery_app import celery as _celery
        task = _celery.AsyncResult(task_id)

        if task.state == 'PENDING':
            return jsonify({'status': 'pending'})
        elif task.state in ('STARTED', 'RETRY'):
            return jsonify({'status': 'running'})
        elif task.state == 'SUCCESS':
            result = task.result or {}
            return jsonify({
                'status': 'complete',
                'success': True,
                'total_resources': result.get('total_resources', 0),
                'total_savings': result.get('total_savings', 0),
            })
        elif task.state == 'FAILURE':
            return jsonify({'status': 'failed', 'error': str(task.result)})
        else:
            return jsonify({'status': task.state.lower()})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/api/dashboard/recommendations/<int:rec_id>/dismiss', methods=['POST'])
@login_required
def dismiss_recommendation(rec_id):
    """Dismiss a cost optimization recommendation."""
    try:
        from models import CostOptimization
        from datetime import datetime

        # Get recommendation
        recommendation = CostOptimization.query.get_or_404(rec_id)

        # Verify ownership
        if recommendation.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        recommendation.status = 'dismissed'
        recommendation.dismissed_at = utcnow()
        db.session.commit()

        return jsonify({'success': True})
    except HTTPException:
        raise  # let get_or_404's 404 (and other HTTP errors) pass through
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/security/summary', methods=['GET'])
@login_required
def security_summary():
    """Open findings from the AWS security checks, highest risk first."""
    from services.security_scanner import get_security_summary
    return jsonify(get_security_summary(current_user.id))


@app.route('/api/security/scan', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def security_scan():
    """Run the AWS security checks now.

    502 when no check could read the account: that is not a clean result, and the
    page must say so rather than show "no issues".
    """
    from services.security_scanner import scan_aws_security, SecurityScanError
    from models import UserCloudCredential
    if not UserCloudCredential.query.filter_by(user_id=current_user.id, cloud_provider='aws',
                                               is_active=True).first():
        return jsonify({'success': False, 'no_cloud_account': True,
                        'error': 'Connect an AWS account in Settings to run security checks.'}), 400
    try:
        results = scan_aws_security(current_user.id)
    except SecurityScanError as e:
        return jsonify({'success': False, 'scan_failed': True, 'error': str(e)}), 502
    except Exception as e:
        logger.error(f"Security scan failed for user {current_user.id}: {e}", exc_info=True)
        return jsonify({'success': False, 'scan_failed': True, 'error': 'The security checks could not run.'}), 500
    return jsonify({'success': True, **{k: results[k] for k in (
        'critical', 'high', 'medium', 'low', 'total', 'checks', 'region', 'resolved', 'scanned_at')}})


@app.route('/api/security/findings/<int:finding_id>/dismiss', methods=['POST'])
@login_required
def dismiss_security_finding(finding_id):
    """Hide a finding the user has decided to accept. Later scans leave it hidden."""
    from models import SecurityFinding
    finding = SecurityFinding.query.filter_by(id=finding_id, user_id=current_user.id).first()
    if finding is None:
        return jsonify({'error': 'Finding not found'}), 404
    data = request.get_json(silent=True) or {}
    finding.status = 'suppressed'
    finding.resolved_at = utcnow()
    finding.resolved_by = current_user.id
    finding.resolution_notes = (data.get('notes') or 'Dismissed by the user')[:500]
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/tools', methods=['GET'])
@login_required
def get_tools():
    """Get list of available tools."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        tools = agent.list_available_tools()

        # Categorize tools
        categorized = {
            'Command Execution': [],
            'AWS': [],
            'Kubernetes': [],
            'Git': [],
            'CI/CD': []
        }

        for tool in tools:
            if tool.startswith(('execute_command', 'execute_script')):
                categorized['Command Execution'].append(tool)
            elif tool.startswith(('get_ec2', 'list_s3', 'get_eks', 'get_cloudwatch', 'list_iam', 'manage_ec2')):
                categorized['AWS'].append(tool)
            elif tool.startswith(('get_pods', 'get_deployments', 'scale_', 'restart_', 'get_services', 'get_nodes', 'describe_pod')):
                categorized['Kubernetes'].append(tool)
            elif 'repository' in tool or 'pull_request' in tool or 'commit' in tool or 'branch' in tool or 'diff' in tool:
                categorized['Git'].append(tool)
            elif 'jenkins' in tool or 'github_workflow' in tool:
                categorized['CI/CD'].append(tool)

        return jsonify({
            'total': len(tools),
            'categories': categorized
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history', methods=['GET'])
@login_required
def get_history():
    """Get chat history for current conversation."""
    try:
        conversation_id = session.get('conversation_id')
        if not conversation_id:
            return jsonify({'messages': []})

        # Query messages for this conversation
        messages = ChatMessage.query.filter_by(
            user_id=current_user.id,
            conversation_id=conversation_id
        ).order_by(ChatMessage.timestamp).all()

        return jsonify({
            'messages': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        logger.error(f"Error retrieving chat history: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear', methods=['POST'])
@login_required
def clear_conversation():
    """Clear conversation history."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        # Clear agent conversation
        agent.clear_conversation()

        # Clear database messages for this conversation
        conversation_id = session.get('conversation_id')
        if conversation_id:
            ChatMessage.query.filter_by(
                user_id=current_user.id,
                conversation_id=conversation_id
            ).delete()
            db.session.commit()

        # Create new conversation ID
        session['conversation_id'] = secrets.token_hex(8)

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/contact', methods=['POST'])
def submit_contact():
    """Submit a contact form message."""
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No data provided'}), 400

        name = str(data.get('name', '')).strip()
        email = str(data.get('email', '')).strip()
        category = str(data.get('category', '')).strip()
        message = str(data.get('message', '')).strip()

        if not all([name, email, category, message]):
            return jsonify({'error': 'All fields are required'}), 400

        if (len(name) > 100 or len(email) > 254 or len(category) > 50
                or len(message) > 5000 or any(c in name + email + category for c in '\r\n')):
            return jsonify({'error': 'One or more fields are too long or contain invalid characters'}), 400

        try:
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            return jsonify({'error': 'Please provide a valid email address'}), 400

        # Import ContactMessage model
        from models import ContactMessage

        # Create new contact message
        contact_msg = ContactMessage(
            name=name,
            email=email,
            category=category,
            message=message,
            user_id=current_user.id if current_user.is_authenticated else None
        )

        db.session.add(contact_msg)
        db.session.commit()

        logger.info(f"New contact message from {email}: {category}")

        # Forward message to support inbox
        try:
            support_email = os.getenv('SUPPORT_EMAIL', 'hello@devopsagent.io')
            safe_name, safe_email = html_escape(name), html_escape(email)
            safe_category, safe_message = html_escape(category), html_escape(message)
            html = email_service._wrap_html(f"""
                <h2 style="color:#333;margin-bottom:12px;">New Contact Message</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr><td style="padding:8px 0;color:#666;width:100px;"><strong>From</strong></td><td style="padding:8px 0;">{safe_name} &lt;{safe_email}&gt;</td></tr>
                    <tr><td style="padding:8px 0;color:#666;"><strong>Category</strong></td><td style="padding:8px 0;">{safe_category}</td></tr>
                    <tr><td style="padding:8px 0;color:#666;"><strong>Message</strong></td><td style="padding:8px 0;white-space:pre-wrap;">{safe_message}</td></tr>
                </table>
                <div style="margin-top:20px;">
                    <a href="mailto:{safe_email}" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#ff6b35,#f7931e);color:white;text-decoration:none;border-radius:8px;font-weight:600;">Reply to {safe_name}</a>
                </div>
            """)
            email_service.send_email(support_email, f"[DevOps Agent] Contact: {category} from {name}", html)
        except Exception as email_err:
            logger.warning(f"Failed to forward contact message to support: {email_err}")

        return jsonify({
            'success': True,
            'message': 'Your message has been sent successfully'
        })

    except Exception as e:
        logger.error(f"Error submitting contact form: {str(e)}", exc_info=True)
        return jsonify({'error': 'Failed to send message'}), 500


@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get conversation statistics for the current user."""
    try:
        conversation_id = session.get('conversation_id')
        if not conversation_id:
            return jsonify({
                'total_messages': 0,
                'user_messages': 0,
                'assistant_messages': 0,
                'session_duration_seconds': 0
            })

        # Get stats from database for this user's conversation
        messages = ChatMessage.query.filter_by(
            user_id=current_user.id,
            conversation_id=conversation_id
        ).all()

        user_messages = sum(1 for msg in messages if msg.role == 'user')
        assistant_messages = sum(1 for msg in messages if msg.role == 'assistant')

        # Calculate session duration from first to last message
        if messages:
            first_msg = min(messages, key=lambda m: m.timestamp)
            last_msg = max(messages, key=lambda m: m.timestamp)
            duration = (last_msg.timestamp - first_msg.timestamp).total_seconds()
        else:
            duration = 0

        return jsonify({
            'total_messages': len(messages),
            'user_messages': user_messages,
            'assistant_messages': assistant_messages,
            'session_duration_seconds': duration
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    """Get all conversations for the current user."""
    try:
        limit = request.args.get('limit', 50, type=int)
        limit = max(1, min(limit, 200))
        conversations = Conversation.query.filter_by(
            user_id=current_user.id
        ).order_by(Conversation.updated_at.desc()).limit(limit).all()

        return jsonify({
            'conversations': [conv.to_dict() for conv in conversations]
        })
    except Exception as e:
        logger.error(f"Error retrieving conversations: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations/new', methods=['POST'])
@login_required
def new_conversation():
    """Start a new conversation."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        # Clear agent conversation
        agent.clear_conversation()

        # Create new conversation ID
        conversation_id = secrets.token_hex(8)
        session['conversation_id'] = conversation_id

        # Clean up empty "New Chat" conversations older than 7 days for this user
        from datetime import timedelta
        cutoff = utcnow() - timedelta(days=7)
        stale_ids = [
            c.id for c in Conversation.query.filter(
                Conversation.user_id == current_user.id,
                Conversation.title == 'New Chat',
                Conversation.updated_at < cutoff,
            ).all()
        ]
        if stale_ids:
            ChatMessage.query.filter(
                ChatMessage.conversation_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            Conversation.query.filter(
                Conversation.id.in_(stale_ids)
            ).delete(synchronize_session=False)

        # Create new conversation record
        conversation = Conversation(
            id=conversation_id,
            user_id=current_user.id,
            title='New Chat'
        )
        db.session.add(conversation)
        db.session.commit()

        return jsonify({
            'success': True,
            'conversation_id': conversation_id
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating new conversation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations/<conversation_id>', methods=['GET'])
@login_required
def load_conversation(conversation_id):
    """Load a specific conversation."""
    try:
        # Verify conversation belongs to user
        conversation = Conversation.query.filter_by(
            id=conversation_id,
            user_id=current_user.id
        ).first()

        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

        # Set as current conversation
        session['conversation_id'] = conversation_id

        # Get messages for this conversation (filter by user_id for defense in depth)
        messages = ChatMessage.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).order_by(ChatMessage.timestamp).all()

        return jsonify({
            'conversation': conversation.to_dict(),
            'messages': [msg.to_dict() for msg in messages]
        })
    except Exception as e:
        logger.error(f"Error loading conversation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
@login_required
def delete_conversation(conversation_id):
    """Delete a conversation."""
    from models import WorkflowExecution, ChatArtifact, ApprovalRequest
    try:
        # Verify conversation belongs to user
        conversation = Conversation.query.filter_by(
            id=conversation_id,
            user_id=current_user.id
        ).first()

        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

        # Delete every other row that FKs to this conversation — the DB enforces
        # these constraints, so leaving any of them behind makes the conversation
        # delete below fail with an IntegrityError (caught, rolled back, 500).
        # ChatArtifact.message_id also FKs to chat_messages.id with no cascade,
        # so it must be deleted BEFORE the ChatMessage delete below, not after —
        # deleting messages first raises the identical IntegrityError this block
        # exists to prevent, just one FK hop further out.
        ChatArtifact.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).delete()
        UsageLog.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).delete()
        LearningSession.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).delete()
        WorkflowExecution.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).delete()
        ApprovalRequest.query.filter_by(
            conversation_id=conversation_id,
            requester_id=current_user.id
        ).delete()

        # Delete all messages in this conversation (include user_id for defense in depth)
        ChatMessage.query.filter_by(
            conversation_id=conversation_id,
            user_id=current_user.id
        ).delete()

        # Delete the conversation
        db.session.delete(conversation)
        db.session.commit()

        # If this was the current conversation, start a new one
        if session.get('conversation_id') == conversation_id:
            session['conversation_id'] = secrets.token_hex(8)

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting conversation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences', methods=['GET'])
@login_required
def get_preferences():
    """Get user preferences."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()

        if not prefs:
            # Create default preferences
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)
            db.session.commit()

        return jsonify({'preferences': prefs.to_dict()})
    except Exception as e:
        logger.error(f"Error retrieving preferences: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences', methods=['PUT'])
@login_required
def update_preferences():
    """Update user preferences."""
    try:
        data = request.get_json()
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()

        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)

        # Update preferences
        for key, value in data.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)

        db.session.commit()

        return jsonify({'success': True, 'preferences': prefs.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating preferences: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences/favorites', methods=['POST'])
@login_required
def add_favorite():
    """Add command to favorites."""
    try:
        data = request.get_json()
        command = data.get('command')

        if not command:
            return jsonify({'error': 'Command is required'}), 400

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)
            db.session.commit()

        prefs.add_favorite_command(command)

        return jsonify({'success': True, 'favorites': prefs.favorite_commands})
    except Exception as e:
        logger.error(f"Error adding favorite: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences/favorites', methods=['DELETE'])
@login_required
def remove_favorite():
    """Remove command from favorites."""
    try:
        data = request.get_json()
        command = data.get('command')

        if not command:
            return jsonify({'error': 'Command is required'}), 400

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if prefs:
            prefs.remove_favorite_command(command)

        return jsonify({'success': True, 'favorites': prefs.favorite_commands if prefs else []})
    except Exception as e:
        logger.error(f"Error removing favorite: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences/shortcuts', methods=['POST'])
@login_required
def add_shortcut():
    """Add custom shortcut."""
    try:
        data = request.get_json()
        shortcut = data.get('shortcut')
        command = data.get('command')

        if not shortcut or not command:
            return jsonify({'error': 'Shortcut and command are required'}), 400

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)
            db.session.commit()

        prefs.add_shortcut(shortcut, command)

        return jsonify({'success': True, 'shortcuts': prefs.custom_shortcuts})
    except Exception as e:
        logger.error(f"Error adding shortcut: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/preferences/shortcuts/<shortcut>', methods=['DELETE'])
@login_required
def remove_shortcut(shortcut):
    """Remove custom shortcut."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if prefs:
            prefs.remove_shortcut(shortcut)

        return jsonify({'success': True, 'shortcuts': prefs.custom_shortcuts if prefs else {}})
    except Exception as e:
        logger.error(f"Error removing shortcut: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ===== LEARNING MODE API =====

@app.route('/api/learning/session-summary', methods=['POST'])
@login_required
def learning_session_summary():
    """Generate an AI session summary for the current learning conversation."""
    try:
        data = request.get_json() or {}
        conversation_id = data.get('conversation_id') or session.get('conversation_id')
        if not conversation_id:
            return jsonify({'error': 'No active conversation'}), 400

        messages = ChatMessage.query.filter_by(
            user_id=current_user.id,
            conversation_id=conversation_id
        ).order_by(ChatMessage.timestamp).all()

        if not messages:
            return jsonify({'error': 'No messages in conversation'}), 400

        transcript = '\n'.join(f"[{m.role}] {m.content[:500]}" for m in messages[-30:])
        message_count = len(messages)

        duration = 0
        if len(messages) >= 2:
            first_ts = messages[0].timestamp
            last_ts = messages[-1].timestamp
            if first_ts and last_ts:
                duration = max(1, int((last_ts - first_ts).total_seconds() / 60))

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        was_sandbox = prefs.sandbox_mode if prefs else False

        import anthropic as _anthropic
        _client = _anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))
        summary_response = _client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': f"""Analyze this DevOps learning session transcript and return a JSON object with these fields:
- "summary": 2-3 sentence overview of what was learned
- "topics_covered": array of topic strings (e.g. ["ec2", "security_groups", "vpc"])
- "tools_used": array of tool names that were executed
- "key_lessons": array of 2-4 key takeaways
- "study_recommendations": array of 2-3 suggestions for what to study next
- "proficiency_deltas": object mapping domain to points gained (e.g. {{"aws": 5, "security": 3}})

Return ONLY valid JSON, no markdown wrapping.

Transcript:
{transcript}"""}]
        )

        import json as _json
        raw = summary_response.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        summary_data = _json.loads(raw)

        ls = LearningSession(
            user_id=current_user.id,
            conversation_id=conversation_id,
            summary=summary_data.get('summary', ''),
            topics_covered=summary_data.get('topics_covered', []),
            tools_used=summary_data.get('tools_used', []),
            key_lessons=summary_data.get('key_lessons', []),
            study_recommendations=summary_data.get('study_recommendations', []),
            proficiency_deltas=summary_data.get('proficiency_deltas', {}),
            message_count=message_count,
            was_sandbox=was_sandbox,
            duration_minutes=duration
        )
        db.session.add(ls)

        if prefs:
            levels = prefs.learning_level if isinstance(prefs.learning_level, dict) else {}
            for domain, delta in summary_data.get('proficiency_deltas', {}).items():
                current = levels.get(domain, 0)
                levels[domain] = min(100, current + int(delta))
            prefs.learning_level = levels
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(prefs, 'learning_level')

        db.session.commit()

        return jsonify({'success': True, 'session': ls.to_dict()})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating learning summary: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/history', methods=['GET'])
@login_required
def learning_history():
    """Get paginated list of past learning sessions."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        sessions = LearningSession.query.filter_by(
            user_id=current_user.id
        ).order_by(LearningSession.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return jsonify({
            'sessions': [s.to_dict() for s in sessions.items],
            'total': sessions.total,
            'page': sessions.page,
            'pages': sessions.pages
        })
    except Exception as e:
        logger.error(f"Error fetching learning history: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/proficiency', methods=['GET'])
@login_required
def learning_proficiency():
    """Get current proficiency levels and session count."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        levels = prefs.learning_level if prefs and isinstance(prefs.learning_level, dict) else {}

        session_count = LearningSession.query.filter_by(user_id=current_user.id).count()

        return jsonify({
            'proficiency': levels,
            'session_count': session_count
        })
    except Exception as e:
        logger.error(f"Error fetching proficiency: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/paths', methods=['GET'])
@login_required
def learning_paths():
    """Return structured learning curriculum with suggested path based on proficiency."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        levels = prefs.learning_level if prefs and isinstance(prefs.learning_level, dict) else {}

        paths = []
        for path_id, path_data in LEARNING_CURRICULUM.items():
            paths.append({
                'id': path_id,
                'title': path_data['title'],
                'description': path_data['description'],
                'level': path_data['level'],
                'estimated_hours': path_data.get('estimated_hours', 0),
                'prerequisite': path_data.get('prerequisite'),
                'icon': path_data.get('icon', 'book'),
                'modules': path_data['modules'],
                'module_count': len(path_data['modules']),
            })

        # Suggest next path based on current proficiency
        if not levels:
            suggested = 'devops_fundamentals'
        elif levels.get('devops', 0) < 20:
            suggested = 'devops_fundamentals'
        elif levels.get('aws', 0) < 30:
            suggested = 'aws_foundations'
        elif levels.get('kubernetes', 0) < 30:
            suggested = 'kubernetes_basics'
        elif levels.get('cicd', 0) < 30:
            suggested = 'cicd_pipelines'
        else:
            suggested = 'infrastructure_as_code'

        return jsonify({
            'paths': paths,
            'suggested_path': suggested,
            'proficiency': levels
        })
    except Exception as e:
        logger.error(f"Error fetching learning paths: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/reset-proficiency', methods=['POST'])
@login_required
def reset_proficiency():
    """Reset proficiency levels (allows user to start fresh or set initial level)."""
    try:
        data = request.get_json() or {}
        initial_levels = data.get('levels', {})

        # Validate — only known domains, values 0-100
        valid_domains = {'aws', 'kubernetes', 'azure', 'gcp', 'devops', 'cicd',
                         'terraform', 'docker', 'linux', 'networking', 'security', 'monitoring'}
        sanitized = {}
        for domain, val in initial_levels.items():
            if domain in valid_domains:
                sanitized[domain] = max(0, min(100, int(val)))

        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        if not prefs:
            prefs = UserPreferences(user_id=current_user.id)
            db.session.add(prefs)

        prefs.learning_level = sanitized
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(prefs, 'learning_level')
        db.session.commit()

        return jsonify({'success': True, 'levels': sanitized})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error resetting proficiency: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/scenarios', methods=['GET'])
@login_required
def learning_scenarios():
    """Return available debugging scenarios for sandbox practice."""
    try:
        from services.learning_sandbox import get_failure_scenarios
        scenarios = get_failure_scenarios()
        return jsonify({'scenarios': scenarios})
    except Exception as e:
        logger.error(f"Error fetching scenarios: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ===== COMMAND TEMPLATES API =====

# ===== FEEDBACK API =====

@app.route('/api/feedback', methods=['POST'])
@login_required
def submit_feedback():
    """Submit feedback for a message."""
    try:
        data = request.get_json()
        message_id = data.get('message_id')
        rating = data.get('rating')

        if not message_id or not rating:
            return jsonify({'error': 'Message ID and rating are required'}), 400

        if rating < 1 or rating > 5:
            return jsonify({'error': 'Rating must be between 1 and 5'}), 400

        # Check if feedback already exists
        existing = ResponseFeedback.query.filter_by(
            user_id=current_user.id,
            message_id=message_id
        ).first()

        if existing:
            # Update existing feedback
            existing.rating = rating
            existing.feedback_text = data.get('feedback_text')
        else:
            # Create new feedback
            feedback = ResponseFeedback(
                user_id=current_user.id,
                message_id=message_id,
                rating=rating,
                feedback_text=data.get('feedback_text')
            )
            db.session.add(feedback)

        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting feedback: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/feedback/stats', methods=['GET'])
@login_required
def feedback_stats():
    """Get feedback statistics for the current user."""
    try:
        feedbacks = ResponseFeedback.query.filter_by(user_id=current_user.id).all()

        if not feedbacks:
            return jsonify({
                'total_feedbacks': 0,
                'average_rating': 0,
                'rating_distribution': {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
            })

        total = len(feedbacks)
        ratings = [f.rating for f in feedbacks]
        average = sum(ratings) / total

        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for rating in ratings:
            distribution[rating] += 1

        return jsonify({
            'total_feedbacks': total,
            'average_rating': round(average, 2),
            'rating_distribution': distribution
        })
    except Exception as e:
        logger.error(f"Error getting feedback stats: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/language/available', methods=['GET'])
def get_available_languages():
    """Get list of available languages."""
    from i18n_config import LANGUAGES
    return jsonify({'languages': LANGUAGES})


@app.route('/api/language/set', methods=['POST'])
@login_required
def set_language():
    """Set user's preferred language."""
    try:
        data = request.get_json()
        language = data.get('language', 'en')

        # Validate language
        from i18n_config import LANGUAGES
        if language not in LANGUAGES:
            return jsonify({'error': 'Invalid language code'}), 400

        # Update user language
        current_user.language = language
        db.session.commit()

        # Also store in session for non-logged-in contexts
        session['language'] = language

        return jsonify({
            'success': True,
            'language': language,
            'message': 'Language updated successfully'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error setting language: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/language/translations', methods=['GET'])
def get_translations():
    """Get translations for current language."""
    try:
        # Get language from query parameter, user preference, or session
        language = request.args.get('language')

        if not language and current_user.is_authenticated:
            language = current_user.language

        if not language:
            language = session.get('language', 'en')

        from translations_helper import TranslationHelper
        translations = TranslationHelper.get_all_translations(language)

        return jsonify({
            'language': language,
            'translations': translations
        })

    except Exception as e:
        logger.error(f"Error getting translations: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory', methods=['GET'])
@login_required
def get_memories():
    """List user's stored memories."""
    from services.memory_service import list_memories
    category = request.args.get('category')
    memories = list_memories(db, current_user.id, category=category)
    return jsonify({'memories': memories})


@app.route('/api/memory', methods=['POST'])
@login_required
def add_memory():
    """Store a new memory entry."""
    from services.memory_service import store_memory
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'error': 'Content required'}), 400
    memory = store_memory(
        db, current_user.id, content,
        category=data.get('category', 'general'),
        source='user',
        importance=data.get('importance', 7),
    )
    return jsonify({'memory': memory})


@app.route('/api/memory/<int:memory_id>', methods=['DELETE'])
@login_required
def remove_memory(memory_id):
    """Delete a memory entry."""
    from services.memory_service import delete_memory
    deleted = delete_memory(db, current_user.id, memory_id)
    if deleted:
        return jsonify({'success': True})
    return jsonify({'error': 'Memory not found'}), 404


@app.route('/api/sandbox/run', methods=['POST'])
@login_required
def run_sandbox_command():
    """Execute a command in a Docker sandbox."""
    from services.sandbox import run_sandboxed, run_script_sandboxed, is_docker_available

    if not is_docker_available():
        return jsonify({'error': 'Docker sandbox not available on this system'}), 503

    data = request.get_json() or {}
    command = data.get('command', '').strip()
    script = data.get('script', '').strip()

    if not command and not script:
        return jsonify({'error': 'command or script required'}), 400

    if script:
        result = run_script_sandboxed(
            script=script,
            language=data.get('language', 'sh'),
            timeout=min(data.get('timeout', 30), 60),
        )
    else:
        result = run_sandboxed(
            command=command,
            timeout=min(data.get('timeout', 30), 60),
            network=data.get('network', False),
        )

    return jsonify(result)


@app.route('/api/sandbox/status', methods=['GET'])
@login_required
def sandbox_status():
    """Check Docker sandbox availability."""
    from services.sandbox import get_sandbox_status
    return jsonify(get_sandbox_status())


@app.route('/api/memory/search', methods=['GET'])
@login_required
def search_user_memories():
    """Search memories by query."""
    from services.memory_service import search_memories
    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': 'Query parameter q required'}), 400
    results = search_memories(db, current_user.id, query)
    return jsonify({'results': results})


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
    })


@app.route('/init-database-secret-endpoint-12345', methods=['POST'])
def init_database():
    """Initialize database tables (one-time setup for production).

    SECURITY: This endpoint requires a secret token from environment variable.
    Set INIT_DB_SECRET environment variable to enable database initialization.
    """
    # Require a secret token from environment variable
    init_secret = os.environ.get('INIT_DB_SECRET')
    if not init_secret:
        return jsonify({
            'error': 'Database initialization is not enabled. Set INIT_DB_SECRET environment variable.'
        }), 403

    # Verify the secret token
    body = request.get_json(silent=True) or {}
    provided_token = request.headers.get('X-Init-Secret') or body.get('secret')
    if not provided_token or not hmac.compare_digest(str(provided_token), init_secret):
        security_logger.warning(f"Unauthorized database initialization attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        db.create_all()

        # Upsert subscription tiers — create if missing, update every field
        from services.subscription_tiers import upsert_all_tiers
        created, updated = upsert_all_tiers(db)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Database initialized. Tiers: {created} created, {updated} updated.',
            'tables_created': True,
            'tiers_created': created,
            'tiers_updated': updated
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ===== ADMIN CRISIS MANAGEMENT APIs =====

@app.route('/api/admin/crisis-incidents', methods=['GET'])
@login_required
def admin_list_crisis_incidents():
    """
    List crisis incidents with filtering.

    Query params:
    - user_id: Filter by user
    - date_from: ISO date (e.g., 2026-01-01)
    - date_to: ISO date
    - severity: 'high', 'medium', 'low'
    - resolved: 'true' or 'false'

    Requires admin role.
    """
    try:
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        query = CrisisIncident.query

        # Filter by user_id if provided
        user_id = request.args.get('user_id', type=int)
        if user_id:
            query = query.filter_by(user_id=user_id)

        # Filter by severity
        severity = request.args.get('severity')
        if severity:
            query = query.filter_by(severity=severity)

        # Filter by resolved status
        resolved = request.args.get('resolved')
        if resolved is not None:
            query = query.filter_by(resolved=resolved.lower() == 'true')

        # Filter by date range
        date_from = request.args.get('date_from')
        if date_from:
            try:
                from_dt = datetime.fromisoformat(date_from)
                query = query.filter(CrisisIncident.detected_at >= from_dt)
            except ValueError:
                return jsonify({'error': 'Invalid date_from format'}), 400

        date_to = request.args.get('date_to')
        if date_to:
            try:
                to_dt = datetime.fromisoformat(date_to)
                query = query.filter(CrisisIncident.detected_at <= to_dt)
            except ValueError:
                return jsonify({'error': 'Invalid date_to format'}), 400

        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        # Sort by detected_at descending (newest first)
        incidents_paginated = query.order_by(CrisisIncident.detected_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return jsonify({
            'incidents': [
                {
                    'id': inc.id,
                    'user_id': inc.user_id,
                    'user_email': inc.user.email if inc.user else None,
                    'detected_at': inc.detected_at.isoformat() if inc.detected_at else None,
                    'severity': inc.severity,
                    'crisis_keywords': inc.crisis_keywords,
                    'action': inc.action,
                    'user_country': inc.user_country,
                    'resolved': inc.resolved,
                    'support_notes': inc.support_notes,
                }
                for inc in incidents_paginated.items
            ],
            'total': incidents_paginated.total,
            'pages': incidents_paginated.pages,
            'current_page': page,
        }), 200

    except Exception as e:
        logger.error(f"Error listing crisis incidents: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/crisis-incidents/<int:incident_id>', methods=['GET'])
@login_required
def admin_get_crisis_incident(incident_id):
    """Get a single crisis incident with full details."""
    try:
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        incident = CrisisIncident.query.get(incident_id)
        if not incident:
            return jsonify({'error': 'Incident not found'}), 404

        return jsonify({
            'id': incident.id,
            'user_id': incident.user_id,
            'user_email': incident.user.email if incident.user else None,
            'conversation_id': incident.conversation_id,
            'detected_at': incident.detected_at.isoformat() if incident.detected_at else None,
            'message_snippet': incident.message_snippet,
            'severity': incident.severity,
            'crisis_keywords': incident.crisis_keywords,
            'action': incident.action,
            'resources_provided': incident.resources_provided,
            'user_country': incident.user_country,
            'user_ip': incident.user_ip,
            'user_agent': incident.user_agent,
            'resolved': incident.resolved,
            'resolved_at': incident.resolved_at.isoformat() if incident.resolved_at else None,
            'support_notes': incident.support_notes,
        }), 200

    except Exception as e:
        logger.error(f"Error getting crisis incident: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/crisis-incidents/<int:incident_id>', methods=['PUT'])
@login_required
def admin_update_crisis_incident(incident_id):
    """Update a crisis incident (mark as resolved, add support notes)."""
    try:
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        incident = CrisisIncident.query.get(incident_id)
        if not incident:
            return jsonify({'error': 'Incident not found'}), 404

        data = request.get_json() or {}

        # Update resolved status
        if 'resolved' in data:
            incident.resolved = bool(data['resolved'])
            if incident.resolved and not incident.resolved_at:
                incident.resolved_at = utcnow()

        # Update support notes
        if 'support_notes' in data:
            incident.support_notes = data['support_notes']

        db.session.commit()
        logger.info(f"Crisis incident {incident_id} updated by {current_user.email}")

        return jsonify({
            'success': True,
            'incident': {
                'id': incident.id,
                'resolved': incident.resolved,
                'resolved_at': incident.resolved_at.isoformat() if incident.resolved_at else None,
                'support_notes': incident.support_notes,
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating crisis incident: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/crisis-statistics', methods=['GET'])
@login_required
def admin_crisis_statistics():
    """Get statistics on crisis detections."""
    try:
        if current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403

        # Total incidents
        total_incidents = CrisisIncident.query.count()

        # By severity
        severity_counts = db.session.query(
            CrisisIncident.severity,
            db.func.count(CrisisIncident.id)
        ).group_by(CrisisIncident.severity).all()

        # By country (top 10)
        country_counts = db.session.query(
            CrisisIncident.user_country,
            db.func.count(CrisisIncident.id)
        ).group_by(CrisisIncident.user_country).order_by(
            db.func.count(CrisisIncident.id).desc()
        ).limit(10).all()

        # Unresolved incidents
        unresolved_count = CrisisIncident.query.filter_by(resolved=False).count()

        # Last 7 days trend
        seven_days_ago = utcnow() - timedelta(days=7)
        last_7_days_count = CrisisIncident.query.filter(
            CrisisIncident.detected_at >= seven_days_ago
        ).count()

        return jsonify({
            'total_incidents': total_incidents,
            'unresolved_count': unresolved_count,
            'last_7_days': last_7_days_count,
            'by_severity': {
                severity: count for severity, count in severity_counts
            },
            'top_countries': {
                country or 'unknown': count for country, count in country_counts
            },
        }), 200

    except Exception as e:
        logger.error(f"Error getting crisis statistics: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Eager agent initialization for WSGI servers (gunicorn).
# Under gunicorn the module is imported, not run as __main__, so the agent was
# only ever built lazily by chat routes — and only on the worker that served
# that request. The /api/v1 REST endpoints (e.g. /v1/tools/execute) read
# app.config['DEVOPS_AGENT'] and 503'd on any worker that hadn't served a chat
# request. Build it at import so every worker has it. Fail-soft: a bad/missing
# Anthropic key does NOT crash the worker (the client is constructed lazily and
# only errors when Claude is actually called); the endpoint keeps returning 503
# exactly as before if init fails, so this is strictly an improvement.
# Skip under pytest: the test harness configures its own in-memory DB engine
# (StaticPool) in a fixture that runs after import, and eager init here would
# bind the engine before those options apply. Tests exercise the endpoint with
# their own agent fixture instead.
def _run_schema_migration():
    """Create any tables missing from the DB and ALTER TABLE in any columns
    present in models.py but missing from an existing table. Idempotent and
    safe to run on every startup — must be called from both the gunicorn
    import path and the __main__ dev-server path (see the comment above
    _under_gunicorn below: anything only in the __main__ block silently never
    runs in production, which is exactly how mcp_oauth_clients and
    drift_baselines/drift_reports ended up missing from prod after being
    added to models.py — see CLAUDE_RUNBOOK.md, 2026-08-12)."""
    with app.app_context():
        db.create_all()

        try:
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            _COLUMN_TYPE_MAP = {
                'Boolean': 'BOOLEAN', 'Integer': 'INTEGER', 'String': 'VARCHAR(255)',
                'Text': 'TEXT', 'DateTime': 'TIMESTAMP', 'Float': 'FLOAT', 'JSON': 'JSONB',
            }
            def _col_sql_type(col):
                tn = type(col.type).__name__
                if tn == 'String' and getattr(col.type, 'length', None):
                    return f'VARCHAR({col.type.length})'
                return _COLUMN_TYPE_MAP.get(tn, 'TEXT')
            def _col_default(col):
                if col.default and col.default.is_scalar:
                    v = col.default.arg
                    if isinstance(v, bool): return ' DEFAULT ' + ('TRUE' if v else 'FALSE')
                    if isinstance(v, int): return f' DEFAULT {v}'
                if not col.nullable:
                    tn = type(col.type).__name__
                    if tn == 'Boolean': return ' DEFAULT FALSE'
                    if tn == 'Integer': return ' DEFAULT 0'
                return ''
            _inspector = _sa_inspect(db.engine)
            _existing_tables = set(_inspector.get_table_names())
            _auto_migrated = []
            for _mapper in db.Model.registry.mappers:
                _cls = _mapper.class_
                _table = getattr(_cls, '__tablename__', None)
                if not _table or _table not in _existing_tables:
                    continue
                _db_cols = {c['name'] for c in _inspector.get_columns(_table)}
                _missing = [c for c in _cls.__table__.columns if c.key not in _db_cols]
                if not _missing:
                    continue
                with db.engine.connect() as _conn:
                    for _col in _missing:
                        _sql = (f'ALTER TABLE {_table} ADD COLUMN IF NOT EXISTS '
                                f'{_col.key} {_col_sql_type(_col)}{_col_default(_col)}')
                        _conn.execute(_sa_text(_sql))
                        _auto_migrated.append(f'{_table}.{_col.key}')
                    _conn.commit()
            if _auto_migrated:
                logger.info(f"Auto-migration: added {len(_auto_migrated)} column(s): {', '.join(_auto_migrated)}")
        except Exception as _me:
            logger.warning(f"Auto-migration warning (non-fatal): {_me}")


_is_testing = os.environ.get('TESTING') == 'true' or os.environ.get('FLASK_ENV') == 'testing'
if __name__ != '__main__' and not _is_testing:
    # Schema migration must run before agent init / seeding below, which query
    # tables this may need to create first.
    try:
        _run_schema_migration()
    except Exception as _e:
        logger.warning(f"Schema migration skipped (non-fatal): {_e}")

    try:
        with app.app_context():
            _ok, _err = initialize_agent()
            if _ok:
                logger.info("Agent initialized at import (WSGI) — /api/v1 tool endpoints ready")
            else:
                logger.warning(f"Agent not initialized at import: {_err} — /api/v1 tool endpoints will 503 until configured")
    except Exception as _e:
        logger.warning(f"Eager agent init skipped (non-fatal): {_e}")

    # Seed the public starter infrastructure templates (idempotent). Like the
    # agent init above this must run at import for gunicorn — the __main__ block
    # never executes under WSGI, so the templates catalog stayed empty in prod.
    try:
        with app.app_context():
            from services.ai_infrastructure import seed_public_templates
            seed_public_templates()
    except Exception as _e:
        logger.warning(f"Public template seeding skipped (non-fatal): {_e}")

    # Same story for the pre-built workflow catalog: seeding only ever lived in
    # scripts/seed_workflows.py, which nobody runs on deploy, so /workflows showed
    # "No workflows in this category" in prod. Idempotent — skips existing names.
    try:
        with app.app_context():
            from services.starter_workflows import seed_workflow_templates
            seed_workflow_templates()
    except Exception as _e:
        logger.warning(f"Workflow template seeding skipped (non-fatal): {_e}")
    # Plan feature lists shown on the Billing page. Only /init-database ever wrote
    # them, so corrected copy never reached production. Copy fields only.
    try:
        with app.app_context():
            from services.subscription_tiers import sync_tier_features
            sync_tier_features()
    except Exception as _e:
        logger.warning(f"Subscription tier feature sync skipped (non-fatal): {_e}")


# ---------------------------------------------------------------------------
# Start the background scheduler under gunicorn.
# Like the agent init above, start_scheduler() was only ever called from the
# __main__ block (dev `python app.py`) — so under gunicorn in production it
# NEVER ran, leaving proactive monitoring, cost/security scans, drip + digest
# emails, infra auto-sync, and DB backups all dead. Start it here so gunicorn
# runs it; the scheduler's PID-file lock ensures exactly one worker owns it.
# Gated to gunicorn specifically (not migration scripts, shells, or tests):
# the loop runs every task immediately on its first tick, so an accidental
# start in a short-lived import could fire emails mid-process. Opt out with
# DISABLE_SCHEDULER=1.
import sys as _sys
from src.utils.timeutils import utcnow
_under_gunicorn = 'gunicorn' in os.path.basename(_sys.argv[0] if _sys.argv else '').lower()
if _under_gunicorn and not _is_testing and os.environ.get('DISABLE_SCHEDULER') != '1':
    try:
        from services.scheduler import start_scheduler
        start_scheduler(app, db)
        logger.info("Background scheduler started at import (WSGI)")
    except Exception as _e:
        logger.warning(f"Scheduler autostart skipped (non-fatal): {_e}")


if __name__ == '__main__':
    print("=" * 60)
    print("DevOps Automation Agent - Web Interface")
    print("=" * 60)

    # (Built-in skills are loaded at module import time — see the block after
    # the skills blueprint registration.)

    # Initialize database — table creation + column auto-migration lives in
    # _run_schema_migration() so it also runs under gunicorn (see that
    # function's docstring above).
    _run_schema_migration()

    with app.app_context():
        # Backfill mfa_method for existing TOTP users
        # Schema changes are now managed by Alembic migrations (migrations/versions/)
        try:
            from sqlalchemy import text as sa_text
            _backfill = sa_text(
                "UPDATE users SET mfa_method='totp' "
                "WHERE two_factor_enabled=TRUE AND (mfa_method IS NULL OR mfa_method='none')"
            )
            with db.engine.connect() as _conn:
                _result = _conn.execute(_backfill)
                _conn.commit()
                if _result.rowcount:
                    print(f"Backfilled mfa_method='totp' for {_result.rowcount} existing TOTP user(s)")
        except Exception as _e:
            print(f"mfa_method backfill skipped: {_e}")

        # Seed public starter infrastructure templates (idempotent).
        try:
            from services.ai_infrastructure import seed_public_templates
            _seeded = seed_public_templates()
            if _seeded:
                print(f"Seeded {_seeded} public infrastructure template(s)")
        except Exception as _e:
            print(f"Public template seeding skipped: {_e}")

        print("\nDatabase initialized")
        _db_safe = _re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', database_url)
        print(f"  Host: {_db_safe}")

        # Upsert subscription tiers — create if missing, update every field
        from services.subscription_tiers import upsert_all_tiers
        _created, _updated = upsert_all_tiers(db)
        print(f"  Subscription tiers: {_created} created, {_updated} updated")
        db.session.commit()
        print("Subscription tiers synced")

    # Check if API key is already configured
    if check_api_key_configured():
        print("\nInitializing agent...")
        success, error = initialize_agent()

        if success:
            print(f"\nAgent initialized with {len(agent.list_available_tools())} tools")
        else:
            print(f"\nWarning: Failed to initialize agent: {error}")
            print("You can configure the API key through the web interface")
    else:
        print("\nAPI key not configured yet.")
        print("Access the web interface to set up your Anthropic API key.")

    print("\n" + "=" * 60)
    print("Starting web server...")
    print("=" * 60)

    # Get port from environment (for production) or use 5000 (for local dev)
    port = int(os.environ.get('PORT', 5000))

    print("\nAccess the agent at:")
    print(f"  http://localhost:{port}")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    # Start background scheduler
    try:
        from services.scheduler import start_scheduler
        start_scheduler(app, db)
        print("  Background scheduler started")
    except Exception as e:
        print(f"  Warning: Scheduler failed to start: {e}")

    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    # Loopback by default so `python app.py` does not expose the development
    # server to the whole network. Containers need to bind all interfaces to be
    # reachable through a published port, so docker-compose.yml sets
    # FLASK_RUN_HOST=0.0.0.0 explicitly. Production serves via gunicorn, not here.
    run_host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    app.run(host=run_host, port=port, debug=debug_mode, use_reloader=False, threaded=True)
