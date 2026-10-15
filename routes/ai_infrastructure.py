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

