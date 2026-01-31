"""
Route blueprints for DevOps Agent.
"""

from .admin import admin_bp
from .incidents import incidents_bp
from .monitoring import monitoring_bp
from .notifications import notifications_bp
from .optimization import optimization_bp
from .analysis import analysis_bp
from .webhooks import webhooks_bp
from .chatops import chatops_bp
from .drift import drift_bp
from .scaling import scaling_bp

__all__ = ['admin_bp', 'incidents_bp', 'monitoring_bp', 'notifications_bp', 'optimization_bp', 'analysis_bp', 'webhooks_bp', 'chatops_bp', 'drift_bp', 'scaling_bp']
