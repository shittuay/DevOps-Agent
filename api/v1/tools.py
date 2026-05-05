"""
Tools API Endpoint

Allows CLI and programmatic clients to execute individual DevOps tools directly,
bypassing the AI agent layer. Requires an API key with 'write' scope.
"""

import logging
from flask import jsonify, request, g, current_app
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key

logger = logging.getLogger(__name__)

# Tools that require confirmation in the web UI are blocked here unless
# the request includes "confirm": true. This mirrors safety.py risk levels.
_HIGH_RISK_PREFIXES = ('delete_', 'terminate_', 'destroy_', 'remove_', 'drop_', 'purge_')
_HIGH_RISK_TOOLS = {
    'abort_jenkins_build', 'delete_jenkins_build', 'terraform_destroy',
    'terraform_state_rm', 'delete_sonar_project', 'nexus_delete_repository',
    'nexus_delete_component', 'nexus_delete_asset', 'git_reset_to_commit',
    'git_clean_working_directory', 'git_force_push_branch', 'resize_ec2_instance',
}


def _is_high_risk(tool_name: str, params: dict) -> bool:
    if tool_name in _HIGH_RISK_TOOLS:
        return True
    if any(tool_name.startswith(p) for p in _HIGH_RISK_PREFIXES):
        return True
    if tool_name == 'manage_ec2_instance' and params.get('action') == 'terminate':
        return True
    return False


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

    if _is_high_risk(tool_name, params) and not confirmed:
        return jsonify({
            'error': 'This tool is high-risk. Re-send with "confirm": true to proceed.',
            'tool': tool_name,
            'requires_confirm': True,
        }), 409

    try:
        result = agent.tools[tool_name](**params)
        return jsonify({'tool': tool_name, 'result': result})
    except TypeError as e:
        logger.warning("Tool param error for %s: %s", tool_name, e)
        return jsonify({'error': f"Invalid parameters: {e}", 'tool': tool_name}), 422
    except Exception as e:
        logger.error("Tool execution error for %s: %s", tool_name, e, exc_info=True)
        return jsonify({'error': str(e), 'tool': tool_name}), 500
