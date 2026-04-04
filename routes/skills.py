"""
Skills API routes — list, activate, and deactivate agent skills.
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import logging

logger = logging.getLogger(__name__)

skills_bp = Blueprint('skills', __name__, url_prefix='/api/skills')


@skills_bp.route('', methods=['GET'])
@login_required
def list_skills():
    """List all skills with activation status for the current user."""
    from services.skills_engine import get_skills_engine
    engine = get_skills_engine()
    skills = engine.list_skills_with_status(current_user.id)
    return jsonify({'skills': skills, 'total': len(skills)})


@skills_bp.route('/<skill_id>/activate', methods=['POST'])
@login_required
def activate_skill(skill_id):
    """Enable a skill for the current user."""
    from models import db, UserSkillActivation
    row = UserSkillActivation.query.filter_by(user_id=current_user.id, skill_id=skill_id).first()
    if row:
        row.is_active = True
    else:
        row = UserSkillActivation(
            user_id=current_user.id,
            skill_id=skill_id,
            is_active=True,
            activation_source='manual',
        )
        db.session.add(row)
    db.session.commit()
    return jsonify({'success': True, 'skill_id': skill_id, 'is_active': True})


@skills_bp.route('/<skill_id>/activate', methods=['DELETE'])
@login_required
def deactivate_skill(skill_id):
    """Disable a skill for the current user."""
    from models import db, UserSkillActivation
    row = UserSkillActivation.query.filter_by(user_id=current_user.id, skill_id=skill_id).first()
    if row:
        row.is_active = False
    else:
        row = UserSkillActivation(
            user_id=current_user.id,
            skill_id=skill_id,
            is_active=False,
            activation_source='manual',
        )
        db.session.add(row)
    db.session.commit()
    return jsonify({'success': True, 'skill_id': skill_id, 'is_active': False})


@skills_bp.route('/learned', methods=['GET'])
@login_required
def get_learned_skills():
    """Return the learned skills text derived from the user's infrastructure."""
    from services.skills_engine import get_skills_engine
    engine = get_skills_engine()
    learned = engine.generate_learned_skills_context(current_user.id)
    return jsonify({'context': learned})


@skills_bp.route('/refresh-learned', methods=['POST'])
@login_required
def refresh_learned_skills():
    """Regenerate learned skills from latest infrastructure sync."""
    from services.skills_engine import get_skills_engine
    engine = get_skills_engine()
    learned = engine.generate_learned_skills_context(current_user.id)
    return jsonify({'success': True, 'context': learned})
