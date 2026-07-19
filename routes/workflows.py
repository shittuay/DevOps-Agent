"""Pre-built workflow templates — browse, execute, track."""
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import db, WorkflowTemplate, WorkflowExecution, Conversation, ChatMessage

workflows_bp = Blueprint('workflows', __name__)


@workflows_bp.route('/api/workflows', methods=['GET'])
@login_required
def list_workflows():
    """Return all public templates plus any private ones the user created."""
    category = request.args.get('category')
    query = WorkflowTemplate.query.filter(
        (WorkflowTemplate.is_public == True) |
        (WorkflowTemplate.created_by == current_user.id)
    )
    if category:
        query = query.filter_by(category=category)
    templates = query.order_by(WorkflowTemplate.execution_count.desc()).all()
    return jsonify({'workflows': [t.to_dict() for t in templates]})


@workflows_bp.route('/api/workflows/<int:template_id>', methods=['GET'])
@login_required
def get_workflow(template_id: int):
    template = WorkflowTemplate.query.filter(
        (WorkflowTemplate.id == template_id) &
        ((WorkflowTemplate.is_public == True) | (WorkflowTemplate.created_by == current_user.id))
    ).first_or_404()
    return jsonify(template.to_dict())


@workflows_bp.route('/api/workflows/<int:template_id>/execute', methods=['POST'])
@login_required
def execute_workflow(template_id: int):
    """
    Chat-dispatch execution:
    1. Validate template access
    2. Create WorkflowExecution (status=running)
    3. Create a new Conversation with the workflow steps as the first user message
    4. Return conversation_id so the frontend redirects to /chat?cid=X
    """
    template = WorkflowTemplate.query.filter(
        (WorkflowTemplate.id == template_id) &
        ((WorkflowTemplate.is_public == True) | (WorkflowTemplate.created_by == current_user.id))
    ).first_or_404()

    # Build the prompt from workflow steps
    steps_text = '\n'.join(f'{i+1}. {step}' for i, step in enumerate(template.steps))
    prompt = (
        f"Execute the following workflow: **{template.name}**\n\n"
        f"{template.description}\n\n"
        f"Steps to complete:\n{steps_text}\n\n"
        "Please execute each step in order, reporting the result of each step before proceeding to the next."
    )

    # Create conversation (ID format matches app.py: secrets.token_hex(8))
    conv_id = secrets.token_hex(8)
    conv = Conversation(
        id=conv_id,
        user_id=current_user.id,
        title=f"Workflow: {template.name}",
    )
    db.session.add(conv)

    # Seed with user message so chat stream picks it up
    msg = ChatMessage(
        conversation_id=conv_id,
        user_id=current_user.id,   # NOT NULL — omitting it 500'd every execute
        role='user',
        content=prompt,
    )
    db.session.add(msg)

    # Create execution record
    execution = WorkflowExecution(
        user_id=current_user.id,
        template_id=template.id,
        conversation_id=conv_id,
        status='running',
        started_at=datetime.utcnow(),
    )
    db.session.add(execution)

    # Increment popularity counter
    template.execution_count = (template.execution_count or 0) + 1

    db.session.commit()

    return jsonify({
        'execution_id': execution.id,
        'conversation_id': conv_id,
        'redirect_url': f'/chat?cid={conv_id}&wf_exec={execution.id}',
    })


@workflows_bp.route('/api/workflows/executions/<int:execution_id>', methods=['PATCH'])
@login_required
def update_execution(execution_id: int):
    """Frontend calls this when the SSE 'done' event fires to update execution status."""
    execution = WorkflowExecution.query.filter_by(
        id=execution_id, user_id=current_user.id
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in ('completed', 'failed', 'timed_out'):
        return jsonify({'error': 'Invalid status'}), 400

    execution.status = new_status
    execution.completed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(execution.to_dict())


@workflows_bp.route('/api/workflows/executions', methods=['GET'])
@login_required
def list_executions():
    """Return the current user's recent workflow executions."""
    executions = (
        WorkflowExecution.query
        .filter_by(user_id=current_user.id)
        .order_by(WorkflowExecution.created_at.desc())
        .limit(50)
        .all()
    )
    result = []
    for ex in executions:
        d = ex.to_dict()
        if ex.template:
            d['template_name'] = ex.template.name
            d['template_category'] = ex.template.category
        result.append(d)
    return jsonify({'executions': result})
