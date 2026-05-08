"""
Curriculum routes — DevOps Engineer learning roadmap.
"""
import json
import os
import logging
import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, render_template, Response, stream_with_context
from flask_login import login_required, current_user

from extensions import limiter
from models import db, UserCurriculumProgress, UserQuizAttempt, UserPendingQuiz
from curriculum.data import CURRICULUM, CERTIFICATIONS, TOTAL_MODULES
from services.secrets_manager import get_anthropic_api_key

logger = logging.getLogger(__name__)

curriculum_bp = Blueprint('curriculum', __name__, url_prefix='/curriculum')

# Quiz question cache: module_id → (questions_list, expiry_timestamp)
# Shared across users — questions are per-module, not per-user.
_quiz_cache: dict[str, tuple[list, float]] = {}
_QUIZ_CACHE_TTL = 3600  # 1 hour


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

    # Load best quiz scores for all modules in one query (avoids N+1 fetches client-side)
    module_ids = [m["id"] for m in phase["modules"]]
    attempts = (
        UserQuizAttempt.query
        .filter(
            UserQuizAttempt.user_id == current_user.id,
            UserQuizAttempt.module_id.in_(module_ids),
        )
        .all()
    )
    best_scores = {}
    for a in attempts:
        pct = a.pct()
        if a.module_id not in best_scores or pct > best_scores[a.module_id]:
            best_scores[a.module_id] = pct

    return render_template('curriculum/phase.html', phase=phase, progress=progress,
                           best_scores=best_scores)


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
@limiter.limit("15 per minute", key_func=lambda: str(current_user.id))
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
            api_key = get_anthropic_api_key()
            if not api_key:
                yield f"data: {json.dumps({'error': 'AI Coach is not configured (missing API key). Please contact support.'})}\n\n"
                yield "data: [DONE]\n\n"
                return

            client = anthropic.Anthropic(api_key=api_key)

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
            logger.error(f"AI guide error: {e}", exc_info=True)
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


# ─── Quiz Routes ─────────────────────────────────────────────────────────────

def _save_pending_quiz(user_id, module_id, questions):
    """Upsert quiz questions for a user+module into the DB (TTL: 24 h)."""
    record = UserPendingQuiz.query.filter_by(
        user_id=user_id, module_id=module_id
    ).first()
    expires = datetime.utcnow() + timedelta(hours=24)
    if record:
        record.questions = questions
        record.expires_at = expires
    else:
        record = UserPendingQuiz(
            user_id=user_id,
            module_id=module_id,
            questions=questions,
            expires_at=expires,
        )
        db.session.add(record)
    db.session.commit()


def _get_module_ctx(module_id):
    for phase in CURRICULUM:
        for module in phase["modules"]:
            if module["id"] == module_id:
                return {"phase": phase, "module": module}
    return None


@curriculum_bp.route('/api/quiz/generate', methods=['POST'])
@login_required
@limiter.limit("10 per minute", key_func=lambda: str(current_user.id))
def api_quiz_generate():
    """Ask Claude to generate 5 multiple-choice questions for a module."""
    data = request.get_json() or {}
    module_id = data.get('module_id', '').strip()

    ctx = _get_module_ctx(module_id)
    if not ctx:
        return jsonify({'error': 'Module not found'}), 404

    module = ctx['module']
    phase = ctx['phase']

    # Serve from cache if still fresh
    cached = _quiz_cache.get(module_id)
    if cached:
        questions, expiry = cached
        if time.time() < expiry:
            _save_pending_quiz(current_user.id, module_id, questions)
            return jsonify({'success': True, 'questions': questions, 'module_id': module_id})

    api_key = get_anthropic_api_key()
    if not api_key:
        return jsonify({'error': 'Quiz generation is not configured (missing API key). Please contact support.'}), 503

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Generate exactly 5 multiple-choice quiz questions for a DevOps student studying:

Module: {module['title']} (Phase {phase['phase']}: {phase['title']})
Topics covered: {json.dumps(module['topics'])}

Return ONLY valid JSON — no markdown, no explanation, just the JSON array.

Format:
[
  {{
    "question": "Question text here?",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "correct": 0,
    "explanation": "Brief explanation of why the correct answer is right."
  }}
]

Rules:
- correct is the index (0-3) of the right answer in options
- Questions must be practical and relevant to real DevOps work
- Vary difficulty: 2 easy, 2 medium, 1 hard
- No trick questions — test genuine understanding"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        questions = json.loads(raw.strip())

        # Cache for 1 hour (shared across users — questions are per-module)
        _quiz_cache[module_id] = (questions, time.time() + _QUIZ_CACHE_TTL)

        # Store questions in DB so submit can't be faked by the client
        # (avoids the ~4 KB Flask cookie session limit that caused silent failures)
        _save_pending_quiz(current_user.id, module_id, questions)

        return jsonify({'success': True, 'questions': questions, 'module_id': module_id})

    except json.JSONDecodeError as e:
        logger.error(f"Quiz JSON parse error: {e}")
        return jsonify({'error': 'Failed to parse quiz questions. Please try again.'}), 500
    except Exception as e:
        logger.error(f"Quiz generation error: {e}")
        return jsonify({'error': str(e)}), 500


@curriculum_bp.route('/api/quiz/submit', methods=['POST'])
@login_required
def api_quiz_submit():
    """Score a completed quiz and save the attempt."""
    data = request.get_json() or {}
    module_id = data.get('module_id', '').strip()
    user_answers = data.get('answers', [])

    if not module_id or not user_answers:
        return jsonify({'error': 'module_id and answers are required'}), 400

    # Use server-side questions (stored in DB) to prevent score manipulation
    pending = UserPendingQuiz.query.filter_by(
        user_id=current_user.id, module_id=module_id
    ).first()
    if not pending or pending.is_expired():
        if pending:
            db.session.delete(pending)
            db.session.commit()
        return jsonify({'error': 'No active quiz session for this module. Please generate a quiz first.'}), 400
    questions = pending.questions

    if len(user_answers) != len(questions):
        return jsonify({'error': 'Answer count does not match question count'}), 400

    # Score it
    results = []
    score = 0
    for i, q in enumerate(questions):
        chosen = user_answers[i]
        correct = q.get('correct', -1)
        is_correct = (chosen == correct)
        if is_correct:
            score += 1
        results.append({
            'question': q['question'],
            'options': q['options'],
            'correct': correct,
            'chosen': chosen,
            'is_correct': is_correct,
            'explanation': q.get('explanation', ''),
        })

    # Save attempt (using server-side questions, not client-supplied)
    attempt = UserQuizAttempt(
        user_id=current_user.id,
        module_id=module_id,
        score=score,
        total=len(questions),
        questions=questions,
        user_answers=user_answers,
    )
    db.session.add(attempt)
    # Delete the pending quiz so the same quiz can't be submitted twice
    db.session.delete(pending)
    db.session.commit()

    pct = round((score / len(questions)) * 100)
    passed = pct >= 70

    # Auto-mark module complete on quiz pass
    if passed:
        progress = UserCurriculumProgress.query.filter_by(
            user_id=current_user.id, module_id=module_id
        ).first()
        if progress is None:
            ctx = _get_module_ctx(module_id)
            phase_id = ctx["phase"]["phase"] if ctx else "01"
            progress = UserCurriculumProgress(
                user_id=current_user.id,
                module_id=module_id,
                phase_id=phase_id,
            )
            db.session.add(progress)
        progress.completed = True
        progress.completed_at = datetime.utcnow()
        db.session.commit()

    return jsonify({
        'success': True,
        'score': score,
        'total': len(questions),
        'pct': pct,
        'passed': passed,
        'results': results,
        'attempt_id': attempt.id,
    })


@curriculum_bp.route('/api/quiz/history/<module_id>')
@login_required
def api_quiz_history(module_id):
    """Get past quiz attempts for a module."""
    attempts = (
        UserQuizAttempt.query
        .filter_by(user_id=current_user.id, module_id=module_id)
        .order_by(UserQuizAttempt.created_at.desc())
        .limit(10)
        .all()
    )
    best = max((a.pct() for a in attempts), default=None)
    return jsonify({
        'attempts': [a.to_dict() for a in attempts],
        'best_pct': best,
        'attempt_count': len(attempts),
    })
