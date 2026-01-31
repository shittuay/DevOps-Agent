"""
Infrastructure Drift Detection Routes for DevOps Agent.

Provides endpoints for drift detection, baseline management, and reporting.
"""

from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
import logging

from services.drift_detection import (
    get_drift_service, BaselineResource, ResourceType, DriftSeverity
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

    baselines = service.get_baselines()
    reports = service.get_recent_reports(limit=10)

    # Get latest report summary if available
    latest_report = reports[0] if reports else None

    return render_template('drift/dashboard.html',
        baselines=baselines,
        reports=reports,
        latest_report=latest_report,
        baseline_count=service.get_baseline_count(),
        ResourceType=ResourceType
    )


@drift_bp.route('/report/<report_id>')
@login_required
def view_report(report_id: str):
    """View a specific drift report."""
    service = get_drift_service()
    report = service.get_report(report_id)

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

    if service.get_baseline_count() == 0:
        return jsonify({
            'success': False,
            'error': 'No baselines configured. Import a Terraform state or add baselines first.'
        }), 400

    report = service.scan_for_drift()

    logger.info(f"Drift scan completed by {current_user.email}: {report.summary['total_drifts']} drifts found")

    return jsonify({
        'success': True,
        'report_id': report.id,
        'summary': report.summary
    })


@drift_bp.route('/api/reports')
@login_required
def api_list_reports():
    """API: List drift reports."""
    service = get_drift_service()
    limit = request.args.get('limit', 10, type=int)

    reports = service.get_recent_reports(limit=limit)

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
    report = service.get_report(report_id)

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

    baselines = service.get_baselines(resource_type=resource_type)

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

    service.add_baseline(baseline)

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
    service.remove_baseline(rt, resource_id)

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
    initial_count = service.get_baseline_count()

    service.import_terraform_state(data['state'])

    new_count = service.get_baseline_count()
    imported = new_count - initial_count

    logger.info(f"Terraform state imported by {current_user.email}: {imported} resources")

    return jsonify({
        'success': True,
        'imported': imported,
        'total_baselines': new_count
    })


@drift_bp.route('/api/import/sample', methods=['POST'])
@login_required
def api_import_sample():
    """API: Import sample baselines for testing."""
    service = get_drift_service()

    # Add sample baselines
    sample_baselines = [
        BaselineResource(
            resource_type=ResourceType.EC2_INSTANCE,
            resource_id='i-0abc123def456',
            resource_name='web-server-1',
            expected_config={
                'instance_type': 't3.small',
                'state': 'running',
                'security_groups': ['sg-12345'],
                'tags': {'Environment': 'production'}
            },
            tags={'Environment': 'production', 'Team': 'platform'}
        ),
        BaselineResource(
            resource_type=ResourceType.EC2_SECURITY_GROUP,
            resource_id='sg-12345',
            resource_name='web-sg',
            expected_config={
                'name': 'web-sg',
                'vpc_id': 'vpc-12345',
                'ingress': [
                    {'port': 443, 'cidr': '10.0.0.0/8'},
                    {'port': 80, 'cidr': '10.0.0.0/8'}
                ]
            },
            tags={'Environment': 'production'}
        ),
        BaselineResource(
            resource_type=ResourceType.S3_BUCKET,
            resource_id='my-app-data-bucket',
            resource_name='my-app-data-bucket',
            expected_config={
                'versioning': True,
                'encryption': 'AES256',
                'public_access_block': {
                    'block_public_acls': True,
                    'block_public_policy': True
                }
            },
            tags={'Environment': 'production'}
        ),
        BaselineResource(
            resource_type=ResourceType.RDS_INSTANCE,
            resource_id='mydb-instance',
            resource_name='production-database',
            expected_config={
                'engine': 'postgres',
                'engine_version': '14.9',
                'instance_class': 'db.t3.medium',
                'publicly_accessible': False,
                'storage_encrypted': True,
                'multi_az': True
            },
            tags={'Environment': 'production'}
        ),
    ]

    for baseline in sample_baselines:
        service.add_baseline(baseline)

    return jsonify({
        'success': True,
        'imported': len(sample_baselines),
        'total_baselines': service.get_baseline_count()
    })
