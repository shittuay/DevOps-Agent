"""
API Gateway Routes
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
import time
from services.credit_service import CreditService

api_gateway_bp = Blueprint('api_gateway', __name__, url_prefix='/api-gateway')

_WEBHOOK_EVENTS = [
    {'id': 'resource.created', 'name': 'Resource Created'},
    {'id': 'resource.updated', 'name': 'Resource Updated'},
    {'id': 'resource.deleted', 'name': 'Resource Deleted'},
    {'id': 'incident.created', 'name': 'Incident Created'},
    {'id': 'incident.resolved', 'name': 'Incident Resolved'},
    {'id': 'alert.triggered', 'name': 'Alert Triggered'},
    {'id': 'deployment.started', 'name': 'Deployment Started'},
    {'id': 'deployment.completed', 'name': 'Deployment Completed'},
    {'id': 'deployment.failed', 'name': 'Deployment Failed'},
    {'id': 'cost.threshold', 'name': 'Cost Threshold Exceeded'},
]


def api_key_required(f):
    """Decorator to validate API key and inject X-RateLimit-* headers."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from services.api_gateway import APIGatewayService

        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({'error': 'API key required', 'docs': '/developers'}), 401

        service = APIGatewayService()
        key_record = service.get_api_key_by_key(api_key)

        if not key_record:
            return jsonify({'error': 'Invalid API key', 'docs': '/developers'}), 401

        allowed, rate_info = service.check_rate_limit(key_record)
        if not allowed:
            resp = jsonify({'error': 'Rate limit exceeded', 'retry_after': rate_info.get('retry_after', 3600)})
            resp.status_code = 429
            resp.headers['X-RateLimit-Limit'] = str(rate_info.get('limit', 1000))
            resp.headers['X-RateLimit-Remaining'] = '0'
            resp.headers['Retry-After'] = str(rate_info.get('retry_after', 3600))
            return resp

        request.api_key = key_record
        request._rate_info = rate_info
        response = f(*args, **kwargs)

        # Inject rate limit headers into every successful response
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(rate_info.get('limit', 1000))
            response.headers['X-RateLimit-Remaining'] = str(rate_info.get('remaining', 0))
        return response
    return decorated_function


# Dashboard routes
@api_gateway_bp.route('/')
@login_required
def dashboard():
    """API Gateway dashboard"""
    return render_template('api_gateway/dashboard.html')


@api_gateway_bp.route('/keys')
@login_required
def list_keys():
    """List API keys"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    keys = service.get_user_api_keys(current_user.id)
    return render_template('api_gateway/keys.html', keys=keys)


@api_gateway_bp.route('/keys/create', methods=['GET', 'POST'])
@login_required
def create_key():
    """Create new API key"""
    if request.method == 'POST':
        from services.api_gateway import APIGatewayService
        service = APIGatewayService()

        try:
            rate_limit = max(1, min(int(request.form.get('rate_limit', 1000)), 100000))
        except (ValueError, TypeError):
            rate_limit = 1000
        try:
            expires_days = max(0, min(int(request.form.get('expires_days', 0)), 365))
        except (ValueError, TypeError):
            expires_days = 0

        name = (request.form.get('name') or '')[:100]
        scopes = request.form.getlist('scopes') or ['agent']

        api_key, plain_key = service.create_api_key(
            user_id=current_user.id,
            name=name,
            scopes=scopes,
            expires_in_days=expires_days or None
        )
        if api_key:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({'success': True, 'key': plain_key, 'id': api_key.id, 'name': api_key.name})
            flash(f'API Key created: {plain_key}. Save this key - it will not be shown again!', 'success')
            return redirect(url_for('api_gateway.list_keys'))
        else:
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                return jsonify({'success': False, 'error': 'Failed to create API key'}), 500
            flash('Failed to create API key.', 'error')

    scopes = [
        {'id': 'read:resources', 'name': 'Read Resources', 'description': 'View infrastructure resources'},
        {'id': 'write:resources', 'name': 'Write Resources', 'description': 'Create/update resources'},
        {'id': 'delete:resources', 'name': 'Delete Resources', 'description': 'Delete resources'},
        {'id': 'read:analytics', 'name': 'Read Analytics', 'description': 'View analytics data'},
        {'id': 'read:incidents', 'name': 'Read Incidents', 'description': 'View incidents'},
        {'id': 'write:incidents', 'name': 'Write Incidents', 'description': 'Create/update incidents'},
        {'id': 'admin', 'name': 'Admin Access', 'description': 'Full administrative access'},
    ]
    return render_template('api_gateway/create_key.html', scopes=scopes)


@api_gateway_bp.route('/keys/<int:key_id>/revoke', methods=['POST'])
@login_required
def revoke_key(key_id):
    """Revoke an API key"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.revoke_api_key(key_id, current_user.id):
        flash('API key revoked.', 'success')
    else:
        flash('Failed to revoke API key.', 'error')

    return redirect(url_for('api_gateway.list_keys'))


@api_gateway_bp.route('/webhooks')
@login_required
def list_webhooks():
    """List webhooks"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    webhooks = service.get_user_webhooks(current_user.id)
    return render_template('api_gateway/webhooks.html', webhooks=webhooks)


@api_gateway_bp.route('/webhooks/create', methods=['GET', 'POST'])
@login_required
def create_webhook():
    """Create new webhook"""
    if request.method == 'POST':
        from services.api_gateway import APIGatewayService
        service = APIGatewayService()

        name = (request.form.get('name') or '').strip()
        url = (request.form.get('url') or '').strip()
        if not name or not url:
            flash('Webhook name and URL are required.', 'error')
            return render_template('api_gateway/create_webhook.html', events=_WEBHOOK_EVENTS), 400

        webhook = service.create_webhook(
            user_id=current_user.id,
            name=name,
            url=url,
            events=request.form.getlist('events'),
        )
        if webhook:
            flash('Webhook created successfully!', 'success')
            return redirect(url_for('api_gateway.list_webhooks'))
        flash('Failed to create webhook.', 'error')
        return render_template('api_gateway/create_webhook.html', events=_WEBHOOK_EVENTS), 400

    return render_template('api_gateway/create_webhook.html', events=_WEBHOOK_EVENTS)


@api_gateway_bp.route('/webhooks/<int:webhook_id>/toggle', methods=['POST'])
@login_required
def toggle_webhook(webhook_id):
    """Enable/disable webhook"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.toggle_webhook(webhook_id, current_user.id):
        flash('Webhook status updated.', 'success')
    else:
        flash('Failed to update webhook.', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/webhooks/<int:webhook_id>/delete', methods=['POST'])
@login_required
def delete_webhook(webhook_id):
    """Delete webhook"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    if service.delete_webhook(webhook_id, current_user.id):
        flash('Webhook deleted.', 'success')
    else:
        flash('Failed to delete webhook.', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/webhooks/<int:webhook_id>/test', methods=['POST'])
@login_required
def test_webhook(webhook_id):
    """Test webhook delivery"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    result = service.test_webhook(webhook_id, current_user.id)
    if result.get('success'):
        flash('Test webhook delivered successfully!', 'success')
    else:
        flash(f'Webhook test failed: {result.get("error")}', 'error')

    return redirect(url_for('api_gateway.list_webhooks'))


@api_gateway_bp.route('/usage')
@login_required
def usage_stats():
    """API usage statistics"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()
    stats = service.get_api_usage_stats(current_user.id)
    return render_template('api_gateway/usage.html', stats=stats)


@api_gateway_bp.route('/docs')
@login_required
def api_docs():
    """API documentation"""
    return render_template('api_gateway/docs.html')


# External API endpoints (for SDK/external use)
@api_gateway_bp.route('/v1/resources', methods=['GET'])
@api_key_required
def api_list_resources():
    """External API: List resources"""
    from models import InfrastructureResource

    resources = InfrastructureResource.query.filter_by(
        user_id=request.api_key.user_id
    ).all()

    return jsonify({
        'resources': [{
            'id': r.id,
            'name': r.name,
            'type': r.resource_type,
            'provider': r.provider,
            'status': r.status,
            'region': r.region,
            'created_at': r.created_at.isoformat() if r.created_at else None
        } for r in resources]
    })


@api_gateway_bp.route('/v1/resources/<resource_id>', methods=['GET'])
@api_key_required
def api_get_resource(resource_id):
    """External API: Get resource details"""
    from models import InfrastructureResource

    resource = InfrastructureResource.query.filter_by(
        id=resource_id,
        user_id=request.api_key.user_id
    ).first()

    if not resource:
        return jsonify({'error': 'Resource not found'}), 404

    return jsonify({
        'resource': {
            'id': resource.id,
            'name': resource.name,
            'type': resource.resource_type,
            'provider': resource.provider,
            'status': resource.status,
            'region': resource.region,
            'resource_id': resource.resource_id,
            'metadata': resource.metadata,
            'created_at': resource.created_at.isoformat() if resource.created_at else None,
            'last_synced': resource.last_synced.isoformat() if resource.last_synced else None
        }
    })


@api_gateway_bp.route('/v1/analytics/costs', methods=['GET'])
@api_key_required
def api_get_costs():
    """External API: Get cost data"""
    from services.analytics_service import AnalyticsService
    from datetime import datetime, timedelta

    period = request.args.get('period', '30d')
    try:
        days = max(1, min(int(period.rstrip('dh')), 365))
    except (ValueError, TypeError):
        days = 30

    service = AnalyticsService(request.api_key.user_id)
    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify(data)


@api_gateway_bp.route('/v1/incidents', methods=['GET'])
@api_key_required
def api_list_incidents():
    """External API: List incidents"""
    from models import Incident

    status = request.args.get('status')
    query = Incident.query.filter_by(user_id=request.api_key.user_id)

    if status:
        query = query.filter_by(status=status)

    incidents = query.order_by(Incident.created_at.desc()).limit(100).all()

    return jsonify({
        'incidents': [{
            'id': i.id,
            'title': i.title,
            'severity': i.severity,
            'status': i.status,
            'created_at': i.created_at.isoformat() if i.created_at else None,
            'resolved_at': i.resolved_at.isoformat() if i.resolved_at else None
        } for i in incidents]
    })


@api_gateway_bp.route('/v1/incidents', methods=['POST'])
@api_key_required
def api_create_incident():
    """External API: Create incident"""
    from models import db, Incident
    from datetime import datetime

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    incident = Incident(
        user_id=request.api_key.user_id,
        title=data.get('title'),
        description=data.get('description'),
        severity=data.get('severity', 'medium'),
        status='open',
        created_at=datetime.utcnow()
    )

    db.session.add(incident)
    db.session.commit()

    from services.api_gateway import APIGatewayService
    gateway = APIGatewayService()
    gateway.trigger_webhooks(request.api_key.user_id, 'incident.created', {
        'incident_id': incident.id,
        'title': incident.title,
        'severity': incident.severity
    })

    return jsonify({
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'status': incident.status
        }
    }), 201


@api_gateway_bp.route('/v1/health', methods=['GET'])
def api_health():
    """External API: Health check — no auth required."""
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'timestamp': time.time(),
        'docs': '/developers',
    })


@api_gateway_bp.route('/v1/conversations', methods=['GET'])
@api_key_required
def api_list_conversations():
    """List the authenticated user's API conversations.

    Query params:
      limit  (int, default 20, max 100)
      offset (int, default 0)

    Response:
      { "conversations": [{ "id", "title", "message_count", "updated_at" }],
        "total": N }
    """
    from models import Conversation
    api_key_record = request.api_key
    user_id = api_key_record.user_id

    try:
        limit = min(int(request.args.get('limit', 20)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
    except ValueError:
        return jsonify({'error': 'limit and offset must be integers'}), 400

    # Only return conversations created via API (prefixed with 'api-')
    query = Conversation.query.filter(
        Conversation.user_id == user_id,
        Conversation.conversation_id.like('api-%')
    )
    total = query.count()
    convs = query.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit).all()

    return jsonify({
        'conversations': [
            {
                'id': c.conversation_id,
                'title': c.title or c.conversation_id,
                'message_count': c.message_count if hasattr(c, 'message_count') else 0,
                'updated_at': c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ],
        'total': total,
        'limit': limit,
        'offset': offset,
    })


@api_gateway_bp.route('/v1/tools', methods=['GET'])
@api_key_required
def api_list_tools():
    """List all available DevOps tools.

    Query params:
      provider  (aws | k8s | azure | gcp)  — filter by provider
      search    (string)                    — filter by name keyword

    Response:
      { "tools": [{ "name", "description", "provider" }], "total": N }
    """
    from flask import current_app
    try:
        from src.tools.aws_tools import get_tools as aws_tools
        from src.tools.kubernetes_tools import get_tools as k8s_tools
        from src.tools.azure_tools import get_tools as azure_tools
        from src.tools.gcp_tools import get_tools as gcp_tools
    except Exception as e:
        return jsonify({'error': f'Could not load tools: {e}'}), 500

    all_tools = (
        [{'name': t['name'], 'description': t['description'], 'provider': 'aws'} for t in aws_tools()] +
        [{'name': t['name'], 'description': t['description'], 'provider': 'k8s'} for t in k8s_tools()] +
        [{'name': t['name'], 'description': t['description'], 'provider': 'azure'} for t in azure_tools()] +
        [{'name': t['name'], 'description': t['description'], 'provider': 'gcp'} for t in gcp_tools()]
    )

    provider_filter = request.args.get('provider', '').lower()
    search = request.args.get('search', '').lower()

    if provider_filter:
        all_tools = [t for t in all_tools if t['provider'] == provider_filter]
    if search:
        all_tools = [t for t in all_tools if search in t['name'].lower() or search in t['description'].lower()]

    return jsonify({'tools': all_tools, 'total': len(all_tools)})


def _make_confirm_token(api_key_id: int, tool_name: str, params: dict) -> str:
    """Generate a stateless HMAC confirmation token for destructive tool calls.

    Token is deterministic for the same (api_key_id, tool_name, params, hour) tuple,
    valid for 1 hour. No server-side storage required.
    """
    import hashlib
    import hmac
    import json
    import os
    import time

    hour_bucket = str(int(time.time()) // 3600)
    payload = f"{api_key_id}:{tool_name}:{json.dumps(params, sort_keys=True)}:{hour_bucket}"
    secret = os.environ.get('SECRET_KEY', 'devops-agent-secret').encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def _verify_confirm_token(api_key_id: int, tool_name: str, params: dict, token: str) -> bool:
    """Verify a confirm token — accepts tokens from the current or previous hour."""
    import hashlib
    import hmac
    import json
    import os
    import time

    secret = os.environ.get('SECRET_KEY', 'devops-agent-secret').encode()
    for hour_offset in (0, -1):  # current hour or previous hour
        hour_bucket = str(int(time.time()) // 3600 + hour_offset)
        payload = f"{api_key_id}:{tool_name}:{json.dumps(params, sort_keys=True)}:{hour_bucket}"
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, token):
            return True
    return False


@api_gateway_bp.route('/v1/execute', methods=['POST'])
@api_key_required
def api_execute_tool():
    """Execute a specific DevOps tool directly (no AI layer).

    Requires Professional or Business tier.

    Request body:
      {
        "tool": "list_ec2_instances",
        "params": { "region": "us-east-1" },
        "confirm_token": "<token>"   // required for high/medium risk tools
      }

    For destructive tools, the first call returns 403 with a confirm_token.
    Re-send the same request with that token included to execute.

    Response:
      { "result": { ... }, "tool": "list_ec2_instances", "credits_remaining": N }
    """
    from flask import current_app
    from models import db, UserSubscription, UsageLog

    api_key_record = request.api_key
    user_id = api_key_record.user_id

    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    tier_name = sub.tier.name if (sub and sub.tier) else 'free'
    if tier_name not in ('professional', 'business'):
        return jsonify({
            'error': 'api_access_restricted',
            'message': 'Direct tool execution requires Professional ($99/mo) or Business ($299/mo).',
            'upgrade_url': '/billing'
        }), 403

    if not sub.has_credits():
        return jsonify({'error': 'insufficient_credits', 'credits_remaining': 0}), 402

    data = request.get_json(silent=True) or {}
    tool_name = (data.get('tool') or '').strip()
    params = data.get('params') or {}
    confirm_token = (data.get('confirm_token') or '').strip()

    if not tool_name:
        return jsonify({'error': 'tool is required'}), 400
    if not isinstance(params, dict):
        return jsonify({'error': 'params must be an object'}), 400

    # Find the tool handler
    from src.tools.aws_tools import get_tools as aws_tools
    from src.tools.kubernetes_tools import get_tools as k8s_tools
    from src.tools.azure_tools import get_tools as azure_tools
    from src.tools.gcp_tools import get_tools as gcp_tools

    all_tools = {}
    for t in aws_tools() + k8s_tools() + azure_tools() + gcp_tools():
        all_tools[t['name']] = t

    if tool_name not in all_tools:
        return jsonify({'error': f'Unknown tool: {tool_name}. See GET /v1/tools for available tools.'}), 404

    # Safety gate — run SafetyValidator before any execution
    try:
        from src.agent.safety import SafetyValidator
        validation = SafetyValidator().validate_tool_call(tool_name, params)
    except Exception as e:
        # Deliberate fail-open (matches routes/mcp.py and the Haiku
        # guardrail screen), but log it — a silently-broken validator would
        # otherwise disable confirmation gating for every high-risk tool
        # call indefinitely with zero operational visibility.
        current_app.logger.error(f"Safety validator raised for tool '{tool_name}', executing without a safety gate: {e}")
        validation = None

    if validation and validation.requires_confirmation:
        # High/medium risk tool — require explicit confirmation token
        if not confirm_token or not _verify_confirm_token(api_key_record.id, tool_name, params, confirm_token):
            token = _make_confirm_token(api_key_record.id, tool_name, params)
            return jsonify({
                'error': 'tool_requires_confirmation',
                'risk': validation.risk_level,
                'reason': validation.reason,
                'confirm_token': token,
                'message': (
                    f"'{tool_name}' is a {validation.risk_level}-risk operation. "
                    "Re-send this request with the confirm_token field to proceed. "
                    "Token expires in ~1 hour."
                ),
            }), 403

        current_app.logger.warning(
            f"API confirmed destructive tool execution: user={user_id} "
            f"key={api_key_record.id} tool={tool_name} risk={validation.risk_level} params={params}"
        )

    # Set the requester's cloud credential context before running the tool —
    # without it, aws_tools._get_boto_client (and the Azure/GCP equivalents)
    # have no user to resolve credentials for; they either fail closed or,
    # worse, run against whatever context a previous request left on this
    # worker (see services/approval_service.py::_execute_tool for the same
    # pattern, and CLAUDE.md's "Any code path that runs a tool outside
    # process_message_isolated/process_message_streaming" note).
    from app import agent as _agent
    _agent._set_cloud_user_context(user_id)
    try:
        result = all_tools[tool_name]['handler'](**params)
    except TypeError as e:
        return jsonify({'error': f'Invalid params for {tool_name}: {e}'}), 400
    except Exception as e:
        current_app.logger.error(f"Tool execution error {tool_name}: {e}", exc_info=True)
        return jsonify({'error': f'Tool execution failed: {e}'}), 500
    finally:
        _agent._clear_cloud_user_context()

    db.session.add(UsageLog(
        user_id=user_id, action_type='api_tool_use',
        tool_name=tool_name, credits_used=1, success=True,
    ))
    remaining = CreditService.deduct(user_id, commit=False)
    db.session.commit()

    return jsonify({
        'result': result,
        'tool': tool_name,
        'credits_remaining': remaining,
    })


@api_gateway_bp.route('/v1/agent/stream', methods=['POST'])
@api_key_required
def api_agent_stream():
    """Stream an agent response via Server-Sent Events.

    Requires Professional or Business tier.

    Request body:  same as POST /v1/agent
    SSE events:
      data: {"type": "chunk",   "content": "..."}
      data: {"type": "tool",    "name": "list_ec2_instances"}
      data: {"type": "done",    "tools_used": [...], "credits_remaining": N, "conversation_id": "..."}
      data: {"type": "error",   "message": "..."}
    """
    from flask import Response, current_app, stream_with_context
    from models import db, UserSubscription, UsageLog, ChatMessage
    import json as _json
    import re

    api_key_record = request.api_key
    user_id = api_key_record.user_id

    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    tier_name = sub.tier.name if (sub and sub.tier) else 'free'
    if tier_name not in ('professional', 'business'):
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Developer API requires Professional or Business plan.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    if not sub.has_credits():
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Insufficient credits.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    data = request.get_json(silent=True) or {}
    from services.input_sanitizer import sanitize_input, validate_message
    from src.agent.guardrails import screen_message
    from models import User

    message = sanitize_input((data.get('message') or '').strip())
    if not message:
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'message is required'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    api_user = User.query.get(user_id)

    # Guardrail layer 1: check if account is locked out from repeated violations
    if api_user.is_guardrail_blocked():
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Account temporarily restricted due to repeated policy violations.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    # Guardrail layer 2: injection pattern check
    is_valid, reason = validate_message(message)
    if not is_valid:
        api_user.record_guardrail_violation()
        db.session.commit()
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': reason})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    # Guardrail layer 3: Haiku harmlessness screen
    guardrail_result = screen_message(message)
    if guardrail_result.blocked:
        api_user.record_guardrail_violation()
        db.session.commit()
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Message blocked by content policy. Repeated violations may result in account suspension.'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    raw_conv_id = data.get('conversation_id')
    if raw_conv_id and isinstance(raw_conv_id, str) and re.match(r'^[a-zA-Z0-9_-]{1,64}$', raw_conv_id):
        conversation_id = raw_conv_id if raw_conv_id.startswith('api-') else f'api-{raw_conv_id}'
    else:
        conversation_id = f'api-{api_key_record.id}-default'

    history_rows = ChatMessage.query.filter_by(
        user_id=user_id, conversation_id=conversation_id
    ).order_by(ChatMessage.created_at.desc()).limit(20).all()
    history = [{'role': r.role, 'content': r.content} for r in reversed(history_rows)]

    agent_instance = current_app.config.get('DEVOPS_AGENT')
    if not agent_instance:
        def _err():
            yield f"data: {_json.dumps({'type': 'error', 'message': 'Agent not initialized'})}\n\n"
        return Response(stream_with_context(_err()), mimetype='text/event-stream')

    from services.model_router import resolve_model_with_preference
    from models import UserPreferences
    prefs = UserPreferences.query.filter_by(user_id=user_id).first()
    prefs_provider = getattr(prefs, 'preferred_model_provider', None) if prefs else None
    model_config = resolve_model_with_preference(tier_name, prefs_provider)

    def generate():
        try:
            full_response = []
            for chunk in agent_instance.process_message_streaming(
                user_message=message,
                conversation_history=history,
                user_id=user_id,
                provider=model_config.provider if model_config.provider == 'kimi' else None,
                model_override=model_config.model,
            ):
                if isinstance(chunk, dict):
                    if chunk.get('type') == 'tool_use':
                        yield f"data: {_json.dumps({'type': 'tool', 'name': chunk.get('name', '')})}\n\n"
                    elif chunk.get('type') == 'text':
                        text = chunk.get('text', '')
                        full_response.append(text)
                        yield f"data: {_json.dumps({'type': 'chunk', 'content': text})}\n\n"
                elif isinstance(chunk, str):
                    full_response.append(chunk)
                    yield f"data: {_json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            response_text = ''.join(full_response)
            tools_used = getattr(agent_instance, 'last_tools_used', [])

            with current_app.app_context():
                from models import db, ChatMessage, UsageLog, UserSubscription
                _sub = UserSubscription.query.filter_by(user_id=user_id).first()
                db.session.add(ChatMessage(user_id=user_id, conversation_id=conversation_id, role='user', content=message))
                db.session.add(ChatMessage(user_id=user_id, conversation_id=conversation_id, role='assistant', content=response_text))
                db.session.add(UsageLog(user_id=user_id, conversation_id=conversation_id,
                    action_type='api_tool_use' if tools_used else 'api_message',
                    tool_name=tools_used[0] if tools_used else None,
                    credits_used=1, success=True, ai_model=model_config.model))
                credits_left = CreditService.deduct(user_id, commit=False)
                db.session.commit()

            yield f"data: {_json.dumps({'type': 'done', 'tools_used': tools_used, 'credits_remaining': credits_left, 'conversation_id': conversation_id})}\n\n"

        except Exception as e:
            current_app.logger.error(f"API stream error for user {user_id}: {e}", exc_info=True)
            yield f"data: {_json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@api_gateway_bp.route('/v1/agent', methods=['POST'])
@api_key_required
def api_agent():
    """
    Developer REST API — run an agent query programmatically.

    Required header:  X-API-Key: <your_api_key>
    Content-Type:     application/json

    Request body:
      {
        "message": "List all EC2 instances in us-east-1",
        "conversation_id": "optional-string-for-session-continuity"
      }

    Response:
      {
        "response": "...",
        "tools_used": ["list_ec2_instances"],
        "credits_remaining": 42,
        "conversation_id": "..."
      }

    This endpoint requires Professional or Business tier.
    Free and Starter tier users receive a 403 with an upgrade message.
    """
    from flask import current_app
    from models import db, UserSubscription, UsageLog, ConversionEvent
    import json as _json

    api_key_record = request.api_key
    user_id = api_key_record.user_id

    # Enforce Professional/Business tier gate
    sub = UserSubscription.query.filter_by(user_id=user_id).first()
    tier_name = sub.tier.name if (sub and sub.tier) else 'free'
    if tier_name not in ('professional', 'business'):
        return jsonify({
            'error': 'api_access_restricted',
            'message': 'Developer API access requires Professional ($99/mo) or Business ($299/mo) plan.',
            'upgrade_url': '/billing'
        }), 403

    if not sub.has_credits():
        return jsonify({'error': 'insufficient_credits', 'credits_remaining': 0}), 402

    from services.input_sanitizer import sanitize_input, validate_message
    from src.agent.guardrails import screen_message
    from models import User

    data = request.get_json(silent=True) or {}
    message = sanitize_input((data.get('message') or '').strip())
    if not message:
        return jsonify({'error': 'message is required'}), 400

    api_user = User.query.get(user_id)

    # Guardrail layer 1: check if account is locked out from repeated violations
    if api_user.is_guardrail_blocked():
        return jsonify({'error': 'Account temporarily restricted due to repeated policy violations.'}), 403

    # Guardrail layer 2: injection pattern check
    is_valid, validation_reason = validate_message(message)
    if not is_valid:
        api_user.record_guardrail_violation()
        db.session.commit()
        return jsonify({'error': validation_reason}), 400

    # Guardrail layer 3: Haiku harmlessness screen
    guardrail_result = screen_message(message)
    if guardrail_result.blocked:
        api_user.record_guardrail_violation()
        db.session.commit()
        return jsonify({'error': 'Message blocked by content policy. Repeated violations may result in account suspension.'}), 400

    import re
    raw_conv_id = data.get('conversation_id')
    if raw_conv_id is not None:
        if not isinstance(raw_conv_id, str) or len(raw_conv_id) > 64 or not re.match(r'^[a-zA-Z0-9_-]+$', raw_conv_id):
            return jsonify({'error': 'conversation_id must be alphanumeric (hyphens/underscores allowed), max 64 chars'}), 400
        # Enforce api- prefix to prevent collision with web-UI conversation IDs
        if not raw_conv_id.startswith('api-'):
            raw_conv_id = f'api-{raw_conv_id}'
        conversation_id = raw_conv_id
    else:
        conversation_id = f'api-{api_key_record.id}-default'

    # Load recent conversation history for this conversation_id (last 20 turns)
    from models import ChatMessage
    history_rows = ChatMessage.query.filter_by(
        user_id=user_id, conversation_id=conversation_id
    ).order_by(ChatMessage.created_at.desc()).limit(20).all()
    history = [{'role': r.role, 'content': r.content} for r in reversed(history_rows)]

    # Run the agent
    from src.agent.core import DevOpsAgent
    from services.model_router import resolve_model_with_preference

    agent_instance = current_app.config.get('DEVOPS_AGENT')
    if agent_instance is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    prefs_provider = None
    from models import UserPreferences
    prefs = UserPreferences.query.filter_by(user_id=user_id).first()
    if prefs:
        prefs_provider = getattr(prefs, 'preferred_model_provider', None)

    model_config = resolve_model_with_preference(tier_name, prefs_provider)
    provider = model_config.provider

    try:
        response_text = agent_instance.process_message_isolated(
            user_message=message,
            conversation_history=history,
            user_id=user_id,
            provider=provider if provider == 'kimi' else None,
            model_override=model_config.model,
        )
        tools_used = agent_instance.last_tools_used
        success = True
    except Exception as e:
        current_app.logger.error(f"API agent error for user {user_id}: {e}", exc_info=True)
        return jsonify({'error': 'Agent error', 'detail': str(e)}), 500

    # Save user message + assistant response
    db.session.add(ChatMessage(user_id=user_id, conversation_id=conversation_id, role='user', content=message))
    db.session.add(ChatMessage(user_id=user_id, conversation_id=conversation_id, role='assistant', content=response_text))

    # Log usage
    db.session.add(UsageLog(
        user_id=user_id,
        conversation_id=conversation_id,
        action_type='api_tool_use' if tools_used else 'api_message',
        tool_name=tools_used[0] if tools_used else None,
        credits_used=1,
        success=success,
        ai_model=model_config.model,
    ))
    for t in tools_used[1:]:
        db.session.add(UsageLog(
            user_id=user_id, conversation_id=conversation_id,
            action_type='api_tool_use', tool_name=t, credits_used=0,
            success=True, ai_model=model_config.model,
        ))

    remaining = CreditService.deduct(user_id, commit=False)
    db.session.commit()

    return jsonify({
        'response': response_text,
        'tools_used': tools_used,
        'credits_remaining': remaining,
        'conversation_id': conversation_id,
    })


# Dashboard API endpoints
@api_gateway_bp.route('/api/keys')
@login_required
def api_list_keys():
    """JSON endpoint: list current user's API keys."""
    from services.api_gateway import APIGatewayService
    keys = APIGatewayService().get_user_api_keys(current_user.id)
    return jsonify({'keys': [k.to_dict() for k in keys]})


@api_gateway_bp.route('/api/stats')
@login_required
def dashboard_stats():
    """Get API gateway stats for dashboard"""
    from services.api_gateway import APIGatewayService
    service = APIGatewayService()

    stats = service.get_api_usage_stats(current_user.id)
    keys = service.get_user_api_keys(current_user.id)
    webhooks = service.get_user_webhooks(current_user.id)

    return jsonify({
        'total_keys': len(keys),
        'active_keys': len([k for k in keys if k.is_active]),
        'total_webhooks': len(webhooks),
        'active_webhooks': len([w for w in webhooks if w.is_active]),
        'requests_today': stats.get('requests_today', 0),
        'requests_month': stats.get('requests_month', 0),
        'rate_limit_hits': stats.get('rate_limit_hits', 0)
    })
