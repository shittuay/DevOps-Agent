"""Pre-built workflow templates — browse, execute, track."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import db, WorkflowTemplate, WorkflowExecution, Conversation, ChatMessage
from src.utils.timeutils import utcnow

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
    2. Create WorkflowExecution (status=queued)
    3. Create an empty Conversation for the run
    4. Return conversation_id + the prompt, so the chat page can send it through
       the normal /api/chat/stream path

    The prompt is deliberately NOT persisted as a ChatMessage here. Writing a user
    message row does not run the agent — only /api/chat/stream does — so seeding
    one produced a conversation that showed the prompt and then sat there forever
    with the execution stuck at 'running'. The chat page now sends it as a real
    message, which reuses guardrails, credit accounting, streaming, and the
    execution status PATCH that were already working.
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

    # Create execution record. 'queued' until the chat page actually dispatches the
    # prompt — it only becomes 'running' once the stream starts.
    execution = WorkflowExecution(
        user_id=current_user.id,
        template_id=template.id,
        conversation_id=conv_id,
        status='queued',
        started_at=utcnow(),
    )
    db.session.add(execution)

    # Increment popularity counter
    template.execution_count = (template.execution_count or 0) + 1

    db.session.commit()

    return jsonify({
        'execution_id': execution.id,
        'conversation_id': conv_id,
        'prompt': prompt,
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
    if new_status not in ('running', 'completed', 'failed', 'timed_out'):
        return jsonify({'error': 'Invalid status'}), 400

    execution.status = new_status
    if new_status == 'running':
        execution.started_at = utcnow()
    else:
        execution.completed_at = utcnow()
    db.session.commit()
    return jsonify(execution.to_dict())


# An execution older than this with no assistant reply is not running any more —
# the tab was closed, the stream died, or the dispatch never happened.
STALE_EXECUTION_MINUTES = 30


def _reconcile_stale_executions(executions):
    """Correct executions left mid-flight by a browser that never reported back.

    'completed'/'failed' are only ever written by the SSE done handler in the
    page, so closing the tab stranded a row at 'running' forever — the dashboard
    then showed "Running" for something that had long since stopped. Derive the
    real outcome from the conversation instead: an assistant reply means it ran
    to completion; nothing after the cutoff means it timed out.
    """
    cutoff = utcnow() - timedelta(minutes=STALE_EXECUTION_MINUTES)
    changed = False

    for ex in executions:
        if ex.status not in ('queued', 'running'):
            continue
        if (ex.started_at or ex.created_at) > cutoff:
            continue  # still plausibly in flight

        last_reply = None
        if ex.conversation_id:
            last_reply = (
                ChatMessage.query
                .filter_by(conversation_id=ex.conversation_id, role='assistant')
                .order_by(ChatMessage.timestamp.desc())
                .first()
            )

        if last_reply:
            ex.status = 'completed'
            ex.completed_at = ex.completed_at or last_reply.timestamp
        else:
            ex.status = 'timed_out'
            ex.completed_at = ex.completed_at or utcnow()
        changed = True

    if changed:
        db.session.commit()


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
    _reconcile_stale_executions(executions)
    result = []
    for ex in executions:
        d = ex.to_dict()
        if ex.template:
            d['template_name'] = ex.template.name
            d['template_category'] = ex.template.category
        result.append(d)
    return jsonify({'executions': result})
