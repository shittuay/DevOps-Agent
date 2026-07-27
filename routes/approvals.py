from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import ApprovalRequest, InfrastructureChange, User, db

approvals_bp = Blueprint('approvals', __name__)


def _approver_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role not in ('approver', 'admin'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Approver access required'}), 403
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


@approvals_bp.route('/approvals')
@login_required
@_approver_required
def queue_page():
    return render_template('approvals/queue.html')


def _org_scoped_change_query(query):
    """Restrict an InfrastructureChange query to the current approver's organizations.

    Mirrors routes/changes.py's list_pending_approvals(): admins see every
    organization's changes; non-admin approvers only see changes belonging to
    an organization they're an active member of. ApprovalRequest (agent tool-call
    approvals) has no organization_id and is intentionally platform-wide for any
    approver, so this only needs to apply to InfrastructureChange queries.
    """
    if current_user.role == 'admin':
        return query
    from routes.changes import _user_active_org_ids
    org_ids = _user_active_org_ids(current_user)
    if not org_ids:
        return query.filter(db.false())
    return query.filter(InfrastructureChange.organization_id.in_(org_ids))


@approvals_bp.route('/api/approvals/pending')
@login_required
@_approver_required
def get_pending():
    from services import approval_service
    result = []

    # Agent-triggered approval requests
    reqs = approval_service.get_pending_for_approver()
    for r in reqs:
        d = r.to_dict()
        d['_type'] = 'agent'
        result.append(d)

    # Manually-submitted change requests awaiting human approval
    changes_query = _org_scoped_change_query(
        InfrastructureChange.query.filter_by(status='pending')
    )
    changes = changes_query.order_by(InfrastructureChange.created_at.asc()).all()
    for c in changes:
        details = c.change_details or {}
        requester = User.query.get(c.user_id)
        tool_label = f"{c.action_type} {c.resource_type}"
        if c.resource_name:
            tool_label += f" ({c.resource_name})"
        result.append({
            '_type': 'change',
            'id': c.id,
            'requester_id': c.user_id,
            'requester_name': requester.username if requester else 'Unknown',
            'tool_name': tool_label,
            'risk_level': details.get('risk_level', 'medium'),
            'risk_reason': c.title,
            'created_at': c.created_at.isoformat() + 'Z',
            'description': c.description,
        })

    result.sort(key=lambda x: x['created_at'])
    return jsonify(result)


@approvals_bp.route('/api/approvals/count')
@login_required
@_approver_required
def get_count():
    from services import approval_service
    reqs = approval_service.get_pending_for_approver()
    pending_changes = _org_scoped_change_query(
        InfrastructureChange.query.filter_by(status='pending')
    ).count()
    return jsonify({'count': len(reqs) + pending_changes})


@approvals_bp.route('/api/approvals/<int:approval_id>/status')
@login_required
def get_status(approval_id):
    req = ApprovalRequest.query.get_or_404(approval_id)
    if current_user.id != req.requester_id and current_user.role not in ('approver', 'admin'):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(req.to_dict())


@approvals_bp.route('/approvals/history')
@login_required
@_approver_required
def history_page():
    return render_template('approvals/history.html')


@approvals_bp.route('/api/approvals/history')
@login_required
@_approver_required
def get_history():
    status_filter = request.args.get('status', 'all')
    limit = min(int(request.args.get('limit', 100)), 500)

    # Agent approval requests (non-pending)
    query = ApprovalRequest.query.filter(ApprovalRequest.status != 'pending')
    if status_filter == 'approved':
        query = query.filter(ApprovalRequest.status.in_(['approved', 'executed']))
    elif status_filter in ('rejected', 'expired'):
        query = query.filter(ApprovalRequest.status == status_filter)
    reqs = query.order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
    result = [r.to_dict() for r in reqs]

    # InfrastructureChange records (non-pending)
    if status_filter != 'expired':  # changes have no "expired" status
        cq = _org_scoped_change_query(
            InfrastructureChange.query.filter(InfrastructureChange.status != 'pending')
        )
        if status_filter == 'approved':
            cq = cq.filter(InfrastructureChange.status.in_(['approved', 'executed']))
        elif status_filter == 'rejected':
            cq = cq.filter(InfrastructureChange.status == 'rejected')
        changes = cq.order_by(InfrastructureChange.created_at.desc()).limit(limit).all()
        for c in changes:
            details = c.change_details or {}
            requester = User.query.get(c.user_id)
            approver = User.query.get(c.approver_id) if c.approver_id else None
            tool_label = f"{c.action_type} {c.resource_type}"
            if c.resource_name:
                tool_label += f" ({c.resource_name})"
            result.append({
                '_type': 'change',
                'id': c.id,
                'requester_id': c.user_id,
                'requester_name': requester.username if requester else 'Unknown',
                'tool_name': tool_label,
                'risk_level': details.get('risk_level', 'medium'),
                'risk_reason': c.title,
                'status': c.status,
                'created_at': c.created_at.isoformat() + 'Z',
                'decided_at': (c.approved_at.isoformat() + 'Z') if c.approved_at else None,
                'approver_name': approver.username if approver else None,
                'approver_note': c.approval_comment,
                'execution_result': c.execution_result,
            })

    result.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(result[:limit])


@approvals_bp.route('/api/approvals/<int:approval_id>/approve', methods=['POST'])
@login_required
@_approver_required
def approve(approval_id):
    data = request.get_json() or {}
    from services import approval_service
    result = approval_service.approve(approval_id, current_user.id, data.get('note'))
    status = 200 if result['success'] else 400
    return jsonify(result), status


@approvals_bp.route('/api/approvals/<int:approval_id>/reject', methods=['POST'])
@login_required
@_approver_required
def reject(approval_id):
    data = request.get_json() or {}
    from services import approval_service
    result = approval_service.reject(approval_id, current_user.id, data.get('note'))
    status = 200 if result['success'] else 400
    return jsonify(result), status
