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
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    # Relationship
    user = db.relationship('User', backref=db.backref('conversations', lazy='dynamic'))

    def to_dict(self):
        """Convert conversation to dictionary"""
        # Get first message for preview
        first_message = ChatMessage.query.filter_by(
            conversation_id=self.id,
            role='user'
        ).first()

        preview = first_message.content[:100] if first_message else 'New Chat'

        return {
            'id': self.id,
            'title': self.title,
            'preview': preview,
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

    # Relationships
    user = db.relationship('User', backref=db.backref('messages', lazy='dynamic'))
    conversation = db.relationship('Conversation', backref=db.backref('messages', lazy='dynamic'))

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
    enable_cost_warnings = db.Column(db.Boolean, default=True)
    enable_suggestions = db.Column(db.Boolean, default=True)
    verbose_mode = db.Column(db.Boolean, default=False)

    # Favorite Commands (JSON array)
    favorite_commands = db.Column(db.JSON, default=list)

    # Custom Shortcuts (JSON object: shortcut -> command)
    custom_shortcuts = db.Column(db.JSON, default=dict)

    # Recently Used (JSON array)
    recent_operations = db.Column(db.JSON, default=list)

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
            'enable_cost_warnings': self.enable_cost_warnings,
            'enable_suggestions': self.enable_suggestions,
            'verbose_mode': self.verbose_mode,
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
    features = db.Column(db.JSON, default=list)  # List of feature descriptions
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
            'is_active': self.is_active
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

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref=db.backref('subscription', uselist=False))
    tier = db.relationship('SubscriptionTier', backref=db.backref('subscriptions', lazy='dynamic'))

    def has_credits(self) -> bool:
        """Check if user has available credits"""
        return self.credits_remaining > 0

    def use_credit(self) -> bool:
        """
        Deduct one credit from user's account.

        Returns:
            bool: True if credit was deducted, False if no credits available
        """
        if self.credits_remaining <= 0:
            return False

        self.credits_remaining -= 1
        self.credits_used_this_month += 1
        self.total_credits_used += 1
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

    # Success tracking
    success = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('usage_logs', lazy='dynamic'))
    conversation = db.relationship('Conversation', backref=db.backref('usage_logs', lazy='dynamic'))

    def to_dict(self):
        """Convert usage log to dictionary"""
        return {
            'id': self.id,
            'action_type': self.action_type,
            'tool_name': self.tool_name,
            'credits_used': self.credits_used,
            'success': self.success,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<UsageLog user={self.user_id} action={self.action_type}>'
