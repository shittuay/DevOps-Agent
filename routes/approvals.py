from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import ApprovalRequest, InfrastructureChange, OrganizationMember, User, db
from functools import wraps

from services.rbac import user_is_admin, user_is_approver, user_active_org_ids, user_admin_org_ids

approvals_bp = Blueprint('approvals', __name__)


def _is_reviewer(user) -> bool:
    """Platform approvers/admins, and owners/admins of any organization."""
    return user_is_approver(user) or bool(user_admin_org_ids(user.id))


def _reviewer_required(f):
    """Like rbac.approver_required, but also lets organization owners and admins in:
    they approve their own team's agent requests without the platform role."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _is_reviewer(current_user):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Approver access required'}), 403
            return redirect(url_for('approvals.my_requests_page'))
        return f(*args, **kwargs)
    return wrapper


def _reviewable_requester_ids(user):
    from services.approval_service import reviewable_requester_ids
    return reviewable_requester_ids(user)


@approvals_bp.route('/approvals')
@login_required
@_reviewer_required
def queue_page():
    return render_template('approvals/queue.html')


def _org_scoped_change_query(query):
    """Restrict an InfrastructureChange query to requesters this reviewer covers.

    Since 2026-10-14 change requests follow the same reviewer rules as agent
    requests (organization owners/admins, platform approvers in the org, platform
    admins), scoped by the *requester's* organizations, not the change's stamp.
    """
    visible = _reviewable_requester_ids(current_user)
    if visible is None:
        return query
    if not visible:
        return query.filter(db.false())
    return query.filter(InfrastructureChange.user_id.in_(visible))


def _pending_changes_for_reviewer():
    from services.approval_service import can_review_change
    rows = _org_scoped_change_query(InfrastructureChange.query.filter_by(status='pending'))
    return [c for c in rows.order_by(InfrastructureChange.created_at.asc()).all()
            if can_review_change(c, current_user)]


@approvals_bp.route('/api/approvals/pending')
@login_required
@_reviewer_required
def get_pending():
    from services import approval_service
    result = []

    # Agent-triggered approval requests
    reqs = approval_service.get_pending_for_approver(current_user.id)
    for r in reqs:
        d = r.to_dict()
        d['_type'] = 'agent'
        result.append(d)

    # Manually-submitted change requests awaiting human approval
    for c in _pending_changes_for_reviewer():
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
@_reviewer_required
def get_count():
    from services import approval_service
    reqs = approval_service.get_pending_for_approver(current_user.id)
    return jsonify({'count': len(reqs) + len(_pending_changes_for_reviewer())})


@approvals_bp.route('/api/approvals/<int:approval_id>/status')
@login_required
def get_status(approval_id):
    from services import approval_service
    req = ApprovalRequest.query.get_or_404(approval_id)
    is_approver = approval_service.can_approve(req, current_user)
    if current_user.id != req.requester_id and not is_approver:
        return jsonify({'error': 'Access denied'}), 403
    data = req.to_dict()
    data['can_confirm'] = (
        current_user.id == req.requester_id
        and req.status == 'pending'
        and approval_service.can_self_confirm(req)
    )
    return jsonify(data)


@approvals_bp.route('/approvals/mine')
@login_required
def my_requests_page():
    return render_template('approvals/mine.html')


@approvals_bp.route('/api/approvals/mine')
@login_required
def get_mine():
    from services import approval_service
    result = []
    for r in approval_service.get_pending_for_requester(current_user.id):
        d = r.to_dict()
        d['_type'] = 'agent'
        d['can_confirm'] = approval_service.can_self_confirm(r)
        result.append(d)
    own_changes = (InfrastructureChange.query
                   .filter_by(user_id=current_user.id, status='pending')
                   .order_by(InfrastructureChange.created_at.asc()).all())
    for c in own_changes:
        details = c.change_details or {}
        label = f"{c.action_type} {c.resource_type}" + (f" ({c.resource_name})" if c.resource_name else '')
        result.append({
            '_type': 'change',
            'id': c.id,
            'tool_name': label,
            'risk_level': details.get('risk_level', 'medium'),
            'risk_reason': c.title,
            'status': c.status,
            'created_at': c.created_at.isoformat() + 'Z',
            'can_confirm': approval_service.can_confirm_own_change(c, current_user),
        })
    return jsonify(result)


@approvals_bp.route('/api/approvals/<int:approval_id>/confirm', methods=['POST'])
@login_required
def confirm_own(approval_id):
    from services import approval_service
    result = approval_service.confirm_own(approval_id, current_user.id)
    return jsonify(result), (200 if result['success'] else 400)


@approvals_bp.route('/api/approvals/<int:approval_id>/cancel', methods=['POST'])
@login_required
def cancel_own(approval_id):
    from services import approval_service
    result = approval_service.cancel_own(approval_id, current_user.id)
    return jsonify(result), (200 if result['success'] else 400)


@approvals_bp.route('/approvals/history')
@login_required
@_reviewer_required
def history_page():
    return render_template('approvals/history.html')


@approvals_bp.route('/api/approvals/history')
@login_required
@_reviewer_required
def get_history():
    status_filter = request.args.get('status', 'all')
    limit = min(int(request.args.get('limit', 100)), 500)

    # Agent approval requests (non-pending), scoped to this approver's organization(s)
    query = ApprovalRequest.query.filter(ApprovalRequest.status != 'pending')
    visible = _reviewable_requester_ids(current_user)
    if visible is not None:
        if not visible:
            query = query.filter(db.false())
        else:
            query = query.filter(ApprovalRequest.requester_id.in_(visible))
    if status_filter == 'approved':
        query = query.filter(ApprovalRequest.status.in_(['approved', 'executed']))
    elif status_filter in ('rejected', 'expired'):
        query = query.filter(ApprovalRequest.status == status_filter)
    reqs = query.order_by(ApprovalRequest.created_at.desc()).limit(limit).all()
    result = [r.to_dict() for r in reqs]

    # InfrastructureChange records (non-pending), same org scoping
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
@_reviewer_required
def approve(approval_id):
    data = request.get_json() or {}
    from services import approval_service
    result = approval_service.approve(approval_id, current_user.id, data.get('note'))
    status = 200 if result['success'] else 400
    return jsonify(result), status


@approvals_bp.route('/api/approvals/<int:approval_id>/reject', methods=['POST'])
@login_required
@_reviewer_required
def reject(approval_id):
    data = request.get_json() or {}
    from services import approval_service
    result = approval_service.reject(approval_id, current_user.id, data.get('note'))
    status = 200 if result['success'] else 400
    return jsonify(result), status
