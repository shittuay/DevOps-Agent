"""
Curriculum routes — DevOps Engineer learning roadmap.
"""
import json
import os
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, render_template, Response, stream_with_context
from flask_login import login_required, current_user

from models import db, UserCurriculumProgress
from curriculum.data import CURRICULUM, CERTIFICATIONS, TOTAL_MODULES

logger = logging.getLogger(__name__)

curriculum_bp = Blueprint('curriculum', __name__, url_prefix='/curriculum')


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_user_progress(user_id):
    """Return {module_id: {...}} dict for a user."""
    records = UserCurriculumProgress.query.filter_by(user_id=user_id).all()
    return {r.module_id: r.to_dict() for r in records}


def _progress_summary(user_id):
    records = UserCurriculumProgress.query.filter_by(user_id=user_id, completed=True).all()
    completed_ids = {r.module_id for r in records}
    projects_done = sum(1 for r in records if r.project_done)
    pct = round((len(completed_ids) / TOTAL_MODULES) * 100, 1) if TOTAL_MODULES else 0

    phase_progress = {}
    for phase in CURRICULUM:
        phase_mods = [m["id"] for m in phase["modules"]]
        done = len([m for m in phase_mods if m in completed_ids])
        phase_progress[phase["phase"]] = {
            "title": phase["title"],
            "color": phase["color"],
            "completed": done,
            "total": len(phase_mods),
            "pct": round((done / len(phase_mods)) * 100) if phase_mods else 0,
        }

    return {
        "total": TOTAL_MODULES,
        "completed": len(completed_ids),
        "projects_done": projects_done,
        "overall_pct": pct,
        "phases": phase_progress,
    }


# ─── Page Routes ─────────────────────────────────────────────────────────────

@curriculum_bp.route('/')
@login_required
def index():
    progress = _get_user_progress(current_user.id)
    summary = _progress_summary(current_user.id)
    return render_template(
        'curriculum/index.html',
        curriculum=CURRICULUM,
        certifications=CERTIFICATIONS,
        progress=progress,
        summary=summary,
    )


@curriculum_bp.route('/phase/<phase_id>')
@login_required
def phase_detail(phase_id):
    phase = next((p for p in CURRICULUM if p["phase"] == phase_id), None)
    if not phase:
        return render_template('404.html'), 404
    progress = _get_user_progress(current_user.id)
    return render_template('curriculum/phase.html', phase=phase, progress=progress)


# ─── API Routes ──────────────────────────────────────────────────────────────

@curriculum_bp.route('/api/phases')
@login_required
def api_list():
    progress = _get_user_progress(current_user.id)
    summary = _progress_summary(current_user.id)
    return jsonify({
        "phases": CURRICULUM,
        "certifications": CERTIFICATIONS,
        "progress": progress,
        "summary": summary,
    })


@curriculum_bp.route('/api/progress', methods=['POST'])
@login_required
def api_update_progress():
    data = request.get_json() or {}
    module_id = data.get('module_id', '').strip()
    phase_id = data.get('phase_id', '').strip()

    if not module_id or not phase_id:
        return jsonify({'error': 'module_id and phase_id are required'}), 400

    record = UserCurriculumProgress.query.filter_by(
        user_id=current_user.id, module_id=module_id
    ).first()

    if not record:
        record = UserCurriculumProgress(
            user_id=current_user.id,
            module_id=module_id,
            phase_id=phase_id,
        )
        db.session.add(record)

    record.completed = bool(data.get('completed', False))
    record.project_done = bool(data.get('project_done', False))
    if data.get('notes') is not None:
        record.notes = data['notes']
    if record.completed and not record.completed_at:
        record.completed_at = datetime.utcnow()
    elif not record.completed:
        record.completed_at = None

    db.session.commit()
    return jsonify({'success': True, 'progress': record.to_dict()})


@curriculum_bp.route('/api/progress/summary')
@login_required
def api_progress_summary():
    return jsonify(_progress_summary(current_user.id))


@curriculum_bp.route('/api/ai-guide', methods=['POST'])
@login_required
def api_ai_guide():
    """Stream Claude's study guidance for a specific module."""
    data = request.get_json() or {}
    module_id = data.get('module_id', '').strip()
    question = data.get('question', '').strip()

    if not module_id or not question:
        return jsonify({'error': 'module_id and question are required'}), 400

    # Find module context
    module_ctx = None
    for phase in CURRICULUM:
        for module in phase["modules"]:
            if module["id"] == module_id:
                module_ctx = {"phase": phase, "module": module}
                break
        if module_ctx:
            break

    if not module_ctx:
        return jsonify({'error': 'Module not found'}), 404

    phase = module_ctx["phase"]
    module = module_ctx["module"]

    def generate():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY', ''))

            system_prompt = (
                f"You are a DevOps learning coach on devopsagent.io. "
                f"You are helping a user study the '{module['title']}' module "
                f"in Phase {phase['phase']}: {phase['title']}.\n\n"
                f"Module topics: {json.dumps(module['topics'])}\n"
                f"Capstone project: {module['project']}\n\n"
                f"Respond in Learning Mode: explain concepts clearly, use real-world DevOps "
                f"examples, provide commands/configs where helpful, and guide toward the "
                f"capstone project. Be concise but thorough. Format with markdown."
            )

            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": question}],
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"AI guide error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )
