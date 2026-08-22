"""
Infrastructure Drift Detection Routes for DevOps Agent.

Provides endpoints for drift detection, baseline management, and reporting.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
import logging

from services.drift_detection import (
    get_drift_service, BaselineResource, ResourceType, DriftSeverity, DriftScanError
)
from services.rbac import approver_required

logger = logging.getLogger(__name__)

drift_bp = Blueprint('drift', __name__, url_prefix='/drift')


# ==================== WEB ROUTES ====================


@drift_bp.route('/')
@login_required
def drift_dashboard():
    """Drift detection dashboard."""
    service = get_drift_service()

    baselines = service.get_baselines(current_user.id)
    reports = service.get_recent_reports(current_user.id, limit=10)

    # Get latest report summary if available
    latest_report = reports[0] if reports else None

    return render_template('drift/dashboard.html',
        baselines=baselines,
        reports=reports,
        latest_report=latest_report,
        baseline_count=service.get_baseline_count(current_user.id),
        ResourceType=ResourceType
    )


@drift_bp.route('/report/<report_id>')
@login_required
def view_report(report_id: str):
    """View a specific drift report."""
    service = get_drift_service()
    report = service.get_report(current_user.id, report_id)

    if not report:
        return "Report not found", 404

    return render_template('drift/report.html',
        report=report,
        DriftSeverity=DriftSeverity
    )


# ==================== API ROUTES ====================


@drift_bp.route('/api/scan', methods=['POST'])
@login_required
@approver_required
def api_scan():
    """API: Trigger a drift detection scan."""
    service = get_drift_service()

    if service.get_baseline_count(current_user.id) == 0:
        return jsonify({
            'success': False,
            'error': 'No baselines configured. Import a Terraform state or add baselines first.'
        }), 400

    try:
        report = service.scan_for_drift(current_user.id)
    except DriftScanError as e:
        # Could not read the account. Report that plainly — an unreadable account
        # is not the same as a clean one, and must never be shown as findings.
        logger.warning(f"Drift scan aborted for {current_user.email}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'scan_failed': True,
        }), 502

    logger.info(f"Drift scan completed by {current_user.email}: {report.summary['total_drifts']} drifts found")

    return jsonify({
        'success': True,
        'report_id': report.id,
        'summary': report.summary
    })


@drift_bp.route('/api/baselines/capture', methods=['POST'])
@login_required
@approver_required
def api_capture_baselines():
    """API: Snapshot the user's live cloud resources as baselines.

    The cloud-account-native way to start using drift: pin what you actually
    have, so any later change shows up. Terraform state import is the other path.
    """
    service = get_drift_service()

    data = request.get_json(silent=True) or {}
    requested = data.get('resource_types')
    resource_types = None
    if requested:
        try:
            resource_types = [ResourceType(rt) for rt in requested]
        except ValueError as e:
            return jsonify({'success': False, 'error': f'Unknown resource type: {e}'}), 400

    try:
        result = service.capture_baselines_from_account(current_user.id, resource_types)
    except DriftScanError as e:
        logger.warning(f"Baseline capture failed for {current_user.email}: {e}")
        return jsonify({'success': False, 'error': str(e), 'scan_failed': True}), 502

    logger.info(f"Baselines captured by {current_user.email}: {result['total']}")

    return jsonify({
        'success': True,
        'captured': result['total'],
        'by_type': result['by_type'],
        'total_baselines': service.get_baseline_count(current_user.id),
    })


@drift_bp.route('/api/reports')
@login_required
def api_list_reports():
    """API: List drift reports."""
    service = get_drift_service()
    limit = request.args.get('limit', 10, type=int)

    reports = service.get_recent_reports(current_user.id, limit=limit)

    return jsonify({
        'success': True,
        'count': len(reports),
        'reports': [{
            'id': r.id,
            'scan_started': r.scan_started.isoformat(),
            'scan_completed': r.scan_completed.isoformat(),
            'total_resources': r.total_resources,
            'drifted_resources': r.drifted_resources,
            'total_drifts': r.summary['total_drifts'],
            'critical_count': r.summary['critical_count']
        } for r in reports]
    })


@drift_bp.route('/api/reports/<report_id>')
@login_required
def api_get_report(report_id: str):
    """API: Get a specific drift report."""
    service = get_drift_service()
    report = service.get_report(current_user.id, report_id)

    if not report:
        return jsonify({'success': False, 'error': 'Report not found'}), 404

    return jsonify({
        'success': True,
        'report': {
            'id': report.id,
            'scan_started': report.scan_started.isoformat(),
            'scan_completed': report.scan_completed.isoformat(),
            'total_resources': report.total_resources,
            'drifted_resources': report.drifted_resources,
            'summary': report.summary,
            'drift_items': [{
                'id': d.id,
                'resource_type': d.resource_type.value,
                'resource_id': d.resource_id,
                'resource_name': d.resource_name,
                'drift_type': d.drift_type.value,
                'severity': d.severity.value,
                'expected_value': str(d.expected_value)[:200],
                'actual_value': str(d.actual_value)[:200],
                'property_path': d.property_path,
                'description': d.description,
                'remediation_suggestion': d.remediation_suggestion
            } for d in report.drift_items]
        }
    })


@drift_bp.route('/api/baselines')
@login_required
def api_list_baselines():
    """API: List all baselines."""
    service = get_drift_service()

    resource_type = request.args.get('type')
    if resource_type:
        try:
            resource_type = ResourceType(resource_type)
        except ValueError:
            resource_type = None

    baselines = service.get_baselines(current_user.id, resource_type=resource_type)

    return jsonify({
        'success': True,
        'count': len(baselines),
        'baselines': [{
            'resource_type': b.resource_type.value,
            'resource_id': b.resource_id,
            'resource_name': b.resource_name,
            'tags': b.tags,
            'last_updated': b.last_updated.isoformat()
        } for b in baselines]
    })


@drift_bp.route('/api/baselines', methods=['POST'])
@login_required
@approver_required
def api_add_baseline():
    """API: Add a baseline resource."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    required = ['resource_type', 'resource_id', 'expected_config']
    for field in required:
        if field not in data:
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400

    try:
        resource_type = ResourceType(data['resource_type'])
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid resource_type'}), 400

    service = get_drift_service()

    baseline = BaselineResource(
        resource_type=resource_type,
        resource_id=data['resource_id'],
        resource_name=data.get('resource_name', data['resource_id']),
        expected_config=data['expected_config'],
        tags=data.get('tags', {})
    )

    service.add_baseline(current_user.id, baseline)

    logger.info(f"Baseline added by {current_user.email}: {resource_type.value}:{data['resource_id']}")

    return jsonify({
        'success': True,
        'message': 'Baseline added successfully'
    })


@drift_bp.route('/api/baselines/<resource_type>/<resource_id>', methods=['DELETE'])
@login_required
@approver_required
def api_delete_baseline(resource_type: str, resource_id: str):
    """API: Delete a baseline resource."""
    try:
        rt = ResourceType(resource_type)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid resource_type'}), 400

    service = get_drift_service()
    service.remove_baseline(current_user.id, rt, resource_id)

    logger.info(f"Baseline removed by {current_user.email}: {resource_type}:{resource_id}")

    return jsonify({
        'success': True,
        'message': 'Baseline removed successfully'
    })


@drift_bp.route('/api/import/terraform', methods=['POST'])
@login_required
@approver_required
def api_import_terraform():
    """API: Import baselines from Terraform state."""
    data = request.get_json()

    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    if 'state' not in data:
        return jsonify({'success': False, 'error': 'Terraform state required'}), 400

    service = get_drift_service()
    initial_count = service.get_baseline_count(current_user.id)

    service.import_terraform_state(current_user.id, data['state'])

    new_count = service.get_baseline_count(current_user.id)
    imported = new_count - initial_count

    logger.info(f"Terraform state imported by {current_user.email}: {imported} resources")

    return jsonify({
        'success': True,
        'imported': imported,
        'total_baselines': new_count
    })
