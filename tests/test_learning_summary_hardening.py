"""The learning-session summary is model output built from the chat transcript, which includes
cloud tool results anyone can write to (tags, names, descriptions). It must not inject proficiency
domains, lower scores, or reach Settings > Learning as HTML."""
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import g

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = 'Summary-Pass-123!'


def _signed_in(app, db):
    from models import User
    tag = uuid.uuid4().hex[:8]
    user = User(email=f'lsum-{tag}@example.com', username=f'lsum_{tag}', email_verified=True,
                onboarding_completed=True)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    c = app.test_client()
    g.pop('_login_user', None)
    assert c.post('/login', data={'email': user.email, 'password': PASSWORD}).status_code == 302
    g.pop('_login_user', None)
    return c, user


def test_summary_keeps_only_known_domains_and_bounded_gains(app, db_session):
    from models import db, ChatMessage, Conversation, UserPreferences
    c, user = _signed_in(app, db)
    conv = Conversation(id=uuid.uuid4().hex, user_id=user.id, title='t')
    db.session.add(conv)
    db.session.flush()
    for role in ('user', 'assistant'):
        db.session.add(ChatMessage(user_id=user.id, conversation_id=conv.id, role=role, content='x'))
    db.session.add(UserPreferences(user_id=user.id, learning_level={'aws': 50}))
    db.session.commit()

    model_out = json.dumps({
        'summary': 's', 'topics_covered': [], 'tools_used': [], 'key_lessons': [],
        'study_recommendations': [],
        'proficiency_deltas': {'aws': 500, 'docker': -40, '<img src=x onerror=alert(1)>': 5,
                               'security': 'lots', 'kubernetes': 3},
    })
    fake = SimpleNamespace(content=[SimpleNamespace(text=model_out)])
    with patch('anthropic.Anthropic') as cls:
        cls.return_value.messages.create.return_value = fake
        r = c.post('/api/learning/session-summary', json={'conversation_id': conv.id})
    assert r.status_code == 200, r.get_json()
    levels = UserPreferences.query.filter_by(user_id=user.id).first().learning_level
    assert levels == {'aws': 60, 'docker': 0, 'kubernetes': 3}


def test_settings_learning_panel_escapes_model_text():
    html = (ROOT / 'templates' / 'settings.html').read_text()
    start = html.index("fetch('/api/learning/proficiency')")
    block = html[start:html.index('loadLearningPaths();', start)]
    assert '_escBudget(s.summary' in block
    assert '_escBudget(l.substring' in block
    assert re.search(r"const topics = _escBudget\(", block)
    assert re.search(r"const label = _escBudget\(", block)
