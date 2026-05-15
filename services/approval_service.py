"""
Approval workflow service.

Manages creation, notification, approval, rejection, and tool execution
for high-risk tool calls that require a second human sign-off.
"""
import json
import logging
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
    """Create in-app notifications and send email to all approvers/admins."""
    from models import User, AppNotification, db
    from services.email_service import EmailService

    approvers = User.query.filter(User.role.in_(['approver', 'admin'])).all()
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
                f'<p><a href="/approvals">Review and approve on DevOps Agent</a></p>'
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


def get_pending_for_approver() -> list:
    """Return all non-expired pending requests, newest first."""
    from models import ApprovalRequest

    _expire_stale()
    now = datetime.utcnow()
    return (
        ApprovalRequest.query
        .filter(ApprovalRequest.status == 'pending', ApprovalRequest.expires_at > now)
        .order_by(ApprovalRequest.created_at.desc())
        .all()
    )


def _execute_tool(req) -> dict:
    """Execute the stored tool call by looking it up in the agent's tool registry."""
    try:
        from app import agent
        tool_name = req.tool_name
        if tool_name not in agent.tools:
            return {'success': False, 'error': f'Unknown tool: {tool_name}'}
        return agent.tools[tool_name](**(req.tool_input or {}))
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
