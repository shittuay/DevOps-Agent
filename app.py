"""
Flask Web Interface for DevOps Agent with API Key Configuration and Authentication
"""
import os
import sys
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, make_response, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets
import logging
import re
from email_validator import validate_email, EmailNotValidError

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.agent import DevOpsAgent
from src.utils import setup_logging, get_logger
from src.tools import (
    command_tools,
    aws_tools,
    gcp_tools,
    kubernetes_tools,
    git_tools,
    cicd_tools,
    pentest_tools
)

# Import database models
from models import (
    db, User, ChatMessage, Conversation, UserPreferences, CommandTemplate,
    ResponseFeedback, SubscriptionTier, UserSubscription, CreditPurchase, UsageLog
)

# Import Stripe integration
try:
    import stripe
    from stripe_integration import (
        StripePaymentService,
        create_subscription_checkout,
        create_credit_pack_checkout
    )
    STRIPE_ENABLED = True
except ImportError:
    STRIPE_ENABLED = False
    print("Warning: Stripe not installed. Payment features will be disabled.")

app = Flask(__name__)

# Initialize security features
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

# CSRF Protection
csrf = CSRFProtect(app)
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit for CSRF tokens
app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # Don't check CSRF on all requests by default
# We'll enable CSRF only on forms (POST requests to /login, /signup, etc.)

# Rate Limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

# Security Headers (disable HTTPS redirect for local development)
# In production, set force_https=True
# Temporarily disabled Talisman to fix inline script issues
# Talisman(app,
#     force_https=False,  # Set to True in production
#     content_security_policy={
#         'default-src': "'self'",
#         'script-src': ["'self'", "'unsafe-inline'", "https://js.stripe.com"],
#         'style-src': ["'self'", "'unsafe-inline'"],
#         'img-src': ["'self'", "data:", "https:"],
#         'font-src': ["'self'", "data:"],
#         'connect-src': ["'self'", "https://api.stripe.com"],
#         'frame-src': ["'self'", "https://js.stripe.com", "https://hooks.stripe.com"],
#     },
#     content_security_policy_nonce_in=['script-src']
# )

# Security logging
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)
security_handler = logging.FileHandler('logs/security.log')
security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
security_logger.addHandler(security_handler)

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

app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours in seconds
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_DURATION'] = 86400  # 24 hours

# Database configuration
# Support both SQLite (dev) and PostgreSQL (production)
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Railway/Render provide DATABASE_URL with postgres:// which needs to be postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
else:
    # Development: use SQLite with optimizations for concurrency
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///devops_agent.db'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'timeout': 30,  # 30 second timeout for database locks
            'check_same_thread': False,  # Allow multiple threads
        },
        'pool_pre_ping': True,
        'pool_size': 10,
        'max_overflow': 20,
    }

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Configure SQLite for better concurrency (WAL mode)
if not database_url:  # Only for SQLite
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        """Enable Write-Ahead Logging mode for SQLite to reduce lock contention."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

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

# Error handler for database errors
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle uncaught exceptions and ensure database rollback."""
    # Rollback database session on error
    db.session.rollback()

    # Log the error
    app.logger.error(f"Unhandled exception: {str(e)}", exc_info=True)

    # For database-specific errors, provide helpful message
    if 'database is locked' in str(e).lower():
        return jsonify({
            'error': 'Database is temporarily busy. Please try again in a moment.',
            'details': 'The system is processing another request. This usually resolves quickly.'
        }), 503

    # For other errors in API endpoints, return JSON
    if request.path.startswith('/api/') or request.path.startswith('/chat'):
        return jsonify({'error': 'An internal error occurred. Please try again.'}), 500

    # For page requests, render error template or return error message
    return f"An error occurred: {str(e)}", 500

# Global agent instance
agent = None
config_manager = None

# Temporary storage for file downloads (token -> {file_data, expires_at})
# Downloads expire after 5 minutes for security
download_storage = {}

def check_api_key_configured():
    """Check if API key is configured in environment or .env file."""
    # First check environment variable (for production)
    env_api_key = os.environ.get('ANTHROPIC_API_KEY')
    if env_api_key and env_api_key.startswith('sk-ant-'):
        return True

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
        # Always enable GCP tools
        agent.register_tools_from_module(gcp_tools)
        if config_manager.k8s_enabled:
            agent.register_tools_from_module(kubernetes_tools)
        agent.register_tools_from_module(git_tools)
        if config_manager.jenkins_enabled or config_manager.github_enabled:
            agent.register_tools_from_module(cicd_tools)

        # Register Penetration Testing tools if enabled
        if config_manager.get('pentest.enabled', False):
            agent.register_tools_from_module(pentest_tools)
            logger.info("Penetration testing tools enabled - ensure authorized usage")

        logger.info(f"Agent initialized with {len(agent.list_available_tools())} tools")

        return True, None

    except Exception as e:
        return False, str(e)


@app.route('/')
def index():
    """Redirect to appropriate page based on auth status."""
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return redirect(url_for('chat'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # Max 10 login attempts per minute
def login():
    """User login page with security features."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        email_or_username = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        ip_address = request.remote_addr

        # Security logging
        security_logger.info(f"Login attempt from IP: {ip_address} for user: {email_or_username}")

        if not email_or_username or not password:
            security_logger.warning(f"Failed login attempt from {ip_address}: Missing credentials")
            return render_template('login.html', error='Email/Username and password are required')

        # Try to find user by email or username
        user = User.query.filter(
            (User.email == email_or_username) | (User.username == email_or_username)
        ).first()

        if not user:
            security_logger.warning(f"Failed login attempt from {ip_address}: User not found - {email_or_username}")
            return render_template('login.html', error='Invalid email/username or password')

        # Check if account is locked
        if user.is_locked():
            security_logger.warning(f"Login attempt for locked account: {user.email} from {ip_address}")
            return render_template('login.html', error=f'Account temporarily locked due to multiple failed login attempts. Try again in 15 minutes.')

        # Verify password
        if user.check_password(password):
            # Successful login
            login_user(user, remember=True)
            user.update_last_login(ip_address=ip_address)

            # Make session permanent
            session.permanent = True

            security_logger.info(f"Successful login: {user.email} from {ip_address}")

            # Redirect to next page or chat
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('chat'))
        else:
            # Failed login - record attempt
            user.record_failed_login()
            attempts_remaining = max(0, 5 - user.failed_login_attempts)

            security_logger.warning(f"Failed login attempt for {user.email} from {ip_address}. Attempts remaining: {attempts_remaining}")

            if attempts_remaining == 0:
                return render_template('login.html', error='Account locked due to multiple failed login attempts. Try again in 15 minutes.')
            else:
                return render_template('login.html', error=f'Invalid email/username or password. {attempts_remaining} attempts remaining before account lockout.')

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
@limiter.limit("5 per hour")  # Max 5 signup attempts per hour
def signup():
    """User registration page with input validation."""
    if current_user.is_authenticated:
        return redirect(url_for('chat'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        ip_address = request.remote_addr

        # Security logging
        security_logger.info(f"Signup attempt from IP: {ip_address} for email: {email}")

        # Basic validation
        if not email or not username or not password:
            return render_template('signup.html', error='Email, username, and password are required')

        # Email validation
        try:
            valid = validate_email(email, check_deliverability=False)
            email = valid.email
        except EmailNotValidError as e:
            security_logger.warning(f"Invalid email format from {ip_address}: {email}")
            return render_template('signup.html', error=f'Invalid email address: {str(e)}')

        # Username validation (alphanumeric, underscore, 3-20 characters)
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            return render_template('signup.html', error='Username must be 3-20 characters long and contain only letters, numbers, and underscores')

        # Password strength validation
        if len(password) < 8:
            return render_template('signup.html', error='Password must be at least 8 characters long')

        # Check password complexity
        if not re.search(r'[A-Z]', password):
            return render_template('signup.html', error='Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', password):
            return render_template('signup.html', error='Password must contain at least one lowercase letter')
        if not re.search(r'[0-9]', password):
            return render_template('signup.html', error='Password must contain at least one number')

        # Check if user already exists
        if User.query.filter_by(email=email).first():
            security_logger.warning(f"Signup attempt with existing email from {ip_address}: {email}")
            return render_template('signup.html', error='Email already registered')

        if User.query.filter_by(username=username).first():
            security_logger.warning(f"Signup attempt with existing username from {ip_address}: {username}")
            return render_template('signup.html', error='Username already taken')

        # Create new user
        try:
            user = User(
                email=email,
                username=username,
                full_name=full_name if full_name else None,
                last_login_ip=ip_address
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            security_logger.info(f"New user registered: {email} from {ip_address}")

            # Log the user in
            login_user(user, remember=True)
            user.update_last_login(ip_address=ip_address)

            return redirect(url_for('chat'))
        except Exception as e:
            db.session.rollback()
            return render_template('signup.html', error=f'Error creating account: {str(e)}')

    return render_template('signup.html')


@app.route('/logout')
@login_required
def logout():
    """Logout user."""
    logout_user()
    return redirect(url_for('login'))


@app.route('/chat')
@login_required
def chat():
    """Render the main chat interface or setup page."""
    # Check if API key is configured
    if not check_api_key_configured():
        return render_template('setup.html')

    # Initialize session if needed
    if 'conversation_id' not in session:
        session['conversation_id'] = secrets.token_hex(8)

    return render_template('index.html', user=current_user)


@app.route('/dashboard')
@login_required
def dashboard():
    """Infrastructure dashboard with real-time monitoring."""
    return render_template('dashboard_live.html', user=current_user)


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


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """Setup page for API key configuration."""
    if request.method == 'POST':
        data = request.get_json()
        api_key = data.get('api_key', '').strip()

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


@app.route('/billing')
@login_required
def billing():
    """Billing and credits management page."""
    return render_template('billing.html', user=current_user)


@app.route('/usage-policy')
def usage_policy():
    """Usage Policy (Terms of Service) page - Public access."""
    return render_template('usage-policy.html')


@app.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page - Public access."""
    return render_template('privacy-policy.html')


@app.route('/teams')
@login_required
def teams():
    """Team management page."""
    # Get all users for team management
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('teams.html', users=users, current_user=current_user)


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

        # Create new user with a default password (they should change it on first login)
        from werkzeug.security import generate_password_hash
        default_password = 'ChangeMe123!'  # They'll need to change this

        new_user = User(
            username=username,
            email=email,
            password=generate_password_hash(default_password),
            role=role
        )
        db.session.add(new_user)
        db.session.commit()

        # In a production app, you'd send an email invitation here
        return jsonify({
            'success': True,
            'message': f'Team member invited successfully. Default password: {default_password}',
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


@app.route('/api/aws-config', methods=['GET', 'POST'])
@login_required
def aws_config():
    """Handle AWS configuration."""
    if request.method == 'GET':
        return jsonify(get_aws_config_status())

    # POST - Save AWS credentials
    try:
        data = request.get_json()
        access_key = data.get('access_key', '').strip()
        secret_key = data.get('secret_key', '').strip()
        region = data.get('region', 'us-east-1').strip()

        if not access_key or not secret_key:
            return jsonify({'error': 'AWS Access Key and Secret Key are required'}), 400

        # Basic validation
        if not access_key.startswith('AKIA'):
            return jsonify({'error': 'Invalid AWS Access Key format (should start with AKIA)'}), 400

        # Save credentials
        save_aws_credentials(access_key, secret_key, region)

        # Reload agent to use new credentials
        if agent is not None:
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Credentials saved but agent reload failed: {error}'}), 500

        return jsonify({
            'success': True,
            'message': 'AWS credentials configured successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/azure-config', methods=['GET', 'POST'])
@login_required
def azure_config():
    """Handle Azure configuration."""
    if request.method == 'GET':
        return jsonify(get_azure_config_status())

    # POST - Save Azure credentials
    try:
        data = request.get_json()
        subscription_id = data.get('subscription_id', '').strip()
        tenant_id = data.get('tenant_id', '').strip()
        client_id = data.get('client_id', '').strip()
        client_secret = data.get('client_secret', '').strip()
        location = data.get('location', 'eastus').strip()

        if not all([subscription_id, tenant_id, client_id, client_secret]):
            return jsonify({'error': 'All Azure credentials are required'}), 400

        # Save credentials
        save_azure_credentials(subscription_id, tenant_id, client_id, client_secret, location)

        # Reload agent to use new credentials
        if agent is not None:
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Credentials saved but agent reload failed: {error}'}), 500

        return jsonify({
            'success': True,
            'message': 'Azure credentials configured successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/gcp-config', methods=['GET', 'POST'])
@login_required
def gcp_config():
    """Handle GCP configuration."""
    if request.method == 'GET':
        return jsonify(get_gcp_config_status())

    # POST - Save GCP credentials
    try:
        data = request.get_json()
        project_id = data.get('project_id', '').strip()
        credentials_json = data.get('credentials_json', '').strip()
        region = data.get('region', 'us-central1').strip()
        zone = data.get('zone', 'us-central1-a').strip()

        if not project_id:
            return jsonify({'error': 'GCP Project ID is required'}), 400

        if not credentials_json:
            return jsonify({'error': 'GCP Service Account credentials (JSON) are required'}), 400

        # Validate JSON
        try:
            import json
            json.loads(credentials_json)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid JSON format for credentials'}), 400

        # Save credentials
        save_gcp_credentials(project_id, credentials_json, region, zone)

        # Reload agent to use new credentials
        if agent is not None:
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Credentials saved but agent reload failed: {error}'}), 500

        return jsonify({
            'success': True,
            'message': 'GCP credentials configured successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Handle chat messages."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized. Please configure API key.'}), 503

    try:
        data = request.get_json()
        message = data.get('message', '').strip()

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Check user subscription and credits
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            # Create free tier subscription for new user
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            if not free_tier:
                return jsonify({'error': 'Subscription system not initialized. Please contact support.'}), 500

            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=free_tier.id,
                credits_remaining=free_tier.monthly_credits
            )
            db.session.add(subscription)
            db.session.commit()

        # Check if credits need to be reset
        if subscription.should_reset_credits():
            subscription.reset_monthly_credits()

        # Check if user has credits
        if not subscription.has_credits():
            return jsonify({
                'error': 'insufficient_credits',
                'message': 'You have run out of credits. Please upgrade your plan or purchase more credits.',
                'credits_remaining': 0,
                'tier': subscription.tier.to_dict() if subscription.tier else None
            }), 402  # Payment Required

        # Deduct credit BEFORE processing
        if not subscription.use_credit():
            return jsonify({
                'error': 'insufficient_credits',
                'message': 'Failed to deduct credit. Please try again.',
                'credits_remaining': subscription.credits_remaining
            }), 402

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
            # Update conversation timestamp
            conversation = Conversation.query.get(conversation_id)
            if conversation:
                conversation.updated_at = datetime.utcnow()
                # Check if this is the first message (title still default)
                if conversation.title == 'New Chat':
                    is_first_message = True

        # Save user message
        user_message = ChatMessage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            role='user',
            content=message
        )
        db.session.add(user_message)

        # Get user preferences for personalized context
        prefs = UserPreferences.query.filter_by(user_id=current_user.id).first()
        preferences_context = None
        if prefs:
            preferences_context = prefs.get_context_for_prompt()

        # Process message with agent
        try:
            response = agent.process_message(message, user_preferences_context=preferences_context)
            success = True
            error_msg = None
        except Exception as agent_error:
            response = f"Error processing request: {str(agent_error)}"
            success = False
            error_msg = str(agent_error)

        # Log usage
        usage_log = UsageLog(
            user_id=current_user.id,
            conversation_id=conversation_id,
            action_type='agent_message',
            tool_name=None,
            credits_used=1,
            success=success,
            error_message=error_msg
        )
        db.session.add(usage_log)

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

        db.session.commit()

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
            'conversation_title': conversation.title if conversation else None
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


@app.route('/api/dashboard/sync', methods=['POST'])
@login_required
def sync_infrastructure():
    """Trigger infrastructure sync for current user."""
    try:
        from services.infrastructure_sync import sync_user_infrastructure
        result = sync_user_infrastructure(current_user.id)
        return jsonify({
            'success': True,
            'message': 'Infrastructure sync completed',
            'result': result
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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


@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get conversation statistics."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        stats = agent.get_conversation_summary()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/conversations', methods=['GET'])
@login_required
def get_conversations():
    """Get all conversations for the current user."""
    try:
        conversations = Conversation.query.filter_by(
            user_id=current_user.id
        ).order_by(Conversation.updated_at.desc()).all()

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

        # Get messages for this conversation
        messages = ChatMessage.query.filter_by(
            conversation_id=conversation_id
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

        # Delete all messages in this conversation
        ChatMessage.query.filter_by(
            conversation_id=conversation_id
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


# ===== SUBSCRIPTION & CREDITS API =====

@app.route('/api/subscription', methods=['GET'])
@login_required
def get_subscription():
    """Get current user's subscription details."""
    try:
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            # Return free tier info if no subscription
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            return jsonify({
                'subscription': None,
                'available_tiers': [t.to_dict() for t in SubscriptionTier.query.filter_by(is_active=True).all()],
                'suggested_tier': free_tier.to_dict() if free_tier else None
            })

        # Check if credits need reset
        if subscription.should_reset_credits():
            subscription.reset_monthly_credits()

        return jsonify({
            'subscription': subscription.to_dict(),
            'available_tiers': [t.to_dict() for t in SubscriptionTier.query.filter_by(is_active=True).all()]
        })

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error retrieving subscription: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/subscription/tiers', methods=['GET'])
def get_subscription_tiers():
    """Get all available subscription tiers (public endpoint)."""
    try:
        tiers = SubscriptionTier.query.filter_by(is_active=True).order_by(SubscriptionTier.monthly_price).all()
        return jsonify({
            'tiers': [tier.to_dict() for tier in tiers]
        })
    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error retrieving tiers: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/subscription/upgrade', methods=['POST'])
@login_required
def upgrade_subscription():
    """Upgrade user's subscription tier."""
    try:
        data = request.get_json()
        tier_id = data.get('tier_id')

        if not tier_id:
            return jsonify({'error': 'Tier ID is required'}), 400

        # Get the new tier
        new_tier = SubscriptionTier.query.get(tier_id)
        if not new_tier or not new_tier.is_active:
            return jsonify({'error': 'Invalid tier'}), 400

        # Get or create subscription
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            # Create new subscription
            from dateutil.relativedelta import relativedelta
            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=new_tier.id,
                credits_remaining=new_tier.monthly_credits,
                current_period_end=datetime.utcnow() + relativedelta(months=1)
            )
            db.session.add(subscription)
        else:
            # Upgrade existing subscription
            old_tier = subscription.tier

            # Update tier
            subscription.tier_id = new_tier.id

            # Add the difference in credits (upgrade bonus)
            credit_difference = new_tier.monthly_credits - old_tier.monthly_credits
            if credit_difference > 0:
                subscription.add_credits(credit_difference)

        db.session.commit()

        return jsonify({
            'success': True,
            'subscription': subscription.to_dict(),
            'message': f'Successfully upgraded to {new_tier.display_name}!'
        })

    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error upgrading subscription: {str(e)}", exc_info=True)
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


@app.route('/api/subscription/create-checkout', methods=['POST'])
@login_required
def create_subscription_checkout_session():
    """Create Stripe checkout session for subscription upgrade."""
    if not STRIPE_ENABLED:
        return jsonify({'error': 'Payment processing is not enabled'}), 503

    try:
        data = request.get_json()
        tier_name = data.get('tier_name')  # starter, professional, business

        if not tier_name:
            return jsonify({'error': 'Tier name is required'}), 400

        # Create checkout session
        result = create_subscription_checkout(current_user, tier_name)

        if result['success']:
            return jsonify({
                'success': True,
                'checkout_url': result['checkout_url'],
                'session_id': result['session_id']
            })
        else:
            return jsonify({'error': result.get('error', 'Failed to create checkout')}), 500

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error creating checkout: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/credits/purchase', methods=['POST'])
@login_required
def purchase_credits():
    """Purchase additional credit packs."""
    try:
        data = request.get_json()
        pack_size = data.get('pack_size', 100)  # Default 100 credits

        # Define credit pack pricing
        credit_packs = {
            100: 10.0,   # $10 for 100 credits
            250: 20.0,   # $20 for 250 credits
            500: 35.0,   # $35 for 500 credits
            1000: 60.0   # $60 for 1000 credits
        }

        if pack_size not in credit_packs:
            return jsonify({'error': 'Invalid pack size. Available: 100, 250, 500, 1000'}), 400

        price = credit_packs[pack_size]

        # For now, we'll create the purchase record (Stripe integration to be added)
        purchase = CreditPurchase(
            user_id=current_user.id,
            credits_amount=pack_size,
            price_paid=price,
            payment_status='completed',  # Would be 'pending' with real Stripe
            completed_at=datetime.utcnow()
        )
        db.session.add(purchase)

        # Add credits to user's account
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()
        if subscription:
            subscription.add_credits(pack_size)
        else:
            # Create subscription if doesn't exist
            free_tier = SubscriptionTier.query.filter_by(name='free').first()
            subscription = UserSubscription(
                user_id=current_user.id,
                tier_id=free_tier.id,
                credits_remaining=pack_size
            )
            db.session.add(subscription)

        db.session.commit()

        return jsonify({
            'success': True,
            'purchase': purchase.to_dict(),
            'credits_remaining': subscription.credits_remaining,
            'message': f'Successfully purchased {pack_size} credits for ${price}!'
        })

    except Exception as e:
        db.session.rollback()
        logger = get_logger(__name__)
        logger.error(f"Error purchasing credits: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/credits/create-checkout', methods=['POST'])
@login_required
def create_credits_checkout_session():
    """Create Stripe checkout session for credit pack purchase."""
    if not STRIPE_ENABLED:
        return jsonify({'error': 'Payment processing is not enabled'}), 503

    try:
        data = request.get_json()
        pack_size = data.get('pack_size', 100)

        if pack_size not in [100, 250, 500, 1000]:
            return jsonify({'error': 'Invalid pack size'}), 400

        # Create checkout session
        result = create_credit_pack_checkout(current_user, pack_size)

        if result['success']:
            return jsonify({
                'success': True,
                'checkout_url': result['checkout_url'],
                'session_id': result['session_id']
            })
        else:
            return jsonify({'error': result.get('error', 'Failed to create checkout')}), 500

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error creating checkout: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/credits/packs', methods=['GET'])
def get_credit_packs():
    """Get available credit pack options (public endpoint)."""
    credit_packs = [
        {'credits': 100, 'price': 10.0, 'price_per_credit': 0.10, 'popular': False},
        {'credits': 250, 'price': 20.0, 'price_per_credit': 0.08, 'popular': True},
        {'credits': 500, 'price': 35.0, 'price_per_credit': 0.07, 'popular': False},
        {'credits': 1000, 'price': 60.0, 'price_per_credit': 0.06, 'popular': False}
    ]
    return jsonify({'packs': credit_packs})


@app.route('/api/usage/history', methods=['GET'])
@login_required
def get_usage_history():
    """Get user's credit usage history."""
    try:
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        # Query usage logs
        logs = UsageLog.query.filter_by(
            user_id=current_user.id
        ).order_by(
            UsageLog.created_at.desc()
        ).limit(limit).offset(offset).all()

        total_count = UsageLog.query.filter_by(user_id=current_user.id).count()

        return jsonify({
            'logs': [log.to_dict() for log in logs],
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        })

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error retrieving usage history: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/usage/stats', methods=['GET'])
@login_required
def get_usage_stats():
    """Get usage statistics for current user."""
    try:
        subscription = UserSubscription.query.filter_by(user_id=current_user.id).first()

        if not subscription:
            return jsonify({
                'credits_remaining': 0,
                'credits_used_this_month': 0,
                'total_credits_used': 0,
                'tier': None
            })

        # Get this month's usage breakdown
        from sqlalchemy import func
        from datetime import timedelta

        month_start = subscription.current_period_start or (datetime.utcnow() - timedelta(days=30))

        tool_usage = db.session.query(
            UsageLog.tool_name,
            func.count(UsageLog.id).label('count')
        ).filter(
            UsageLog.user_id == current_user.id,
            UsageLog.created_at >= month_start
        ).group_by(UsageLog.tool_name).all()

        return jsonify({
            'credits_remaining': subscription.credits_remaining,
            'credits_used_this_month': subscription.credits_used_this_month,
            'total_credits_used': subscription.total_credits_used,
            'tier': subscription.tier.to_dict() if subscription.tier else None,
            'current_period_start': subscription.current_period_start.isoformat() if subscription.current_period_start else None,
            'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None,
            'tool_usage_breakdown': [{'tool': tool or 'agent_message', 'count': count} for tool, count in tool_usage]
        })

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error retrieving usage stats: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events."""
    if not STRIPE_ENABLED:
        return jsonify({'error': 'Stripe not enabled'}), 503

    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = StripePaymentService.construct_webhook_event(payload, sig_header)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    logger = get_logger(__name__)
    logger.info(f"Received Stripe webhook: {event['type']}")

    # Handle different event types
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_completed(session)

    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        handle_invoice_payment_succeeded(invoice)

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        handle_subscription_deleted(subscription)

    return jsonify({'success': True})


def handle_checkout_completed(session):
    """Handle successful checkout session."""
    logger = get_logger(__name__)

    try:
        customer_email = session.get('customer_email')
        metadata = session.get('metadata', {})
        product_type = metadata.get('product_type')

        # Find user by email
        user = User.query.filter_by(email=customer_email).first()
        if not user:
            logger.error(f"User not found for email: {customer_email}")
            return

        if product_type == 'subscription':
            # Handle subscription purchase
            tier_name = metadata.get('tier_name')
            tier = SubscriptionTier.query.filter_by(name=tier_name).first()

            if tier:
                subscription = UserSubscription.query.filter_by(user_id=user.id).first()
                if subscription:
                    subscription.tier_id = tier.id
                    subscription.stripe_subscription_id = session.get('subscription')
                    subscription.payment_status = 'active'
                    subscription.add_credits(tier.monthly_credits - subscription.tier.monthly_credits)
                else:
                    from dateutil.relativedelta import relativedelta
                    subscription = UserSubscription(
                        user_id=user.id,
                        tier_id=tier.id,
                        credits_remaining=tier.monthly_credits,
                        stripe_subscription_id=session.get('subscription'),
                        payment_status='active',
                        current_period_end=datetime.utcnow() + relativedelta(months=1)
                    )
                    db.session.add(subscription)

                db.session.commit()
                logger.info(f"Subscription created/updated for user {user.id}")

        elif product_type == 'credit_pack':
            # Handle credit pack purchase
            pack_size = int(metadata.get('pack_size', 0))
            amount_paid = session.get('amount_total', 0) / 100  # Convert from cents

            # Create purchase record
            purchase = CreditPurchase(
                user_id=user.id,
                credits_amount=pack_size,
                price_paid=amount_paid,
                stripe_payment_intent_id=session.get('payment_intent'),
                payment_status='completed',
                completed_at=datetime.utcnow()
            )
            db.session.add(purchase)

            # Add credits to user
            subscription = UserSubscription.query.filter_by(user_id=user.id).first()
            if subscription:
                subscription.add_credits(pack_size)
            else:
                # Create subscription if doesn't exist
                free_tier = SubscriptionTier.query.filter_by(name='free').first()
                subscription = UserSubscription(
                    user_id=user.id,
                    tier_id=free_tier.id if free_tier else 1,
                    credits_remaining=pack_size
                )
                db.session.add(subscription)

            db.session.commit()
            logger.info(f"Credit pack ({pack_size}) purchased for user {user.id}")

    except Exception as e:
        logger.error(f"Error handling checkout: {str(e)}", exc_info=True)
        db.session.rollback()


def handle_invoice_payment_succeeded(invoice):
    """Handle successful subscription invoice payment."""
    logger = get_logger(__name__)
    logger.info(f"Invoice payment succeeded: {invoice.get('id')}")
    # Additional logic for recurring payments can be added here


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation."""
    logger = get_logger(__name__)

    try:
        stripe_sub_id = subscription.get('id')
        user_subscription = UserSubscription.query.filter_by(
            stripe_subscription_id=stripe_sub_id
        ).first()

        if user_subscription:
            user_subscription.payment_status = 'cancelled'
            db.session.commit()
            logger.info(f"Subscription cancelled for user {user_subscription.user_id}")

    except Exception as e:
        logger.error(f"Error handling subscription deletion: {str(e)}", exc_info=True)
        db.session.rollback()


@app.route('/billing/success')
@login_required
def billing_success():
    """Success page after Stripe checkout."""
    session_id = request.args.get('session_id')

    if session_id and STRIPE_ENABLED:
        result = StripePaymentService.retrieve_session(session_id)
        if result['success']:
            session = result['session']
            # You can display session details here
            pass

    return redirect(url_for('billing') + '?success=true')


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'agent_initialized': agent is not None,
        'api_key_configured': check_api_key_configured(),
        'timestamp': datetime.now().isoformat()
    })


@app.route('/init-database-secret-endpoint-12345', methods=['GET'])
def init_database():
    """Initialize database tables (one-time setup for production)."""
    try:
        db.create_all()

        # Also initialize subscription tiers if they don't exist
        from models import SubscriptionTier

        if SubscriptionTier.query.count() == 0:
            # Create default subscription tiers
            free_tier = SubscriptionTier(
                name='free',
                display_name='Free',
                monthly_credits=10,
                monthly_price=0.0,
                features={'basic_chat': True},
                is_active=True
            )

            starter_tier = SubscriptionTier(
                name='starter',
                display_name='Starter',
                monthly_credits=100,
                monthly_price=9.99,
                features={'basic_chat': True, 'aws_tools': True},
                is_active=True
            )

            pro_tier = SubscriptionTier(
                name='professional',
                display_name='Professional',
                monthly_credits=500,
                monthly_price=29.99,
                features={'basic_chat': True, 'aws_tools': True, 'gcp_tools': True, 'k8s_tools': True},
                is_active=True
            )

            business_tier = SubscriptionTier(
                name='business',
                display_name='Business',
                monthly_credits=2000,
                monthly_price=99.99,
                features={'basic_chat': True, 'aws_tools': True, 'gcp_tools': True, 'k8s_tools': True, 'priority_support': True},
                is_active=True
            )

            db.session.add_all([free_tier, starter_tier, pro_tier, business_tier])
            db.session.commit()

            return jsonify({
                'success': True,
                'message': 'Database initialized successfully with subscription tiers!',
                'tables_created': True,
                'tiers_created': 4
            })

        return jsonify({
            'success': True,
            'message': 'Database tables initialized!',
            'tables_created': True,
            'tiers_already_exist': True
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
        print("\nDatabase initialized")

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

    # In production, debug should be False
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug_mode, use_reloader=False)
