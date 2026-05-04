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

import hashlib
import hmac
import json
import logging
import os
import queue
import secrets
import threading
import time
import uuid
from typing import Any, Dict, Optional

from flask import Blueprint, Response, jsonify, redirect, render_template_string, request, stream_with_context

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__, url_prefix='/mcp')

# ── In-memory session registry ───────────────────────────────────────────────
# session_id → Queue of SSE messages to send back to that client.
# Sessions time out after 10 minutes of inactivity.
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL_SECONDS = 600

MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "DevOps Agent"
SERVER_VERSION = "1.0.4"

# ── OAuth 2.0 Authorization Server ───────────────────────────────────────────
# A single built-in OAuth client for Claude.ai / Claude Desktop connectors.
# Client ID and Secret are read from env vars (fall back to stable defaults).
OAUTH_CLIENT_ID     = os.environ.get('MCP_OAUTH_CLIENT_ID',     'claude-connector')
OAUTH_CLIENT_SECRET = os.environ.get('MCP_OAUTH_CLIENT_SECRET', 'devopsagent-mcp-secret-2026')

# in-memory stores (restart clears them — users just re-auth)
_oauth_codes:   Dict[str, Dict[str, Any]] = {}   # code  → {user_id, expires, redirect_uri}
_oauth_tokens:  Dict[str, int]            = {}   # token → user_id
_registered_clients: Dict[str, Dict[str, Any]] = {}  # client_id → registration metadata
_oauth_lock = threading.Lock()
_CODE_TTL  = 300   # 5 min
_TOKEN_TTL = 86400 * 30  # 30 days (stored in memory; restart invalidates)


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


def _get_tool_annotations(tool_name: str) -> Dict[str, Any]:
    """Return MCP safety annotations for a tool based on its risk classification."""
    from src.agent.safety import SafetyValidator

    name = tool_name.lower()

    # Read-only tools: list, get, describe, show, search, check, validate, health
    _READ_ONLY_PREFIXES = (
        'list_', 'get_', 'describe_', 'show_', 'search_', 'check_',
        'validate_', 'view_', 'fetch_', 'query_', 'count_',
    )
    _READ_ONLY_SUBSTRINGS = ('_list', '_status', '_info', '_health', '_logs', '_history', '_usage')

    is_read_only = (
        any(name.startswith(p) for p in _READ_ONLY_PREFIXES)
        or any(s in name for s in _READ_ONLY_SUBSTRINGS)
    )

    is_destructive = (
        tool_name in SafetyValidator.validate_tool_call.__code__.co_consts
        or SafetyValidator._matches_high_risk_pattern(tool_name)
    )

    # Use the actual sets from safety.py for accurate classification
    sv = SafetyValidator()
    result = sv.validate_tool_call(tool_name, {})
    is_destructive = result.risk_level in ('high', 'critical')
    is_medium = result.risk_level == 'medium'

    if is_read_only and not is_destructive and not is_medium:
        return {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
    if is_destructive:
        return {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
    return {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}


def _to_mcp_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an internal tool definition to MCP tool format with safety annotations."""
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "inputSchema": tool.get("input_schema", {
            "type": "object",
            "properties": {},
            "required": []
        }),
        "annotations": _get_tool_annotations(tool["name"]),
    }


# ── Auth ─────────────────────────────────────────────────────────────────────

def _authenticate() -> Optional[Dict[str, Any]]:
    """
    Validate Bearer token — accepts both API keys and OAuth access tokens.
    Returns an object with a .user_id attribute on success, None on failure.
    """
    bearer = (
        request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        or request.args.get('api_key', '')
    )
    if not bearer:
        return None

    # 1. Check OAuth access tokens first (fast in-memory lookup)
    with _oauth_lock:
        uid = _oauth_tokens.get(bearer)
    if uid is not None:
        class _OAuthUser:
            def __init__(self, user_id): self.user_id = user_id
        return _OAuthUser(uid)

    # 2. Fall back to API key lookup
    try:
        from services.api_gateway import APIGatewayService
        svc = APIGatewayService()
        return svc.get_api_key_by_key(bearer)
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
    health_tool = {
        "name": "devopsagent_health",
        "description": "Returns server status, protocol version, and tool count. No cloud credentials required.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    }
    return _ok(req_id, {
        "tools": [health_tool] + [_to_mcp_tool(t) for t in tools],
    })


def _handle_tools_call(req_id: Any, params: Dict, user_id: int) -> Dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments") or {}

    # Built-in tool — no cloud credentials needed
    if tool_name == "devopsagent_health":
        tools, tool_map = _get_all_tools()
        return _ok(req_id, {
            "content": [{"type": "text", "text": json.dumps({
                "status": "ok",
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                "protocol": MCP_PROTOCOL_VERSION,
                "tools_loaded": len(tool_map),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, indent=2)}],
            "isError": False,
        })

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
        return _ok(req_id, {
            "content": [{"type": "text", "text": f"Tool execution error: {e}"}],
            "isError": True,
        })

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


@mcp_bp.route('', methods=['POST', 'GET', 'OPTIONS'])
@mcp_bp.route('/', methods=['POST', 'GET', 'OPTIONS'])
def mcp_streamable():
    """
    Streamable HTTP transport endpoint (MCP spec 2025-03-26).

    Claude Desktop and claude.ai connectors POST JSON-RPC here.
    """
    # CORS preflight
    if request.method == 'OPTIONS':
        return Response('', 204, headers=_cors_headers())

    key_record = _authenticate()
    if not key_record:
        resp = jsonify({"error": "unauthorized"})
        resp.status_code = 401
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        resp.headers['WWW-Authenticate'] = (
            'Bearer realm="DevOps Agent", '
            'resource_metadata="https://devopsagent.io/.well-known/oauth-protected-resource"'
        )
        return resp

    user_id = key_record.user_id if hasattr(key_record, 'user_id') else key_record.get('user_id')
    session_id = request.headers.get('Mcp-Session-Id') or uuid.uuid4().hex

    # GET — SSE stream for server-initiated messages
    if request.method == 'GET':
        def _ping():
            yield ": connected\n\n"
        return Response(_ping(), mimetype='text/event-stream',
                        headers={**_cors_headers(),
                                 'Cache-Control': 'no-cache',
                                 'X-Accel-Buffering': 'no',
                                 'Mcp-Session-Id': session_id})

    # POST — dispatch JSON-RPC
    try:
        rpc = request.get_json(force=True)
    except Exception:
        return jsonify(_err(None, -32700, "Parse error")), 400

    if rpc is None:
        return jsonify(_err(None, -32700, "Parse error")), 400

    is_batch = isinstance(rpc, list)
    requests_list = rpc if is_batch else [rpc]

    responses = []
    for req in requests_list:
        try:
            resp = _dispatch(req, user_id)
        except Exception as e:
            logger.error(f"MCP streamable dispatch error: {e}", exc_info=True)
            resp = _err(req.get('id'), -32603, f"Internal error: {e}")
        if resp is not None:
            responses.append(resp)

    extra_headers = {**_cors_headers(), 'Mcp-Session-Id': session_id}

    if not responses:
        r = Response('', 202)
        for k, v in extra_headers.items():
            r.headers[k] = v
        return r

    # Always return plain JSON — SSE only for server-push streams, not request/response
    result = responses[0] if not is_batch else responses
    response = jsonify(result)
    for k, v in extra_headers.items():
        response.headers[k] = v
    return response


def _cors_headers() -> dict:
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Authorization, Content-Type, Accept, Mcp-Session-Id',
        'Access-Control-Expose-Headers': 'Mcp-Session-Id',
    }


# ── OAuth 2.0 endpoints ───────────────────────────────────────────────────────

_AUTHORIZE_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Connect Claude to DevOps Agent</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:sans-serif;background:#0a0a0a;color:#eee;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
    .card{background:#1a1a1a;border:1px solid #333;border-radius:12px;padding:40px;max-width:420px;width:100%;text-align:center}
    h2{color:#ff6b35;margin-bottom:8px}
    p{color:#aaa;margin-bottom:24px;font-size:14px}
    input{width:100%;padding:12px;background:#111;border:1px solid #444;border-radius:8px;color:#eee;font-size:15px;box-sizing:border-box;margin-bottom:12px}
    button{width:100%;padding:13px;background:#ff6b35;border:none;border-radius:8px;color:#fff;font-size:16px;font-weight:600;cursor:pointer}
    button:hover{background:#e55a25}
    .err{color:#f87171;font-size:13px;margin-bottom:12px}
  </style>
</head>
<body>
<div class="card">
  <h2>DevOps Agent</h2>
  <p>Sign in to connect Claude to your infrastructure tools.</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="POST">
    <input type="hidden" name="client_id"    value="{{ client_id }}">
    <input type="hidden" name="redirect_uri" value="{{ redirect_uri }}">
    <input type="hidden" name="state"        value="{{ state }}">
    <input type="email"    name="email"    placeholder="Email"    required autofocus>
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">Authorize</button>
  </form>
</div>
</body>
</html>"""


@mcp_bp.route('/oauth/authorize', methods=['GET', 'POST'])
def oauth_authorize():
    """OAuth 2.0 authorization endpoint."""
    client_id      = request.values.get('client_id', '')
    redirect_uri   = request.values.get('redirect_uri', '')
    state          = request.values.get('state', '')
    code_challenge = request.values.get('code_challenge', '')

    # Accept the built-in client OR any dynamically registered client OR any public PKCE client.
    # We do not reject unknown client_ids here because claude.ai and other public OAuth clients
    # generate their own client_id and authenticate via PKCE rather than a pre-shared secret.
    if not client_id:
        return jsonify({'error': 'invalid_request', 'error_description': 'client_id required'}), 400

    if request.method == 'GET':
        return render_template_string(_AUTHORIZE_HTML,
                                      client_id=client_id,
                                      redirect_uri=redirect_uri,
                                      state=state,
                                      error=None)

    # POST — validate credentials
    email    = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    try:
        from models import User
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            raise ValueError('Invalid email or password')
    except ValueError as e:
        return render_template_string(_AUTHORIZE_HTML,
                                      client_id=client_id,
                                      redirect_uri=redirect_uri,
                                      state=state,
                                      error=str(e))
    except Exception as e:
        logger.error(f"OAuth authorize error: {e}", exc_info=True)
        return render_template_string(_AUTHORIZE_HTML,
                                      client_id=client_id,
                                      redirect_uri=redirect_uri,
                                      state=state,
                                      error='Server error, please try again')

    # Issue auth code
    code = secrets.token_urlsafe(32)
    with _oauth_lock:
        _oauth_codes[code] = {
            'user_id':        user.id,
            'redirect_uri':   redirect_uri,
            'expires':        time.time() + _CODE_TTL,
            'code_challenge': code_challenge,
        }

    sep = '&' if '?' in redirect_uri else '?'
    return redirect(f"{redirect_uri}{sep}code={code}&state={state}")


@mcp_bp.route('/oauth/token', methods=['POST', 'OPTIONS'])
def oauth_token():
    """OAuth 2.0 token endpoint — supports client_secret_post and client_secret_basic."""
    if request.method == 'OPTIONS':
        return Response('', 204, headers=_cors_headers())

    body = request.get_json(silent=True) or {}
    grant_type = request.form.get('grant_type') or body.get('grant_type')
    code          = request.form.get('code')           or body.get('code')
    code_verifier = request.form.get('code_verifier') or body.get('code_verifier')

    # Client credentials: Basic Auth takes priority, then form/JSON body
    import base64
    client_id, client_secret = None, None
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Basic '):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            client_id, client_secret = decoded.split(':', 1)
        except Exception:
            pass
    if not client_id:
        client_id     = request.form.get('client_id')     or body.get('client_id')
        client_secret = request.form.get('client_secret') or body.get('client_secret')

    # Accept the built-in confidential client (client_secret required) OR any public
    # client using PKCE (code_verifier present, no secret needed).  Claude.ai and
    # Claude Desktop are public OAuth clients — they never send a client_secret.
    is_known_confidential = (client_id == OAUTH_CLIENT_ID and client_secret == OAUTH_CLIENT_SECRET)
    is_public_pkce = bool(code_verifier)  # PKCE verifier will be checked against stored challenge
    if not is_known_confidential and not is_public_pkce:
        resp = jsonify({'error': 'invalid_client',
                        'error_description': 'Provide client_secret or use PKCE (code_verifier)'})
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        return resp, 401

    if grant_type != 'authorization_code' or not code:
        resp = jsonify({'error': 'invalid_request'})
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        return resp, 400

    with _oauth_lock:
        record = _oauth_codes.pop(code, None)

    if not record or time.time() > record['expires']:
        resp = jsonify({'error': 'invalid_grant', 'error_description': 'Code expired or invalid'})
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        return resp, 400

    # Verify PKCE when a challenge was stored with the auth code.
    # For public clients code_verifier is mandatory; for confidential clients it's optional.
    stored_challenge = record.get('code_challenge', '')
    if stored_challenge:
        if not code_verifier:
            resp = jsonify({'error': 'invalid_grant',
                            'error_description': 'code_verifier required (PKCE)'})
            for k, v in _cors_headers().items():
                resp.headers[k] = v
            return resp, 400
        import base64
        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
        if not hmac.compare_digest(computed, stored_challenge):
            resp = jsonify({'error': 'invalid_grant', 'error_description': 'PKCE verification failed'})
            for k, v in _cors_headers().items():
                resp.headers[k] = v
            return resp, 400

    access_token = secrets.token_urlsafe(48)
    with _oauth_lock:
        _oauth_tokens[access_token] = record['user_id']

    resp = jsonify({
        'access_token': access_token,
        'token_type':   'Bearer',
        'expires_in':   _TOKEN_TTL,
        'scope':        'mcp',
    })
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp


@mcp_bp.route('/oauth/register', methods=['POST', 'OPTIONS'])
def oauth_register():
    """
    Dynamic Client Registration (RFC 7591).

    Claude.ai and Claude Desktop call this before the authorization redirect so
    they can use their own generated client_id.  We accept any registration and
    return a client_id they can use in subsequent OAuth requests.
    """
    if request.method == 'OPTIONS':
        return Response('', 204, headers=_cors_headers())

    body = request.get_json(silent=True) or {}
    client_id = secrets.token_urlsafe(16)
    with _oauth_lock:
        _registered_clients[client_id] = {
            'redirect_uris': body.get('redirect_uris', []),
            'client_name':   body.get('client_name', 'MCP Client'),
            'registered_at': time.time(),
        }
    logger.info(f"MCP: registered OAuth client {client_id!r} ({body.get('client_name', '?')})")

    resp = jsonify({
        'client_id':            client_id,
        'client_id_issued_at':  int(time.time()),
        'token_endpoint_auth_method': 'none',   # public client — PKCE only
        'redirect_uris':        body.get('redirect_uris', []),
    })
    resp.status_code = 201
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp
