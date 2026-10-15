"""
Route blueprints for DevOps Agent.
"""

from .auth import auth_bp
from .billing import billing_bp
from .admin import admin_bp
from .drift import drift_bp
from .ai_infrastructure import ai_infrastructure_bp
from .analytics import analytics_bp
from .api_gateway import api_gateway_bp
from .organizations import organizations_bp

__all__ = [
    'auth_bp', 'billing_bp', 'admin_bp',
    'drift_bp', 'ai_infrastructure_bp', 'analytics_bp',
    'api_gateway_bp', 'organizations_bp'
]
