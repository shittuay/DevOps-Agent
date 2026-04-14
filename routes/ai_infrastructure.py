"""
AI Infrastructure Routes - Natural Language Provisioning
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime

ai_infrastructure_bp = Blueprint('ai_infrastructure', __name__, url_prefix='/ai')


@ai_infrastructure_bp.route('/')
@login_required
def dashboard():
    """AI Infrastructure dashboard"""
    return render_template('ai_infrastructure/dashboard.html')


@ai_infrastructure_bp.route('/provision')
@login_required
def provision():
    """Natural language infrastructure provisioning"""
    return render_template('ai_infrastructure/provision.html')


@ai_infrastructure_bp.route('/templates')
@login_required
def templates():
    """Infrastructure templates"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    all_templates = service.get_user_templates(current_user.id)
    return render_template('ai_infrastructure/templates.html', templates=all_templates)


@ai_infrastructure_bp.route('/templates/<template_id>')
@login_required
def template_detail(template_id):
    """Template detail"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    template = service.get_template(template_id)

    if not template:
        flash('Template not found.', 'error')
        return redirect(url_for('ai_infrastructure.templates'))

    return render_template('ai_infrastructure/template_detail.html', template=template)


@ai_infrastructure_bp.route('/recommendations')
@login_required
def recommendations():
    """AI-powered recommendations"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    all_recommendations = service.get_recommendations(current_user.id)
    return render_template('ai_infrastructure/recommendations.html', recommendations=all_recommendations)


@ai_infrastructure_bp.route('/deployments')
@login_required
def deployments():
    """AI-assisted deployments history"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    all_deployments = service.get_user_deployments(current_user.id)
    return render_template('ai_infrastructure/deployments.html', deployments=all_deployments)


@ai_infrastructure_bp.route('/deployments/<int:deployment_id>')
@login_required
def deployment_detail(deployment_id):
    """Deployment detail"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    deployment = service.get_user_deployment(current_user.id, deployment_id)

    if not deployment:
        flash('Deployment not found.', 'error')
        return redirect(url_for('ai_infrastructure.deployments'))

    return render_template('ai_infrastructure/deployment_detail.html', deployment=deployment)


# API Endpoints
@ai_infrastructure_bp.route('/api/parse', methods=['POST'])
@login_required
def api_parse_request():
    """Parse natural language infrastructure request"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'request' not in data:
        return jsonify({'error': 'Request text is required'}), 400

    result = service.parse_natural_language(data['request'])
    return jsonify(result)


@ai_infrastructure_bp.route('/api/generate-terraform', methods=['POST'])
@login_required
def api_generate_terraform():
    """Generate Terraform code from spec"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'spec' not in data:
        return jsonify({'error': 'Infrastructure spec is required'}), 400

    terraform_code = service.generate_terraform(data['spec'])
    return jsonify({
        'terraform': terraform_code,
        'format': 'hcl'
    })


@ai_infrastructure_bp.route('/api/generate-cloudformation', methods=['POST'])
@login_required
def api_generate_cloudformation():
    """Generate CloudFormation template from spec"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'spec' not in data:
        return jsonify({'error': 'Infrastructure spec is required'}), 400

    template = service.generate_cloudformation(data['spec'])
    return jsonify({
        'template': template,
        'format': 'yaml'
    })


@ai_infrastructure_bp.route('/api/estimate-cost', methods=['POST'])
@login_required
def api_estimate_cost():
    """Estimate infrastructure cost"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'spec' not in data:
        return jsonify({'error': 'Infrastructure spec is required'}), 400

    estimate = service.estimate_cost(data['spec'])
    return jsonify(estimate)


@ai_infrastructure_bp.route('/api/validate', methods=['POST'])
@login_required
def api_validate_spec():
    """Validate infrastructure spec"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'spec' not in data:
        return jsonify({'error': 'Infrastructure spec is required'}), 400

    validation = service.validate_spec(data['spec'])
    return jsonify(validation)


@ai_infrastructure_bp.route('/api/deploy', methods=['POST'])
@login_required
def api_deploy():
    """Deploy infrastructure from spec"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'spec' not in data:
        return jsonify({'error': 'Infrastructure spec is required'}), 400

    dry_run = data.get('dry_run', True)
    result = service.deploy(data['spec'], dry_run=dry_run)

    return jsonify(result)


@ai_infrastructure_bp.route('/api/recommendations')
@login_required
def api_recommendations():
    """Get AI recommendations"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    category = request.args.get('category')
    recommendations = service.get_recommendations(current_user.id)

    return jsonify({
        'recommendations': [{
            'id': r.get('id'),
            'category': r.get('category'),
            'title': r.get('title'),
            'description': r.get('description'),
            'impact': r.get('impact'),
            'effort': r.get('effort'),
            'potential_savings': r.get('potential_savings'),
            'created_at': None
        } for r in recommendations]
    })


@ai_infrastructure_bp.route('/api/recommendations/<int:rec_id>/apply', methods=['POST'])
@login_required
def api_apply_recommendation(rec_id):
    """Apply a recommendation"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    result = service.apply_recommendation(rec_id)
    return jsonify(result)


@ai_infrastructure_bp.route('/api/recommendations/<int:rec_id>/dismiss', methods=['POST'])
@login_required
def api_dismiss_recommendation(rec_id):
    """Dismiss a recommendation"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    reason = request.json.get('reason') if request.is_json else None
    if service.dismiss_recommendation(rec_id, reason):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to dismiss recommendation'}), 400


@ai_infrastructure_bp.route('/api/templates')
@login_required
def api_templates():
    """Get infrastructure templates"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    category = request.args.get('category')
    provider = request.args.get('provider')
    templates = service.get_user_templates(current_user.id)

    return jsonify({
        'templates': [{
            'id': t.id,
            'name': t.name,
            'description': t.description,
            'category': t.category,
            'provider': t.provider,
            'complexity': t.complexity,
            'estimated_cost': t.estimated_cost
        } for t in templates]
    })


@ai_infrastructure_bp.route('/api/templates/<template_id>/preview', methods=['POST'])
@login_required
def api_template_preview(template_id):
    """Preview template with parameters"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    params = request.get_json() or {}
    preview = service.preview_template(template_id, params)

    return jsonify(preview)


@ai_infrastructure_bp.route('/api/optimize', methods=['POST'])
@login_required
def api_optimize():
    """Get optimization suggestions for current infrastructure"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json() or {}
    optimization_type = data.get('type', 'cost')

    suggestions = service.get_optimization_suggestions(optimization_type)
    return jsonify({'suggestions': suggestions})


@ai_infrastructure_bp.route('/api/explain', methods=['POST'])
@login_required
def api_explain():
    """Explain infrastructure code"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'error': 'Code is required'}), 400

    code_type = data.get('type', 'terraform')
    explanation = service.explain_code(data['code'], code_type)

    return jsonify({'explanation': explanation})


@ai_infrastructure_bp.route('/api/convert', methods=['POST'])
@login_required
def api_convert():
    """Convert between infrastructure formats"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'error': 'Code is required'}), 400

    source_format = data.get('source_format', 'terraform')
    target_format = data.get('target_format', 'cloudformation')

    converted = service.convert_code(data['code'], source_format, target_format)
    return jsonify({
        'converted': converted,
        'source_format': source_format,
        'target_format': target_format
    })


@ai_infrastructure_bp.route('/api/analyze-drift', methods=['POST'])
@login_required
def api_analyze_drift():
    """Analyze infrastructure drift"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json() or {}
    resource_ids = data.get('resource_ids')

    drift_report = service.analyze_drift(resource_ids)
    return jsonify(drift_report)


@ai_infrastructure_bp.route('/api/security-scan', methods=['POST'])
@login_required
def api_security_scan():
    """Scan infrastructure code for security issues"""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)

    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'error': 'Code is required'}), 400

    code_type = data.get('type', 'terraform')
    scan_result = service.security_scan(data['code'], code_type)

    return jsonify(scan_result)
