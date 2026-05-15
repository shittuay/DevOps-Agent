from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import ApprovalRequest

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


@approvals_bp.route('/api/approvals/pending')
@login_required
@_approver_required
def get_pending():
    from services import approval_service
    reqs = approval_service.get_pending_for_approver()
    return jsonify([r.to_dict() for r in reqs])


@approvals_bp.route('/api/approvals/count')
@login_required
@_approver_required
def get_count():
    from services import approval_service
    reqs = approval_service.get_pending_for_approver()
    return jsonify({'count': len(reqs)})


@approvals_bp.route('/api/approvals/<int:approval_id>/status')
@login_required
def get_status(approval_id):
    req = ApprovalRequest.query.get_or_404(approval_id)
    if current_user.id != req.requester_id and current_user.role not in ('approver', 'admin'):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(req.to_dict())


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
