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
  tools/list              Returns all exposed tools in MCP inputSchema format
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

from flask import (Blueprint, Response, has_request_context, jsonify, redirect,
                   render_template_string, request, stream_with_context)

from extensions import limiter
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

mcp_bp = Blueprint('mcp', __name__, url_prefix='/mcp')

# Hosts we trust to derive the OAuth issuer from (prevents Host-header poisoning
# of the public metadata documents).
_MCP_ALLOWED_HOST_SUFFIX = 'devopsagent.io'


def mcp_base_url() -> str:
    """Base URL used for all MCP OAuth metadata and endpoint advertisement.

    RFC 8414 requires the authorization-server metadata ``issuer`` to match the
    host the client used for discovery. The Claude connector may talk to either
    the apex (``devopsagent.io``) or the dedicated subdomain
    (``mcp.devopsagent.io``), so we derive the base from the *request host*
    (forcing https) so issuer + endpoints always match the host in use.

    Falls back to ``MCP_BASE_URL`` (or the apex) outside a request context.
    """
    try:
        if has_request_context():
            host = (request.host or '').split(':')[0]
            if host == _MCP_ALLOWED_HOST_SUFFIX or host.endswith(f'.{_MCP_ALLOWED_HOST_SUFFIX}'):
                return f'https://{host}'
    except Exception:
        pass
    return os.environ.get('MCP_BASE_URL', 'https://devopsagent.io').rstrip('/')

# ── In-memory session registry ───────────────────────────────────────────────
# session_id → Queue of SSE messages to send back to that client.
# Sessions time out after 10 minutes of inactivity.
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL_SECONDS = 600

MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "DevOps Agent"
SERVER_VERSION = "1.0.7"

# ── OAuth 2.0 Authorization Server ───────────────────────────────────────────
# A single built-in OAuth client for Claude.ai / Claude Desktop connectors.
# Client ID and Secret are read from env vars (fall back to stable defaults).
OAUTH_CLIENT_ID     = os.environ.get('MCP_OAUTH_CLIENT_ID',     'claude-connector')
OAUTH_CLIENT_SECRET = os.environ.get('MCP_OAUTH_CLIENT_SECRET', 'devopsagent-mcp-secret-2026')

# Redirect URIs the built-in client is allowed to send an authorization code
# to. Both OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET are published in
# templates/docs.html for the self-service "Connect via Claude.ai
# (Connectors)" flow, so this client cannot rely on the secret as its actual
# security boundary — the redirect_uri allowlist below is what actually
# stops an attacker from pointing a victim's authorization code at an
# attacker-controlled origin (see CLAUDE_RUNBOOK.md's 2026-08-30 entry).
_BUILTIN_CLIENT_REDIRECT_URIS = frozenset(
    u.strip() for u in os.environ.get(
        'MCP_OAUTH_BUILTIN_REDIRECT_URIS',
        'https://claude.ai/api/mcp/auth_callback',
    ).split(',') if u.strip()
)

# in-memory stores (restart clears them — users just re-auth)
_oauth_codes:   Dict[str, Dict[str, Any]] = {}   # code  → {user_id, expires, redirect_uri}
_oauth_tokens:  Dict[str, int]            = {}   # token → user_id  (L1 cache; DB is source of truth)
_registered_clients: Dict[str, Dict[str, Any]] = {}  # client_id → registration metadata
_oauth_lock = threading.Lock()
_CODE_TTL    = 300          # 5 min
_TOKEN_TTL   = 86400 * 30   # access tokens: 30 days
_REFRESH_TTL = 86400 * 90   # refresh tokens: 90 days


# ── DB-backed token helpers ───────────────────────────────────────────────────

def _store_token_db(token: str, user_id: int, kind: str = 'access',
                     client_id: Optional[str] = None) -> None:
    """Persist an OAuth token to the database and warm the in-memory cache."""
    from datetime import datetime, timedelta
    ttl = _REFRESH_TTL if kind == 'refresh' else _TOKEN_TTL
    try:
        from models import MCPOAuthToken, db
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthToken(
                token=token,
                user_id=user_id,
                token_kind=kind,
                client_id=client_id,
                expires_at=utcnow() + timedelta(seconds=ttl),
            )
            db.session.add(row)
            # Prune tokens that expired more than a day ago (keep the table tidy)
            cutoff = utcnow() - timedelta(days=1)
            MCPOAuthToken.query.filter(MCPOAuthToken.expires_at < cutoff).delete()
            db.session.commit()
    except Exception as e:
        logger.warning(f"MCP: failed to persist token to DB (falling back to memory-only): {e}")
    # Only access tokens authenticate requests — never cache refresh tokens
    # where _authenticate() would find them.
    if kind == 'access':
        with _oauth_lock:
            _oauth_tokens[token] = user_id


def _lookup_token_db(token: str) -> Optional[int]:
    """Look up an ACCESS token: L1 = in-memory cache, L2 = database."""
    # L1: in-memory cache
    with _oauth_lock:
        uid = _oauth_tokens.get(token)
    if uid is not None:
        return uid

    # L2: database (handles server restarts)
    try:
        from models import MCPOAuthToken
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthToken.query.filter_by(token=token, token_kind='access').first()
            if row and not row.is_expired():
                # Warm the cache for subsequent requests
                with _oauth_lock:
                    _oauth_tokens[row.token] = row.user_id
                return row.user_id
    except Exception as e:
        logger.warning(f"MCP: DB token lookup failed: {e}")

    return None


def _consume_refresh_token_db(token: str, client_id: Optional[str] = None,
                               client_secret: Optional[str] = None) -> Optional[int]:
    """Validate a refresh token and delete it (rotation: each refresh token is
    single-use; the token endpoint issues a replacement). Returns user_id.

    Binds redemption to the client the token was issued to: a refresh token
    minted for the confidential built-in client requires the client_secret to
    redeem (matching the authorization_code grant's requirement); a refresh
    token minted for any other client_id must be redeemed with that same
    client_id, so a leaked refresh token can't be redeemed under a different
    client identity than the one it was issued to.
    """
    try:
        from models import MCPOAuthToken, db
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthToken.query.filter_by(token=token, token_kind='refresh').first()
            if row is None or row.is_expired():
                return None
            if row.client_id:
                if row.client_id == OAUTH_CLIENT_ID:
                    if client_secret != OAUTH_CLIENT_SECRET:
                        return None
                elif client_id != row.client_id:
                    return None
            user_id = row.user_id
            # Atomic single-use: only the request that deletes the row wins
            deleted = MCPOAuthToken.query.filter_by(id=row.id).delete()
            db.session.commit()
            return user_id if deleted else None
    except Exception as e:
        logger.warning(f"MCP: refresh token lookup failed: {e}")
        return None


# ── DB-backed client registry (RFC 7591 dynamic client registration) ────────
# Registered in the DB, not just per-process memory: DCR (POST /register) and
# the later /authorize request can land on different gunicorn workers, so a
# purely in-memory registry would make a just-registered client look unknown
# to whichever worker serves /authorize. Mirrors the code/token DB helpers.

def _store_client_db(client_id: str, client_name: str, redirect_uris: list) -> None:
    try:
        from models import MCPOAuthClient, db
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthClient(
                client_id=client_id,
                client_name=client_name,
                redirect_uris=json.dumps(redirect_uris or []),
            )
            db.session.add(row)
            db.session.commit()
    except Exception as e:
        logger.warning(f"MCP: failed to persist client registration to DB (falling back to memory-only): {e}")
    with _oauth_lock:
        _registered_clients[client_id] = {
            'redirect_uris': redirect_uris or [],
            'client_name':   client_name,
            'registered_at': time.time(),
        }


def _find_existing_client_by_redirect_uris(redirect_uris: list) -> Optional[str]:
    """Look up a previously-registered client with the same redirect_uris set.

    Dynamic Client Registration (RFC 7591) doesn't require idempotency, but
    claude.ai calls POST /register again on every single reconnect attempt
    with an otherwise-identical payload (same client_name, same redirect_uris)
    and gets back a brand-new random client_id each time. If claude.ai's own
    connector bookkeeping expects a stable client identity across reconnects
    (rather than treating every attempt as a new, unrelated OAuth client),
    that churn could plausibly stop the connection from ever settling into a
    "connected" state even though each individual token issued is valid.
    Returns the existing client_id if one is found with the same redirect_uris
    (order-independent), else None.
    """
    wanted = set(redirect_uris or [])
    if not wanted:
        return None
    with _oauth_lock:
        for cid, info in _registered_clients.items():
            if set(info.get('redirect_uris') or []) == wanted:
                return cid
    try:
        from models import MCPOAuthClient
        from flask import current_app
        with current_app.app_context():
            for row in MCPOAuthClient.query.order_by(MCPOAuthClient.id.asc()).all():
                try:
                    existing_uris = set(json.loads(row.redirect_uris or '[]'))
                except (TypeError, ValueError):
                    continue
                if existing_uris == wanted:
                    return row.client_id
    except Exception as e:
        logger.warning(f"MCP: DB client search failed: {e}")
    return None


def _lookup_client_db(client_id: str) -> Optional[Dict[str, Any]]:
    """Look up a registered client: L1 = in-memory cache, L2 = database."""
    with _oauth_lock:
        cached = _registered_clients.get(client_id)
    if cached is not None:
        return cached

    try:
        from models import MCPOAuthClient
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthClient.query.filter_by(client_id=client_id).first()
            if row is not None:
                try:
                    redirect_uris = json.loads(row.redirect_uris or '[]')
                except (TypeError, ValueError):
                    redirect_uris = []
                info = {'redirect_uris': redirect_uris, 'client_name': row.client_name}
                with _oauth_lock:
                    _registered_clients[client_id] = info
                return info
    except Exception as e:
        logger.warning(f"MCP: DB client lookup failed: {e}")

    return None


# ── DB-backed authorization-code helpers ──────────────────────────────────────
# Auth codes MUST live in the DB, not per-process memory: claude.ai / Claude
# Desktop send /authorize and /token to different gunicorn workers, so an
# in-memory code issued by one worker is invisible to the worker doing the token
# exchange (→ invalid_grant → failed connection). Mirrors the token helpers.

def _store_code_db(code: str, user_id: int, redirect_uri: str, code_challenge: str) -> None:
    """Persist an auth code to the DB (shared by all workers) and warm L1 cache."""
    from datetime import datetime, timedelta
    try:
        from models import MCPOAuthCode, db
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthCode(
                code=code,
                user_id=user_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge or '',
                expires_at=utcnow() + timedelta(seconds=_CODE_TTL),
            )
            db.session.add(row)
            # Prune already-expired codes to keep the table tidy
            MCPOAuthCode.query.filter(MCPOAuthCode.expires_at < utcnow()).delete()
            db.session.commit()
    except Exception as e:
        logger.warning(f"MCP: failed to persist auth code to DB (memory-only fallback): {e}")
    # Always warm the local in-memory store (L1 / fallback if DB is unavailable)
    with _oauth_lock:
        _oauth_codes[code] = {
            'user_id':        user_id,
            'redirect_uri':   redirect_uri,
            'expires':        time.time() + _CODE_TTL,
            'code_challenge': code_challenge,
        }


def _consume_code_db(code: str) -> Optional[Dict[str, Any]]:
    """Single-use: atomically fetch+delete the auth code from the DB (authoritative,
    shared across workers). Falls back to in-memory only if the DB is unavailable."""
    try:
        from datetime import datetime, timezone
        from models import MCPOAuthCode, db
        from flask import current_app
        with current_app.app_context():
            row = MCPOAuthCode.query.filter_by(code=code).first()
            if row is not None:
                rec = {
                    'user_id':        row.user_id,
                    'redirect_uri':   row.redirect_uri,
                    # expires_at is a naive datetime holding a UTC value (from
                    # utcnow()). Calling .timestamp() directly on it
                    # would make Python interpret it as *local* server time,
                    # silently shifting the expiry by the server's UTC offset —
                    # tag it UTC explicitly before converting to epoch.
                    'expires':        row.expires_at.replace(tzinfo=timezone.utc).timestamp(),
                    'code_challenge': row.code_challenge or '',
                }
                # Atomic single-use: only the request that deletes the row wins
                deleted = MCPOAuthCode.query.filter_by(code=code).delete()
                db.session.commit()
                with _oauth_lock:
                    _oauth_codes.pop(code, None)
                return rec if deleted else None
    except Exception as e:
        logger.warning(f"MCP: DB code consume failed, trying memory: {e}")
    # Fallback: in-memory (only reached if the DB write failed at issue time)
    with _oauth_lock:
        return _oauth_codes.pop(code, None)


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


def _resource_metadata_url() -> str:
    """RFC 9728 metadata URL matching the resource path the client requested.

    A client bound to the /mcp path must be pointed at the /mcp-suffixed
    document (which advertises resource=…/mcp); a client bound to the origin
    root gets the root document (resource=origin). Mixing them up makes strict
    clients discard freshly issued tokens as resource-mismatched.
    """
    base = mcp_base_url()
    suffix = '/mcp' if request.path.startswith('/mcp') else ''
    return f'{base}/.well-known/oauth-protected-resource{suffix}'


# ── Auth ─────────────────────────────────────────────────────────────────────

def _authenticate() -> Optional[Dict[str, Any]]:
    """
    Validate Bearer token — accepts both API keys and OAuth access tokens.
    Returns an object with a .user_id attribute on success, None on failure.
    """
    raw_auth = request.headers.get('Authorization', '')
    bearer = (
        raw_auth.removeprefix('Bearer ').strip()
        or request.args.get('api_key', '')
    )
    logger.info(f"MCP auth: method={request.method} path={request.path} "
                f"has_auth_header={bool(raw_auth)} bearer_len={len(bearer)} "
                f"oauth_tokens_count={len(_oauth_tokens)}")
    if not bearer:
        logger.warning("MCP auth: no bearer token in request")
        return None

    # 1. Check OAuth access tokens (L1 memory cache → L2 database)
    uid = _lookup_token_db(bearer)
    if uid is not None:
        logger.info(f"MCP auth: OAuth token accepted for user_id={uid}")
        class _OAuthUser:
            def __init__(self, user_id): self.user_id = user_id
        return _OAuthUser(uid)

    logger.warning(f"MCP auth: OAuth token not found (memory+DB), trying API key lookup")
    # 2. Fall back to API key lookup
    try:
        from services.api_gateway import APIGatewayService
        svc = APIGatewayService()
        result = svc.get_api_key_by_key(bearer)
        if result:
            logger.info(f"MCP auth: API key accepted")
        else:
            logger.warning(f"MCP auth: API key not found either — rejecting")
        return result
    except Exception as e:
        logger.error(f"MCP auth: API key lookup error: {e}")
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
            # Same approval-workflow gate as the chat entry points
            # (src/agent/core.py's _handle_tool_uses): a non-approver/non-admin
            # caller cannot self-approve a high-risk tool call just by having an
            # MCP client willing to send it — defer to a real approver instead of
            # trusting the MCP client to have confirmed with a human first.
            _blocked = None
            try:
                from models import User
                user = User.query.get(user_id)
                if not user:
                    raise RuntimeError(f"user {user_id} not found")
                from services.approval_service import needs_approval
                if needs_approval(user, result.risk_level):
                    from services.approval_service import create_request, build_risk_reason, waiting_message
                    reason = build_risk_reason(tool_name, arguments)
                    req = create_request(
                        tool_name=tool_name,
                        tool_input=arguments,
                        risk_level=result.risk_level,
                        risk_reason=reason,
                        requester_id=user_id,
                    )
                    _blocked = {
                        "success": False,
                        "error": waiting_message(req),
                        "approval_id": req.id,
                        "risk_level": result.risk_level,
                        "risk_reason": reason,
                    }
            except Exception as e:
                # Fail closed: a risky call whose approval request can't be filed
                # must not run anyway.
                logger.error(f"MCP approval intercept failed for '{tool_name}', blocking: {e}")
                _blocked = {
                    "success": False,
                    "error": "Not run: this action needs approval and the approval request could not be created. Try again later.",
                }
            if _blocked is not None:
                return _ok(req_id, {
                    "content": [{"type": "text", "text": json.dumps(_blocked)}],
                    "isError": True,
                })
            logger.warning(f"MCP executing high-risk tool '{tool_name}' for user {user_id}")
    except Exception as e:
        # Deliberate fail-open (matches /v1/execute and the Haiku guardrail
        # screen), but a silent failure here means a broken validator would
        # disable safety gating for every high-risk tool call indefinitely
        # with zero operational visibility — log it.
        logger.error(f"MCP safety validator raised for tool '{tool_name}', executing without a safety gate: {e}")

    # Execute the tool handler with user context set. Use the agent's
    # _set_cloud_user_context (covers AWS, Azure, GCP, and
    # devops_operations_tools — see CLAUDE.md's Concurrency Model section)
    # rather than aws_tools.set_user_context alone, which left every non-AWS
    # tool call through this MCP path with no user context to resolve
    # credentials against.
    try:
        from app import agent as _agent
        _agent._set_cloud_user_context(user_id)
        try:
            result = tool['handler'](**arguments)
        finally:
            _agent._clear_cloud_user_context()
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
        resp = jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32000,
                "message": "Unauthorized: provide a valid Bearer token",
            },
        })
        resp.status_code = 401
        resp.headers['WWW-Authenticate'] = (
            f'Bearer realm="DevOps Agent", '
            f'resource_metadata="{_resource_metadata_url()}"'
        )
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        return resp

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
            return jsonify(_err(None, -32000, "Unauthorized: provide a valid Bearer token")), 401
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
        # Extract the request id from the body so we can return a well-formed
        # JSON-RPC 2.0 error.  Claude Desktop validates every response with Zod;
        # a bare {"error":"..."} body (not JSON-RPC) causes a parse-union failure.
        req_id = None
        if request.method == 'POST':
            try:
                body = request.get_json(force=True, silent=True)
                if isinstance(body, dict):
                    req_id = body.get('id')
                elif isinstance(body, list) and body:
                    req_id = body[0].get('id') if isinstance(body[0], dict) else None
            except Exception:
                pass

        resp = jsonify({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": "Unauthorized: provide a valid Bearer token",
            },
        })
        resp.status_code = 401
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        resp.headers['WWW-Authenticate'] = (
            f'Bearer realm="DevOps Agent", '
            f'resource_metadata="{_resource_metadata_url()}"'
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
    .note{color:#9ca3af;font-size:13px;margin:16px 0 0}
    .link{background:none;border:none;color:#ff6b35;font-size:14px;font-weight:500;padding:8px;width:auto;margin-top:8px}
    .link:hover{background:none;text-decoration:underline}
  </style>
</head>
<body>
<div class="card">
  <h2>DevOps Agent</h2>
  {% macro oauth_fields() %}
    <input type="hidden" name="client_id"             value="{{ client_id }}">
    <input type="hidden" name="redirect_uri"          value="{{ redirect_uri }}">
    <input type="hidden" name="state"                 value="{{ state }}">
    <input type="hidden" name="code_challenge"        value="{{ code_challenge }}">
    <input type="hidden" name="code_challenge_method" value="{{ code_challenge_method }}">
  {% endmacro %}
  {% if mfa_token %}
  {% if mfa_method == 'email' %}
  <p>Enter the 6-digit code we emailed you.</p>
  {% else %}
  <p>Enter the 6-digit code from your authenticator app, or a backup code.</p>
  {% endif %}
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  {% if message %}<div class="note" style="margin:0 0 12px">{{ message }}</div>{% endif %}
  <form method="POST">
    {{ oauth_fields() }}
    <input type="hidden" name="mfa_token" value="{{ mfa_token }}">
    <input type="text" name="code" placeholder="6-digit code" required autofocus
           inputmode="numeric" autocomplete="one-time-code" maxlength="12">
    <button type="submit">Verify</button>
  </form>
  {% if mfa_method == 'email' %}
  <form method="POST">
    {{ oauth_fields() }}
    <input type="hidden" name="mfa_token" value="{{ mfa_token }}">
    <input type="hidden" name="resend" value="1">
    <button type="submit" class="link">Resend code</button>
  </form>
  {% endif %}
  <p class="note">Signing in as <strong>{{ account_email }}</strong></p>
  {% else %}
  {% if client_name %}
  <p>Sign in to let <strong>{{ client_name }}</strong> access your infrastructure tools.</p>
  {% else %}
  <p>Sign in to connect Claude to your infrastructure tools.</p>
  {% endif %}
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="POST">
    {{ oauth_fields() }}
    <input type="email"    name="email"    placeholder="Email"    required autofocus>
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">Authorize</button>
  </form>
  {% endif %}
</div>
</body>
</html>"""

# Two-factor step of the connector sign-in. After the password is accepted the
# browser holds a signed, short-lived token naming the user and the exact OAuth
# request (client, redirect_uri, PKCE challenge); no auth code is issued until a
# valid 2FA code comes back with it. The lifetime matches /login's code screen.
_MFA_TOKEN_SALT = 'mcp-oauth-mfa'
_MFA_TOKEN_MAX_AGE = 10 * 60


def _mfa_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key, salt=_MFA_TOKEN_SALT)


def _oauth_request_binding(client_id: str, redirect_uri: str, code_challenge: str) -> str:
    """Ties a 2FA token to one authorization request, so it can't be replayed
    against another client, redirect target or PKCE challenge."""
    raw = f'{client_id}\n{redirect_uri}\n{code_challenge}'.encode()
    return hashlib.sha256(raw).hexdigest()


@mcp_bp.route('/oauth/authorize', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def oauth_authorize():
    """OAuth 2.0 authorization endpoint."""
    client_id              = request.values.get('client_id', '')
    redirect_uri           = request.values.get('redirect_uri', '')
    state                  = request.values.get('state', '')
    code_challenge         = request.values.get('code_challenge', '')
    code_challenge_method  = request.values.get('code_challenge_method', 'S256')

    if not client_id:
        return jsonify({'error': 'invalid_request', 'error_description': 'client_id required'}), 400

    # Every client_id must be known: either the built-in confidential client,
    # or one that completed dynamic client registration (POST
    # /mcp/oauth/register). Accepting an arbitrary, never-registered client_id
    # here would let an attacker reuse a real client's client_id together with
    # a redirect_uri that client never registered — redirecting a
    # legitimately-authenticated victim's auth code to an attacker-controlled
    # URL (authorization code interception / account takeover). The built-in
    # client_id is just as exploitable this way as a registered one — its
    # allowlist is the fixed _BUILTIN_CLIENT_REDIRECT_URIS set rather than a
    # DB lookup, but it MUST still be enforced (never left as None, which
    # would skip the check below entirely).
    client_name = None
    if client_id == OAUTH_CLIENT_ID:
        allowed_redirect_uris = _BUILTIN_CLIENT_REDIRECT_URIS
    else:
        client_record = _lookup_client_db(client_id)
        if client_record is None:
            return jsonify({'error': 'invalid_client',
                            'error_description': 'Unknown client_id — register via /mcp/oauth/register first'}), 400
        # A client that registered with NO redirect_uris has nowhere valid to
        # send a code — that must mean "reject every redirect_uri", never
        # "skip the check". `client_record.get(...) or None` previously
        # collapsed an empty list to None, and the check below was gated on
        # `if allowed_redirect_uris`, so a client registered with
        # `redirect_uris: []` (trivial via the open POST /mcp/oauth/register)
        # bypassed the allowlist entirely and could redirect any victim's
        # auth code to an arbitrary attacker-controlled origin. Keep it as a
        # (possibly empty) set and always enforce membership — see the
        # regression tests added alongside this fix.
        allowed_redirect_uris = set(client_record.get('redirect_uris') or [])
        client_name = client_record.get('client_name')

    # redirect_uri is mandatory — an authorization response with no verified
    # destination to send the code to is unsafe by construction (and used to
    # silently skip the https/allowlist checks below entirely).
    if not redirect_uri:
        return jsonify({'error': 'invalid_request', 'error_description': 'redirect_uri required'}), 400

    # Redirect target guard: https for real clients, plain http only for
    # loopback (Claude Desktop / Claude Code use http://localhost:<port>).
    from urllib.parse import urlparse
    parsed = urlparse(redirect_uri)
    is_loopback = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and is_loopback):
        return jsonify({'error': 'invalid_request',
                        'error_description': 'redirect_uri must be https (or http on loopback)'}), 400
    if redirect_uri not in allowed_redirect_uris:
        return jsonify({'error': 'invalid_request',
                        'error_description': 'redirect_uri does not match a redirect_uri registered for this client_id'}), 400

    def render(error=None, **extra):
        return render_template_string(_AUTHORIZE_HTML,
                                      client_id=client_id,
                                      redirect_uri=redirect_uri,
                                      state=state,
                                      code_challenge=code_challenge,
                                      code_challenge_method=code_challenge_method,
                                      client_name=client_name,
                                      error=error,
                                      **extra)

    if request.method == 'GET':
        return render()

    binding = _oauth_request_binding(client_id, redirect_uri, code_challenge)

    # POST, second step: the 2FA code
    mfa_token = request.form.get('mfa_token', '')
    if mfa_token:
        try:
            user = _authorize_mfa_step(mfa_token, binding, render)
        except _AuthorizeStepResponse as step:
            return step.response
        return _redirect_with_code(user, redirect_uri, code_challenge, state)

    # POST, first step: email + password
    email    = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    try:
        from models import User
        from routes.auth import _run_timing_safe_password_check
        user = User.query.filter_by(email=email).first()

        # Enforce the same account-lockout invariant as the real /login route
        # (models.User.is_locked/record_failed_login — 15-minute lock after 5
        # failed attempts). This endpoint previously checked the password with
        # no lockout at all, so a known email could be brute-forced here with
        # no per-account limit, bypassed entirely regardless of how many
        # attempts /login itself would have blocked by now.
        if user and user.is_locked():
            raise ValueError('Account temporarily locked due to multiple failed login attempts. Try again in 15 minutes.')

        # Always pay bcrypt's cost, even for an unknown email, so response time
        # can't be used to enumerate valid accounts (see _run_timing_safe_password_check).
        password_matches = _run_timing_safe_password_check(user, password)
        if not user or not password_matches:
            if user:
                user.record_failed_login()
            raise ValueError('Invalid email or password')

        # Same rule as /login: an organization that enforces SSO doesn't allow
        # password sign-in, so it can't be used to connect Claude either.
        from services import sso_service
        if sso_service.sso_login_required(user):
            raise ValueError('Your organization requires single sign-on, so this '
                             'account cannot be connected with a password.')

        # 2FA accounts get the code step before any auth code is issued. As on
        # /login, the failed-password counter is only reset once that passes.
        if user.has_mfa_enabled():
            from routes.auth import _EMAIL_SEND_FAILED, _migrate_sms_mfa, _send_email_otp
            _migrate_sms_mfa(user)
            if user.mfa_method == 'email' and not _send_email_otp(user):
                raise ValueError(_EMAIL_SEND_FAILED)
            token = _mfa_serializer().dumps({'uid': user.id, 'b': binding})
            logger.info(f"MCP OAuth: 2FA ({user.mfa_method}) required for user_id={user.id}")
            return render(mfa_token=token, mfa_method=user.mfa_method,
                          account_email=user.email)

        # Correct password, no 2FA: reset the shared failed-attempt counter,
        # mirroring /login's own success path.
        user.update_last_login(ip_address=request.remote_addr)
    except ValueError as e:
        return render(error=str(e))
    except Exception as e:
        logger.error(f"OAuth authorize error: {e}", exc_info=True)
        return render(error='Server error, please try again')

    return _redirect_with_code(user, redirect_uri, code_challenge, state)


class _AuthorizeStepResponse(Exception):
    """Carries the page to show when the 2FA step does not complete."""

    def __init__(self, response):
        super().__init__()
        self.response = response


def _authorize_mfa_step(mfa_token: str, binding: str, render):
    """Check the second (2FA) step of the connector sign-in.

    Returns the signed-in User, or raises _AuthorizeStepResponse with the page
    to show instead. Uses /login's code check, attempt counter and lockout, so
    the two pages can't be played against each other."""
    from itsdangerous import BadSignature, SignatureExpired
    from models import User, db
    from routes.auth import (_EMAIL_SEND_FAILED, _check_mfa_code, _mfa_lockout_message,
                             _register_failed_mfa, _send_email_otp)

    try:
        data = _mfa_serializer().loads(mfa_token, max_age=_MFA_TOKEN_MAX_AGE)
    except SignatureExpired:
        raise _AuthorizeStepResponse(render(
            error='Your sign-in timed out before the code was entered. Please sign in again.'))
    except BadSignature:
        raise _AuthorizeStepResponse(render(error='Your sign-in could not be verified. Please sign in again.'))

    user = db.session.get(User, data.get('uid')) if isinstance(data, dict) else None
    if user is None or data.get('b') != binding or not user.has_mfa_enabled():
        raise _AuthorizeStepResponse(render(error='Your sign-in could not be verified. Please sign in again.'))

    mfa_method = user.mfa_method
    ip_address = request.remote_addr

    def code_page(error=None, message=None):
        return render(error=error, message=message, mfa_token=mfa_token,
                      mfa_method=mfa_method, account_email=user.email)

    if user.is_locked():
        raise _AuthorizeStepResponse(render(
            error='Account temporarily locked due to multiple failed login attempts. Try again in 15 minutes.'))

    if request.form.get('resend'):
        if mfa_method != 'email':
            raise _AuthorizeStepResponse(code_page())
        if not user.can_resend_otp():
            raise _AuthorizeStepResponse(code_page(error='Please wait 60 seconds before resending.'))
        if not _send_email_otp(user):
            raise _AuthorizeStepResponse(code_page(error=_EMAIL_SEND_FAILED))
        raise _AuthorizeStepResponse(code_page(message='A new code is on its way.'))

    code = request.form.get('code', '').strip()
    if not code:
        raise _AuthorizeStepResponse(code_page(error='Please enter a verification code.'))

    lockout = _mfa_lockout_message(user)
    if lockout:
        db.session.commit()
        raise _AuthorizeStepResponse(code_page(error=lockout))

    if not _check_mfa_code(user, mfa_method, code):
        raise _AuthorizeStepResponse(code_page(error=_register_failed_mfa(user, ip_address)))

    user.two_factor_attempts = 0
    db.session.commit()
    user.update_last_login(ip_address=ip_address)
    logger.info(f"MCP OAuth: 2FA ({mfa_method}) verified for user_id={user.id}")
    return user


def _redirect_with_code(user, redirect_uri: str, code_challenge: str, state: str):
    """Issue the auth code and send the browser back to the client."""
    # Persisted to the DB so any worker can exchange it
    code = secrets.token_urlsafe(32)
    _store_code_db(code, user.id, redirect_uri, code_challenge)

    # RFC 9207: identify the issuer in the authorization response so clients
    # can detect mix-up attacks (and strict clients don't reject the redirect).
    from urllib.parse import quote
    iss = quote(mcp_base_url(), safe='')
    sep = '&' if '?' in redirect_uri else '?'
    return redirect(f"{redirect_uri}{sep}code={code}&state={state}&iss={iss}")


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

    # ── refresh_token grant (RFC 6749 §6, single-use rotating tokens) ─────────
    if grant_type == 'refresh_token':
        refresh_token = request.form.get('refresh_token') or body.get('refresh_token')
        if not refresh_token:
            return _token_error('invalid_request', 'refresh_token required')
        user_id = _consume_refresh_token_db(refresh_token, client_id, client_secret)
        if user_id is None:
            return _token_error('invalid_grant', 'Refresh token expired or invalid')
        return _issue_token_response(user_id, client_id)

    # ── authorization_code grant ──────────────────────────────────────────────
    # Accept the built-in confidential client (client_secret required) OR any public
    # client using PKCE (code_verifier present, no secret needed).  Claude.ai and
    # Claude Desktop are public OAuth clients — they never send a client_secret.
    is_known_confidential = (client_id == OAUTH_CLIENT_ID and client_secret == OAUTH_CLIENT_SECRET)
    is_public_pkce = bool(code_verifier)  # PKCE verifier will be checked against stored challenge
    if not is_known_confidential and not is_public_pkce:
        return _token_error('invalid_client', 'Provide client_secret or use PKCE (code_verifier)', 401)

    if grant_type != 'authorization_code' or not code:
        error = 'unsupported_grant_type' if grant_type not in (None, 'authorization_code') else 'invalid_request'
        return _token_error(error, 'grant_type must be authorization_code or refresh_token')

    record = _consume_code_db(code)

    if not record or time.time() > record['expires']:
        return _token_error('invalid_grant', 'Code expired or invalid')

    # Verify PKCE when a challenge was stored with the auth code.
    # For public clients code_verifier is mandatory; for confidential clients it's optional.
    stored_challenge = record.get('code_challenge', '')
    if stored_challenge:
        if not code_verifier:
            return _token_error('invalid_grant', 'code_verifier required (PKCE)')
        import base64
        digest = hashlib.sha256(code_verifier.encode()).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
        if not hmac.compare_digest(computed, stored_challenge):
            return _token_error('invalid_grant', 'PKCE verification failed')

    return _issue_token_response(record['user_id'], client_id)


def _token_error(error: str, description: str, status: int = 400):
    resp = jsonify({'error': error, 'error_description': description})
    resp.headers['Cache-Control'] = 'no-store'
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp, status


def _issue_token_response(user_id: int, client_id: Optional[str] = None):
    """Issue a fresh access + refresh token pair (used by both grant types)."""
    access_token  = secrets.token_urlsafe(48)
    refresh_token = secrets.token_urlsafe(48)
    _store_token_db(access_token, user_id, kind='access', client_id=client_id)
    _store_token_db(refresh_token, user_id, kind='refresh', client_id=client_id)
    logger.info(f"MCP OAuth: token issued for user_id={user_id} "
                f"token_prefix={access_token[:8]}...")

    resp = jsonify({
        'access_token':  access_token,
        'token_type':    'Bearer',
        'expires_in':    _TOKEN_TTL,
        'refresh_token': refresh_token,
        'scope':         'mcp',
    })
    # RFC 6749 §5.1: token responses MUST NOT be cached
    resp.headers['Cache-Control'] = 'no-store'
    resp.headers['Pragma'] = 'no-cache'
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp


@mcp_bp.route('/oauth/register', methods=['POST', 'OPTIONS'])
def oauth_register():
    """
    Dynamic Client Registration (RFC 7591).

    Claude.ai and Claude Desktop call this before the authorization redirect so
    they can use their own generated client_id. We accept any registration and
    return a client_id they can use in subsequent OAuth requests.

    Idempotent by redirect_uris: if a client with the same redirect_uris was
    already registered (e.g. a previous reconnect attempt), reuse that
    client_id instead of minting a new one every time — see
    _find_existing_client_by_redirect_uris for why this matters.
    """
    if request.method == 'OPTIONS':
        return Response('', 204, headers=_cors_headers())

    body = request.get_json(silent=True) or {}
    redirect_uris = body.get('redirect_uris') or []
    client_name = body.get('client_name', 'MCP Client')

    # RFC 7591 §2: redirect_uris is REQUIRED for the authorization_code grant,
    # which is the only grant a newly-registered client can use here. A client
    # registered with none would previously end up with an unrestricted
    # allowlist at /oauth/authorize (see the fix there) instead of one that
    # can never authorize — reject the registration outright instead.
    redirect_uris = [u for u in redirect_uris if isinstance(u, str) and u.strip()]
    if not redirect_uris:
        resp = jsonify({'error': 'invalid_client_metadata',
                        'error_description': 'redirect_uris must contain at least one URI'})
        resp.status_code = 400
        for k, v in _cors_headers().items():
            resp.headers[k] = v
        return resp

    client_id = _find_existing_client_by_redirect_uris(redirect_uris)
    if client_id:
        logger.info(f"MCP: reusing existing OAuth client {client_id!r} ({client_name}) for repeat registration")
    else:
        client_id = secrets.token_urlsafe(16)
        _store_client_db(client_id, client_name, redirect_uris)
        logger.info(f"MCP: registered OAuth client {client_id!r} ({client_name})")

    # RFC 7591 §3.2.1: echo the registered metadata — strict clients validate
    # that the response covers the grant types they asked for.
    requested_grants = body.get('grant_types') or ['authorization_code']
    supported_grants = [g for g in requested_grants
                        if g in ('authorization_code', 'refresh_token')] or ['authorization_code']
    resp = jsonify({
        'client_id':            client_id,
        'client_id_issued_at':  int(time.time()),
        'client_name':          client_name,
        'token_endpoint_auth_method': 'none',   # public client — PKCE only
        'redirect_uris':        redirect_uris,
        'grant_types':          supported_grants,
        'response_types':       ['code'],
        'scope':                'mcp',
    })
    resp.status_code = 201
    for k, v in _cors_headers().items():
        resp.headers[k] = v
    return resp


# ── Root-level OAuth aliases ──────────────────────────────────────────────────
# Some MCP clients ignore the metadata's authorization_endpoint and probe the
# default OAuth paths relative to the server origin (e.g. /authorize, /token,
# /register). Register those at the root and delegate to the canonical handlers
# above so the flow completes regardless of which paths the client chooses.
mcp_oauth_alias_bp = Blueprint('mcp_oauth_alias', __name__)


@mcp_oauth_alias_bp.route('/authorize', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def oauth_authorize_alias():
    return oauth_authorize()


@mcp_oauth_alias_bp.route('/token', methods=['POST', 'OPTIONS'])
def oauth_token_alias():
    return oauth_token()


@mcp_oauth_alias_bp.route('/register', methods=['POST', 'OPTIONS'])
def oauth_register_alias():
    return oauth_register()


# ── Root-level MCP transport ─────────────────────────────────────────────────
# Claude.ai custom connectors are frequently configured with the bare origin
# (https://mcp.devopsagent.io) instead of the /mcp path. Before this route,
# their JSON-RPC POSTs hit the GET-only landing page and got a 405 — the OAuth
# flow completed and tokens were issued, but the client could never initialize,
# so the connector stayed "unauthorized" forever. Serving the streamable
# transport at POST / makes both URL styles work. GET / stays the landing page.

@mcp_oauth_alias_bp.route('/', methods=['POST'])
def mcp_root_streamable():
    return mcp_streamable()
