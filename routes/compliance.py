"""
Compliance and Audit Routes
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, Response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json

compliance_bp = Blueprint('compliance', __name__, url_prefix='/compliance')


@compliance_bp.route('/')
@login_required
def dashboard():
    """Compliance dashboard"""
    return render_template('compliance/dashboard.html')


@compliance_bp.route('/frameworks')
@login_required
def frameworks():
    """List compliance frameworks"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)
    frameworks_data = service.get_enabled_frameworks()
    return render_template('compliance/frameworks.html', frameworks=frameworks_data)


@compliance_bp.route('/frameworks/<framework_id>')
@login_required
def framework_detail(framework_id):
    """Framework detail with controls"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    framework = service.get_framework(framework_id)
    if not framework:
        flash('Framework not found.', 'error')
        return redirect(url_for('compliance.frameworks'))

    controls = service.get_framework_controls(framework_id)
    framework_name = framework.name if hasattr(framework, 'name') else str(framework_id)
    assessment = service.run_compliance_check(current_user.id, framework_name)

    return render_template('compliance/framework_detail.html',
                         framework=framework,
                         controls=controls,
                         assessment=assessment)


@compliance_bp.route('/frameworks/<framework_id>/enable', methods=['POST'])
@login_required
def enable_framework(framework_id):
    """Enable a compliance framework"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    framework = service.get_framework(framework_id)
    framework_name = framework.name if framework and hasattr(framework, 'name') else str(framework_id)
    if service.enable_framework(current_user.id, framework_name):
        flash('Framework enabled successfully!', 'success')
    else:
        flash('Failed to enable framework.', 'error')

    return redirect(url_for('compliance.frameworks'))


@compliance_bp.route('/controls')
@login_required
def controls():
    """List all controls across frameworks"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)
    all_controls = service.get_all_controls()
    return render_template('compliance/controls.html', controls=all_controls)


@compliance_bp.route('/controls/<control_id>')
@login_required
def control_detail(control_id):
    """Control detail with evidence"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    control = service.get_control(control_id)
    if not control:
        flash('Control not found.', 'error')
        return redirect(url_for('compliance.controls'))

    evidence = service.get_control_evidence(control_id)
    remediation = service.get_remediation_steps(control_id)

    return render_template('compliance/control_detail.html',
                         control=control,
                         evidence=evidence,
                         remediation=remediation)


@compliance_bp.route('/controls/<control_id>/evidence', methods=['POST'])
@login_required
def add_evidence(control_id):
    """Add evidence for a control"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    data = {
        'control_id': control_id,
        'type': request.form.get('type'),
        'description': request.form.get('description'),
        'evidence_data': request.form.get('evidence_data'),
        'collected_by': current_user.id
    }

    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            from werkzeug.utils import secure_filename
            safe_name = secure_filename(file.filename)
            allowed_ext = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xlsx', 'csv', 'txt'}
            ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
            if ext not in allowed_ext:
                flash('File type not allowed. Accepted: PDF, images, documents.', 'error')
                return redirect(url_for('compliance.control_detail', control_id=control_id))
            file_data = file.read(10 * 1024 * 1024 + 1)  # Read up to 10MB + 1 byte
            if len(file_data) > 10 * 1024 * 1024:
                flash('File too large. Maximum size is 10MB.', 'error')
                return redirect(url_for('compliance.control_detail', control_id=control_id))
            data['file_name'] = safe_name
            data['file_data'] = file_data

    if service.add_evidence(data):
        flash('Evidence added successfully!', 'success')
    else:
        flash('Failed to add evidence.', 'error')

    return redirect(url_for('compliance.control_detail', control_id=control_id))


@compliance_bp.route('/audit-log')
@login_required
def audit_log():
    """Audit log viewer"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    action_type = request.args.get('action_type')
    resource_type = request.args.get('resource_type')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    filters = {}
    if action_type:
        filters['action_type'] = action_type
    if resource_type:
        filters['resource_type'] = resource_type
    if start_date:
        filters['start_date'] = datetime.fromisoformat(start_date)
    if end_date:
        filters['end_date'] = datetime.fromisoformat(end_date)

    limit = per_page * page  # fetch enough to cover current page
    logs = service.get_audit_logs(
        user_id=current_user.id,
        action=filters.get('action_type'),
        limit=limit
    )

    action_types = ['create', 'read', 'update', 'delete', 'login', 'logout', 'config_change', 'access_grant', 'access_revoke']
    resource_types = ['user', 'resource', 'credential', 'organization', 'api_key', 'webhook', 'policy']

    return render_template('compliance/audit_log.html',
                         logs=logs,
                         action_types=action_types,
                         resource_types=resource_types,
                         filters=filters)


@compliance_bp.route('/policies')
@login_required
def policies():
    """Security policies"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)
    all_policies = service.get_policies()
    return render_template('compliance/policies.html', policies=all_policies)


@compliance_bp.route('/policies/create', methods=['GET', 'POST'])
@login_required
def create_policy():
    """Create new policy"""
    if request.method == 'POST':
        from services.compliance_service import ComplianceService
        service = ComplianceService(current_user.id)

        conditions = []
        cond_fields = request.form.getlist('condition_field')
        cond_operators = request.form.getlist('condition_operator')
        cond_values = request.form.getlist('condition_value')

        for i in range(len(cond_fields)):
            if cond_fields[i]:
                conditions.append({
                    'field': cond_fields[i],
                    'operator': cond_operators[i] if i < len(cond_operators) else 'equals',
                    'value': cond_values[i] if i < len(cond_values) else ''
                })

        data = {
            'name': request.form.get('name'),
            'description': request.form.get('description'),
            'policy_type': request.form.get('policy_type'),
            'resource_types': request.form.getlist('resource_types'),
            'conditions': conditions,
            'enforcement': request.form.get('enforcement', 'warn'),
            'created_by': current_user.id
        }

        policy = service.create_policy(data)
        if policy:
            flash('Policy created successfully!', 'success')
            return redirect(url_for('compliance.policies'))
        else:
            flash('Failed to create policy.', 'error')

    policy_types = ['access_control', 'data_retention', 'encryption', 'network', 'resource_tagging', 'cost_limit']
    resource_types = ['ec2', 's3', 'rds', 'lambda', 'vpc', 'iam', 'kubernetes', 'all']

    return render_template('compliance/create_policy.html',
                         policy_types=policy_types,
                         resource_types=resource_types)


@compliance_bp.route('/policies/<int:policy_id>/toggle', methods=['POST'])
@login_required
def toggle_policy(policy_id):
    """Enable/disable policy"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    if service.toggle_policy(policy_id):
        flash('Policy status updated.', 'success')
    else:
        flash('Failed to update policy.', 'error')

    return redirect(url_for('compliance.policies'))


@compliance_bp.route('/policies/<int:policy_id>/delete', methods=['POST'])
@login_required
def delete_policy(policy_id):
    """Delete policy"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    if service.delete_policy(policy_id):
        flash('Policy deleted.', 'success')
    else:
        flash('Failed to delete policy.', 'error')

    return redirect(url_for('compliance.policies'))


@compliance_bp.route('/reports')
@login_required
def reports():
    """Compliance reports"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)
    recent_reports = service.get_recent_reports()
    return render_template('compliance/reports.html', reports=recent_reports)


@compliance_bp.route('/reports/generate', methods=['POST'])
@login_required
def generate_report():
    """Generate compliance report"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    framework_id = request.form.get('framework')
    report_type = request.form.get('report_type', 'summary')

    report = service.generate_report(framework_id, report_type)
    if report:
        flash('Report generated successfully!', 'success')
    else:
        flash('Failed to generate report.', 'error')

    return redirect(url_for('compliance.reports'))


@compliance_bp.route('/reports/<int:report_id>/download')
@login_required
def download_report(report_id):
    """Download compliance report"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    report = service.get_report(report_id)
    if not report:
        flash('Report not found.', 'error')
        return redirect(url_for('compliance.reports'))

    format_type = request.args.get('format', 'pdf')
    content = service.export_report(report_id, format_type)

    if format_type == 'pdf':
        mimetype = 'application/pdf'
        ext = 'pdf'
    elif format_type == 'csv':
        mimetype = 'text/csv'
        ext = 'csv'
    else:
        mimetype = 'application/json'
        ext = 'json'

    return Response(
        content,
        mimetype=mimetype,
        headers={'Content-Disposition': f'attachment; filename=compliance_report_{report_id}.{ext}'}
    )


# API Endpoints
@compliance_bp.route('/api/dashboard')
@login_required
def api_dashboard():
    """Get compliance dashboard data"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    data = {
        'overall_score': service.get_overall_compliance_score(),
        'frameworks': service.get_framework_scores(),
        'critical_findings': service.get_critical_findings(),
        'recent_violations': service.get_recent_violations(limit=10),
        'trends': service.get_compliance_trends(days=30)
    }

    return jsonify(data)


@compliance_bp.route('/api/run-check', methods=['POST'])
@login_required
def api_run_check():
    """Run compliance check"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    framework_id = request.json.get('framework_id')
    result = service.run_compliance_check(current_user.id, framework_id)

    return jsonify(result)


@compliance_bp.route('/api/audit-log')
@login_required
def api_audit_log():
    """Get audit log entries"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    logs = service.get_audit_logs(user_id=current_user.id, limit=per_page)

    return jsonify({
        'logs': [{
            'id': getattr(log, 'id', None),
            'action': getattr(log, 'action_type', None),
            'resource_type': getattr(log, 'resource_type', None),
            'resource_id': getattr(log, 'resource_id', None),
            'details': getattr(log, 'details', None),
            'ip_address': getattr(log, 'ip_address', None),
            'timestamp': log.timestamp.isoformat() if getattr(log, 'timestamp', None) else None
        } for log in logs],
        'total': len(logs),
        'pages': 1,
        'current_page': page
    })


@compliance_bp.route('/api/violations')
@login_required
def api_violations():
    """Get policy violations"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    status = request.args.get('status', 'open')
    violations = service.get_violations(status=status)

    return jsonify({
        'violations': [{
            'id': v.id,
            'policy_name': v.policy.name if v.policy else None,
            'resource_type': v.resource_type,
            'resource_id': v.resource_id,
            'severity': v.severity,
            'status': v.status,
            'detected_at': v.detected_at.isoformat() if v.detected_at else None
        } for v in violations]
    })


@compliance_bp.route('/api/violations/<int:violation_id>/resolve', methods=['POST'])
@login_required
def api_resolve_violation(violation_id):
    """Resolve a violation"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    resolution = request.json.get('resolution')
    if service.resolve_violation(violation_id, resolution, current_user.id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to resolve violation'}), 400


@compliance_bp.route('/api/export/audit-log')
@login_required
def api_export_audit_log():
    """Export audit log"""
    from services.compliance_service import ComplianceService
    service = ComplianceService(current_user.id)

    format_type = request.args.get('format', 'csv')
    days = int(request.args.get('days', 30))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    content = service.export_audit_log(start_date, end_date, format_type)

    if format_type == 'csv':
        mimetype = 'text/csv'
    else:
        mimetype = 'application/json'

    return Response(
        content,
        mimetype=mimetype,
        headers={'Content-Disposition': f'attachment; filename=audit_log.{format_type}'}
    )
