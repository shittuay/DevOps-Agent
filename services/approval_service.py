"""
Approval workflow service.

Manages creation, notification, approval, rejection, and tool execution
for high-risk tool calls that require a second human sign-off.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_KEY_FIELDS = [
    'instance_id', 'bucket_name', 'cluster_name', 'db_instance_identifier',
    'function_name', 'resource_id', 'name', 'table_name', 'volume_id',
    'image_id', 'stack_name', 'working_dir', 'repository', 'project_key',
    'namespace', 'deployment_name', 'service_name', 'job_name',
]


def build_risk_reason(tool_name: str, tool_input: dict) -> str:
    """Generate a human-readable risk reason from tool name and input."""
    parts = []
    for field in _KEY_FIELDS:
        val = tool_input.get(field)
        if val:
            parts.append(f"{field}={val}")
    action = tool_name.replace('_', ' ')
    if parts:
        return f"This will {action}: {', '.join(parts[:3])}"
    return f"This will execute: {action}"


def is_visible_to_approver(req, approver) -> bool:
    """Whether a non-admin approver may view/act on this ApprovalRequest.

    ApprovalRequest has no organization_id of its own (unlike InfrastructureChange),
    so visibility is derived from whether the approver shares an active organization
    membership with the request's requester — mirrors routes/changes.py's
    _change_visible_to_approver. A requester with no active org membership (solo
    account) is only visible to admins, same convention as changes.py.
    """
    from services.rbac import user_is_admin, user_active_org_ids
    if user_is_admin(approver):
        return True
    requester_orgs = user_active_org_ids(req.requester_id)
    if not requester_orgs:
        return False
    return bool(requester_orgs & user_active_org_ids(approver.id))


def create_request(tool_name: str, tool_input: dict, risk_level: str,
                   risk_reason: str, requester_id: int,
                   conversation_id: Optional[str] = None):
    """Create a pending ApprovalRequest and notify approvers."""
    from models import ApprovalRequest, db

    now = datetime.utcnow()
    req = ApprovalRequest(
        requester_id=requester_id,
        conversation_id=conversation_id,
        tool_name=tool_name,
        tool_input=tool_input,
        risk_level=risk_level,
        risk_reason=risk_reason,
        status='pending',
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    db.session.add(req)
    db.session.commit()

    try:
        _notify_approvers(req)
    except Exception as e:
        logger.warning(f"Failed to notify approvers for request {req.id}: {e}")

    return req


def _notify_approvers(req):
    """Create in-app notifications and send email to approvers who can act on this request."""
    from models import User, AppNotification, db
    from services.email_service import EmailService

    candidates = User.query.filter(User.role.in_(['approver', 'admin'])).all()
    approvers = [a for a in candidates if is_visible_to_approver(req, a)]
    if not approvers:
        logger.warning("No approvers configured to notify")
        return

    requester_name = req.requester.username if req.requester else f"User {req.requester_id}"
    email_svc = EmailService()

    for approver in approvers:
        notif = AppNotification(
            user_id=approver.id,
            title=f"Approval required: {req.tool_name}",
            body=f"{requester_name} requested approval for {req.tool_name}. Risk: {req.risk_level.upper()}",
            category='warning',
            link='/approvals',
        )
        db.session.add(notif)

        try:
            html = (
                f"<h2>Approval Required</h2>"
                f"<p><strong>Requester:</strong> {requester_name}</p>"
                f"<p><strong>Tool:</strong> {req.tool_name}</p>"
                f"<p><strong>Risk Level:</strong> {req.risk_level.upper()}</p>"
                f"<p><strong>Details:</strong> {req.risk_reason}</p>"
                f'<p><a href="{os.environ.get("BASE_URL", "https://devopsagent.io")}/approvals">Review and approve on DevOps Agent</a></p>'
            )
            email_svc.send_email(
                approver.email,
                f"[DevOps Agent] Approval required: {req.tool_name}",
                html,
            )
        except Exception as e:
            logger.warning(f"Failed to email approver {approver.email}: {e}")

    db.session.commit()


def approve(approval_id: int, approver_id: int, note: Optional[str] = None) -> dict:
    """Approve a request, execute the tool, and notify the requester."""
    from models import ApprovalRequest, User, AppNotification, ChatMessage, db

    req = ApprovalRequest.query.get(approval_id)
    if not req:
        return {'success': False, 'error': 'Request not found'}

    approver = User.query.get(approver_id)
    if not approver or approver.role not in ('approver', 'admin'):
        return {'success': False, 'error': 'Unauthorized'}

    if not is_visible_to_approver(req, approver):
        return {'success': False, 'error': 'Unauthorized'}

    if approver_id == req.requester_id:
        return {'success': False, 'error': 'Cannot approve your own request'}

    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}

    now = datetime.utcnow()
    req.status = 'approved'
    req.approver_id = approver_id
    req.decided_at = now
    req.approver_note = note
    db.session.commit()

    try:
        result = _execute_tool(req)
    except Exception as e:
        logger.error(f"Tool execution failed for approval {approval_id}: {e}", exc_info=True)
        result = {'success': False, 'error': str(e)}

    req.status = 'executed'
    req.execution_result = result
    req.executed_at = datetime.utcnow()
    db.session.commit()

    if req.conversation_id:
        try:
            result_text = (
                f"**Approval granted** by {approver.username}.\n\n"
                f"**Result ({req.tool_name}):**\n```json\n{json.dumps(result, indent=2)}\n```"
            )
            msg = ChatMessage(
                user_id=req.requester_id,
                conversation_id=req.conversation_id,
                role='assistant',
                content=result_text,
            )
            db.session.add(msg)
            db.session.commit()
        except Exception as e:
            logger.warning(f"Failed to append result to conversation: {e}")

    try:
        result_summary = 'succeeded' if result.get('success') else 'failed'
        notif = AppNotification(
            user_id=req.requester_id,
            title=f"Request approved: {req.tool_name}",
            body=f"Approved by {approver.username}. Execution {result_summary}.",
            category='success' if result.get('success') else 'warning',
            link='/chat',
        )
        db.session.add(notif)
        db.session.commit()

        requester = User.query.get(req.requester_id)
        if requester:
            from services.email_service import EmailService
            html = (
                f"<h2>Your Request Was Approved</h2>"
                f"<p><strong>Tool:</strong> {req.tool_name}</p>"
                f"<p><strong>Approved by:</strong> {approver.username}</p>"
                f"<p><strong>Result:</strong> {result_summary}</p>"
            )
            EmailService().send_email(
                requester.email,
                f"[DevOps Agent] Request approved: {req.tool_name}",
                html,
            )
    except Exception as e:
        logger.warning(f"Failed to notify requester after approval: {e}")

    return {'success': True, 'result': result}


def reject(approval_id: int, approver_id: int, note: Optional[str] = None) -> dict:
    """Reject a request and notify the requester."""
    from models import ApprovalRequest, User, AppNotification, db

    req = ApprovalRequest.query.get(approval_id)
    if not req:
        return {'success': False, 'error': 'Request not found'}

    approver = User.query.get(approver_id)
    if not approver or approver.role not in ('approver', 'admin'):
        return {'success': False, 'error': 'Unauthorized'}

    if not is_visible_to_approver(req, approver):
        return {'success': False, 'error': 'Unauthorized'}

    if approver_id == req.requester_id:
        return {'success': False, 'error': 'Cannot reject your own request'}

    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}

    req.status = 'rejected'
    req.approver_id = approver_id
    req.decided_at = datetime.utcnow()
    req.approver_note = note
    db.session.commit()

    try:
        note_text = f" Note: {note}" if note else ""
        notif = AppNotification(
            user_id=req.requester_id,
            title=f"Request rejected: {req.tool_name}",
            body=f"Rejected by {approver.username}.{note_text}",
            category='warning',
        )
        db.session.add(notif)
        db.session.commit()

        requester = User.query.get(req.requester_id)
        if requester:
            from services.email_service import EmailService
            html = (
                f"<h2>Your Request Was Rejected</h2>"
                f"<p><strong>Tool:</strong> {req.tool_name}</p>"
                f"<p><strong>Rejected by:</strong> {approver.username}</p>"
                + (f"<p><strong>Note:</strong> {note}</p>" if note else "")
            )
            EmailService().send_email(
                requester.email,
                f"[DevOps Agent] Request rejected: {req.tool_name}",
                html,
            )
    except Exception as e:
        logger.warning(f"Failed to notify requester after rejection: {e}")

    return {'success': True}


def get_pending_for_approver(approver_id: int) -> list:
    """Return non-expired pending requests visible to this approver, newest first.

    Admins see every pending request; other approvers only see requests from
    requesters who share an active organization with them (see
    is_visible_to_approver) — without this filter any role='approver' account could
    see (and, before the approve()/reject() checks above, act on) every
    organization's pending requests platform-wide.
    """
    from models import ApprovalRequest, User

    _expire_stale()
    now = datetime.utcnow()
    reqs = (
        ApprovalRequest.query
        .filter(ApprovalRequest.status == 'pending', ApprovalRequest.expires_at > now)
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )

    approver = User.query.get(approver_id)
    if not approver:
        return []
    from services.rbac import user_is_admin
    if user_is_admin(approver):
        return reqs
    return [r for r in reqs if is_visible_to_approver(r, approver)]


def _execute_tool(req) -> dict:
    """Execute the stored tool call by looking it up in the agent's tool registry.

    Must set the requester's cloud credential context before running the tool —
    without it, aws_tools._get_boto_client has no user to look up credentials for
    (see _set_cloud_user_context's callers in src/agent/core.py), which either
    fails closed with "Authentication required" or, worse, runs against whatever
    user context a previous request left behind on this greenlet.

    Also mirrors the three instrumentation calls every other tool-execution site
    in src/agent/core.py makes around a real handler invocation — this is the
    approve-and-run path for exactly the tool calls flagged high/medium risk, so
    skipping them here left every approved delete/terminate/etc. with no
    InfrastructureChange audit row (and no purge from the synced-resource list)
    and no Execution Integrity read-back verification, the two things this class
    of tool call needs most:
      - _record_tool_call: per-call observability (see core._record_tool_call).
      - _verify_and_annotate: read-back-verifies a create/delete/update and
        attaches result['_verification'].
      - _audit_infrastructure_change: writes the audit trail row — runs last so
        a destructive row can record the verification result (Phase 5 rule 10).
    These read self._current_user_id / self._current_conversation_id
    (greenlet-local, same mechanism as the cloud credential context above), so
    they must be set alongside it and cleared in the same finally, and the
    per-turn trackers reset first (agent._reset_turn_tool_state()).
    """
    try:
        from app import agent
        tool_name = req.tool_name
        if tool_name not in agent.tools:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}
        tool_input = req.tool_input or {}
        try:
            # This is a 4th tool-execution entry point — reset the per-turn
            # trackers _verify_and_annotate reads (stale on a pooled worker).
            agent._reset_turn_tool_state()
            agent._set_cloud_user_context(req.requester_id)
            agent._current_user_id = req.requester_id
            agent._current_conversation_id = req.conversation_id
            try:
                result = agent.tools[tool_name](**tool_input)
            except Exception as e:
                result = {'success': False, 'error': str(e)}
                agent._record_tool_call(tool_name, result, outcome='raised')
                return result
            # Order matches core.py's model-loop sites (Phase 5): record, then
            # verify (attaches result['_verification']), then audit — so the
            # rule-10 destructive audit trail can read the verification result.
            agent._record_tool_call(tool_name, result, outcome='ran')
            result = agent._verify_and_annotate(tool_name, tool_input, result)
            agent._audit_infrastructure_change(tool_name, tool_input, result)
            return result
        finally:
            agent._current_user_id = None
            agent._current_conversation_id = None
            agent._clear_cloud_user_context()
    except Exception as e:
        logger.error(f"_execute_tool failed for {req.tool_name}: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def _expire_stale():
    """Mark stale pending requests as expired (lazy, no background job needed)."""
    from models import ApprovalRequest, db

    now = datetime.utcnow()
    ApprovalRequest.query.filter(
        ApprovalRequest.status == 'pending',
        ApprovalRequest.expires_at <= now,
    ).update({'status': 'expired'})
    db.session.commit()
