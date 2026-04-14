"""
Database models for user authentication
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import bcrypt

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for authentication"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Profile settings
    avatar_color = db.Column(db.String(7), default='#cd7c48')  # Hex color for avatar
    bio = db.Column(db.Text)

    # Preferences
    theme = db.Column(db.String(20), default='light')
    language = db.Column(db.String(10), default='en')  # Language preference (en, es, fr, de, zh, ja, etc.)

    # Security fields
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)  # IPv6 support

    # Role-based access control
    role = db.Column(db.String(20), default='user')  # user, admin, approver, viewer

    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(100), nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)

    # Password reset
    password_reset_token = db.Column(db.String(100), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)

    # MFA reset
    mfa_reset_token = db.Column(db.String(100), nullable=True)
    mfa_reset_expires = db.Column(db.DateTime, nullable=True)

    # Guardrail violation tracking
    guardrail_violations = db.Column(db.Integer, default=0)
    guardrail_blocked_until = db.Column(db.DateTime, nullable=True)

    # Two-Factor Authentication
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_secret = db.Column(db.String(32), nullable=True)
    backup_codes = db.Column(db.JSON, nullable=True)  # List of hashed backup codes
    two_factor_verified_at = db.Column(db.DateTime, nullable=True)
    two_factor_attempts = db.Column(db.Integer, default=0)
    two_factor_locked_until = db.Column(db.DateTime, nullable=True)

    # Multi-method MFA
    mfa_method = db.Column(db.String(10), default='none')  # 'none'|'email'|'sms'|'totp'
    phone_number = db.Column(db.String(20), nullable=True)  # E.164: +1234567890
    phone_verified = db.Column(db.Boolean, default=False)
    mfa_otp_hash = db.Column(db.String(64), nullable=True)  # SHA-256 of 6-digit code
    mfa_otp_expires = db.Column(db.DateTime, nullable=True)
    mfa_otp_sent_at = db.Column(db.DateTime, nullable=True)  # Rate-limit resends

    # Onboarding
    onboarding_completed = db.Column(db.Boolean, default=False)
    onboarding_step = db.Column(db.Integer, default=0)

    # Email preferences
    email_opt_out = db.Column(db.Boolean, default=False)

    # API Key Management
    api_keys = db.relationship('APIKey', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        """Hash and set user password"""
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def get_avatar_initials(self):
        """Get user initials for avatar"""
        if self.full_name:
            parts = self.full_name.split()
            if len(parts) >= 2:
                return f"{parts[0][0]}{parts[1][0]}".upper()
            return parts[0][0].upper()
        return self.username[0].upper()

    def update_last_login(self, ip_address=None):
        """Update last login timestamp and reset failed attempts"""
        self.last_login = datetime.utcnow()
        self.failed_login_attempts = 0
        self.locked_until = None
        if ip_address:
            self.last_login_ip = ip_address
        db.session.commit()

    def is_locked(self):
        """Check if account is locked"""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        # Auto-unlock if lock period has expired
        if self.locked_until and self.locked_until <= datetime.utcnow():
            self.locked_until = None
            self.failed_login_attempts = 0
            db.session.commit()
        return False

    def record_failed_login(self):
        """Record a failed login attempt and lock account if needed"""
        self.failed_login_attempts += 1
        # Lock account for 15 minutes after 5 failed attempts
        if self.failed_login_attempts >= 5:
            from datetime import timedelta
            self.locked_until = datetime.utcnow() + timedelta(minutes=15)
        db.session.commit()

    def record_guardrail_violation(self):
        """Record a guardrail policy violation with escalating block durations.

        Escalation schedule (cumulative violations):
          3  → 1 hour block
          5  → 24 hour block
          8  → 7 day block
          10+ → 30 day block (requires manual review to lift)
        """
        from datetime import timedelta
        self.guardrail_violations = (self.guardrail_violations or 0) + 1
        v = self.guardrail_violations
        if v >= 10:
            self.guardrail_blocked_until = datetime.utcnow() + timedelta(days=30)
        elif v >= 8:
            self.guardrail_blocked_until = datetime.utcnow() + timedelta(days=7)
        elif v >= 5:
            self.guardrail_blocked_until = datetime.utcnow() + timedelta(hours=24)
        elif v >= 3:
            self.guardrail_blocked_until = datetime.utcnow() + timedelta(hours=1)

    def is_guardrail_blocked(self) -> bool:
        """Check if the user is currently blocked due to guardrail violations."""
        if self.guardrail_blocked_until and self.guardrail_blocked_until > datetime.utcnow():
            return True
        if self.guardrail_blocked_until and self.guardrail_blocked_until <= datetime.utcnow():
            # Block period served — clear the timer but keep the violation count
            # so escalation continues if they re-offend.
            self.guardrail_blocked_until = None
            db.session.commit()
        return False

    # --- MFA helper methods ---

    def has_mfa_enabled(self):
        """Check if any MFA method is active (email, sms, or totp)."""
        return (self.mfa_method or 'none') not in ('none', '')

    def set_mfa_otp(self, code):
        """Hash and store a 6-digit OTP with 10-minute expiry."""
        import hashlib
        from datetime import timedelta
        self.mfa_otp_hash = hashlib.sha256(code.encode()).hexdigest()
        self.mfa_otp_expires = datetime.utcnow() + timedelta(minutes=10)
        self.mfa_otp_sent_at = datetime.utcnow()

    def verify_mfa_otp(self, code):
        """Verify a 6-digit OTP against stored hash. Returns True if valid."""
        import hashlib
        if not self.mfa_otp_hash or not self.mfa_otp_expires:
            return False
        if datetime.utcnow() > self.mfa_otp_expires:
            return False
        return hashlib.sha256(code.encode()).hexdigest() == self.mfa_otp_hash

    def clear_mfa_otp(self):
        """Clear OTP after successful verification or expiry."""
        self.mfa_otp_hash = None
        self.mfa_otp_expires = None
        self.mfa_otp_sent_at = None

    def can_resend_otp(self):
        """Check if 60-second cooldown has passed since last OTP send."""
        from datetime import timedelta
        if not self.mfa_otp_sent_at:
            return True
        return datetime.utcnow() > self.mfa_otp_sent_at + timedelta(seconds=60)

    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'full_name': self.full_name,
            'avatar_color': self.avatar_color,
            'bio': self.bio,
            'theme': self.theme,
            'language': self.language,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

    def __repr__(self):
        return f'<User {self.username}>'


class Conversation(db.Model):
    """Conversation model for storing conversation metadata"""
    __tablename__ = 'conversations'

    id = db.Column(db.String(50), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), default='New Chat')
    preview = db.Column(db.String(200), default='New Chat')
    is_streaming = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # Relationship
    user = db.relationship('User', backref=db.backref('conversations', lazy='dynamic'))

    def to_dict(self):
        """Convert conversation to dictionary — no extra queries."""
        return {
            'id': self.id,
            'title': self.title,
            'preview': self.preview or 'New Chat',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<Conversation {self.id}>'


class ChatMessage(db.Model):
    """Chat message model for storing conversation history"""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.String(50), db.ForeignKey('conversations.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    tool_trace = db.Column(db.JSON, nullable=True)   # [{tool, success, duration_ms}]
    page_context = db.Column(db.String(100), nullable=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('messages', lazy='dynamic'))
    conversation = db.relationship('Conversation', backref=db.backref('messages', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_chatmsg_conv_user_role', 'conversation_id', 'user_id', 'role'),
        db.Index('idx_chatmsg_conv_ts', 'conversation_id', 'timestamp'),
    )

    def to_dict(self):
        """Convert message to dictionary"""
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

    def __repr__(self):
        return f'<ChatMessage {self.id} from {self.user_id}>'


class UserPreferences(db.Model):
    """User preferences for personalized DevOps agent experience"""
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)

    # Cloud Preferences - AWS
    aws_default_region = db.Column(db.String(20), default='us-east-1')
    aws_default_instance_type = db.Column(db.String(20), default='t2.micro')
    aws_default_key_pair = db.Column(db.String(100))

    # Cloud Preferences - Azure
    azure_default_region = db.Column(db.String(20), default='eastus')
    azure_default_vm_size = db.Column(db.String(20), default='Standard_B1s')

    # Cloud Preferences - GCP
    gcp_default_region = db.Column(db.String(20), default='us-central1')
    gcp_default_zone = db.Column(db.String(20), default='us-central1-a')
    gcp_default_machine_type = db.Column(db.String(20), default='e2-micro')

    # Kubernetes Preferences
    k8s_default_namespace = db.Column(db.String(50), default='default')
    k8s_default_replicas = db.Column(db.Integer, default=3)

    # General Preferences
    preferred_cloud_provider = db.Column(db.String(20), default='aws')  # aws, azure, gcp
    preferred_model_provider = db.Column(db.String(20), default=None, nullable=True)  # None=tier default, 'anthropic', 'kimi'
    enable_cost_warnings = db.Column(db.Boolean, default=True)
    enable_suggestions = db.Column(db.Boolean, default=True)
    verbose_mode = db.Column(db.Boolean, default=False)

    # Learning Mode
    learning_mode = db.Column(db.Boolean, default=False)
    sandbox_mode = db.Column(db.Boolean, default=False)

    # Currency preference
    preferred_currency = db.Column(db.String(3), nullable=True)  # None=auto-detect, 'USD', 'NGN'
    learning_level = db.Column(db.JSON, default=lambda: {})  # {"aws": 30, "kubernetes": 10, ...}

    # Favorite Commands (JSON array)
    favorite_commands = db.Column(db.JSON, default=lambda: [])

    # Custom Shortcuts (JSON object: shortcut -> command)
    custom_shortcuts = db.Column(db.JSON, default=lambda: {})

    # Recently Used (JSON array)
    recent_operations = db.Column(db.JSON, default=lambda: [])

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('preferences', uselist=False))

    def to_dict(self):
        """Convert preferences to dictionary"""
        return {
            'aws_default_region': self.aws_default_region,
            'aws_default_instance_type': self.aws_default_instance_type,
            'aws_default_key_pair': self.aws_default_key_pair,
            'azure_default_region': self.azure_default_region,
            'azure_default_vm_size': self.azure_default_vm_size,
            'gcp_default_region': self.gcp_default_region,
            'gcp_default_zone': self.gcp_default_zone,
            'gcp_default_machine_type': self.gcp_default_machine_type,
            'k8s_default_namespace': self.k8s_default_namespace,
            'k8s_default_replicas': self.k8s_default_replicas,
            'preferred_cloud_provider': self.preferred_cloud_provider,
            'preferred_model_provider': self.preferred_model_provider,
            'enable_cost_warnings': self.enable_cost_warnings,
            'enable_suggestions': self.enable_suggestions,
            'verbose_mode': self.verbose_mode,
            'learning_mode': self.learning_mode or False,
            'sandbox_mode': self.sandbox_mode or False,
            'preferred_currency': self.preferred_currency,
            'learning_level': self.learning_level or {},
            'favorite_commands': self.favorite_commands or [],
            'custom_shortcuts': self.custom_shortcuts or {},
            'recent_operations': self.recent_operations or []
        }

    def add_recent_operation(self, operation):
        """Add operation to recent operations (keep last 20)"""
        if not self.recent_operations:
            self.recent_operations = []

        # Remove duplicates
        if operation in self.recent_operations:
            self.recent_operations.remove(operation)

        # Add to beginning
        self.recent_operations.insert(0, operation)

        # Keep only last 20
        self.recent_operations = self.recent_operations[:20]

        db.session.commit()

    def add_favorite_command(self, command):
        """Add command to favorites"""
        if not self.favorite_commands:
            self.favorite_commands = []

        if command not in self.favorite_commands:
            self.favorite_commands.append(command)
            db.session.commit()

    def remove_favorite_command(self, command):
        """Remove command from favorites"""
        if self.favorite_commands and command in self.favorite_commands:
            self.favorite_commands.remove(command)
            db.session.commit()

    def add_shortcut(self, shortcut, command):
        """Add custom shortcut"""
        if not self.custom_shortcuts:
            self.custom_shortcuts = {}

        self.custom_shortcuts[shortcut] = command
        db.session.commit()

    def remove_shortcut(self, shortcut):
        """Remove custom shortcut"""
        if self.custom_shortcuts and shortcut in self.custom_shortcuts:
            del self.custom_shortcuts[shortcut]
            db.session.commit()

    def get_context_for_prompt(self):
        """Generate context string for Claude API prompt"""
        context = []

        context.append(f"User's preferred cloud provider: {self.preferred_cloud_provider.upper()}")

        if self.preferred_cloud_provider == 'aws':
            context.append(f"Default AWS region: {self.aws_default_region}")
            context.append(f"Default instance type: {self.aws_default_instance_type}")
        elif self.preferred_cloud_provider == 'azure':
            context.append(f"Default Azure region: {self.azure_default_region}")
            context.append(f"Default VM size: {self.azure_default_vm_size}")
        elif self.preferred_cloud_provider == 'gcp':
            context.append(f"Default GCP region: {self.gcp_default_region}")
            context.append(f"Default machine type: {self.gcp_default_machine_type}")

        if self.k8s_default_namespace != 'default':
            context.append(f"Default Kubernetes namespace: {self.k8s_default_namespace}")

        if self.favorite_commands:
            context.append(f"Frequently used commands: {', '.join(self.favorite_commands[:5])}")

        if self.recent_operations:
            context.append(f"Recent operations: {', '.join(self.recent_operations[:3])}")

        if self.enable_suggestions:
            context.append("User appreciates proactive suggestions")

        if self.verbose_mode:
            context.append("User prefers detailed explanations")

        if self.learning_mode:
            levels = self.learning_level or {}
            level_str = ', '.join(f'{k}: {v}/100' for k, v in levels.items()) if levels else 'all beginner'
            context.append(f"LEARNING MODE ACTIVE. Proficiency levels: {level_str}")
            if self.sandbox_mode:
                context.append("SANDBOX MODE ACTIVE. All tool executions are simulated.")

        return "\n".join(context)

    def __repr__(self):
        return f'<UserPreferences for user {self.user_id}>'


class CommandTemplate(db.Model):
    """Command templates for quick access to common operations"""
    __tablename__ = 'command_templates'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    command = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50))  # aws, azure, gcp, kubernetes, docker, etc.
    is_public = db.Column(db.Boolean, default=False)  # Share with all users
    use_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('templates', lazy='dynamic'))

    def to_dict(self):
        """Convert template to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'command': self.command,
            'category': self.category,
            'is_public': self.is_public,
            'use_count': self.use_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def increment_use_count(self):
        """Increment the use count"""
        self.use_count += 1
        db.session.commit()

    def __repr__(self):
        return f'<CommandTemplate {self.name}>'


class ResponseFeedback(db.Model):
    """Feedback/ratings for agent responses"""
    __tablename__ = 'response_feedback'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_messages.id'), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    feedback_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('feedback', lazy='dynamic'))
    message = db.relationship('ChatMessage', backref=db.backref('feedback', uselist=False))

    def to_dict(self):
        """Convert feedback to dictionary"""
        return {
            'id': self.id,
            'message_id': self.message_id,
            'rating': self.rating,
            'feedback_text': self.feedback_text,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<ResponseFeedback {self.id} - {self.rating} stars>'


class SubscriptionTier(db.Model):
    """Subscription tier/plan definitions"""
    __tablename__ = 'subscription_tiers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)  # free, starter, professional, business
    display_name = db.Column(db.String(100), nullable=False)
    monthly_price = db.Column(db.Float, default=0.0)  # Price in USD
    monthly_credits = db.Column(db.Integer, nullable=False)  # Credits per month
    description = db.Column(db.Text)
    features = db.Column(db.JSON, default=lambda: [])  # List of feature descriptions
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Feature limits
    max_cloud_accounts = db.Column(db.Integer, default=1)
    max_resources = db.Column(db.Integer, default=50)
    max_team_members = db.Column(db.Integer, default=1)
    sync_interval_minutes = db.Column(db.Integer, default=0)  # 0 = manual only
    compliance_frameworks = db.Column(db.JSON, default=lambda: [])
    has_pdf_export = db.Column(db.Boolean, default=False)
    has_auto_remediation = db.Column(db.Boolean, default=False)
    has_sso = db.Column(db.Boolean, default=False)
    has_audit_export = db.Column(db.Boolean, default=False)

    def to_dict(self):
        """Convert tier to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'monthly_price': self.monthly_price,
            'monthly_credits': self.monthly_credits,
            'description': self.description,
            'features': self.features or [],
            'is_active': self.is_active,
            'max_cloud_accounts': self.max_cloud_accounts or 1,
            'max_resources': self.max_resources or 50,
            'max_team_members': self.max_team_members or 1,
            'sync_interval_minutes': self.sync_interval_minutes or 0,
            'compliance_frameworks': self.compliance_frameworks or [],
            'has_pdf_export': self.has_pdf_export or False,
            'has_auto_remediation': self.has_auto_remediation or False,
            'has_sso': self.has_sso or False,
            'has_audit_export': self.has_audit_export or False,
        }

    def __repr__(self):
        return f'<SubscriptionTier {self.display_name}>'


class UserSubscription(db.Model):
    """User subscription and credits tracking"""
    __tablename__ = 'user_subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)
    tier_id = db.Column(db.Integer, db.ForeignKey('subscription_tiers.id'), nullable=False)

    # Credits tracking
    credits_remaining = db.Column(db.Integer, default=0)
    credits_used_this_month = db.Column(db.Integer, default=0)
    total_credits_used = db.Column(db.Integer, default=0)

    # Subscription dates
    subscription_start_date = db.Column(db.DateTime, default=datetime.utcnow)
    current_period_start = db.Column(db.DateTime, default=datetime.utcnow)
    current_period_end = db.Column(db.DateTime, nullable=True)
    last_reset_date = db.Column(db.DateTime, default=datetime.utcnow)

    # Payment information
    stripe_customer_id = db.Column(db.String(100), unique=True, index=True)
    stripe_subscription_id = db.Column(db.String(100), unique=True, index=True)
    payment_status = db.Column(db.String(20), default='active')  # active, cancelled, past_due, unpaid
    payment_failed_at = db.Column(db.DateTime, nullable=True)

    # Payment gateway
    payment_gateway = db.Column(db.String(20), nullable=True)  # stripe

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('subscription', uselist=False))
    tier = db.relationship('SubscriptionTier', backref=db.backref('subscriptions', lazy='dynamic'))

    def has_credits(self) -> bool:
        """Check if user has available credits"""
        return self.credits_remaining > 0

    def repair_if_never_used(self) -> bool:
        """
        Detect and fix a bad initialization: credits_remaining=0 but total_credits_used=0
        means the subscription was created with 0 credits (e.g. free tier had monthly_credits=0
        at the time of signup). Gives the user their proper trial credits.
        Returns True if a repair was made.
        """
        if self.credits_remaining > 0 or (self.total_credits_used or 0) > 0:
            return False
        monthly = self.tier.monthly_credits if self.tier else 0
        if monthly <= 0:
            return False
        self.credits_remaining = monthly
        db.session.commit()
        return True

    def use_credit(self, commit: bool = True) -> bool:
        """
        Deduct one credit from user's account.

        Args:
            commit: If True (default), commits immediately. Pass False to let
                    the caller commit as part of a larger transaction.

        Returns:
            bool: True if credit was deducted, False if no credits available
        """
        if self.credits_remaining <= 0:
            return False

        self.credits_remaining -= 1
        self.credits_used_this_month += 1
        self.total_credits_used += 1
        if commit:
            db.session.commit()
        return True

    def add_credits(self, amount: int):
        """Add credits to user's account"""
        self.credits_remaining += amount
        db.session.commit()

    def reset_monthly_credits(self):
        """Reset credits at the start of a new billing period"""
        from dateutil.relativedelta import relativedelta

        # Get monthly credits from tier
        monthly_credits = self.tier.monthly_credits

        # Reset credits
        self.credits_remaining = monthly_credits
        self.credits_used_this_month = 0
        self.last_reset_date = datetime.utcnow()

        # Update period dates
        self.current_period_start = datetime.utcnow()
        self.current_period_end = datetime.utcnow() + relativedelta(months=1)

        db.session.commit()

    def should_reset_credits(self) -> bool:
        """Check if it's time to reset monthly credits"""
        if not self.current_period_end:
            return True
        return datetime.utcnow() >= self.current_period_end

    def to_dict(self):
        """Convert subscription to dictionary"""
        return {
            'id': self.id,
            'tier': self.tier.to_dict() if self.tier else None,
            'credits_remaining': self.credits_remaining,
            'credits_used_this_month': self.credits_used_this_month,
            'total_credits_used': self.total_credits_used,
            'subscription_start_date': self.subscription_start_date.isoformat() if self.subscription_start_date else None,
            'current_period_start': self.current_period_start.isoformat() if self.current_period_start else None,
            'current_period_end': self.current_period_end.isoformat() if self.current_period_end else None,
            'last_reset_date': self.last_reset_date.isoformat() if self.last_reset_date else None,
            'payment_status': self.payment_status
        }

    def __repr__(self):
        return f'<UserSubscription user={self.user_id} tier={self.tier.name if self.tier else "none"}>'


class CreditPurchase(db.Model):
    """Record of credit pack purchases"""
    __tablename__ = 'credit_purchases'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Purchase details
    credits_amount = db.Column(db.Integer, nullable=False)
    price_paid = db.Column(db.Float, nullable=False)  # Amount in USD

    # Payment information
    stripe_payment_intent_id = db.Column(db.String(100), unique=True, index=True)
    payment_status = db.Column(db.String(20), default='pending')  # pending, completed, failed, refunded

    # Payment gateway
    payment_gateway = db.Column(db.String(20), nullable=True)  # stripe
    currency = db.Column(db.String(3), nullable=True)  # USD, NGN
    price_paid_ngn = db.Column(db.Integer, nullable=True)  # Amount in whole naira
    gateway_reference = db.Column(db.String(100), nullable=True)  # Stripe reference

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    # Relationship
    user = db.relationship('User', backref=db.backref('credit_purchases', lazy='dynamic'))

    def to_dict(self):
        """Convert purchase to dictionary"""
        return {
            'id': self.id,
            'credits_amount': self.credits_amount,
            'price_paid': self.price_paid,
            'payment_status': self.payment_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }

    def __repr__(self):
        return f'<CreditPurchase {self.credits_amount} credits for ${self.price_paid}>'


class UsageLog(db.Model):
    """Log of credit usage for analytics"""
    __tablename__ = 'usage_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.String(50), db.ForeignKey('conversations.id'), index=True)

    # Action details
    action_type = db.Column(db.String(50), nullable=False)  # tool_use, message, etc.
    tool_name = db.Column(db.String(100))  # Specific tool used if applicable
    credits_used = db.Column(db.Integer, default=1)
    ai_model = db.Column(db.String(100))  # Model used for this request (e.g. claude-sonnet-4-5, llama-3.3-70b)

    # Success tracking
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('usage_logs', lazy='dynamic'))
    conversation = db.relationship('Conversation', backref=db.backref('usage_logs', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_usage_user_created', 'user_id', 'created_at'),
        db.Index('idx_usage_user_tool', 'user_id', 'tool_name'),
    )

    def to_dict(self):
        """Convert usage log to dictionary"""
        return {
            'id': self.id,
            'action_type': self.action_type,
            'tool_name': self.tool_name,
            'credits_used': self.credits_used,
            'ai_model': self.ai_model,
            'success': self.success,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<UsageLog user={self.user_id} action={self.action_type}>'


class ConversionEvent(db.Model):
    """Track key funnel events for conversion analytics."""
    __tablename__ = 'conversion_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    # event_type values: trial_start, first_tool_use, credit_exhaustion,
    #                    upgrade_cta_shown, upgrade_completed, api_key_created
    event_metadata = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.Index('idx_conversion_user_event', 'user_id', 'event_type'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'event_type': self.event_type,
            'metadata': self.event_metadata or {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class InfrastructureResource(db.Model):
    """Track user's infrastructure resources across cloud providers"""
    __tablename__ = 'infrastructure_resources'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Resource identification
    cloud_provider = db.Column(db.String(20), nullable=False, index=True)  # aws, gcp, azure
    resource_type = db.Column(db.String(50), nullable=False, index=True)  # ec2, rds, gce, etc
    resource_id = db.Column(db.String(200), nullable=False, index=True)  # Cloud-specific ID
    resource_name = db.Column(db.String(200))
    region = db.Column(db.String(50))

    # Resource state
    status = db.Column(db.String(20))  # running, stopped, terminated, etc
    monthly_cost = db.Column(db.Float, default=0.0)

    # Additional details (JSON for flexibility)
    resource_metadata = db.Column(db.JSON)  # instance_type, tags, IP addresses, etc

    # Tracking
    last_synced = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('infrastructure_resources', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_infra_user_type', 'user_id', 'resource_type'),
        db.Index('idx_infra_user_provider', 'user_id', 'cloud_provider'),
        db.Index('idx_infra_user_created', 'user_id', 'created_at'),
    )

    def to_dict(self):
        """Convert resource to dictionary"""
        return {
            'id': self.id,
            'cloud_provider': self.cloud_provider,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'resource_name': self.resource_name,
            'region': self.region,
            'status': self.status,
            'monthly_cost': self.monthly_cost,
            'metadata': self.resource_metadata or {},
            'last_synced': self.last_synced.isoformat() if self.last_synced else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<InfrastructureResource {self.cloud_provider}:{self.resource_type}:{self.resource_name}>'


class CostOptimization(db.Model):
    """Track cost optimization recommendations"""
    __tablename__ = 'cost_optimizations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('infrastructure_resources.id'))

    # Recommendation details
    recommendation_type = db.Column(db.String(50), nullable=False)  # idle_resource, rightsizing, reserved_instance, etc
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    potential_monthly_savings = db.Column(db.Float, default=0.0)

    # Status tracking
    status = db.Column(db.String(20), default='pending', index=True)  # pending, applied, dismissed
    applied_at = db.Column(db.DateTime)
    dismissed_at = db.Column(db.DateTime)

    # Action details (what to do to apply this optimization)
    action_data = db.Column(db.JSON)  # Parameters needed to apply the optimization

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('cost_optimizations', lazy='dynamic'))
    resource = db.relationship('InfrastructureResource', backref=db.backref('optimizations', lazy='dynamic'))

    def to_dict(self):
        """Convert optimization to dictionary"""
        return {
            'id': self.id,
            'resource_id': self.resource_id,
            'recommendation_type': self.recommendation_type,
            'title': self.title,
            'description': self.description,
            'potential_monthly_savings': self.potential_monthly_savings,
            'status': self.status,
            'applied_at': self.applied_at.isoformat() if self.applied_at else None,
            'dismissed_at': self.dismissed_at.isoformat() if self.dismissed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<CostOptimization {self.recommendation_type}: ${self.potential_monthly_savings}/mo>'


class InfrastructureChange(db.Model):
    """Track infrastructure changes for audit trail and approval workflows"""
    __tablename__ = 'infrastructure_changes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Change details
    action_type = db.Column(db.String(50), nullable=False)  # create, update, delete, start, stop, terminate
    resource_type = db.Column(db.String(50), nullable=False)  # ec2, rds, security_group, etc
    resource_id = db.Column(db.String(200))  # Cloud-specific resource ID
    resource_name = db.Column(db.String(200))
    cloud_provider = db.Column(db.String(20))  # aws, gcp, azure

    # Change description
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    change_details = db.Column(db.JSON)  # Before/after state, parameters, etc

    # Approval workflow
    status = db.Column(db.String(20), default='pending', index=True)  # pending, approved, rejected, executed, failed
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approval_comment = db.Column(db.Text)

    # Execution tracking
    executed_at = db.Column(db.DateTime)
    execution_result = db.Column(db.JSON)  # Result data, error messages, etc
    rollback_data = db.Column(db.JSON)  # Data needed to rollback the change

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    approved_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('initiated_changes', lazy='dynamic'))
    approver = db.relationship('User', foreign_keys=[approver_id], backref=db.backref('approved_changes', lazy='dynamic'))

    def to_dict(self):
        """Convert change to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action_type': self.action_type,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'resource_name': self.resource_name,
            'cloud_provider': self.cloud_provider,
            'title': self.title,
            'description': self.description,
            'change_details': self.change_details or {},
            'status': self.status,
            'approver_id': self.approver_id,
            'approval_comment': self.approval_comment,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None
        }

    def __repr__(self):
        return f'<InfrastructureChange {self.action_type} {self.resource_type} ({self.status})>'


class SecurityFinding(db.Model):
    """Track security findings and compliance issues"""
    __tablename__ = 'security_findings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('infrastructure_resources.id'))

    # Finding details
    finding_type = db.Column(db.String(50), nullable=False, index=True)  # open_s3_bucket, security_group, unencrypted_db, etc
    severity = db.Column(db.String(20), nullable=False, index=True)  # critical, high, medium, low, info
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Compliance frameworks
    compliance_frameworks = db.Column(db.JSON)  # ['CIS', 'SOC2', 'HIPAA', etc]
    cis_benchmark_id = db.Column(db.String(50))  # CIS benchmark identifier

    # Resource details
    cloud_provider = db.Column(db.String(20))  # aws, gcp, azure
    affected_resource_type = db.Column(db.String(50))
    affected_resource_id = db.Column(db.String(200))
    affected_resource_name = db.Column(db.String(200))
    region = db.Column(db.String(50))

    # Finding details
    finding_data = db.Column(db.JSON)  # Specific details about the finding
    remediation_steps = db.Column(db.Text)  # How to fix this issue
    auto_remediation_available = db.Column(db.Boolean, default=False)

    # Status tracking
    status = db.Column(db.String(20), default='open', index=True)  # open, in_progress, resolved, suppressed
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolution_notes = db.Column(db.Text)

    # Risk assessment
    risk_score = db.Column(db.Integer)  # 0-100
    exploitability = db.Column(db.String(20))  # high, medium, low

    # Timestamps
    first_detected = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    last_detected = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('security_findings', lazy='dynamic'))
    resolver = db.relationship('User', foreign_keys=[resolved_by], backref=db.backref('resolved_findings', lazy='dynamic'))
    resource = db.relationship('InfrastructureResource', backref=db.backref('security_findings', lazy='dynamic'))

    def to_dict(self):
        """Convert finding to dictionary"""
        return {
            'id': self.id,
            'finding_type': self.finding_type,
            'severity': self.severity,
            'title': self.title,
            'description': self.description,
            'compliance_frameworks': self.compliance_frameworks or [],
            'cis_benchmark_id': self.cis_benchmark_id,
            'cloud_provider': self.cloud_provider,
            'affected_resource_type': self.affected_resource_type,
            'affected_resource_id': self.affected_resource_id,
            'affected_resource_name': self.affected_resource_name,
            'region': self.region,
            'finding_data': self.finding_data or {},
            'remediation_steps': self.remediation_steps,
            'auto_remediation_available': self.auto_remediation_available,
            'status': self.status,
            'risk_score': self.risk_score,
            'exploitability': self.exploitability,
            'first_detected': self.first_detected.isoformat() if self.first_detected else None,
            'last_detected': self.last_detected.isoformat() if self.last_detected else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

    def __repr__(self):
        return f'<SecurityFinding {self.severity}: {self.title}>'


class Alert(db.Model):
    """Track alerts and notifications for infrastructure monitoring"""
    __tablename__ = 'alerts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('infrastructure_resources.id'))

    # Alert details
    alert_type = db.Column(db.String(50), nullable=False, index=True)  # high_cpu, disk_full, health_check_failed, cost_spike, etc
    severity = db.Column(db.String(20), nullable=False, index=True)  # critical, warning, info
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)

    # Resource context
    cloud_provider = db.Column(db.String(20))  # aws, gcp, azure
    resource_type = db.Column(db.String(50))
    resource_name = db.Column(db.String(200))
    affected_resource_id = db.Column(db.String(200))
    region = db.Column(db.String(50))

    # Alert data
    alert_data = db.Column(db.JSON)  # Metrics, thresholds, current values
    threshold_value = db.Column(db.Float)  # The threshold that was crossed
    current_value = db.Column(db.Float)  # The current value

    # Auto-remediation
    auto_remediation_available = db.Column(db.Boolean, default=False)
    auto_remediation_action = db.Column(db.String(100))  # restart_service, scale_up, expand_disk, etc
    auto_remediated = db.Column(db.Boolean, default=False)
    remediation_result = db.Column(db.JSON)

    # Status tracking
    status = db.Column(db.String(20), default='active', index=True)  # active, acknowledged, resolved, suppressed
    acknowledged_at = db.Column(db.DateTime)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolved_at = db.Column(db.DateTime)
    resolution_notes = db.Column(db.Text)

    # Notification tracking
    notification_sent = db.Column(db.Boolean, default=False)
    notification_channels = db.Column(db.JSON)  # ['email', 'slack', 'pagerduty']
    notification_sent_at = db.Column(db.DateTime)

    # Timestamps
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('alerts', lazy='dynamic'))
    acknowledger = db.relationship('User', foreign_keys=[acknowledged_by], backref=db.backref('acknowledged_alerts', lazy='dynamic'))
    resource = db.relationship('InfrastructureResource', backref=db.backref('alerts', lazy='dynamic'))

    def to_dict(self):
        """Convert alert to dictionary"""
        return {
            'id': self.id,
            'alert_type': self.alert_type,
            'severity': self.severity,
            'title': self.title,
            'message': self.message,
            'cloud_provider': self.cloud_provider,
            'resource_type': self.resource_type,
            'resource_name': self.resource_name,
            'affected_resource_id': self.affected_resource_id,
            'region': self.region,
            'alert_data': self.alert_data or {},
            'threshold_value': self.threshold_value,
            'current_value': self.current_value,
            'auto_remediation_available': self.auto_remediation_available,
            'auto_remediation_action': self.auto_remediation_action,
            'auto_remediated': self.auto_remediated,
            'status': self.status,
            'notification_sent': self.notification_sent,
            'notification_channels': self.notification_channels or [],
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

    def __repr__(self):
        return f'<Alert {self.severity}: {self.title}>'


class MonitoringRuleModel(db.Model):
    """Persisted monitoring rules with user isolation"""
    __tablename__ = 'monitoring_rules'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    rule_key = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    source = db.Column(db.String(20), nullable=False, default='prometheus')
    metric_query = db.Column(db.Text, nullable=False)
    condition = db.Column(db.String(10), nullable=False, default='gt')
    threshold = db.Column(db.Float, nullable=False)
    duration_seconds = db.Column(db.Integer, default=60)
    severity = db.Column(db.String(20), default='medium')
    labels = db.Column(db.JSON, default=lambda: {})
    enabled = db.Column(db.Boolean, default=True)
    check_interval_seconds = db.Column(db.Integer, default=30)
    state = db.Column(db.String(20), default='ok')
    last_value = db.Column(db.Float, nullable=True)
    last_check = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('monitoring_rules', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'rule_key', name='uq_user_rule_key'),
    )

    def to_dict(self):
        return {
            'id': self.rule_key,
            'name': self.name,
            'description': self.description or '',
            'source': self.source,
            'query': self.metric_query,
            'condition': self.condition,
            'threshold': self.threshold,
            'duration_seconds': self.duration_seconds,
            'severity': self.severity,
            'labels': self.labels or {},
            'enabled': self.enabled,
            'check_interval_seconds': self.check_interval_seconds,
            'state': self.state or 'ok',
            'last_value': self.last_value,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'pending_since': None,
            'firing_since': None,
        }

    def __repr__(self):
        return f'<MonitoringRuleModel {self.rule_key} user={self.user_id}>'


class MonitoringAlertModel(db.Model):
    """Persisted monitoring alerts with user isolation"""
    __tablename__ = 'monitoring_alerts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    alert_key = db.Column(db.String(50), nullable=False)
    rule_db_id = db.Column(db.Integer, db.ForeignKey('monitoring_rules.id'), nullable=True)
    rule_key = db.Column(db.String(50), nullable=False)
    rule_name = db.Column(db.String(200), nullable=False)
    severity = db.Column(db.String(20), nullable=False)
    value = db.Column(db.Float, nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    condition = db.Column(db.String(50))
    message = db.Column(db.Text)
    labels = db.Column(db.JSON, default=lambda: {})
    fired_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.String(200), nullable=True)
    incident_id = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('monitoring_alerts', lazy='dynamic'))
    rule = db.relationship('MonitoringRuleModel', backref=db.backref('alerts', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.alert_key,
            'rule_id': self.rule_key,
            'rule_name': self.rule_name,
            'severity': self.severity,
            'value': self.value,
            'threshold': self.threshold,
            'condition': self.condition,
            'message': self.message,
            'labels': self.labels or {},
            'fired_at': self.fired_at.isoformat() if self.fired_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'acknowledged': self.acknowledged,
            'acknowledged_by': self.acknowledged_by,
            'incident_id': self.incident_id,
        }

    def __repr__(self):
        return f'<MonitoringAlertModel {self.alert_key} user={self.user_id}>'


class IncidentModel(db.Model):
    """Persisted incidents with user isolation"""
    __tablename__ = 'incidents'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    incident_key = db.Column(db.String(50), nullable=False, unique=True)
    title = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text, default='')
    severity = db.Column(db.String(20), nullable=False, default='medium')
    status = db.Column(db.String(30), nullable=False, default='detected')
    source = db.Column(db.String(50), nullable=False, default='manual')
    source_id = db.Column(db.String(200), nullable=True)
    playbook_id = db.Column(db.String(100), nullable=True)
    assigned_to = db.Column(db.String(200), nullable=True)
    metadata_json = db.Column(db.JSON, default=lambda: {})
    actions_taken = db.Column(db.JSON, default=lambda: [])
    timeline = db.Column(db.JSON, default=lambda: [])
    correlation_group_key = db.Column(db.String(100), nullable=True, index=True)
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('incidents', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.incident_key,
            'title': self.title,
            'description': self.description or '',
            'severity': self.severity,
            'status': self.status,
            'source': self.source,
            'source_id': self.source_id,
            'playbook_id': self.playbook_id,
            'assigned_to': self.assigned_to,
            'metadata': self.metadata_json or {},
            'actions_taken': self.actions_taken or [],
            'timeline': self.timeline or [],
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
        }

    def __repr__(self):
        return f'<IncidentModel {self.incident_key} user={self.user_id}>'


class PlaybookModel(db.Model):
    """Persisted custom playbooks with user isolation"""
    __tablename__ = 'playbooks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    playbook_key = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    trigger_conditions = db.Column(db.JSON, default=lambda: {})
    severity = db.Column(db.String(20), default='medium')
    actions_json = db.Column(db.JSON, default=lambda: [])
    enabled = db.Column(db.Boolean, default=True)
    auto_execute = db.Column(db.Boolean, default=False)
    notification_channels = db.Column(db.JSON, default=lambda: [])
    escalation_policy = db.Column(db.String(100), nullable=True)
    tags = db.Column(db.JSON, default=lambda: [])
    is_builtin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('playbooks', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'playbook_key', name='uq_user_playbook_key'),
    )

    def to_dict(self):
        return {
            'id': self.playbook_key,
            'name': self.name,
            'description': self.description or '',
            'trigger_conditions': self.trigger_conditions or {},
            'severity': self.severity,
            'actions': self.actions_json or [],
            'enabled': self.enabled,
            'auto_execute': self.auto_execute,
            'notification_channels': self.notification_channels or [],
            'escalation_policy': self.escalation_policy,
            'tags': self.tags or [],
            'is_builtin': self.is_builtin,
        }

    def __repr__(self):
        return f'<PlaybookModel {self.playbook_key} user={self.user_id}>'


class AnalysisModel(db.Model):
    """Persisted root cause analysis with per-user isolation."""
    __tablename__ = 'analyses'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    analysis_key = db.Column(db.String(50), nullable=False)
    incident_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), default='completed')
    summary = db.Column(db.Text, default='')
    timeline_analysis = db.Column(db.Text, default='')
    impact_assessment = db.Column(db.Text, default='')
    root_causes = db.Column(db.JSON, default=list)
    recommendations = db.Column(db.JSON, default=list)
    data_sources_used = db.Column(db.JSON, default=list)
    analysis_duration_seconds = db.Column(db.Float, default=0.0)
    analyzed_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'analysis_key', name='uq_user_analysis_key'),
        db.Index('idx_analysis_user_incident', 'user_id', 'incident_id'),
    )

    def to_dict(self):
        return {
            'id': self.analysis_key,
            'incident_id': self.incident_id or 'unknown',
            'status': self.status or 'completed',
            'summary': self.summary or '',
            'timeline_analysis': self.timeline_analysis or '',
            'impact_assessment': self.impact_assessment or '',
            'root_causes': self.root_causes or [],
            'recommendations': self.recommendations or [],
            'data_sources_used': self.data_sources_used or [],
            'analysis_duration_seconds': self.analysis_duration_seconds or 0.0,
            'analyzed_at': self.analyzed_at.isoformat() if self.analyzed_at else None,
        }

    def __repr__(self):
        return f'<AnalysisModel {self.analysis_key} user={self.user_id}>'


class UserCloudCredential(db.Model):
    """Store per-user cloud credentials (encrypted) for AWS, Azure, and GCP"""
    __tablename__ = 'user_cloud_credentials'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    cloud_provider = db.Column(db.String(20), nullable=False, index=True)  # aws, azure, gcp

    # Encrypted credential storage (all sensitive values encrypted)
    credentials_encrypted = db.Column(db.Text, nullable=False)  # JSON string, encrypted

    # Non-sensitive metadata (not encrypted)
    default_region = db.Column(db.String(50))
    default_zone = db.Column(db.String(50))  # For GCP
    is_active = db.Column(db.Boolean, default=True)
    last_verified = db.Column(db.DateTime)
    verification_status = db.Column(db.String(20), default='pending')  # pending, valid, invalid

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('cloud_credentials', lazy='dynamic'))

    # Unique constraint: one credential set per user per provider
    __table_args__ = (
        db.UniqueConstraint('user_id', 'cloud_provider', name='unique_user_cloud_provider'),
    )

    @staticmethod
    def _get_encryption_key():
        """Derive a Fernet-compatible encryption key from environment variables.

        Preference order:
          1. CREDENTIAL_ENCRYPTION_KEY  — dedicated key (required in production)
          2. SECRET_KEY                 — Flask session secret used as fallback input
          3. Hardcoded sentinel         — development only; emits a CRITICAL log

        When falling back to SECRET_KEY, key material is stretched with PBKDF2-HMAC-SHA256
        (600 000 iterations) so a short or guessable SECRET_KEY can't be trivially reversed
        from a database dump.
        """
        import os
        import base64
        import hashlib
        import logging

        raw_key = os.environ.get('CREDENTIAL_ENCRYPTION_KEY')
        if raw_key:
            key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
            # Accept a raw 32-byte value or an already base64url-encoded 44-byte Fernet key
            if len(key_bytes) == 32:
                return base64.urlsafe_b64encode(key_bytes)
            return key_bytes

        # Fallback: stretch SECRET_KEY with PBKDF2
        secret = os.environ.get('SECRET_KEY')
        if not secret:
            logging.getLogger(__name__).critical(
                "Neither CREDENTIAL_ENCRYPTION_KEY nor SECRET_KEY is set. "
                "Cloud credentials are encrypted with a default key — "
                "set CREDENTIAL_ENCRYPTION_KEY in production immediately."
            )
            secret = 'default-secret-key-change-in-production'
        else:
            logging.getLogger(__name__).warning(
                "CREDENTIAL_ENCRYPTION_KEY not set; falling back to SECRET_KEY "
                "for credential encryption. Set CREDENTIAL_ENCRYPTION_KEY in production."
            )

        _SALT = b'devops-agent-credential-encryption-v1'
        derived = hashlib.pbkdf2_hmac('sha256', secret.encode(), _SALT, iterations=600_000)
        return base64.urlsafe_b64encode(derived)

    def set_credentials(self, credentials_dict):
        """Encrypt and store credentials"""
        import json
        from cryptography.fernet import Fernet

        key = self._get_encryption_key()
        fernet = Fernet(key)

        # Convert credentials to JSON and encrypt
        json_str = json.dumps(credentials_dict)
        encrypted = fernet.encrypt(json_str.encode())
        self.credentials_encrypted = encrypted.decode()

    def get_credentials(self):
        """Decrypt and return credentials"""
        import json
        from cryptography.fernet import Fernet

        if not self.credentials_encrypted:
            return {}

        key = self._get_encryption_key()
        fernet = Fernet(key)

        try:
            decrypted = fernet.decrypt(self.credentials_encrypted.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to decrypt credentials for UserCloudCredential "
                f"id={self.id} provider={self.cloud_provider}: {e}"
            )
            raise Exception(
                f"Credential decryption failed for {self.cloud_provider.upper()}. "
                "This usually means the server's SECRET_KEY changed after credentials were saved. "
                "Please re-save your credentials in Settings > Cloud Credentials."
            )

    def to_dict(self, include_credentials=False):
        """Convert to dictionary (credentials only included if explicitly requested)"""
        result = {
            'id': self.id,
            'cloud_provider': self.cloud_provider,
            'default_region': self.default_region,
            'default_zone': self.default_zone,
            'is_active': self.is_active,
            'verification_status': self.verification_status,
            'last_verified': self.last_verified.isoformat() if self.last_verified else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_credentials:
            creds = self.get_credentials()
            # Mask sensitive values
            if self.cloud_provider == 'aws':
                if creds.get('role_arn'):
                    result['auth_mode'] = 'role_arn'
                    result['role_arn'] = creds['role_arn']
                    result['has_external_id'] = bool(creds.get('external_id'))
                else:
                    result['auth_mode'] = 'access_key'
                    result['has_access_key'] = bool(creds.get('access_key'))
                    result['access_key_preview'] = creds.get('access_key', '')[:8] + '****' if creds.get('access_key') else None
            elif self.cloud_provider == 'azure':
                result['has_client_secret'] = bool(creds.get('client_secret'))
                result['subscription_id'] = creds.get('subscription_id')
                result['tenant_id'] = creds.get('tenant_id')
            elif self.cloud_provider == 'gcp':
                result['has_service_account'] = bool(creds.get('service_account_json'))
                result['project_id'] = creds.get('project_id')
        return result

    def __repr__(self):
        return f'<UserCloudCredential user={self.user_id} provider={self.cloud_provider}>'


class APIKey(db.Model):
    """API keys for programmatic access to the platform"""
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Key identification
    name = db.Column(db.String(100), nullable=False)  # User-friendly name for the key
    key_prefix = db.Column(db.String(8), nullable=False, index=True)  # First 8 chars for identification
    key_hash = db.Column(db.String(64), nullable=False, unique=True)  # SHA-256 hash of full key

    # Permissions and scopes
    scopes = db.Column(db.JSON, default=lambda: [])  # List of allowed scopes: ['read', 'write', 'admin']
    allowed_ips = db.Column(db.JSON, default=lambda: [])  # IP whitelist (empty = all allowed)

    # Rate limiting
    rate_limit = db.Column(db.Integer, default=1000)  # Requests per hour
    requests_today = db.Column(db.Integer, default=0)
    last_request_date = db.Column(db.Date)

    # Usage tracking
    last_used_at = db.Column(db.DateTime)
    last_used_ip = db.Column(db.String(45))
    total_requests = db.Column(db.Integer, default=0)

    # Status
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # Optional expiration

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked_at = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def generate_key():
        """Generate a new API key"""
        import secrets
        # Format: doa_live_<32 random chars>
        random_part = secrets.token_hex(16)
        return f"doa_live_{random_part}"

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage"""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def create_for_user(cls, user_id: int, name: str, scopes: list = None):
        """Create a new API key for a user"""
        key = cls.generate_key()
        api_key = cls(
            user_id=user_id,
            name=name,
            key_prefix=key[:8],
            key_hash=cls.hash_key(key),
            scopes=scopes or ['read']
        )
        return api_key, key  # Return both model and plain key (key shown once)

    @classmethod
    def verify_key(cls, key: str):
        """Verify an API key and return the APIKey object if valid"""
        key_hash = cls.hash_key(key)
        api_key = cls.query.filter_by(key_hash=key_hash, is_active=True).first()

        if api_key:
            # Check expiration
            if api_key.expires_at and api_key.expires_at < datetime.utcnow():
                return None

            # Update usage stats
            api_key.last_used_at = datetime.utcnow()
            api_key.total_requests += 1
            db.session.commit()

        return api_key

    def has_scope(self, scope: str) -> bool:
        """Check if key has a specific scope"""
        return scope in (self.scopes or []) or 'admin' in (self.scopes or [])

    def revoke(self):
        """Revoke the API key"""
        self.is_active = False
        self.revoked_at = datetime.utcnow()
        db.session.commit()

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'key_prefix': self.key_prefix,
            'scopes': self.scopes or [],
            'allowed_ips': self.allowed_ips or [],
            'rate_limit': self.rate_limit,
            'is_active': self.is_active,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'total_requests': self.total_requests,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<APIKey {self.key_prefix}*** ({self.name})>'


class AuditLog(db.Model):
    """Comprehensive audit logging for all user and system actions"""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)  # Nullable for system actions

    # Action details
    action = db.Column(db.String(100), nullable=False, index=True)  # login, logout, create_resource, delete_resource, etc.
    action_category = db.Column(db.String(50), nullable=False, index=True)  # auth, resource, billing, security, settings
    resource_type = db.Column(db.String(50), index=True)  # user, conversation, ec2_instance, api_key, etc.
    resource_id = db.Column(db.String(200))  # ID of the affected resource

    # Request context
    ip_address = db.Column(db.String(45))  # IPv6 support
    user_agent = db.Column(db.String(500))
    request_method = db.Column(db.String(10))  # GET, POST, PUT, DELETE
    request_path = db.Column(db.String(500))
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_keys.id'))  # If action was via API key

    # Action details
    description = db.Column(db.Text)  # Human-readable description
    old_value = db.Column(db.JSON)  # Previous state (for updates)
    new_value = db.Column(db.JSON)  # New state (for creates/updates)
    extra_data = db.Column(db.JSON)  # Additional context

    # Result
    status = db.Column(db.String(20), default='success', index=True)  # success, failure, error
    error_message = db.Column(db.Text)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('audit_logs', lazy='dynamic'))
    api_key = db.relationship('APIKey', backref=db.backref('audit_logs', lazy='dynamic'))

    # Indexes for common queries
    __table_args__ = (
        db.Index('idx_audit_user_action', 'user_id', 'action'),
        db.Index('idx_audit_created_at_desc', created_at.desc()),
    )

    @classmethod
    def log(cls, action: str, category: str, user_id: int = None, **kwargs):
        """Create an audit log entry"""
        log_entry = cls(
            user_id=user_id,
            action=action,
            action_category=category,
            resource_type=kwargs.get('resource_type'),
            resource_id=kwargs.get('resource_id'),
            ip_address=kwargs.get('ip_address'),
            user_agent=kwargs.get('user_agent'),
            request_method=kwargs.get('request_method'),
            request_path=kwargs.get('request_path'),
            api_key_id=kwargs.get('api_key_id'),
            description=kwargs.get('description'),
            old_value=kwargs.get('old_value'),
            new_value=kwargs.get('new_value'),
            metadata=kwargs.get('metadata'),
            status=kwargs.get('status', 'success'),
            error_message=kwargs.get('error_message')
        )
        db.session.add(log_entry)
        db.session.commit()
        return log_entry

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'action_category': self.action_category,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'description': self.description,
            'status': self.status,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<AuditLog {self.action} by user {self.user_id}>'


# ============================================
# Organization & Multi-tenancy Models
# ============================================

class Organization(db.Model):
    """Organization/workspace for multi-tenancy"""
    __tablename__ = 'organizations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    logo_url = db.Column(db.String(500))

    # Owner
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Settings
    settings = db.Column(db.JSON, default=lambda: {})

    # SSO Configuration
    sso_enabled = db.Column(db.Boolean, default=False)
    sso_provider = db.Column(db.String(50))  # okta, azure_ad, google, github
    sso_config = db.Column(db.JSON)

    # Billing
    billing_email = db.Column(db.String(120))
    stripe_customer_id = db.Column(db.String(100))

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_organizations')
    members = db.relationship('OrganizationMember', back_populates='organization', cascade='all, delete-orphan')
    teams = db.relationship('Team', back_populates='organization', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'logo_url': self.logo_url,
            'owner_id': self.owner_id,
            'sso_enabled': self.sso_enabled,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<Organization {self.name}>'


class OrganizationMember(db.Model):
    """Organization membership"""
    __tablename__ = 'organization_members'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Role: owner, admin, member, billing, viewer
    role = db.Column(db.String(20), default='member')

    # Invitation
    invited_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    invited_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)
    invitation_token = db.Column(db.String(100), unique=True)

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    organization = db.relationship('Organization', back_populates='members')
    user = db.relationship('User', foreign_keys=[user_id], backref='organization_memberships')
    inviter = db.relationship('User', foreign_keys=[invited_by])

    __table_args__ = (
        db.UniqueConstraint('organization_id', 'user_id', name='unique_org_member'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'user_id': self.user_id,
            'role': self.role,
            'is_active': self.is_active,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<OrganizationMember org={self.organization_id} user={self.user_id}>'


class Team(db.Model):
    """Team within an organization"""
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = db.relationship('Organization', back_populates='teams')
    members = db.relationship('TeamMember', back_populates='team', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<Team {self.name}>'


class TeamMember(db.Model):
    """Team membership"""
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='member')  # lead, member

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    team = db.relationship('Team', back_populates='members')
    user = db.relationship('User', backref='team_memberships')

    __table_args__ = (
        db.UniqueConstraint('team_id', 'user_id', name='unique_team_member'),
    )

    def __repr__(self):
        return f'<TeamMember team={self.team_id} user={self.user_id}>'


# ============================================
# Webhook Models
# ============================================

class WebhookEndpoint(db.Model):
    """Webhook endpoints for event notifications"""
    __tablename__ = 'webhook_endpoints'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(64))  # For HMAC signature verification

    # Events to subscribe to
    events = db.Column(db.JSON, default=lambda: [])  # ['resource.created', 'alert.triggered', etc.]

    # Configuration
    is_active = db.Column(db.Boolean, default=True)
    retry_count = db.Column(db.Integer, default=3)
    timeout_seconds = db.Column(db.Integer, default=30)

    # Statistics
    total_deliveries = db.Column(db.Integer, default=0)
    successful_deliveries = db.Column(db.Integer, default=0)
    failed_deliveries = db.Column(db.Integer, default=0)
    last_delivery_at = db.Column(db.DateTime)
    last_delivery_status = db.Column(db.String(20))

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('webhook_endpoints', lazy='dynamic'))
    deliveries = db.relationship('WebhookDelivery', back_populates='endpoint', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'events': self.events or [],
            'is_active': self.is_active,
            'total_deliveries': self.total_deliveries,
            'successful_deliveries': self.successful_deliveries,
            'failed_deliveries': self.failed_deliveries,
            'last_delivery_at': self.last_delivery_at.isoformat() if self.last_delivery_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<WebhookEndpoint {self.name}>'


class WebhookDelivery(db.Model):
    """Record of webhook delivery attempts"""
    __tablename__ = 'webhook_deliveries'

    id = db.Column(db.Integer, primary_key=True)
    endpoint_id = db.Column(db.Integer, db.ForeignKey('webhook_endpoints.id'), nullable=False, index=True)

    # Event info
    event_type = db.Column(db.String(100), nullable=False)
    payload = db.Column(db.JSON)

    # Delivery status
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    response_status_code = db.Column(db.Integer)
    response_body = db.Column(db.Text)
    error_message = db.Column(db.Text)

    # Retry tracking
    attempt_count = db.Column(db.Integer, default=0)
    next_retry_at = db.Column(db.DateTime)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime)

    # Relationships
    endpoint = db.relationship('WebhookEndpoint', back_populates='deliveries')

    def to_dict(self):
        return {
            'id': self.id,
            'event_type': self.event_type,
            'status': self.status,
            'response_status_code': self.response_status_code,
            'attempt_count': self.attempt_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'delivered_at': self.delivered_at.isoformat() if self.delivered_at else None
        }

    def __repr__(self):
        return f'<WebhookDelivery {self.event_type} - {self.status}>'


# ============================================
# Compliance Models
# ============================================

class ComplianceFrameworkModel(db.Model):
    """Compliance frameworks configuration"""
    __tablename__ = 'compliance_frameworks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(50), nullable=False)  # soc2, hipaa, pci_dss, gdpr
    display_name = db.Column(db.String(100))
    description = db.Column(db.Text)

    # Configuration
    is_enabled = db.Column(db.Boolean, default=False)
    settings = db.Column(db.JSON, default=lambda: {})

    # Status
    last_assessment_at = db.Column(db.DateTime)
    compliance_score = db.Column(db.Integer)  # 0-100

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('compliance_frameworks', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='unique_user_framework'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'is_enabled': self.is_enabled,
            'compliance_score': self.compliance_score,
            'last_assessment_at': self.last_assessment_at.isoformat() if self.last_assessment_at else None
        }

    def __repr__(self):
        return f'<ComplianceFramework {self.name}>'


class CompliancePolicy(db.Model):
    """User-defined compliance policies"""
    __tablename__ = 'compliance_policies'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    policy_type = db.Column(db.String(50))  # security, access, data, network

    # Policy definition
    rules = db.Column(db.JSON)  # Policy rules/conditions
    enforcement_action = db.Column(db.String(50))  # alert, block, auto_remediate

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Statistics
    violations_count = db.Column(db.Integer, default=0)
    last_violation_at = db.Column(db.DateTime)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('compliance_policies', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'policy_type': self.policy_type,
            'enforcement_action': self.enforcement_action,
            'is_active': self.is_active,
            'violations_count': self.violations_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<CompliancePolicy {self.name}>'


class ComplianceReport(db.Model):
    """Generated compliance reports"""
    __tablename__ = 'compliance_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    report_type = db.Column(db.String(50))  # assessment, audit, summary
    framework = db.Column(db.String(50))  # soc2, hipaa, etc.

    # Report content
    summary = db.Column(db.JSON)
    findings = db.Column(db.JSON)
    recommendations = db.Column(db.JSON)

    # Scores
    overall_score = db.Column(db.Integer)  # 0-100
    controls_passed = db.Column(db.Integer)
    controls_failed = db.Column(db.Integer)

    # File
    file_path = db.Column(db.String(500))
    file_format = db.Column(db.String(10))  # pdf, csv, json

    # Timestamps
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref=db.backref('compliance_reports', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'report_type': self.report_type,
            'framework': self.framework,
            'overall_score': self.overall_score,
            'controls_passed': self.controls_passed,
            'controls_failed': self.controls_failed,
            'file_format': self.file_format,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }

    def __repr__(self):
        return f'<ComplianceReport {self.name}>'


# ============================================
# AI Infrastructure Models
# ============================================

class InfrastructureTemplate(db.Model):
    """Saved infrastructure templates"""
    __tablename__ = 'infrastructure_templates'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))  # web, database, kubernetes, networking

    # Template content
    cloud_provider = db.Column(db.String(20))  # aws, azure, gcp
    template_type = db.Column(db.String(20))  # terraform, cloudformation, pulumi
    template_content = db.Column(db.Text)
    variables = db.Column(db.JSON)

    # Estimated cost
    estimated_monthly_cost = db.Column(db.Float)

    # Sharing
    is_public = db.Column(db.Boolean, default=False)
    use_count = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('infrastructure_templates', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'cloud_provider': self.cloud_provider,
            'template_type': self.template_type,
            'estimated_monthly_cost': self.estimated_monthly_cost,
            'is_public': self.is_public,
            'use_count': self.use_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<InfrastructureTemplate {self.name}>'


class ProvisioningRequestModel(db.Model):
    """Infrastructure provisioning requests"""
    __tablename__ = 'provisioning_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Request details
    request_id = db.Column(db.String(50), unique=True, nullable=False)
    natural_language_input = db.Column(db.Text)
    parsed_spec = db.Column(db.JSON)

    # Generated code
    cloud_provider = db.Column(db.String(20))
    terraform_code = db.Column(db.Text)
    cloudformation_code = db.Column(db.Text)

    # Cost estimation
    estimated_monthly_cost = db.Column(db.Float)

    # Status
    status = db.Column(db.String(20), default='pending')  # pending, planning, approved, provisioning, completed, failed

    # Approval workflow
    requires_approval = db.Column(db.Boolean, default=False)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)

    # Execution
    executed_at = db.Column(db.DateTime)
    execution_result = db.Column(db.JSON)
    error_message = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('provisioning_requests', lazy='dynamic'))
    approver = db.relationship('User', foreign_keys=[approved_by])

    def to_dict(self):
        return {
            'id': self.id,
            'request_id': self.request_id,
            'natural_language_input': self.natural_language_input,
            'cloud_provider': self.cloud_provider,
            'estimated_monthly_cost': self.estimated_monthly_cost,
            'status': self.status,
            'requires_approval': self.requires_approval,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<ProvisioningRequest {self.request_id} - {self.status}>'


# ============================================
# Analytics Models
# ============================================

class AnalyticsDashboard(db.Model):
    """Custom analytics dashboards"""
    __tablename__ = 'analytics_dashboards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Layout configuration
    layout = db.Column(db.JSON)  # Widget positions and sizes

    # Sharing
    is_default = db.Column(db.Boolean, default=False)
    is_shared = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('analytics_dashboards', lazy='dynamic'))
    widgets = db.relationship('AnalyticsWidget', back_populates='dashboard', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_default': self.is_default,
            'is_shared': self.is_shared,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<AnalyticsDashboard {self.name}>'


class AnalyticsWidget(db.Model):
    """Individual analytics widgets"""
    __tablename__ = 'analytics_widgets'

    id = db.Column(db.Integer, primary_key=True)
    dashboard_id = db.Column(db.Integer, db.ForeignKey('analytics_dashboards.id'), nullable=False)

    name = db.Column(db.String(200), nullable=False)
    widget_type = db.Column(db.String(50))  # chart, metric, table, map

    # Configuration
    data_source = db.Column(db.String(100))  # costs, resources, incidents, etc.
    config = db.Column(db.JSON)  # Chart type, colors, filters, etc.

    # Position
    position_x = db.Column(db.Integer, default=0)
    position_y = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=4)
    height = db.Column(db.Integer, default=3)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    dashboard = db.relationship('AnalyticsDashboard', back_populates='widgets')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'widget_type': self.widget_type,
            'data_source': self.data_source,
            'config': self.config,
            'position': {'x': self.position_x, 'y': self.position_y},
            'size': {'width': self.width, 'height': self.height}
        }

    def __repr__(self):
        return f'<AnalyticsWidget {self.name}>'


# ============================================
# Contact/Support Models
# ============================================

class ContactMessage(db.Model):
    """Contact form submissions from users"""
    __tablename__ = 'contact_messages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # bug, feature, question, billing, other
    message = db.Column(db.Text, nullable=False)

    # Status tracking
    status = db.Column(db.String(20), default='new')  # new, in_progress, resolved, closed
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    response = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('contact_messages', lazy='dynamic'))
    assignee = db.relationship('User', foreign_keys=[assigned_to])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'category': self.category,
            'message': self.message,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None
        }

    def __repr__(self):
        return f'<ContactMessage {self.id} - {self.category}>'


class UserNotificationChannel(db.Model):
    """User-configured notification channels (Slack, Teams webhooks)"""
    __tablename__ = 'user_notification_channels'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    channel_type = db.Column(db.String(20), nullable=False)  # slack, teams
    name = db.Column(db.String(100), nullable=False)
    webhook_url = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    # What events to notify on
    notify_changes = db.Column(db.Boolean, default=True)
    notify_security = db.Column(db.Boolean, default=True)
    notify_cost = db.Column(db.Boolean, default=True)
    notify_incidents = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('notification_channels', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'channel_type': self.channel_type,
            'name': self.name,
            'webhook_url': self.webhook_url[:20] + '***' if self.webhook_url else None,
            'is_active': self.is_active,
            'notify_changes': self.notify_changes,
            'notify_security': self.notify_security,
            'notify_cost': self.notify_cost,
            'notify_incidents': self.notify_incidents,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BudgetAlert(db.Model):
    """User-configured budget/cost alerts"""
    __tablename__ = 'budget_alerts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    threshold_amount = db.Column(db.Float, nullable=False)
    period = db.Column(db.String(20), default='monthly')  # monthly, weekly, daily
    is_active = db.Column(db.Boolean, default=True)
    last_triggered = db.Column(db.DateTime)
    last_checked_amount = db.Column(db.Float)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('budget_alerts', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'threshold_amount': self.threshold_amount,
            'period': self.period,
            'is_active': self.is_active,
            'last_triggered': self.last_triggered.isoformat() if self.last_triggered else None,
            'last_checked_amount': self.last_checked_amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserMemory(db.Model):
    """Persistent memory entries for per-user context across conversations."""
    __tablename__ = 'user_memories'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category = db.Column(db.String(50), default='general', index=True)  # general, preference, infrastructure, incident
    content = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(50), default='agent')  # agent, user, system
    importance = db.Column(db.Integer, default=5)  # 1-10, higher = more important
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    user = db.relationship('User', backref=db.backref('memories', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'content': self.content,
            'source': self.source,
            'importance': self.importance,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class LearningSession(db.Model):
    """Track learning mode sessions with summaries and proficiency tracking"""
    __tablename__ = 'learning_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.String(50), db.ForeignKey('conversations.id'), nullable=True)

    summary = db.Column(db.Text)
    topics_covered = db.Column(db.JSON, default=lambda: [])
    tools_used = db.Column(db.JSON, default=lambda: [])
    key_lessons = db.Column(db.JSON, default=lambda: [])
    study_recommendations = db.Column(db.JSON, default=lambda: [])
    proficiency_deltas = db.Column(db.JSON, default=lambda: {})
    message_count = db.Column(db.Integer, default=0)
    was_sandbox = db.Column(db.Boolean, default=False)
    duration_minutes = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('learning_sessions', lazy='dynamic'))
    conversation = db.relationship('Conversation', backref=db.backref('learning_session', uselist=False))

    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'summary': self.summary,
            'topics_covered': self.topics_covered or [],
            'tools_used': self.tools_used or [],
            'key_lessons': self.key_lessons or [],
            'study_recommendations': self.study_recommendations or [],
            'proficiency_deltas': self.proficiency_deltas or {},
            'message_count': self.message_count,
            'was_sandbox': self.was_sandbox,
            'duration_minutes': self.duration_minutes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<LearningSession {self.id} user={self.user_id}>'


class StripeWebhookEvent(db.Model):
    """Track processed Stripe webhook events for idempotency"""
    __tablename__ = 'stripe_webhook_events'

    id = db.Column(db.String(100), primary_key=True)
    event_type = db.Column(db.String(100), nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)


class PaymentWebhookEvent(db.Model):
    """Unified webhook idempotency tracking across all payment gateways"""
    __tablename__ = 'payment_webhook_events'

    id = db.Column(db.String(200), primary_key=True)  # format: "{gateway}:{event_id}"
    gateway = db.Column(db.String(20), nullable=False)  # stripe
    event_type = db.Column(db.String(100), nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    raw_payload = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<PaymentWebhookEvent {self.id}>'


class NGNPriceConfig(db.Model):
    """Nigerian Naira price configuration for products"""
    __tablename__ = 'ngn_price_configs'

    id = db.Column(db.Integer, primary_key=True)
    product_type = db.Column(db.String(20), nullable=False)  # subscription, credit_pack
    product_key = db.Column(db.String(50), nullable=False, unique=True)  # e.g. "starter", "pack_100"
    price_ngn = db.Column(db.Integer, nullable=False)  # Whole naira (not kobo)
    price_usd = db.Column(db.Numeric(10, 2), nullable=True)  # USD price (whole dollars)
    stripe_price_id_ngn = db.Column(db.String(100), nullable=True)  # Stripe Price ID for NGN product
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'product_type': self.product_type,
            'product_key': self.product_key,
            'price_ngn': self.price_ngn,
            'price_usd': float(self.price_usd) if self.price_usd is not None else None,
            'stripe_price_id_ngn': self.stripe_price_id_ngn,
            'is_active': self.is_active,
        }

    def __repr__(self):
        return f'<NGNPriceConfig {self.product_key} NGN{self.price_ngn:,}>'


class UserCurriculumProgress(db.Model):
    """Tracks which curriculum modules a user has completed."""
    __tablename__ = 'user_curriculum_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    module_id = db.Column(db.String(80), nullable=False)   # e.g. "foundations-linux"
    phase_id = db.Column(db.String(10), nullable=False)    # e.g. "01"
    completed = db.Column(db.Boolean, default=False)
    project_done = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'module_id', name='uq_user_curriculum_module'),
    )

    def to_dict(self):
        return {
            'module_id': self.module_id,
            'phase_id': self.phase_id,
            'completed': self.completed,
            'project_done': self.project_done,
            'notes': self.notes,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f'<UserCurriculumProgress user={self.user_id} module={self.module_id}>'


class UserQuizAttempt(db.Model):
    """Stores a single quiz attempt for a curriculum module."""
    __tablename__ = 'user_quiz_attempts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    module_id = db.Column(db.String(80), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)       # number correct
    total = db.Column(db.Integer, nullable=False)       # total questions
    questions = db.Column(db.JSON, nullable=False)      # list of question dicts
    user_answers = db.Column(db.JSON, nullable=False)   # list of chosen answer indices
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def pct(self):
        return round((self.score / self.total) * 100) if self.total else 0

    def to_dict(self):
        return {
            'id': self.id,
            'module_id': self.module_id,
            'score': self.score,
            'total': self.total,
            'pct': self.pct(),
            'created_at': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<UserQuizAttempt user={self.user_id} module={self.module_id} {self.score}/{self.total}>'


class WorkflowTemplate(db.Model):
    """Pre-built workflow templates for common DevOps tasks."""
    __tablename__ = 'workflow_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False, index=True)
    # JSON list of step strings injected as a prompt
    steps = db.Column(db.JSON, nullable=False, default=list)
    # Estimated runtime in minutes
    estimated_minutes = db.Column(db.Integer, default=5)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    execution_count = db.Column(db.Integer, default=0, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    executions = db.relationship('WorkflowExecution', backref='template', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_workflow_templates_category_public', 'category', 'is_public'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'steps': self.steps,
            'estimated_minutes': self.estimated_minutes,
            'is_public': self.is_public,
            'execution_count': self.execution_count,
            'created_at': self.created_at.isoformat(),
        }


class WorkflowExecution(db.Model):
    """Tracks a user's execution of a workflow template."""
    __tablename__ = 'workflow_executions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('workflow_templates.id'), nullable=False)
    # conversation_id links to the chat conversation executing this workflow
    conversation_id = db.Column(db.String(50), db.ForeignKey('conversations.id'), nullable=True)
    status = db.Column(db.String(50), default='queued', nullable=False)  # queued/running/completed/failed/timed_out
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'template_id': self.template_id,
            'conversation_id': self.conversation_id,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'created_at': self.created_at.isoformat(),
        }


class StatusSubscriber(db.Model):
    """Email subscribers for public status page notifications."""
    __tablename__ = 'status_subscribers'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    token = db.Column(db.String(64), nullable=False, unique=True)
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'confirmed': self.confirmed,
            'created_at': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<StatusSubscriber {self.email} confirmed={self.confirmed}>'


class AppNotification(db.Model):
    """In-app notification inbox for alerts, incidents, and system events."""
    __tablename__ = 'app_notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), default='info')  # info | warning | critical | success
    link = db.Column(db.String(500))  # optional deep-link
    read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'body': self.body,
            'category': self.category,
            'link': self.link,
            'read': self.read,
            'created_at': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<AppNotification {self.id} user={self.user_id} read={self.read}>'


class IncidentCorrelationGroup(db.Model):
    """Groups related incidents that fired within a short time window."""
    __tablename__ = 'incident_correlation_groups'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    group_key = db.Column(db.String(100))
    title = db.Column(db.String(500))
    severity = db.Column(db.String(20))
    status = db.Column(db.String(30), default='open')
    window_start = db.Column(db.DateTime)
    window_end = db.Column(db.DateTime)
    incident_keys = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'group_key': self.group_key,
            'title': self.title,
            'severity': self.severity,
            'status': self.status,
            'window_start': self.window_start.isoformat() if self.window_start else None,
            'window_end': self.window_end.isoformat() if self.window_end else None,
            'incident_keys': self.incident_keys or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<IncidentCorrelationGroup {self.id} user={self.user_id} status={self.status}>'


class InvestigationJournalEntry(db.Model):
    """Immutable audit trail of every tool call, finding, and reasoning step per incident."""
    __tablename__ = 'investigation_journal'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    incident_key = db.Column(db.String(50), index=True)
    entry_type = db.Column(db.String(30))   # 'tool_call'|'finding'|'status_change'|'note'
    tool_name = db.Column(db.String(100), nullable=True)
    tool_input = db.Column(db.JSON, nullable=True)
    tool_result = db.Column(db.JSON, nullable=True)
    content = db.Column(db.Text)
    author = db.Column(db.String(20), default='agent')   # 'agent'|'system'|'user'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'incident_key': self.incident_key,
            'entry_type': self.entry_type,
            'tool_name': self.tool_name,
            'tool_input': self.tool_input,
            'tool_result': self.tool_result,
            'content': self.content,
            'author': self.author,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<JournalEntry {self.id} incident={self.incident_key} type={self.entry_type}>'


class ChatArtifact(db.Model):
    """Versioned documents (runbooks, reports, specs) generated during chat."""
    __tablename__ = 'chat_artifacts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    conversation_id = db.Column(db.String(50), db.ForeignKey('conversations.id'), index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_messages.id'), nullable=True)
    artifact_type = db.Column(db.String(30))   # 'runbook'|'incident_report'|'change_plan'|'agent_spec'
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    version = db.Column(db.Integer, default=1)
    parent_id = db.Column(db.Integer, db.ForeignKey('chat_artifacts.id'), nullable=True)
    is_latest = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'artifact_type': self.artifact_type,
            'title': self.title,
            'content': self.content,
            'version': self.version,
            'parent_id': self.parent_id,
            'is_latest': self.is_latest,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ChatArtifact {self.id} type={self.artifact_type} v{self.version}>'


class ProactiveRecommendation(db.Model):
    """Pattern-detected infrastructure recommendations from the Prevention Engine."""
    __tablename__ = 'proactive_recommendations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    category = db.Column(db.String(30), index=True)  # observability|infrastructure|governance|code_optimization
    recommendation_type = db.Column(db.String(80))
    title = db.Column(db.String(300))
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default='medium')
    affected_resource_ids = db.Column(db.JSON, default=list)
    source_incident_ids = db.Column(db.JSON, default=list)
    evidence = db.Column(db.JSON, default=dict)
    remediation_steps = db.Column(db.JSON, default=list)
    estimated_effort = db.Column(db.String(20))
    status = db.Column(db.String(20), default='pending')
    agent_spec = db.Column(db.Text, nullable=True)
    agent_spec_generated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'recommendation_type': self.recommendation_type,
            'title': self.title,
            'description': self.description,
            'severity': self.severity,
            'affected_resource_ids': self.affected_resource_ids or [],
            'source_incident_ids': self.source_incident_ids or [],
            'evidence': self.evidence or {},
            'remediation_steps': self.remediation_steps or [],
            'estimated_effort': self.estimated_effort,
            'status': self.status,
            'has_agent_spec': bool(self.agent_spec),
            'agent_spec_generated_at': self.agent_spec_generated_at.isoformat() if self.agent_spec_generated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<ProactiveRecommendation {self.id} type={self.recommendation_type} status={self.status}>'


class UserSkillActivation(db.Model):
    """Tracks which skills are active per user."""
    __tablename__ = 'user_skill_activations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    skill_id = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    activation_source = db.Column(db.String(20))   # 'manual'|'learned'|'auto'
    activated_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'skill_id', name='uq_user_skill'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'skill_id': self.skill_id,
            'is_active': self.is_active,
            'activation_source': self.activation_source,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
        }

    def __repr__(self):
        return f'<UserSkillActivation user={self.user_id} skill={self.skill_id} active={self.is_active}>'


class DripEmailLog(db.Model):
    """Tracks which drip emails have been sent to each user."""
    __tablename__ = 'drip_email_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    drip_key = db.Column(db.String(50), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'drip_key', name='uq_user_drip_key'),
    )

    def __repr__(self):
        return f'<DripEmailLog user={self.user_id} key={self.drip_key}>'


class CrisisIncident(db.Model):
    """Crisis detection audit trail — logs when crisis language is detected.

    Used for liability protection and incident tracking. Every time crisis language
    is detected, an entry is logged showing:
    - When the detection occurred
    - What crisis keywords triggered it
    - What resources were offered
    - User's country-based locale

    This demonstrates duty of care and platform responsibility.
    """
    __tablename__ = 'crisis_incidents'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    conversation_id = db.Column(db.String(50), nullable=True)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # What triggered the detection
    message_snippet = db.Column(db.String(500), nullable=True)  # First 500 chars of user message

    # Classification and response
    severity = db.Column(db.String(20), default='medium')  # low, medium, high
    crisis_keywords = db.Column(db.JSON, default=dict)  # Keywords that matched: {"suicide": 1, "kill": 2}

    # Action taken
    action = db.Column(db.String(50), default='banner_shown')  # banner_shown, escalated, etc.
    resources_provided = db.Column(db.JSON)  # Crisis resource dict provided to user

    # User context
    user_country = db.Column(db.String(2), nullable=True)  # ISO 3166-1 alpha-2 code
    user_ip = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)

    # Privacy-respecting note: we store that action occurred but NOT the full message
    resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    support_notes = db.Column(db.Text, nullable=True)

    user = db.relationship('User', backref=db.backref('crisis_incidents', lazy='dynamic'))

    def to_dict(self):
        """Convert to dictionary for logging/auditing."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'severity': self.severity,
            'crisis_keywords': self.crisis_keywords,
            'action': self.action,
            'resolved': self.resolved,
        }

    def __repr__(self):
        return f'<CrisisIncident user={self.user_id} severity={self.severity} at={self.detected_at}>'
