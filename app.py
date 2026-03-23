"""
Flask Web Interface for DevOps Agent with API Key Configuration and Authentication
"""
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
else:
    from dotenv import load_dotenv
    for _env_path in ['config/.env', '.env']:
        if os.path.exists(_env_path):
            load_dotenv(_env_path, override=False)
# --- End early secrets initialization ---

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response, send_file, g
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets
import hashlib
import logging
import re
from email_validator import validate_email, EmailNotValidError
from services.email_service import email_service
from services.status_service import status_service
from models import InfrastructureResource, CostOptimization, SecurityFinding, Alert

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.agent import DevOpsAgent
from src.utils import setup_logging, get_logger
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
    monitoring_tools,
    ansible_tools,
    alerting_tools,
    devops_operations_tools
)

# Import database models
from models import (
    db, User, ChatMessage, Conversation, UserPreferences, CommandTemplate,
    ResponseFeedback, SubscriptionTier, UserSubscription, CreditPurchase, UsageLog,
    LearningSession, PaymentWebhookEvent, NGNPriceConfig, ConversionEvent
)


app = Flask(__name__)

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
from flask_wtf.csrf import CSRFProtect
from flask_limiter.errors import RateLimitExceeded
from flask_talisman import Talisman

# Import shared extension instances (limiter + security_logger live in extensions.py
# so blueprints can import them without circular imports)
from extensions import limiter, security_logger

# CSRF Protection
csrf = CSRFProtect(app)
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit for CSRF tokens
app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # Exempt JSON API routes; CSRF enforced on form endpoints via @csrf.protect

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
app.config['REMEMBER_COOKIE_DURATION'] = 86400  # 24 hours
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = _is_production
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'

# Database configuration
# PostgreSQL for both local dev and production
database_url = os.environ.get('DATABASE_URL', 'postgresql://devops:devops_local@localhost:5432/devops_agent')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}
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
from routes.billing import billing_bp
app.register_blueprint(billing_bp)

from routes.admin import admin_bp
app.register_blueprint(admin_bp)

# Register incidents blueprint
from routes.incidents import incidents_bp
app.register_blueprint(incidents_bp)

# Register monitoring blueprint and initialize proactive monitoring
from routes.monitoring import monitoring_bp
app.register_blueprint(monitoring_bp)

# Register notifications blueprint
from routes.notifications import notifications_bp
app.register_blueprint(notifications_bp)

# Register optimization blueprint
from routes.optimization import optimization_bp
app.register_blueprint(optimization_bp)

# Register analysis blueprint for AI-powered root cause analysis
from routes.analysis import analysis_bp
app.register_blueprint(analysis_bp)

# Register webhooks blueprint for GitHub/GitLab/Bitbucket integrations
from routes.webhooks import webhooks_bp
app.register_blueprint(webhooks_bp)

# Register chatops blueprint for Slack/Teams bot integration
from routes.chatops import chatops_bp
app.register_blueprint(chatops_bp)

# Register drift detection blueprint for infrastructure drift detection
from routes.drift import drift_bp
app.register_blueprint(drift_bp)

# Register predictive scaling blueprint
from routes.scaling import scaling_bp
app.register_blueprint(scaling_bp)

# Register AI Infrastructure blueprint
from routes.ai_infrastructure import ai_infrastructure_bp
app.register_blueprint(ai_infrastructure_bp)

# Register Analytics blueprint
from routes.analytics import analytics_bp
app.register_blueprint(analytics_bp)

# Register API Gateway blueprint
from routes.api_gateway import api_gateway_bp
app.register_blueprint(api_gateway_bp)

# Register Compliance blueprint
from routes.compliance import compliance_bp
app.register_blueprint(compliance_bp)

# Register Organizations blueprint
from routes.organizations import organizations_bp
app.register_blueprint(organizations_bp)

# Register Change Governance blueprint
from routes.changes import changes_bp
app.register_blueprint(changes_bp)

from routes.curriculum import curriculum_bp
app.register_blueprint(curriculum_bp)

# Register REST API v1 blueprint (CLI + programmatic access)
from api import api_bp
app.register_blueprint(api_bp)
csrf.exempt(api_bp)

# Initialize proactive monitoring service with incident integration
from services.proactive_monitoring import get_monitoring_service
from services.incident_response import get_incident_engine
from services.notification_service import get_notification_service
from services.root_cause_analyzer import get_root_cause_analyzer

monitoring_service = get_monitoring_service()
monitoring_service.set_app(app)
incident_engine = get_incident_engine()
incident_engine.set_app(app)
notification_service = get_notification_service()
incident_engine.set_notification_service(notification_service)
root_cause_analyzer = get_root_cause_analyzer()
root_cause_analyzer.set_app(app)

monitoring_service.set_incident_engine(incident_engine)

# Initialise status service (public status page + Brevo subscriber broadcasts)
status_service.set_app(app)
status_service.set_email_service(email_service)

# Add notification callback to monitoring service for alert notifications
def send_alert_notification(event_type, alert_data, user_id=None):
    """Send notifications when alerts fire or resolve."""
    if event_type in ("firing", "resolved") and user_id is not None:
        notification_service.send_alert(user_id, alert_data)
    # Broadcast to public status page subscribers via Brevo
    if event_type in ("firing", "resolved"):
        try:
            status_service.broadcast_incident(event_type, alert_data)
        except Exception:
            pass  # never let broadcast failure break the alert pipeline

monitoring_service.add_alert_callback(send_alert_notification)
monitoring_service.start()

# RBAC context processor - makes RBAC helpers available in all templates
from services.rbac import RBACContext, get_user_role, user_has_permission, Permission

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
    return render_template('429.html', limit=limit) if _template_exists('429.html') else (
        f'<h1>429 Too Many Requests</h1><p>{limit}</p>', 429
    )


def _template_exists(name):
    from flask import current_app
    import os
    return os.path.exists(os.path.join(current_app.template_folder, name))


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

    # For page requests, render error template with details in dev mode
    import traceback as _tb2
    error_detail = f"{type(e).__name__}: {str(e)}"
    error_traceback = _tb2.format_exc()
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
    'status_page', 'status_confirm', 'status_unsubscribe',
    'api_status_subscribe', 'api_status_health',
}

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
        if request.endpoint not in ('onboarding_page', 'complete_onboarding', 'update_onboarding_step'):
            return redirect(url_for('onboarding_page'))


# Routes that do NOT require email verification (auth pages, email verify flow, static)
_EMAIL_VERIFY_EXEMPT_ROUTES = {
    'auth.login', 'auth.signup', 'auth.logout', 'auth.verify_email', 'auth.resend_verification',
    'auth.forgot_password', 'auth.reset_password', 'static', 'page_not_found',
    'handle_exception', 'ensure_clean_transaction', 'register_redirect',
    'usage_policy', 'privacy_policy', 'docs',
    'status_page', 'status_confirm', 'status_unsubscribe',
    'api_status_subscribe', 'api_status_health',
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
    """Initialize the DevOps Agent."""
    global agent, config_manager

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

        logger = get_logger(__name__)
        logger.info("Initializing DevOps Agent for web interface")

        # Create agent
        agent = DevOpsAgent(config_manager)

        # Register tools
        agent.register_tools_from_module(command_tools)
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
LEARNING MODE IS ACTIVE. You are both a senior DevOps engineer AND a patient teacher.

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
- Mention real-world costs: "A real t3.medium runs about $0.042/hour (~$30/month on-demand, ~$18/month reserved)"
- Mention real-world permissions: "To run this in real AWS, your IAM user would need the ec2:DescribeInstances permission"

DEBUGGING SCENARIOS — if user wants to practice troubleshooting, suggest:
- "Simulate a pod in CrashLoopBackOff" — Kubernetes debugging workflow
- "Simulate a security group blocking web traffic" — network troubleshooting
- "Simulate a disk full node" — disk pressure and pod eviction
- "Simulate high CPU on EC2" — performance investigation
- "Simulate OOMKilled pod" — memory limit tuning
- "Simulate database connection refused" — security group + networking debug
"""

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
                current_period_start=datetime.utcnow(),
                current_period_end=datetime.utcnow() + relativedelta(months=1),
                last_reset_date=datetime.utcnow(),
            )
            db.session.add(subscription)
            db.session.commit()

    credits = subscription.credits_remaining if subscription else 0
    return render_template('index.html', user=current_user, initial_credits=credits)


@app.route('/dashboard')
@login_required
def dashboard():
    """Infrastructure dashboard with real-time monitoring."""
    return render_template('dashboard_live.html', user=current_user)


@app.route('/changes')
@login_required
def changes_page():
    """Change governance and approval workflows."""
    return render_template('changes.html', user=current_user)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page."""
    if request.method == 'POST':
        try:
            current_user.full_name = request.form.get('full_name', '').strip() or None
            current_user.bio = request.form.get('bio', '').strip() or None
            current_user.avatar_color = request.form.get('avatar_color', '#cd7c48')
            current_user.theme = request.form.get('theme', 'light')
            current_user.language = request.form.get('language', 'en')
            db.session.commit()

            return render_template('profile.html', user=current_user, success='Profile updated successfully!')
        except Exception as e:
            db.session.rollback()
            return render_template('profile.html', user=current_user, error=f'Error updating profile: {str(e)}')

    return render_template('profile.html', user=current_user)


@app.route('/doctor')
@login_required
def doctor_page():
    """System diagnostics page."""
    from services.doctor import run_diagnostics
    results = run_diagnostics(app=app, db=db, agent=agent)
    return render_template('doctor.html', results=results, user=current_user)


@app.route('/onboarding', methods=['GET'])
@login_required
def onboarding_page():
    """Onboarding wizard for new users."""
    return render_template('onboarding.html', user=current_user)


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


@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """Setup page for API key configuration."""
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
    return render_template('settings.html', user=current_user)


@app.route('/templates')
@login_required
def templates_page():
    """Command templates management page."""
    return render_template('templates.html', user=current_user)


@app.route('/docs')
def docs():
    """Documentation page - Public access."""
    return render_template('docs.html')


@app.route('/usage-policy')
def usage_policy():
    """Usage Policy (Terms of Service) page - Public access."""
    return render_template('usage-policy.html')


# ---------------------------------------------------------------------------
# Status page
# ---------------------------------------------------------------------------

@app.route('/status')
def status_page():
    """Public status page — no login required."""
    services = status_service.check_health()
    overall = status_service.get_overall_status(services)
    # Grab last 5 resolved/firing incidents from DB for history section
    from models import IncidentModel
    recent_incidents = (
        IncidentModel.query
        .filter(IncidentModel.status.in_(['resolved', 'firing']))
        .order_by(IncidentModel.created_at.desc())
        .limit(5).all()
    )
    return render_template(
        'status.html',
        services=services,
        overall=overall,
        incidents=[i.to_dict() if hasattr(i, 'to_dict') else {} for i in recent_incidents],
    )


@app.route('/status/confirm/<token>')
def status_confirm(token):
    """Confirm a status-page email subscription."""
    ok, email = status_service.confirm(token)
    if ok:
        return render_template('status.html',
            services=status_service.check_health(),
            overall=status_service.get_overall_status(),
            incidents=[],
            flash_msg='You are now subscribed to status notifications.',
            flash_type='success',
        )
    return render_template('status.html',
        services=status_service.check_health(),
        overall=status_service.get_overall_status(),
        incidents=[],
        flash_msg='Invalid or expired confirmation link.',
        flash_type='error',
    )


@app.route('/status/unsubscribe/<token>')
def status_unsubscribe(token):
    """Unsubscribe from status-page emails."""
    ok, email = status_service.unsubscribe(token)
    msg = 'You have been unsubscribed.' if ok else 'Invalid unsubscribe link.'
    return render_template('status.html',
        services=status_service.check_health(),
        overall=status_service.get_overall_status(),
        incidents=[],
        flash_msg=msg,
        flash_type='success' if ok else 'error',
    )


@app.route('/api/status/subscribe', methods=['POST'])
def api_status_subscribe():
    """Subscribe an email to status page notifications."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400
    ok, msg = status_service.subscribe(email)
    if msg == 'already_subscribed':
        return jsonify({'error': 'Already subscribed'}), 409
    if ok:
        return jsonify({'message': 'Confirmation email sent. Check your inbox.'}), 200
    return jsonify({'error': 'Subscription failed. Please try again.'}), 500


@app.route('/api/status/health')
def api_status_health():
    """JSON health check for external monitors (e.g. UptimeRobot)."""
    services = status_service.check_health()
    overall = status_service.get_overall_status(services)
    code = 200 if overall == 'operational' else 503
    return jsonify({'status': overall, 'services': services, 'ts': datetime.utcnow().isoformat()}), code


@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page - Public access."""
    return render_template('privacy-policy.html')


@app.route('/teams')
@login_required
def teams():
    """Team management page."""
    # Get users for team management (limit to 200)
    users = User.query.order_by(User.created_at.desc()).limit(200).all()
    subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
    team_credits = subscription.credits_remaining if subscription else 0
    return render_template('teams.html', users=users, current_user=current_user, team_credits=team_credits)


@app.route('/about')
def about():
    """About page - Explains all features."""
    return render_template('about.html')


@app.route('/api/team/invite', methods=['POST'])
@login_required
def invite_team_member():
    """Invite a new team member."""
    # Only admins can invite members
    if current_user.role != 'admin':
        return jsonify({'error': 'Only administrators can invite team members'}), 403

    # Check tier limits
    from services.tier_enforcement import check_resource_limit
    allowed, current, limit = check_resource_limit(current_user.id, 'team_members')
    if not allowed:
        return jsonify({'error': f'Team member limit reached ({limit}). Upgrade your plan to invite more members.', 'upgrade_url': '/billing'}), 403

    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        username = data.get('username', '').strip()
        role = data.get('role', 'user').strip()

        if not email or not username:
            return jsonify({'error': 'Email and username are required'}), 400

        # Validate role
        valid_roles = ['admin', 'approver', 'user', 'viewer']
        if role not in valid_roles:
            return jsonify({'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400

        # Check if user already exists
        existing_user = User.query.filter(
            (User.email == email) | (User.username == username)
        ).first()

        if existing_user:
            return jsonify({'error': 'A user with this email or username already exists'}), 400

        # Create new user with a randomly generated secure password
        import string
        password_chars = string.ascii_letters + string.digits + '!@#$%^&*'
        default_password = ''.join(secrets.choice(password_chars) for _ in range(16))

        new_user = User(
            username=username,
            email=email,
            role=role
        )
        new_user.set_password(default_password)
        db.session.add(new_user)
        db.session.commit()

        # In a production app, you'd send an email invitation with a password reset link instead
        return jsonify({
            'success': True,
            'message': f'Team member invited successfully. Temporary password: {default_password}',
            'temporary_password': default_password,  # Admin will need to securely communicate this
            'user': {
                'id': new_user.id,
                'username': new_user.username,
                'email': new_user.email,
                'role': new_user.role
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/users/<int:user_id>/role', methods=['PUT'])
@login_required
def update_user_role(user_id):
    """Update a user's role."""
    # Only admins can update roles
    if current_user.role != 'admin':
        return jsonify({'error': 'Only administrators can update user roles'}), 403

    # Can't change your own role
    if user_id == current_user.id:
        return jsonify({'error': 'You cannot change your own role'}), 400

    try:
        data = request.get_json()
        new_role = data.get('role', '').strip()

        # Validate role
        valid_roles = ['admin', 'approver', 'user', 'viewer']
        if new_role not in valid_roles:
            return jsonify({'error': f'Invalid role. Must be one of: {", ".join(valid_roles)}'}), 400

        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        old_role = user.role
        user.role = new_role
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'User role updated from {old_role} to {new_role}',
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role
            }
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/team/users/<int:user_id>', methods=['DELETE'])
@login_required
def remove_team_member(user_id):
    """Remove a team member."""
    # Only admins can remove members
    if current_user.role != 'admin':
        return jsonify({'error': 'Only administrators can remove team members'}), 403

    # Can't remove yourself
    if user_id == current_user.id:
        return jsonify({'error': 'You cannot remove yourself from the team'}), 400

    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        username = user.username

        # Delete user's related data
        # Delete conversations
        Conversation.query.filter_by(user_id=user_id).delete()

        # Delete infrastructure resources
        InfrastructureResource.query.filter_by(user_id=user_id).delete()

        # Delete cost optimizations
        CostOptimization.query.filter_by(user_id=user_id).delete()

        # Delete security findings
        SecurityFinding.query.filter_by(user_id=user_id).delete()

        # Delete alerts
        Alert.query.filter_by(user_id=user_id).delete()

        # Delete the user
        db.session.delete(user)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Team member {username} removed successfully'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


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
        credentials_json = creds.get('credentials_json', '')
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

    if not webhook_url.startswith('https://'):
        return jsonify({'error': 'Webhook URL must use HTTPS'}), 400

    from urllib.parse import urlparse
    import ipaddress
    import socket
    parsed = urlparse(webhook_url)
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            return jsonify({'error': 'Webhook URL must not point to a private or reserved IP address'}), 400
    except (socket.gaierror, ValueError):
        pass

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

    # Wire into the notification service
    try:
        from services.notification_service import get_notification_service
        svc = get_notification_service()
        if channel_type == 'slack':
            svc.configure_slack(webhook_url=webhook_url)
        elif channel_type == 'teams':
            svc.configure_teams(webhook_url=webhook_url)
    except Exception:
        pass

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
        channel.webhook_url = data['webhook_url']

    db.session.commit()
    return jsonify({'success': True, 'channel': channel.to_dict()})


@app.route('/api/notification-channels/<int:channel_id>/test', methods=['POST'])
@login_required
def test_notification_channel(channel_id):
    """Send a test notification to a channel."""
    from models import UserNotificationChannel
    from services.notification_service import NotificationService, Notification, NotificationPriority

    channel = UserNotificationChannel.query.get_or_404(channel_id)
    if channel.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        svc = NotificationService()
        if channel.channel_type == 'slack':
            svc.configure_slack(webhook_url=channel.webhook_url)
        elif channel.channel_type == 'teams':
            svc.configure_teams(webhook_url=channel.webhook_url)

        notification = Notification(
            title='Test Notification',
            message='This is a test from DevOps Agent. If you see this, notifications are working.',
            priority=NotificationPriority.NORMAL,
            fields={'Source': 'DevOps Agent', 'Type': 'Test'}
        )
        results = svc.send(notification)
        success = any(results.values())
        return jsonify({'success': success, 'message': 'Test notification sent' if success else 'Failed to send'})
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

    data = request.get_json()
    name = data.get('name', '').strip()
    threshold = data.get('threshold_amount', 0)

    if not name or threshold <= 0:
        return jsonify({'error': 'Name and positive threshold amount are required'}), 400

    alert = BudgetAlert(
        user_id=current_user.id,
        name=name,
        threshold_amount=threshold,
        period=data.get('period', 'monthly'),
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
    process_free_tier_chat as _process_free_tier_chat,
    stream_free_tier_chat as _stream_free_tier_chat,
    generate_upgrade_pitch as _generate_upgrade_pitch,
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
            now = datetime.utcnow()
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

        # Reset monthly credits for paid tiers only — free tier is a one-time trial
        tier_name = subscription.tier.name if subscription.tier else 'free'
        if tier_name != 'free' and subscription.should_reset_credits():
            subscription.reset_monthly_credits()

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
                    'response': _generate_upgrade_pitch(),
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
                conversation.updated_at = datetime.utcnow()
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
                if prefs.sandbox_mode:
                    preferences_context += '\n' + SANDBOX_MODE_ADDENDUM
                    sandbox_active = True

        # Inject relevant memory context
        try:
            from services.memory_service import get_context_for_conversation
            memory_ctx = get_context_for_conversation(db, current_user.id, message)
            if memory_ctx:
                preferences_context = (preferences_context or '') + '\n\n' + memory_ctx
        except Exception:
            pass

        # Build trial context for free-tier users
        trial_context = None
        if tier_name == 'free':
            credits_left = subscription.credits_remaining
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
                "They are experiencing the full DevOps agent with real tool execution. "
            )
            if credits_left <= 5:
                trial_context += (
                    "Their credits are running low. Naturally weave in a brief mention that they can "
                    "upgrade to the Starter plan ($29/month) for 500 credits/month to keep using these tools. "
                    "Do NOT make this the focus -- still answer their question fully first."
                )

        # Process message — route based on provider
        try:
            if model_config.provider == 'kimi':
                response = agent.process_message_isolated(
                    user_message=message,
                    conversation_history=conversation_history,
                    user_preferences_context=preferences_context,
                    user_id=current_user.id,
                    model_override=model_config.model,
                    trial_context=trial_context,
                    sandbox_mode=sandbox_active,
                    provider='kimi'
                )
            elif model_config.provider == 'anthropic':
                response = agent.process_message_isolated(
                    user_message=message,
                    conversation_history=conversation_history,
                    user_preferences_context=preferences_context,
                    user_id=current_user.id,
                    model_override=model_config.model,
                    trial_context=trial_context,
                    sandbox_mode=sandbox_active
                )
            else:
                response = _process_free_tier_chat(message, conversation_history, preferences_context)
            success = True
            error_msg = None
        except Exception as agent_error:
            response = f"Error processing request: {str(agent_error)}"
            success = False
            error_msg = str(agent_error)

        # Auto-fallback: if primary provider returned an error string, retry with Groq
        if model_config.provider in ('anthropic', 'kimi') and _is_anthropic_error(response):
            try:
                from services.model_router import ModelConfig
                response = _process_free_tier_chat(message, conversation_history, preferences_context)
                fallback_note = "Claude" if model_config.provider == 'anthropic' else "Kimi"
                response += f"\n\n---\n*Note: {fallback_note} is temporarily unavailable. This response was generated by Llama 3.3 (Groq) without tool execution. Your cloud operations will resume when the primary model is back online.*"
                model_config = ModelConfig(
                    provider='groq', model='llama-3.3-70b-versatile',
                    display_name='Llama 3.3 70B (Fallback)', supports_tools=False,
                )
                success = True
                error_msg = None
            except Exception:
                pass  # Keep the original error response

        # Log usage — capture which tools were actually executed this turn
        _tools_used = getattr(agent, 'last_tools_used', [])
        _primary_tool = _tools_used[0] if _tools_used else None
        usage_log = UsageLog(
            user_id=current_user.id,
            conversation_id=conversation_id,
            action_type='tool_use' if _tools_used else 'agent_message',
            tool_name=_primary_tool,
            credits_used=1,
            success=success,
            error_message=error_msg,
            ai_model=model_config.model
        )
        db.session.add(usage_log)
        for _extra_tool in _tools_used[1:]:
            db.session.add(UsageLog(
                user_id=current_user.id,
                conversation_id=conversation_id,
                action_type='tool_use',
                tool_name=_extra_tool,
                credits_used=0,
                success=success,
                ai_model=model_config.model
            ))

        # Track first-ever tool use for conversion funnel
        if _tools_used and success:
            prior_tool_use = UsageLog.query.filter_by(
                user_id=current_user.id, action_type='tool_use'
            ).filter(UsageLog.id != usage_log.id).first()
            if not prior_tool_use:
                _track_conversion(current_user.id, 'first_tool_use', {'tool': _primary_tool})

        # Sanitize and redact secrets from response
        response = sanitize_output(response)
        response = redact_secrets(response)

        # Save assistant response
        assistant_message = ChatMessage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            role='assistant',
            content=response
        )
        db.session.add(assistant_message)

        # Update conversation title based on first message
        if is_first_message and conversation:
            # Generate title from user's first message (max 50 chars)
            title = message.strip()
            if len(title) > 50:
                title = title[:47] + '...'
            conversation.title = title

        # Deduct credit AFTER successful response (not before)
        if success:
            subscription.use_credit(commit=False)

        db.session.commit()

        # Fire low-credit warning email at exactly 5 credits remaining (once per threshold)
        if success and subscription.credits_remaining == 5 and current_user.email:
            try:
                import threading
                from services.email_service import email_service as _es
                _u = current_user._get_current_object()
                _r = subscription.credits_remaining
                threading.Thread(
                    target=_es.send_credit_low_warning, args=(_u, _r), daemon=True
                ).start()
            except Exception:
                pass

        # Auto-extract memorable facts from the conversation
        try:
            from services.memory_service import auto_extract_memories
            auto_extract_memories(db, current_user.id, message, response)
        except Exception:
            pass

        # Check if there's a pending download from the agent
        download_url = None
        if agent.pending_download:
            # Generate a secure token
            download_token = secrets.token_urlsafe(32)

            # Store the download with expiration (5 minutes)
            download_storage[download_token] = {
                'filename': agent.pending_download.get('filename'),
                'content': agent.pending_download.get('content'),
                'content_type': agent.pending_download.get('content_type', 'application/octet-stream'),
                'user_id': current_user.id,
                'expires_at': datetime.utcnow() + timedelta(minutes=5)
            }

            # Build download URL
            download_url = f'/api/download/{download_token}'

            # Clear the pending download
            agent.pending_download = None

            logger = get_logger(__name__)
            logger.info(f"Download ready for user {current_user.id}: {download_storage[download_token]['filename']}")

        response_data = {
            'response': response,
            'timestamp': datetime.now().isoformat(),
            'credits_remaining': subscription.credits_remaining,
            'credits_used_this_month': subscription.credits_used_this_month,
            'conversation_title': conversation.title if conversation else None,
            'model_info': {
                'provider': model_config.provider,
                'model': model_config.model,
                'display_name': model_config.display_name,
                'supports_tools': model_config.supports_tools,
            }
        }

        # Add download URL if available
        if download_url:
            response_data['download_url'] = download_url
            response_data['download_filename'] = download_storage[download_token]['filename']

        return jsonify(response_data)

    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
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
            now = datetime.utcnow()
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

        # Reset monthly credits for paid tiers only — free tier is a one-time trial
        tier_name = subscription.tier.name if subscription.tier else 'free'
        if tier_name != 'free' and subscription.should_reset_credits():
            subscription.reset_monthly_credits()

        subscription.repair_if_never_used()

        if not subscription.has_credits():
            if tier_name == 'free':
                # Free-tier exhausted: stream the upgrade pitch as SSE
                import json as _json_stream
                pitch = _generate_upgrade_pitch()
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
                conversation.updated_at = datetime.utcnow()
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

        # In-flight guard: atomic UPDATE — only sets is_streaming=True if it was False
        from sqlalchemy import update as _sa_update
        if conversation:
            _guard_result = db.session.execute(
                _sa_update(Conversation).where(
                    Conversation.id == conversation.id,
                    Conversation.is_streaming == False  # noqa: E712
                ).values(is_streaming=True)
            )
            db.session.commit()
            if _guard_result.rowcount == 0:
                return jsonify({'error': 'Another request is already streaming for this conversation.'}), 409
            # Refresh so the in-memory object reflects the DB state
            db.session.refresh(conversation)
        else:
            db.session.commit()

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
        user_msg = ChatMessage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            role='user',
            content=message
        )
        db.session.add(user_msg)
        if conversation and not getattr(conversation, '_preview_set', False):
            conversation.preview = message[:200]
            conversation._preview_set = True
        db.session.commit()  # Persist before agent processes — prevents message loss on crash

        preferences_context = prefs.get_context_for_prompt() if prefs else None
        sandbox_active = False
        if prefs and prefs.learning_mode:
            preferences_context = (preferences_context or '') + '\n\n' + LEARNING_MODE_CONTEXT
            if prefs.sandbox_mode:
                preferences_context += '\n' + SANDBOX_MODE_ADDENDUM
                sandbox_active = True

        # Build trial context for free-tier users
        trial_context = None
        if tier_name == 'free':
            credits_left = subscription.credits_remaining
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
                "They are experiencing the full DevOps agent with real tool execution. "
            )
            if credits_left <= 5:
                trial_context += (
                    "Their credits are running low. Naturally weave in a brief mention that they can "
                    "upgrade to the Starter plan ($29/month) for 500 credits/month to keep using these tools. "
                    "Do NOT make this the focus -- still answer their question fully first."
                )

        # Capture variables for the generator closure
        uid = current_user.id
        cid = conversation_id
        is_first = is_first_message
        conv = conversation
        sub = subscription
        msg_text = message
        mc = model_config
        tc = trial_context
        sb = sandbox_active

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
            _log.warning(f"STREAM DEBUG: tier={getattr(mc, 'provider', '?')}, model={getattr(mc, 'model', '?')}")
            try:
                if mc.provider not in ('anthropic', 'kimi'):
                    _log.warning("STREAM DEBUG: Using Groq path (non-anthropic/kimi)")
                    stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                else:
                    try:
                        _provider_arg = 'kimi' if mc.provider == 'kimi' else None
                        stream_source = agent.process_message_streaming(
                            user_message=msg_text,
                            conversation_history=conversation_history,
                            user_preferences_context=preferences_context,
                            user_id=uid,
                            model_override=mc.model,
                            trial_context=tc,
                            sandbox_mode=sb,
                            provider=_provider_arg
                        )
                        # Collect initial chunks to detect agent-swallowed errors
                        # The agent catches Anthropic exceptions and yields error text
                        initial_buf = []
                        for _c in stream_source:
                            initial_buf.append(_c)
                            # Once we have enough text to check, evaluate
                            combined = ''.join(initial_buf)
                            if _is_anthropic_error(combined):
                                # Anthropic failed — switch to Groq
                                actual_mc = _groq_fallback_mc
                                stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                                break
                            # If we've accumulated a reasonable first chunk without error, emit and continue
                            if len(combined) > 20 or not combined.startswith(('\u274c', 'Error', 'API', '{')):
                                # Looks like a real response, emit buffered chunks
                                for buf_chunk in initial_buf:
                                    full_response.append(buf_chunk)
                                    yield f"data: {_json.dumps({'type': 'chunk', 'content': redact_secrets(buf_chunk)})}\n\n"
                                break
                        else:
                            # Generator exhausted during initial check
                            combined = ''.join(initial_buf)
                            if _is_anthropic_error(combined):
                                actual_mc = _groq_fallback_mc
                                stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)
                            else:
                                # Short but valid response, emit it
                                for buf_chunk in initial_buf:
                                    full_response.append(buf_chunk)
                                    yield f"data: {_json.dumps({'type': 'chunk', 'content': redact_secrets(buf_chunk)})}\n\n"
                                stream_source = iter([])  # already consumed
                    except Exception:
                        # Actual exception (not swallowed by agent) — fallback to Groq
                        actual_mc = _groq_fallback_mc
                        stream_source = _stream_free_tier_chat(msg_text, conversation_history, preferences_context)

                for chunk in stream_source:
                    full_response.append(chunk)
                    yield f"data: {_json.dumps({'type': 'chunk', 'content': redact_secrets(chunk)})}\n\n"

                # Append fallback note if we switched providers
                if actual_mc.provider != mc.provider:
                    _fn = "Claude" if mc.provider == 'anthropic' else "Kimi"
                    fallback_msg = f"\n\n---\n*Note: {_fn} is temporarily unavailable. This response was generated by Llama 3.3 (Groq) without tool execution.*"
                    full_response.append(fallback_msg)
                    yield f"data: {_json.dumps({'type': 'chunk', 'content': fallback_msg})}\n\n"

                # Assemble full response for DB storage
                complete = ''.join(full_response)
                complete = sanitize_output(complete)
                complete = redact_secrets(complete)

                # Save assistant response in app context
                with app.app_context():
                    assistant_msg = ChatMessage(
                        user_id=uid,
                        conversation_id=cid,
                        role='assistant',
                        content=complete
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
                    for _st in _stream_tools[1:]:
                        db.session.add(UsageLog(
                            user_id=uid,
                            conversation_id=cid,
                            action_type='tool_use',
                            tool_name=_st,
                            credits_used=0,
                            success=True,
                            ai_model=actual_mc.model
                        ))

                    # Update conversation: title (first message) + clear streaming flag
                    c = Conversation.query.filter_by(id=cid, user_id=uid).first()
                    if c:
                        if is_first:
                            title = msg_text.strip()
                            c.title = title[:47] + '...' if len(title) > 50 else title
                        c.is_streaming = False

                    # Deduct credit AFTER successful response (not before)
                    fresh_sub = UserSubscription.query.filter_by(user_id=uid).first()
                    if fresh_sub:
                        fresh_sub.use_credit(commit=False)

                    db.session.commit()

                    # Read remaining credits after commit
                    remaining = fresh_sub.credits_remaining if fresh_sub else 0

                    # Fire low-credit warning email at exactly 5 credits remaining
                    if fresh_sub and remaining == 5:
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

                yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': remaining, 'model_info': {'provider': actual_mc.provider, 'model': actual_mc.model, 'display_name': actual_mc.display_name, 'supports_tools': actual_mc.supports_tools}})}\n\n"

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
                with app.app_context():
                    db.session.rollback()
                try:
                    yield f"data: {_json.dumps({'type': 'error', 'content': str(e)})}\n\n"
                    # Always send done so the frontend doesn't hang waiting for stream close
                    yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': 0, 'error': True})}\n\n"
                except (BrokenPipeError, GeneratorExit, ConnectionResetError):
                    pass
            finally:
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
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error in streaming chat: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


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
    now = datetime.utcnow()
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

        logger = get_logger(__name__)
        logger.info(f"User {current_user.id} downloaded file: {filename}")

        return response

    except Exception as e:
        logger = get_logger(__name__)
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
            'forecast': {'forecast_total': round(total * 1.05, 2)},
            'source': 'database'
        })


@app.route('/api/dashboard/utilization/<int:resource_db_id>', methods=['GET'])
@login_required
def get_resource_utilization(resource_db_id):
    """Get real CloudWatch utilization metrics for a resource."""
    try:
        from services.cost_explorer import get_instance_utilization, get_rds_utilization

        resource = InfrastructureResource.query.get_or_404(resource_db_id)
        if resource.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

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
        app.logger.error(f"Failed to queue sync task for user {current_user.id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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


@app.route('/api/dashboard/recommendations/<int:rec_id>/apply', methods=['POST'])
@login_required
def apply_recommendation(rec_id):
    """Apply a cost optimization recommendation."""
    try:
        from models import CostOptimization, InfrastructureResource
        from datetime import datetime

        # Get recommendation
        recommendation = CostOptimization.query.get_or_404(rec_id)

        # Verify ownership
        if recommendation.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        # For now, just mark as applied
        # In production, actually execute the action (stop instance, etc.)
        recommendation.status = 'applied'
        recommendation.applied_at = datetime.utcnow()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Optimization applied successfully',
            'savings': recommendation.potential_monthly_savings
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        recommendation.dismissed_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compliance/summary', methods=['GET'])
@login_required
def get_compliance_summary():
    """Get compliance summary with framework scores and findings."""
    try:
        from services.compliance_service import ComplianceService
        from models import SecurityFinding, ComplianceFrameworkModel

        service = ComplianceService(current_user.id)

        # Get frameworks and their latest scores (without re-running full scan)
        frameworks = ComplianceFrameworkModel.query.filter_by(
            user_id=current_user.id
        ).all()

        framework_data = []
        for fw in frameworks:
            controls = (fw.settings or {}).get('controls', [])
            framework_data.append({
                'id': fw.id,
                'name': fw.name,
                'display_name': fw.display_name or fw.name.upper(),
                'score': fw.compliance_score,
                'is_enabled': fw.is_enabled,
                'last_assessed': fw.last_assessment_at.isoformat() if fw.last_assessment_at else None,
                'controls_count': len(controls)
            })

        # Get open security findings
        findings = SecurityFinding.query.filter_by(
            user_id=current_user.id,
            status='open'
        ).order_by(SecurityFinding.risk_score.desc()).limit(100).all()

        findings_data = [{
            'id': f.id,
            'type': f.finding_type,
            'severity': f.severity,
            'title': f.title,
            'description': f.description,
            'resource_type': f.affected_resource_type,
            'resource_name': f.affected_resource_name,
            'resource_id': f.affected_resource_id,
            'risk_score': f.risk_score,
            'remediation': f.remediation_steps,
            'auto_fix': f.auto_remediation_available,
            'frameworks': f.compliance_frameworks or [],
            'first_detected': f.first_detected.isoformat() if f.first_detected else None
        } for f in findings]

        severity_counts = {
            'critical': len([f for f in findings if f.severity == 'critical']),
            'high': len([f for f in findings if f.severity == 'high']),
            'medium': len([f for f in findings if f.severity == 'medium']),
            'low': len([f for f in findings if f.severity == 'low'])
        }

        # Get active policies count
        from models import CompliancePolicy
        policies = CompliancePolicy.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).all()

        return jsonify({
            'frameworks': framework_data,
            'findings': findings_data,
            'severity_counts': severity_counts,
            'total_findings': len(findings),
            'policies_active': len(policies)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compliance/scan', methods=['POST'])
@login_required
def run_compliance_scan():
    """Run compliance scan for a specific framework."""
    try:
        from services.compliance_service import ComplianceService
        from services.tier_enforcement import check_compliance_framework

        data = request.get_json() or {}
        framework = data.get('framework', 'soc2')

        if not check_compliance_framework(current_user.id, framework):
            return jsonify({'error': f'The {framework.upper()} framework is not available on your plan. Upgrade to access it.', 'upgrade_url': '/billing'}), 403

        service = ComplianceService(current_user.id)
        report = service.run_compliance_check(current_user.id, framework)

        return jsonify({
            'success': True,
            'report': {
                'id': report.id,
                'framework': report.framework,
                'score': report.overall_score,
                'controls_passed': report.controls_passed,
                'controls_failed': report.controls_failed,
                'findings': report.findings,
                'summary': report.summary,
                'generated_at': report.generated_at.isoformat() if report.generated_at else None
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compliance/scan-all', methods=['POST'])
@login_required
@limiter.limit("2 per minute")
def run_all_compliance_scans():
    """Run compliance scans for all supported frameworks."""
    try:
        from services.compliance_service import ComplianceService
        service = ComplianceService(current_user.id)

        results = {}
        total_findings = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'total': 0}
        for fw in ['soc2', 'hipaa', 'pci_dss']:
            report = service.run_compliance_check(current_user.id, fw)
            findings = report.findings or []
            results[fw] = {
                'score': report.overall_score,
                'controls_passed': report.controls_passed,
                'controls_failed': report.controls_failed,
                'findings_count': len(findings)
            }
            for f in findings:
                sev = f.get('severity', 'medium').lower()
                total_findings[sev] = total_findings.get(sev, 0) + 1
                total_findings['total'] += 1

        # Notify if critical or high findings detected
        if total_findings['critical'] > 0 or total_findings['high'] > 0:
            try:
                from services.notification_service import get_notification_service
                svc = get_notification_service()
                svc.send_security_notification(current_user.id, total_findings)
            except Exception:
                pass

        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compliance/report/<framework>/pdf', methods=['GET'])
@login_required
def download_compliance_pdf(framework):
    """Download compliance report as PDF."""
    from services.tier_enforcement import check_feature
    if not check_feature(current_user.id, 'has_pdf_export'):
        return jsonify({'error': 'PDF export is available on Pro and Enterprise plans.', 'upgrade_url': '/billing'}), 403

    try:
        from models import ComplianceReport
        report = ComplianceReport.query.filter_by(
            user_id=current_user.id,
            framework=framework
        ).order_by(ComplianceReport.generated_at.desc()).first()

        if not report:
            return jsonify({'error': f'No {framework.upper()} report found. Run a compliance scan first.'}), 404

        report_data = {
            'overall_score': report.overall_score,
            'controls_passed': report.controls_passed,
            'controls_failed': report.controls_failed,
            'findings': report.findings or [],
            'summary': report.summary,
            'generated_at': report.generated_at.isoformat() if report.generated_at else None,
        }

        from services.pdf_service import generate_compliance_pdf
        pdf_buffer = generate_compliance_pdf(current_user.id, framework, report_data)

        filename = f"devops-agent-{framework}-report-{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )
    except ImportError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/compliance/findings/<int:finding_id>/resolve', methods=['POST'])
@login_required
def resolve_finding(finding_id):
    """Resolve a security finding."""
    try:
        from models import SecurityFinding

        finding = SecurityFinding.query.get_or_404(finding_id)
        if finding.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        data = request.get_json() or {}
        finding.status = 'resolved'
        finding.resolved_at = datetime.utcnow()
        finding.resolved_by = current_user.id
        finding.resolution_notes = data.get('notes', '')
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        logger = get_logger(__name__)
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

        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        category = data.get('category', '').strip()
        message = data.get('message', '').strip()

        if not all([name, email, category, message]):
            return jsonify({'error': 'All fields are required'}), 400

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

        logger = get_logger(__name__)
        logger.info(f"New contact message from {email}: {category}")

        # Forward message to support inbox
        try:
            support_email = os.getenv('SUPPORT_EMAIL', 'hello@devopsagent.io')
            html = email_service._wrap_html(f"""
                <h2 style="color:#333;margin-bottom:12px;">New Contact Message</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                    <tr><td style="padding:8px 0;color:#666;width:100px;"><strong>From</strong></td><td style="padding:8px 0;">{name} &lt;{email}&gt;</td></tr>
                    <tr><td style="padding:8px 0;color:#666;"><strong>Category</strong></td><td style="padding:8px 0;">{category}</td></tr>
                    <tr><td style="padding:8px 0;color:#666;"><strong>Message</strong></td><td style="padding:8px 0;white-space:pre-wrap;">{message}</td></tr>
                </table>
                <div style="margin-top:20px;">
                    <a href="mailto:{email}" style="display:inline-block;padding:10px 24px;background:linear-gradient(135deg,#ff6b35,#f7931e);color:white;text-decoration:none;border-radius:8px;font-weight:600;">Reply to {name}</a>
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
        logger.error(f"Error loading conversation: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
@login_required
def delete_conversation(conversation_id):
    """Delete a conversation."""
    try:
        # Verify conversation belongs to user
        conversation = Conversation.query.filter_by(
            id=conversation_id,
            user_id=current_user.id
        ).first()

        if not conversation:
            return jsonify({'error': 'Conversation not found'}), 404

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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
            levels = prefs.learning_level or {}
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
        logger.error(f"Error fetching learning history: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/proficiency', methods=['GET'])
@login_required
def learning_proficiency():
    """Get current proficiency levels and session count."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        levels = prefs.learning_level if prefs and prefs.learning_level else {}

        session_count = LearningSession.query.filter_by(user_id=current_user.id).count()

        return jsonify({
            'proficiency': levels,
            'session_count': session_count
        })
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error fetching proficiency: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/learning/paths', methods=['GET'])
@login_required
def learning_paths():
    """Return structured learning curriculum with suggested path based on proficiency."""
    try:
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        levels = prefs.learning_level if prefs and prefs.learning_level else {}

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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
        logger.error(f"Error fetching scenarios: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ===== COMMAND TEMPLATES API =====

@app.route('/api/templates', methods=['GET'])
@login_required
def get_templates():
    """Get command templates (user's own + public templates)."""
    try:
        # Get user's own templates
        user_templates = CommandTemplate.query.filter_by(user_id=current_user.id).order_by(CommandTemplate.use_count.desc()).all()

        # Get public templates from other users
        public_templates = CommandTemplate.query.filter_by(is_public=True).filter(
            CommandTemplate.user_id != current_user.id
        ).order_by(CommandTemplate.use_count.desc()).limit(10).all()

        return jsonify({
            'user_templates': [t.to_dict() for t in user_templates],
            'public_templates': [t.to_dict() for t in public_templates]
        })
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error retrieving templates: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/templates', methods=['POST'])
@login_required
def create_template():
    """Create a new command template."""
    try:
        data = request.get_json()
        name = data.get('name')
        command = data.get('command')

        if not name or not command:
            return jsonify({'error': 'Name and command are required'}), 400

        template = CommandTemplate(
            user_id=current_user.id,
            name=name,
            description=data.get('description'),
            command=command,
            category=data.get('category'),
            is_public=data.get('is_public', False)
        )

        db.session.add(template)
        db.session.commit()

        return jsonify({'success': True, 'template': template.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error creating template: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/templates/<int:template_id>', methods=['PUT'])
@login_required
def update_template(template_id):
    """Update a command template."""
    try:
        template = CommandTemplate.query.get(template_id)

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        if template.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        data = request.get_json()

        if 'name' in data:
            template.name = data['name']
        if 'description' in data:
            template.description = data['description']
        if 'command' in data:
            template.command = data['command']
        if 'category' in data:
            template.category = data['category']
        if 'is_public' in data:
            template.is_public = data['is_public']

        db.session.commit()

        return jsonify({'success': True, 'template': template.to_dict()})
    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error updating template: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/templates/<int:template_id>', methods=['DELETE'])
@login_required
def delete_template(template_id):
    """Delete a command template."""
    try:
        template = CommandTemplate.query.get(template_id)

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        if template.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        db.session.delete(template)
        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error deleting template: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/templates/<int:template_id>/use', methods=['POST'])
@login_required
def use_template(template_id):
    """Use a template (increments use count and returns the command)."""
    try:
        template = CommandTemplate.query.get(template_id)

        if not template:
            return jsonify({'error': 'Template not found'}), 404

        # Increment use count
        template.increment_use_count()

        return jsonify({
            'success': True,
            'command': template.command,
            'template': template.to_dict()
        })
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error using template: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
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
        logger = get_logger(__name__)
        logger.error(f"Error getting translations: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/webhooks/<source>', methods=['POST'])
def receive_webhook(source):
    """Receive webhooks from external services (GitHub, PagerDuty, etc.)."""
    from services.webhook_handler import verify_webhook_signature, process_webhook

    payload_bytes = request.get_data()

    # Verify signature if a secret is configured for this source
    secret_key = os.environ.get(f'WEBHOOK_SECRET_{source.upper()}', '')
    if secret_key:
        sig_header = {
            'github': 'X-Hub-Signature-256',
            'pagerduty': 'X-PagerDuty-Signature',
        }.get(source, 'X-Webhook-Signature')
        signature = request.headers.get(sig_header, '')
        if not verify_webhook_signature(payload_bytes, signature, secret_key, source):
            return jsonify({'error': 'Invalid signature'}), 401

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    event_type = request.headers.get('X-GitHub-Event', request.headers.get('X-Event-Type', ''))
    result = process_webhook(source, payload, event_type)

    webhook_logger = logging.getLogger('webhooks')
    webhook_logger.info(f"[{source}] {result.get('summary', 'webhook received')}")

    return jsonify({
        'status': 'received',
        'source': source,
        'summary': result.get('summary', ''),
        'suggested_actions': result.get('suggested_actions', []),
    })


@app.route('/api/webhooks', methods=['GET'])
@login_required
def list_webhook_endpoints():
    """List available webhook endpoints."""
    base = os.environ.get('BASE_URL', request.host_url.rstrip('/'))
    return jsonify({
        'endpoints': {
            'github': f'{base}/api/webhooks/github',
            'pagerduty': f'{base}/api/webhooks/pagerduty',
            'generic': f'{base}/api/webhooks/generic',
        },
        'setup_instructions': {
            'github': 'Add as a GitHub webhook URL. Set Content-Type to application/json. Optionally set WEBHOOK_SECRET_GITHUB env var for signature verification.',
            'pagerduty': 'Add as a PagerDuty webhook endpoint. Set WEBHOOK_SECRET_PAGERDUTY env var for signature verification.',
            'generic': 'POST JSON payloads with optional X-Webhook-Signature header.',
        }
    })


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
    provided_token = request.headers.get('X-Init-Secret') or request.json.get('secret') if request.json else None
    if not provided_token or provided_token != init_secret:
        security_logger.warning(f"Unauthorized database initialization attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        db.create_all()

        # Upsert subscription tiers — create if missing, update if prices/features changed
        from models import SubscriptionTier

        tier_definitions = [
            dict(name='free', display_name='Free', monthly_credits=20, monthly_price=0.0,
                 description='Try the DevOps Agent with limited features',
                 features=['20 AI messages per month', '1 cloud account', '25 resources tracked', 'Manual sync only'],
                 max_cloud_accounts=1, max_resources=25, max_team_members=1, sync_interval_minutes=0,
                 compliance_frameworks=[], has_pdf_export=False, has_auto_remediation=False, has_sso=False, has_audit_export=False),
            dict(name='starter', display_name='Starter', monthly_credits=200, monthly_price=29.0,
                 description='For individual developers and solo operators',
                 features=['200 AI messages per month', '1 cloud account', '50 resources tracked', 'SOC 2 compliance scans', 'Email support'],
                 max_cloud_accounts=1, max_resources=50, max_team_members=1, sync_interval_minutes=0,
                 compliance_frameworks=['soc2'], has_pdf_export=False, has_auto_remediation=False, has_sso=False, has_audit_export=False),
            dict(name='professional', display_name='Pro', monthly_credits=2000, monthly_price=99.0,
                 description='For growing teams with multi-cloud needs',
                 features=['2,000 AI messages per month', '3 cloud accounts (AWS + Azure + GCP)', '500 resources tracked',
                           'Up to 10 team members', 'SOC 2 + HIPAA compliance', 'PDF compliance reports',
                           'Auto-remediation', 'Auto-sync every 6 hours', 'Priority support'],
                 max_cloud_accounts=3, max_resources=500, max_team_members=10, sync_interval_minutes=360,
                 compliance_frameworks=['soc2', 'hipaa'], has_pdf_export=True, has_auto_remediation=True, has_sso=False, has_audit_export=False),
            dict(name='business', display_name='Enterprise', monthly_credits=10000, monthly_price=299.0,
                 description='Full-scale automation for large organizations',
                 features=['10,000 AI messages per month', 'Unlimited cloud accounts', 'Unlimited resources',
                           'Unlimited team members', 'All compliance frameworks', 'PDF compliance reports',
                           'Auto-remediation + custom rules', 'Auto-sync every 15 minutes',
                           'SSO / SAML', 'Audit log export', 'Dedicated support + SLA'],
                 max_cloud_accounts=99, max_resources=99999, max_team_members=99, sync_interval_minutes=15,
                 compliance_frameworks=['soc2', 'hipaa', 'pci_dss', 'gdpr', 'iso27001', 'nist', 'cis'],
                 has_pdf_export=True, has_auto_remediation=True, has_sso=True, has_audit_export=True),
        ]
        created = 0
        updated = 0
        for defn in tier_definitions:
            tier = SubscriptionTier.query.filter_by(name=defn['name']).first()
            if tier:
                changed = False
                for key, val in defn.items():
                    if key == 'name':
                        continue
                    if getattr(tier, key) != val:
                        setattr(tier, key, val)
                        changed = True
                if changed:
                    updated += 1
            else:
                tier = SubscriptionTier(**defn, is_active=True)
                db.session.add(tier)
                created += 1
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


if __name__ == '__main__':
    print("=" * 60)
    print("DevOps Automation Agent - Web Interface")
    print("=" * 60)

    # Initialize database
    with app.app_context():
        db.create_all()

        # Auto-migrate missing columns (db.create_all only creates new tables,
        # it never adds columns to existing tables)
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        _inspector = sa_inspect(db.engine)
        _existing_tables = set(_inspector.get_table_names())
        _cols_added = 0
        _dialect = db.engine.dialect
        for _mapper in db.Model.registry.mappers:
            _cls = _mapper.class_
            _tbl = getattr(_cls, '__tablename__', None)
            if not _tbl or _tbl not in _existing_tables:
                continue
            _db_cols = {c['name'] for c in _inspector.get_columns(_tbl)}
            for _col in _cls.__table__.columns:
                if _col.key not in _db_cols:
                    _st = _col.type.compile(dialect=_dialect)
                    _df = ''
                    if _col.default is not None and getattr(_col.default, 'is_scalar', False):
                        _v = _col.default.arg
                        if isinstance(_v, bool):
                            _df = ' DEFAULT ' + ('TRUE' if _v else 'FALSE')
                        elif isinstance(_v, (int, float)):
                            _df = f' DEFAULT {_v}'
                        elif isinstance(_v, str):
                            _df = f" DEFAULT '{_v.replace(chr(39), chr(39)+chr(39))}'"
                    with db.engine.connect() as _conn:
                        _conn.execute(sa_text(f'ALTER TABLE {_tbl} ADD COLUMN {_col.key} {_st}{_df}'))
                        _conn.commit()
                    _cols_added += 1
        if _cols_added:
            print(f"\nAuto-migrated {_cols_added} missing column(s)")

        # Backfill mfa_method for existing TOTP users
        try:
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

        print("\nDatabase initialized")

        # Upsert subscription tiers — create if missing, update if prices/features changed
        tier_definitions = [
            dict(name='free', display_name='Free', monthly_credits=20, monthly_price=0.0,
                 description='Try the DevOps Agent with limited features',
                 features=['20 AI messages per month', '1 cloud account', '25 resources tracked', 'Manual sync only'],
                 max_cloud_accounts=1, max_resources=25, max_team_members=1, sync_interval_minutes=0,
                 compliance_frameworks=[], has_pdf_export=False, has_auto_remediation=False, has_sso=False, has_audit_export=False),
            dict(name='starter', display_name='Starter', monthly_credits=200, monthly_price=29.0,
                 description='For individual developers and solo operators',
                 features=['200 AI messages per month', '1 cloud account', '50 resources tracked', 'SOC 2 compliance scans', 'Email support'],
                 max_cloud_accounts=1, max_resources=50, max_team_members=1, sync_interval_minutes=0,
                 compliance_frameworks=['soc2'], has_pdf_export=False, has_auto_remediation=False, has_sso=False, has_audit_export=False),
            dict(name='professional', display_name='Pro', monthly_credits=2000, monthly_price=99.0,
                 description='For growing teams with multi-cloud needs',
                 features=['2,000 AI messages per month', '3 cloud accounts (AWS + Azure + GCP)', '500 resources tracked',
                           'Up to 10 team members', 'SOC 2 + HIPAA compliance', 'PDF compliance reports',
                           'Auto-remediation', 'Auto-sync every 6 hours', 'Priority support'],
                 max_cloud_accounts=3, max_resources=500, max_team_members=10, sync_interval_minutes=360,
                 compliance_frameworks=['soc2', 'hipaa'], has_pdf_export=True, has_auto_remediation=True, has_sso=False, has_audit_export=False),
            dict(name='business', display_name='Enterprise', monthly_credits=10000, monthly_price=299.0,
                 description='Full-scale automation for large organizations',
                 features=['10,000 AI messages per month', 'Unlimited cloud accounts', 'Unlimited resources',
                           'Unlimited team members', 'All compliance frameworks', 'PDF compliance reports',
                           'Auto-remediation + custom rules', 'Auto-sync every 15 minutes',
                           'SSO / SAML', 'Audit log export', 'Dedicated support + SLA'],
                 max_cloud_accounts=99, max_resources=99999, max_team_members=99, sync_interval_minutes=15,
                 compliance_frameworks=['soc2', 'hipaa', 'pci_dss', 'gdpr', 'iso27001', 'nist', 'cis'],
                 has_pdf_export=True, has_auto_remediation=True, has_sso=True, has_audit_export=True),
        ]
        for defn in tier_definitions:
            tier = SubscriptionTier.query.filter_by(name=defn['name']).first()
            if tier:
                updated = False
                for key, val in defn.items():
                    if key == 'name':
                        continue
                    if getattr(tier, key) != val:
                        setattr(tier, key, val)
                        updated = True
                if updated:
                    print(f"  Updated tier: {defn['name']} (price=${defn['monthly_price']})")
            else:
                tier = SubscriptionTier(**defn, is_active=True)
                db.session.add(tier)
                print(f"  Created tier: {defn['name']} (price=${defn['monthly_price']})")
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

    # Debug: Print registered blueprints and key routes
    print("\nRegistered Blueprints:", list(app.blueprints.keys()))
    print("Key Routes:")
    for rule in app.url_map.iter_rules():
        if any(x in rule.rule for x in ['/monitoring', '/incidents', '/optimization', '/notifications', '/admin']):
            if rule.rule.endswith('/'):
                print(f"  {rule.rule}")

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
    app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=False)
