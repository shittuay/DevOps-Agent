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
from src.utils.timeutils import utcnow

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


def eligible_approver_ids(req) -> set:
    """Users in the requester's organizations who may approve this request.

    That is every active member of an organization the requester belongs to who
    is either an owner/admin of that organization, or holds the platform-wide
    'approver'/'admin' role. The requester is never included. Platform admins
    outside the requester's organizations can also act (see can_approve), but are
    deliberately not counted here: they know nothing about a customer's account,
    so their existence must not stop a customer confirming their own action.
    """
    from sqlalchemy import or_
    from models import OrganizationMember, User
    from services.rbac import user_active_org_ids, ORG_APPROVER_ROLES

    org_ids = user_active_org_ids(req.requester_id)
    if not org_ids:
        return set()
    rows = (
        OrganizationMember.query
        .join(User, User.id == OrganizationMember.user_id)
        .filter(
            OrganizationMember.organization_id.in_(org_ids),
            OrganizationMember.is_active.is_(True),
            OrganizationMember.user_id != req.requester_id,
            or_(
                OrganizationMember.role.in_(ORG_APPROVER_ROLES),
                User.role.in_(('approver', 'admin')),
            ),
        )
        .with_entities(OrganizationMember.user_id)
        .all()
    )
    return {r[0] for r in rows}


def can_approve(req, user) -> bool:
    """Whether this user may approve or reject someone else's request."""
    from services.rbac import user_is_admin
    if not user or user.id == req.requester_id:
        return False
    if user_is_admin(user):
        return True
    return user.id in eligible_approver_ids(req)


def is_visible_to_approver(req, approver) -> bool:
    """Kept for existing callers: an approver may see a request they can act on."""
    return can_approve(req, approver)


def can_self_confirm(req) -> bool:
    """Whether the requester may confirm (approve) their own request.

    Allowed when nobody in the requester's organizations could approve it: a
    solo account, or an organization with no other owner, admin or approver.
    Otherwise the platform admins were the only reviewers, and they can't judge
    a customer's account, so the request simply expired.
    """
    return not eligible_approver_ids(req)


def waiting_message(req) -> str:
    """Tool-result text telling the model (and through it, the user) what happens next."""
    if can_self_confirm(req):
        return (
            f"Not run yet: {req.tool_name} is a risky action and needs the user's confirmation. "
            f"Tell the user to confirm or cancel it with the buttons in chat, or on the "
            f"My requests page (/approvals/mine). Request id {req.id}, expires in 24 hours."
        )
    return (
        f"Not run yet: approval request {req.id} for {req.tool_name} was sent to the owners, admins "
        f"and approvers of the user's organization. It runs once one of them approves it on /approvals."
    )


def create_request(tool_name: str, tool_input: dict, risk_level: str,
                   risk_reason: str, requester_id: int,
                   conversation_id: Optional[str] = None):
    """Create a pending ApprovalRequest and notify approvers."""
    from models import ApprovalRequest, db

    now = utcnow()
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
        if can_self_confirm(req):
            _notify_requester_to_confirm(req)
        else:
            _notify_approvers(req)
    except Exception as e:
        logger.warning(f"Failed to send notifications for approval request {req.id}: {e}")

    return req


def _notify_requester_to_confirm(req):
    """In-app reminder for a solo requester whose action is waiting on their own confirmation."""
    from models import AppNotification, db
    db.session.add(AppNotification(
        user_id=req.requester_id,
        title=f"Confirm action: {req.tool_name}",
        body=f"{req.risk_reason}. Confirm or cancel it within 24 hours.",
        category='warning',
        link='/approvals/mine',
    ))
    db.session.commit()


def _notify_approvers(req):
    """Create in-app notifications and send email to approvers who can act on this request."""
    from models import User, AppNotification, db
    from services.email_service import EmailService

    ids = eligible_approver_ids(req)
    approvers = User.query.filter(User.id.in_(ids)).all() if ids else []
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
    from models import ApprovalRequest, User

    req = ApprovalRequest.query.get(approval_id)
    if not req:
        return {'success': False, 'error': 'Request not found'}

    if approver_id == req.requester_id:
        return {'success': False, 'error': 'Cannot approve your own request'}

    approver = User.query.get(approver_id)
    if not can_approve(req, approver):
        return {'success': False, 'error': 'Unauthorized'}

    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}

    return _run_approved(req, approver, note, self_confirmed=False)


def confirm_own(approval_id: int, user_id: int) -> dict:
    """The requester confirms their own request. Only allowed for solo accounts."""
    from models import ApprovalRequest, User

    _expire_stale()
    req = ApprovalRequest.query.get(approval_id)
    if not req or req.requester_id != user_id:
        return {'success': False, 'error': 'Request not found'}
    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}
    if not can_self_confirm(req):
        return {'success': False, 'error': 'An approver in your organization must approve this request'}
    user = User.query.get(user_id)
    if not user:
        return {'success': False, 'error': 'Request not found'}
    return _run_approved(req, user, None, self_confirmed=True)


def cancel_own(approval_id: int, user_id: int) -> dict:
    """The requester withdraws their own pending request."""
    from models import ApprovalRequest, db

    _expire_stale()
    req = ApprovalRequest.query.get(approval_id)
    if not req or req.requester_id != user_id:
        return {'success': False, 'error': 'Request not found'}
    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}
    req.status = 'rejected'
    req.approver_id = user_id
    req.decided_at = utcnow()
    req.approver_note = 'Cancelled by the requester'
    db.session.commit()
    return {'success': True}


def get_pending_for_requester(user_id: int) -> list:
    """The user's own non-expired pending requests, newest first."""
    from models import ApprovalRequest

    _expire_stale()
    return (
        ApprovalRequest.query
        .filter(ApprovalRequest.requester_id == user_id, ApprovalRequest.status == 'pending')
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )


def _run_approved(req, decided_by, note: Optional[str], self_confirmed: bool) -> dict:
    """Mark a request approved, execute it, and record the outcome."""
    from models import User, AppNotification, ChatMessage, db

    now = utcnow()
    req.status = 'approved'
    req.approver_id = decided_by.id
    req.decided_at = now
    req.approver_note = note if not self_confirmed else 'Confirmed by the requester'
    db.session.commit()

    try:
        result = _execute_tool(req)
    except Exception as e:
        logger.error(f"Tool execution failed for approval {req.id}: {e}", exc_info=True)
        result = {'success': False, 'error': str(e)}

    req.status = 'executed'
    req.execution_result = result
    req.executed_at = utcnow()
    db.session.commit()

    heading = "**Confirmed by you.**" if self_confirmed else f"**Approval granted** by {decided_by.username}."
    if req.conversation_id:
        try:
            result_text = (
                f"{heading}\n\n"
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

    if self_confirmed:
        return {'success': True, 'result': result}

    try:
        result_summary = 'succeeded' if result.get('success') else 'failed'
        notif = AppNotification(
            user_id=req.requester_id,
            title=f"Request approved: {req.tool_name}",
            body=f"Approved by {decided_by.username}. Execution {result_summary}.",
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
                f"<p><strong>Approved by:</strong> {decided_by.username}</p>"
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

    if approver_id == req.requester_id:
        return {'success': False, 'error': 'Cannot reject your own request'}

    approver = User.query.get(approver_id)
    if not can_approve(req, approver):
        return {'success': False, 'error': 'Unauthorized'}

    if req.status != 'pending':
        return {'success': False, 'error': f'Request is already {req.status}'}

    req.status = 'rejected'
    req.approver_id = approver_id
    req.decided_at = utcnow()
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
    now = utcnow()
    reqs = (
        ApprovalRequest.query
        .filter(ApprovalRequest.status == 'pending', ApprovalRequest.expires_at > now)
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )

    approver = User.query.get(approver_id)
    if not approver:
        return []
    return [r for r in reqs if can_approve(r, approver)]


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
                _invalidate_read_cache(req.requester_id)
                return result
            # Order matches core.py's model-loop sites (Phase 5): record, then
            # verify (attaches result['_verification']), then audit — so the
            # rule-10 destructive audit trail can read the verification result.
            agent._record_tool_call(tool_name, result, outcome='ran')
            _invalidate_read_cache(req.requester_id)
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


def _invalidate_read_cache(user_id) -> None:
    """Drop the requester's cached reads so nothing stale contradicts the change just made.

    DevOpsAgent._invoke_tool does this for the chat paths; this path calls the
    handler directly, so it has to do it itself.
    """
    try:
        from services.tool_cache import READ_CACHE
        READ_CACHE.invalidate_user(user_id)
    except Exception as e:
        logger.warning(f"Read-cache invalidation failed for user {user_id}: {e}")


def _expire_stale():
    """Mark stale pending requests as expired (lazy, no background job needed)."""
    from models import ApprovalRequest, db

    now = utcnow()
    ApprovalRequest.query.filter(
        ApprovalRequest.status == 'pending',
        ApprovalRequest.expires_at <= now,
    ).update({'status': 'expired'})
    db.session.commit()
