"""
Skills Engine — loads built-in skill files and generates learned skills context
from the user's actual deployed infrastructure.
"""

import os
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
_MAX_SKILLS_TOKENS = 1500  # approximate character cap for injected context


class SkillsEngine:
    """Load skill files from disk and generate per-user skills context."""

    _builtin_skills: Dict[str, dict] = {}
    _skills_loaded: bool = False

    def __init__(self, app=None):
        self._app = app

    @classmethod
    def load_skills_from_disk(cls, skills_dir: str):
        """Parse frontmatter + body from each *.md file in skills_dir; cache by id."""
        cls._builtin_skills = {}
        if not os.path.isdir(skills_dir):
            logger.warning(f"Skills directory not found: {skills_dir}")
            return
        for fname in os.listdir(skills_dir):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(skills_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    raw = f.read()
                m = _FRONTMATTER_RE.match(raw)
                if not m:
                    continue
                fm_text = m.group(1)
                body = raw[m.end():]
                fm = {}
                for line in fm_text.splitlines():
                    if ':' in line:
                        k, _, v = line.partition(':')
                        v = v.strip().strip('"\'')
                        # Parse list values like [pod, deployment, ...]
                        if v.startswith('[') and v.endswith(']'):
                            v = [x.strip().strip('"\'') for x in v[1:-1].split(',')]
                        fm[k.strip()] = v
                skill_id = fm.get('id') or fname.replace('.md', '')
                cls._builtin_skills[skill_id] = {
                    'id': skill_id,
                    'name': fm.get('name', skill_id),
                    'triggers': fm.get('triggers', []),
                    'compatible_providers': fm.get('compatible_providers', []),
                    'body': body.strip(),
                }
                logger.info(f"Loaded skill: {skill_id}")
            except Exception as e:
                logger.error(f"Failed to load skill {fname}: {e}")
        cls._skills_loaded = True
        logger.info(f"Skills loaded: {len(cls._builtin_skills)} skills from {skills_dir}")

    def get_active_skills_for_user(self, user_id: int) -> List[str]:
        """Return list of skill_ids that are active for this user (not deactivated)."""
        if not self._app:
            return list(self._builtin_skills.keys())
        with self._app.app_context():
            from models import UserSkillActivation
            deactivated = {
                row.skill_id
                for row in UserSkillActivation.query.filter_by(
                    user_id=user_id, is_active=False
                ).all()
            }
            return [sid for sid in self._builtin_skills if sid not in deactivated]

    def get_active_skills_context(self, user_id: int, message: str) -> str:
        """
        Build skills context string to inject into the system prompt.
        1. Match built-in skills whose trigger keywords appear in message
        2. Append learned skills context
        Cap total at ~_MAX_SKILLS_TOKENS characters.
        """
        parts = []
        active_skill_ids = self.get_active_skills_for_user(user_id)
        msg_lower = message.lower()

        for skill_id in active_skill_ids:
            skill = self._builtin_skills.get(skill_id, {})
            triggers = skill.get('triggers', [])
            if not triggers:
                continue
            if any(t.lower() in msg_lower for t in triggers):
                parts.append(f"### Skill: {skill.get('name', skill_id)}\n{skill.get('body', '')}")

        learned = self.generate_learned_skills_context(user_id)
        if learned:
            parts.append(learned)

        if not parts:
            return ''

        combined = '\n\n'.join(parts)
        if len(combined) > _MAX_SKILLS_TOKENS:
            combined = combined[:_MAX_SKILLS_TOKENS] + '\n...(truncated)'
        return f"\n\n=== SKILLS CONTEXT ===\n{combined}\n=== END SKILLS CONTEXT ==="

    def generate_learned_skills_context(self, user_id: int) -> str:
        """
        Query InfrastructureResource GROUP BY resource_type, COUNT(*).
        Returns a concise plain-text summary of what the user has deployed.
        Pure SQL + string formatting — no AI call.
        """
        if not self._app:
            return ''
        try:
            with self._app.app_context():
                from models import db, InfrastructureResource
                from sqlalchemy import func
                rows = db.session.query(
                    InfrastructureResource.resource_type,
                    InfrastructureResource.cloud_provider,
                    func.count(InfrastructureResource.id).label('cnt')
                ).filter_by(user_id=user_id).group_by(
                    InfrastructureResource.resource_type,
                    InfrastructureResource.cloud_provider
                ).all()

                if not rows:
                    return ''

                lines = ['**Your deployed infrastructure:**']
                for row in rows:
                    provider = (row.cloud_provider or 'unknown').upper()
                    rtype = (row.resource_type or 'resource').replace('_', ' ')
                    lines.append(f'- {row.cnt} {provider} {rtype}(s)')
                lines.append('You can manage lifecycle, view metrics, and optimize any of these resources.')
                return '\n'.join(lines)
        except Exception as e:
            logger.error(f"generate_learned_skills_context error: {e}")
            return ''

    def list_skills_with_status(self, user_id: int) -> List[Dict]:
        """Return all skills with their activation status for this user."""
        if not self._app:
            return []
        with self._app.app_context():
            from models import UserSkillActivation
            activation_map = {
                row.skill_id: row.is_active
                for row in UserSkillActivation.query.filter_by(user_id=user_id).all()
            }
            result = []
            for skill_id, skill in self._builtin_skills.items():
                result.append({
                    'id': skill_id,
                    'name': skill.get('name', skill_id),
                    'triggers': skill.get('triggers', []),
                    'compatible_providers': skill.get('compatible_providers', []),
                    'is_active': activation_map.get(skill_id, True),
                })
            return result


_engine_instance: Optional[SkillsEngine] = None


def get_skills_engine(app=None) -> SkillsEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SkillsEngine(app=app)
    elif app and not _engine_instance._app:
        _engine_instance._app = app
    return _engine_instance
