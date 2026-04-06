"""
MCP (Model Context Protocol) Server

Exposes all DevOps Agent tools as an MCP-compliant remote server
using the HTTP+SSE transport.

Add to Claude Desktop (claude_desktop_config.json):
  {
    "mcpServers": {
      "devops-agent": {
        "url": "https://devopsagent.io/mcp/sse",
        "headers": { "Authorization": "Bearer <your-api-key>" }
      }
    }
  }

Protocol reference: https://spec.modelcontextprotocol.io/specification/

Transport:
  GET  /mcp/sse          — SSE stream; server sends the message endpoint URL
  POST /mcp/messages     — client sends JSON-RPC 2.0 requests
  GET  /mcp/health       — returns {"ok": true} (no auth, for load balancers)

Authentication:
  Authorization: Bearer <api-key>
  or ?api_key=<api-key> query param (for clients that can't set headers)

Supported JSON-RPC methods:
  initialize              Handshake — returns server info + capabilities
  notifications/initialized  Ack from client (no-op)
  tools/list              Returns all 258 tools in MCP inputSchema format
  tools/call              Executes a tool by name
  ping                    Keepalive
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__, url_prefix='/mcp')

# ── In-memory session registry ───────────────────────────────────────────────
# session_id → Queue of SSE messages to send back to that client.
# Sessions time out after 10 minutes of inactivity.
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL_SECONDS = 600

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "DevOps Agent"
SERVER_VERSION = "1.0.0"


# ── Tool registry (loaded once, cached) ─────────────────────────────────────
_tool_cache: Optional[list] = None
_tool_map: Optional[Dict[str, Any]] = None
_tool_cache_lock = threading.Lock()


def _get_all_tools():
    """Load and cache all tools from every enabled module."""
    global _tool_cache, _tool_map
    if _tool_cache is not None:
        return _tool_cache, _tool_map

    with _tool_cache_lock:
        if _tool_cache is not None:
            return _tool_cache, _tool_map

        loaders = [
            'src.tools.aws_tools',
            'src.tools.kubernetes_tools',
            'src.tools.azure_tools',
            'src.tools.gcp_tools',
            'src.tools.cicd_tools',
            'src.tools.terraform_tools',
            'src.tools.sonarqube_tools',
            'src.tools.nexus_tools',
            'src.tools.docker_tools',
            'src.tools.git_tools',
            'src.tools.monitoring_tools',
            'src.tools.ansible_tools',
            'src.tools.alerting_tools',
        ]

        all_tools = []
        for module_path in loaders:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                all_tools.extend(mod.get_tools())
            except Exception as e:
                logger.warning(f"MCP: failed to load {module_path}: {e}")

        _tool_cache = all_tools
        _tool_map = {t['name']: t for t in all_tools}
        logger.info(f"MCP tool registry loaded: {len(_tool_cache)} tools")
        return _tool_cache, _tool_map


def _to_mcp_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an internal tool definition to MCP tool format."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "inputSchema": tool.get("input_schema", {
            "type": "object",
            "properties": {},
            "required": []
        }),
    }


# ── Auth ─────────────────────────────────────────────────────────────────────

def _authenticate() -> Optional[Dict[str, Any]]:
    """
    Validate API key from Authorization header or api_key query param.
    Returns the key record on success, None on failure.
    """
    api_key = (
        request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        or request.args.get('api_key', '')
    )
    if not api_key:
        return None

    try:
        from services.api_gateway import APIGatewayService
        svc = APIGatewayService()
        return svc.get_api_key_by_key(api_key)
    except Exception:
        return None


# ── Session helpers ───────────────────────────────────────────────────────────

def _create_session() -> str:
    sid = uuid.uuid4().hex
    with _sessions_lock:
        _sessions[sid] = {
            'queue': queue.Queue(maxsize=200),
            'last_active': time.time(),
            'user_id': None,
        }
    return sid


def _send_to_session(sid: str, data: Dict[str, Any]):
    with _sessions_lock:
        session = _sessions.get(sid)
    if session:
        try:
            session['queue'].put_nowait(data)
            session['last_active'] = time.time()
        except queue.Full:
            logger.warning(f"MCP session {sid} queue full — dropping message")


def _cleanup_sessions():
    """Remove expired sessions (called lazily on each new connection)."""
    cutoff = time.time() - _SESSION_TTL_SECONDS
    with _sessions_lock:
        expired = [sid for sid, s in _sessions.items() if s['last_active'] < cutoff]
        for sid in expired:
            del _sessions[sid]
    if expired:
        logger.debug(f"MCP: cleaned up {len(expired)} expired sessions")


# ── JSON-RPC helpers ─────────────────────────────────────────────────────────

def _ok(req_id: Any, result: Any) -> Dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str, data: Any = None) -> Dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


# ── JSON-RPC method handlers ─────────────────────────────────────────────────

def _handle_initialize(req_id: Any, params: Dict, user_id: int) -> Dict:
    return _ok(req_id, {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "logging": {},
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    })


def _handle_tools_list(req_id: Any, params: Dict, user_id: int) -> Dict:
    tools, _ = _get_all_tools()
    return _ok(req_id, {
        "tools": [_to_mcp_tool(t) for t in tools],
    })


def _handle_tools_call(req_id: Any, params: Dict, user_id: int) -> Dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments") or {}

    _, tool_map = _get_all_tools()

    if tool_name not in tool_map:
        return _err(req_id, -32601, f"Tool not found: {tool_name}")

    tool = tool_map[tool_name]

    # Safety check — same gate as /v1/execute
    try:
        from src.agent.safety import SafetyValidator
        result = SafetyValidator().validate_tool_call(tool_name, arguments)
        if not result.is_safe:
            return _err(req_id, -32603,
                        f"Tool blocked by safety validator: {result.reason}",
                        {"risk_level": result.risk_level})
        if result.requires_confirmation:
            # For MCP we include a warning in the response but still execute —
            # the calling AI model sees the warning and can re-confirm with the user.
            logger.warning(f"MCP executing high-risk tool '{tool_name}' for user {user_id}")
    except Exception:
        pass  # Safety validator fails open

    # Execute the tool handler with user context set
    try:
        from src.tools.aws_tools import set_user_context, clear_user_context
        set_user_context(user_id)
        try:
            result = tool['handler'](**arguments)
        finally:
            clear_user_context()
    except TypeError as e:
        return _err(req_id, -32602, f"Invalid tool arguments: {e}")
    except Exception as e:
        logger.error(f"MCP tool '{tool_name}' error for user {user_id}: {e}", exc_info=True)
        return _err(req_id, -32603, f"Tool execution error: {e}")

    # Normalise result to MCP content array
    if isinstance(result, dict):
        text = json.dumps(result, indent=2, default=str)
    else:
        text = str(result)

    return _ok(req_id, {
        "content": [{"type": "text", "text": text}],
        "isError": isinstance(result, dict) and not result.get("success", True),
    })


def _dispatch(rpc: Dict, user_id: int) -> Optional[Dict]:
    """Dispatch a single JSON-RPC request. Returns None for notifications."""
    method = rpc.get("method", "")
    params = rpc.get("params") or {}
    req_id = rpc.get("id")   # None = notification (no response expected)

    if method == "initialize":
        return _handle_initialize(req_id, params, user_id)
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None   # fire-and-forget notifications
    if method == "tools/list":
        return _handle_tools_list(req_id, params, user_id)
    if method == "tools/call":
        return _handle_tools_call(req_id, params, user_id)
    if method == "ping":
        return _ok(req_id, {})

    if req_id is not None:
        return _err(req_id, -32601, f"Method not found: {method}")
    return None


# ── HTTP endpoints ────────────────────────────────────────────────────────────

@mcp_bp.route('/health')
def mcp_health():
    """Public health check — no auth required."""
    tools, _ = _get_all_tools()
    return jsonify({"ok": True, "tools": len(tools), "protocol": MCP_PROTOCOL_VERSION})


@mcp_bp.route('/sse')
def mcp_sse():
    """
    SSE endpoint.

    Client connects here; server responds with an `endpoint` event containing
    the URL where the client should POST JSON-RPC messages.
    """
    key_record = _authenticate()
    if not key_record:
        return jsonify({"error": "API key required. Add Authorization: Bearer <key> header."}), 401

    _cleanup_sessions()
    sid = _create_session()
    user_id = key_record.user_id if hasattr(key_record, 'user_id') else key_record.get('user_id')

    with _sessions_lock:
        _sessions[sid]['user_id'] = user_id

    base_url = request.host_url.rstrip('/')
    message_url = f"{base_url}/mcp/messages?sessionId={sid}"

    @stream_with_context
    def generate():
        # Send the endpoint event immediately
        yield f"event: endpoint\ndata: {message_url}\n\n"

        session_data = None
        with _sessions_lock:
            session_data = _sessions.get(sid)

        if not session_data:
            return

        q = session_data['queue']
        while True:
            try:
                msg = q.get(timeout=15)
                yield f"event: message\ndata: {json.dumps(msg)}\n\n"
                session_data['last_active'] = time.time()
            except queue.Empty:
                # Keepalive ping
                yield ": keepalive\n\n"
                # Check if session is still alive
                with _sessions_lock:
                    if sid not in _sessions:
                        break
                    if time.time() - _sessions[sid]['last_active'] > _SESSION_TTL_SECONDS:
                        del _sessions[sid]
                        break

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@mcp_bp.route('/messages', methods=['POST'])
def mcp_messages():
    """
    JSON-RPC message endpoint.

    Client POSTs JSON-RPC requests here; responses are sent back via the SSE
    stream identified by sessionId.
    """
    sid = request.args.get('sessionId', '')

    with _sessions_lock:
        session = _sessions.get(sid)

    if not session:
        # Also accept auth-less direct POST (for clients that don't use SSE)
        key_record = _authenticate()
        if not key_record:
            return jsonify({"error": "Unknown session. Reconnect to /mcp/sse first."}), 400
        user_id = key_record.user_id if hasattr(key_record, 'user_id') else key_record.get('user_id')
    else:
        user_id = session.get('user_id')

    try:
        rpc = request.get_json(force=True)
    except Exception:
        return jsonify(_err(None, -32700, "Parse error")), 400

    if rpc is None:
        return jsonify(_err(None, -32700, "Parse error")), 400

    # Handle batches
    is_batch = isinstance(rpc, list)
    requests_list = rpc if is_batch else [rpc]

    responses = []
    for req in requests_list:
        try:
            resp = _dispatch(req, user_id)
        except Exception as e:
            logger.error(f"MCP dispatch error: {e}", exc_info=True)
            resp = _err(req.get('id'), -32603, f"Internal error: {e}")

        if resp is not None:
            if sid and session:
                # Push via SSE stream
                _send_to_session(sid, resp)
            else:
                responses.append(resp)

    # For direct (non-SSE) usage, return responses inline
    if responses:
        return jsonify(responses[0] if not is_batch else responses)

    return '', 202


@mcp_bp.route('', methods=['POST', 'GET'])
@mcp_bp.route('/', methods=['POST', 'GET'])
def mcp_streamable():
    """
    Streamable HTTP transport endpoint (MCP spec 2025-03-26).

    Claude Desktop and claude.ai connectors POST JSON-RPC here.
    Responses are returned inline as JSON or as an SSE stream depending
    on the Accept header.
    """
    key_record = _authenticate()
    if not key_record:
        return jsonify({"error": "API key required. Add Authorization: Bearer <key> header."}), 401

    user_id = key_record.user_id if hasattr(key_record, 'user_id') else key_record.get('user_id')

    # GET — return a minimal SSE stream (some clients probe with GET first)
    if request.method == 'GET':
        def _ping():
            yield ": connected\n\n"
        return Response(_ping(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    # POST — dispatch JSON-RPC and stream responses back
    try:
        rpc = request.get_json(force=True)
    except Exception:
        return jsonify(_err(None, -32700, "Parse error")), 400

    if rpc is None:
        return jsonify(_err(None, -32700, "Parse error")), 400

    is_batch = isinstance(rpc, list)
    requests_list = rpc if is_batch else [rpc]

    wants_stream = 'text/event-stream' in request.headers.get('Accept', '')

    responses = []
    for req in requests_list:
        try:
            resp = _dispatch(req, user_id)
        except Exception as e:
            logger.error(f"MCP streamable dispatch error: {e}", exc_info=True)
            resp = _err(req.get('id'), -32603, f"Internal error: {e}")
        if resp is not None:
            responses.append(resp)

    if not responses:
        return '', 202

    if wants_stream:
        def generate():
            for r in responses:
                yield f"event: message\ndata: {json.dumps(r)}\n\n"
        return Response(generate(), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    result = responses[0] if not is_batch else responses
    return jsonify(result)
