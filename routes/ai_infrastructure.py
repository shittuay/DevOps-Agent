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
    """Infrastructure templates catalog (grid is populated client-side via API)."""
    return render_template('ai_infrastructure/templates.html')


@ai_infrastructure_bp.route('/templates/<int:template_id>')
@login_required
def template_detail(template_id):
    """Template detail — visible if public or owned by the user."""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    template = service.get_template(template_id)

    if not template or not (template.is_public or template.user_id == current_user.id):
        flash('Template not found.', 'error')
        return redirect(url_for('ai_infrastructure.templates'))

    return render_template('ai_infrastructure/template_detail.html',
                           template=service.template_to_dict(template))


@ai_infrastructure_bp.route('/api/templates/<int:template_id>/clone', methods=['POST'])
@login_required
def api_template_clone(template_id):
    """Save a copy of a template into the user's own templates."""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    source = service.get_template(template_id)
    if not source or not (source.is_public or source.user_id == current_user.id):
        return jsonify({'error': 'Template not found'}), 404
    clone = service.clone_template(template_id, current_user.id)
    return jsonify({'success': True, 'template': service.template_to_dict(clone)})


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
    """Turn a plain-English description into a spec and reviewable Terraform.

    Only generates code; nothing is created in the user's account here.
    """
    from services.ai_infrastructure import AIInfrastructureService, SUPPORTED_PROVIDERS
    service = AIInfrastructureService(current_user.id)

    data = request.get_json(silent=True) or {}
    text = (data.get('request') or data.get('query') or '').strip()
    if not text:
        return jsonify({'error': 'Describe the infrastructure you want.'}), 400
    if len(text) > 2000:
        return jsonify({'error': 'Keep the description under 2,000 characters.'}), 400

    provider = (data.get('cloud_provider') or 'aws').lower()
    if provider not in SUPPORTED_PROVIDERS:
        return jsonify({
            'error': 'Only AWS is supported on this page. For Azure or Google Cloud, ask in Chat.',
        }), 422

    intent = service.parse_request(text)
    if not intent.get('actions'):
        return jsonify({
            'error': ("Couldn't tell what to build. Try something like \"create 2 small servers "
                      "and a database named shop in us west\", or ask in Chat."),
            'intent': intent,
        }), 422

    spec = service.generate_spec(intent)
    return jsonify({
        'intent': intent,
        'spec': spec.to_dict(),
        'terraform': spec.to_terraform(),
        'note': ('Review the code and run terraform plan before applying. No cost estimate is '
                 'shown here; ask in Chat for live pricing from your own account.'),
    })

@ai_infrastructure_bp.route('/api/deployments')
@login_required
def api_deployments():
    """List the user's AI-assisted deployments (JSON for the deployments page)."""
    from services.ai_infrastructure import AIInfrastructureService
    service = AIInfrastructureService(current_user.id)
    deployments = service.get_user_deployments(current_user.id)
    return jsonify({'deployments': deployments})


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

    result = service.apply_recommendation(rec_id, current_user.id)
    return jsonify(result), (200 if result.get('success') else 501)


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
    templates = service.get_visible_templates(current_user.id)

    def matches(t):
        return ((not category or t.category == category) and
                (not provider or t.cloud_provider == provider))

    return jsonify({
        'templates': [service.template_to_dict(t) for t in templates if matches(t)]
    })


@ai_infrastructure_bp.route('/api/templates/<int:template_id>/preview', methods=['POST'])
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
