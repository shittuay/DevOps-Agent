"""
API v1 - REST API endpoints

This module provides the v1 REST API for DevOps Agent.
All endpoints require API key authentication unless noted otherwise.
"""

from flask import Blueprint, jsonify, request, g
from functools import wraps

# Create v1 blueprint
api_v1_bp = Blueprint('api_v1', __name__, url_prefix='/v1')

# Import route modules
from api.v1 import auth, resources, conversations, users, api_keys, health, tools


# ==========================================
# Deprecation (2026-10-14): /api-gateway/v1 is the one developer API.
# Every response says so; nothing is removed before the Sunset date.
# ==========================================

import os as _os
from datetime import datetime as _dt, timezone as _tz
from email.utils import format_datetime as _fmt_http_date

API_V1_SUNSET = _os.environ.get('API_V1_SUNSET', '2027-01-12')  # ISO date; change to move the date

# Old path prefix -> new path prefix, for the successor-version Link header.
_SUCCESSORS = [
    ('/api/v1/auth/me', '/api-gateway/v1/me'),
    ('/api/v1/users/me', '/api-gateway/v1/me'),
    ('/api/v1/resources/security', '/api-gateway/v1/security/findings'),
    ('/api/v1/tools/execute', '/api-gateway/v1/execute'),
    ('/api/v1/chat/stream', '/api-gateway/v1/agent/stream'),
    ('/api/v1/', '/api-gateway/v1/'),
]


def _successor(path: str) -> str:
    for old, new in _SUCCESSORS:
        if path.startswith(old):
            return new + path[len(old):]
    return '/api-gateway/v1/'


@api_v1_bp.after_request
def _deprecation_headers(response):
    try:
        sunset = _dt.strptime(API_V1_SUNSET, '%Y-%m-%d').replace(tzinfo=_tz.utc)
        response.headers['Sunset'] = _fmt_http_date(sunset, usegmt=True)
    except ValueError:
        pass
    response.headers['Deprecation'] = 'true'
    response.headers['Link'] = (f'<{_successor(request.path)}>; rel="successor-version", '
                                '<https://devopsagent.io/developers>; rel="deprecation"')
    return response


# ==========================================
# OpenAPI Specification
# ==========================================

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "DevOps Agent API",
        "description": "REST API for programmatic access to DevOps Agent platform",
        "version": "1.0.0",
        "contact": {
            "name": "DevOps Agent Support",
            "email": "support@devopsagent.io"
        },
        "license": {
            "name": "Proprietary"
        }
    },
    "servers": [
        {
            "url": "/api/v1",
            "description": "Production API server"
        }
    ],
    "security": [
        {"ApiKeyAuth": []},
        {"BearerAuth": []}
    ],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "API key for authentication"
            },
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Bearer token (API key)"
            }
        },
        "schemas": {
            "Error": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "message": {"type": "string"},
                    "code": {"type": "integer"}
                }
            },
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "email": {"type": "string", "format": "email"},
                    "username": {"type": "string"},
                    "full_name": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"}
                }
            },
            "Conversation": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"}
                }
            },
            "Message": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "content": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"}
                }
            },
            "CloudResource": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "cloud_provider": {"type": "string", "enum": ["aws", "gcp", "azure"]},
                    "resource_type": {"type": "string"},
                    "resource_id": {"type": "string"},
                    "resource_name": {"type": "string"},
                    "status": {"type": "string"},
                    "region": {"type": "string"}
                }
            },
            "APIKey": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "key_prefix": {"type": "string"},
                    "scopes": {"type": "array", "items": {"type": "string"}},
                    "is_active": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "expires_at": {"type": "string", "format": "date-time"}
                }
            },
            "Subscription": {
                "type": "object",
                "properties": {
                    "tier": {"type": "string"},
                    "credits_remaining": {"type": "integer"},
                    "credits_used_this_month": {"type": "integer"}
                }
            }
        },
        "responses": {
            "Unauthorized": {
                "description": "Authentication required",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            },
            "Forbidden": {
                "description": "Insufficient permissions",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            },
            "NotFound": {
                "description": "Resource not found",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            },
            "RateLimited": {
                "description": "Rate limit exceeded",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Error"}
                    }
                }
            }
        }
    },
    "paths": {}  # Paths are dynamically generated
}


@api_v1_bp.route('/openapi.json')
def openapi_spec():
    """Return OpenAPI specification."""
    return jsonify(OPENAPI_SPEC)


@api_v1_bp.route('/docs')
def api_docs():
    """Render API documentation page."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>DevOps Agent API Documentation</title>
        <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
        <style>
            body { margin: 0; padding: 0; }
            .swagger-ui .topbar { display: none; }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script>
            SwaggerUIBundle({
                url: '/api/v1/openapi.json',
                dom_id: '#swagger-ui',
                presets: [SwaggerUIBundle.presets.apis],
                layout: "BaseLayout"
            });
        </script>
    </body>
    </html>
    """
    return html
