"""
REST API Package

Provides versioned REST API endpoints for DevOps Agent.
"""

from flask import Blueprint

# Create API blueprint
api_bp = Blueprint('api', __name__, url_prefix='/api')

# Import and register versioned APIs
from api.v1 import api_v1_bp
api_bp.register_blueprint(api_v1_bp)

__all__ = ['api_bp']
