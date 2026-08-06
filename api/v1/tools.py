"""
Tools API Endpoint

Allows CLI and programmatic clients to execute individual DevOps tools directly,
bypassing the AI agent layer. Requires an API key with 'write' scope.
"""

import logging
from flask import jsonify, request, g, current_app
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key
from src.agent.safety import SafetyValidator

logger = logging.getLogger(__name__)

# One shared source of truth for tool risk. The REST API MUST classify tools
# identically to the chat UI and the MCP server — all three route through
# SafetyValidator.validate_tool_call() so a tool added to a risk set in
# safety.py is automatically enforced here too. (A prior local re-implementation
# only knew a 12-tool subset, letting write-scope keys run execute_command,
# the *_api_write passthroughs, and the entire medium-risk set unconfirmed.)
_safety_validator = SafetyValidator()


@api_v1_bp.route('/tools/execute', methods=['POST'])
@require_api_key(scope='write')
def execute_tool():
    """
    Execute a DevOps tool directly.

    Request body:
        tool   (string, required): Tool name (e.g. "list_ec2_instances")
        params (object, optional): Tool input parameters
        confirm (bool, optional): Required for high-risk tools (default: false)

    Returns:
        result: Tool output
        tool:   Tool name echoed back
    """
    body = request.get_json(silent=True) or {}
    tool_name = body.get('tool', '').strip()
    params = body.get('params') or {}
    confirmed = bool(body.get('confirm', False))

    if not tool_name:
        return jsonify({'error': 'Missing required field: tool'}), 400

    agent = current_app.config.get('DEVOPS_AGENT')
    if not agent:
        return jsonify({'error': 'Agent not initialized'}), 503

    if tool_name not in agent.tools:
        available = sorted(agent.tools.keys())
        return jsonify({
            'error': f"Unknown tool: {tool_name}",
            'available_count': len(available),
        }), 404

    # Shared safety gate — same classification the chat UI and MCP server use.
    verdict = _safety_validator.validate_tool_call(tool_name, params)
    if not verdict.is_safe:
        logger.warning("Blocked unsafe tool %s for api_user=%s: %s",
                       tool_name, getattr(g, 'api_user', None) and g.api_user.id, verdict.reason)
        return jsonify({
            'error': verdict.reason or 'This tool is blocked by the safety validator.',
            'tool': tool_name,
            'risk_level': verdict.risk_level,
        }), 403

    # High- and medium-risk tools both require confirmation in the UI; enforce
    # the same here so a write-scope key can't run them silently.
    if verdict.requires_confirmation and not confirmed:
        return jsonify({
            'error': 'This tool requires confirmation. Re-send with "confirm": true to proceed.',
            'tool': tool_name,
            'risk_level': verdict.risk_level,
            'requires_confirm': True,
        }), 409

    # process_message_isolated/process_message_streaming are the only two entry
    # points that set this automatically. Direct tool execution here bypasses
    # both, so without this call aws_tools._get_boto_client (and the Azure/GCP
    # equivalents) has no per-user credential context to look up — same gap
    # fixed for services/approval_service.py's _execute_tool.
    api_user = getattr(g, 'api_user', None)
    if api_user:
        agent._set_cloud_user_context(api_user.id)
    try:
        result = agent.tools[tool_name](**params)
        return jsonify({'tool': tool_name, 'result': result})
    except TypeError as e:
        logger.warning("Tool param error for %s: %s", tool_name, e)
        return jsonify({'error': f"Invalid parameters: {e}", 'tool': tool_name}), 422
    except Exception as e:
        logger.error("Tool execution error for %s: %s", tool_name, e, exc_info=True)
        return jsonify({'error': str(e), 'tool': tool_name}), 500
    finally:
        if api_user:
            agent._clear_cloud_user_context()
