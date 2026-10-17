"""A risky action waiting for approval can always be found and confirmed (2026-10-17).

Seen live on a Kimi account creating an EKS cluster: the agent said "approve request 2 with
the buttons in chat", but there were no buttons (the non-streaming /api/chat path never sent
the card), the bell notification couldn't be clicked (a quoted link broke its onclick), the
admin's Approvals page was empty (it only lists other people's requests), typing "approve"
filed duplicate requests, and the agent then claimed requests had been approved.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _make_user(email, role='user'):
    from models import User, db
    user = User(email=email, username=email.split('@')[0].replace('-', '_'), full_name=email,
                role=role, email_verified=True)
    user.set_password('TestPassword123!')
    db.session.add(user)
    db.session.commit()
    return user


def _login(app, email):
    from flask import g
    g.pop('_login_user', None)
    c = app.test_client()
    resp = c.post('/login', data={'email': email, 'password': 'TestPassword123!'})
    assert resp.status_code == 302, resp.status_code
    return c


@pytest.fixture
def users(app, db_session):
    from models import ApprovalRequest, AppNotification, User, db
    solo = _make_user('chatvis-solo@example.com')
    admin = _make_user('chatvis-admin@example.com', role='admin')
    yield {'solo': solo, 'admin': admin}
    db.session.rollback()
    ids = [solo.id, admin.id]
    ApprovalRequest.query.filter(ApprovalRequest.requester_id.in_(ids)).delete(synchronize_session=False)
    AppNotification.query.filter(AppNotification.user_id.in_(ids)).delete(synchronize_session=False)
    for uid in ids:
        u = User.query.get(uid)
        if u:
            db.session.delete(u)
    db.session.commit()


def _file(user, tool='create_iam_role', tool_input=None, risk='high'):
    from services.approval_service import create_request
    return create_request(tool_name=tool, tool_input=tool_input or {'role_name': 'eksClusterRole'},
                          risk_level=risk, risk_reason='Creates an IAM role', requester_id=user.id)


def test_identical_pending_request_is_reused_not_duplicated(users):
    first = _file(users['solo'])
    again = _file(users['solo'], tool_input={'role_name': 'eksClusterRole'})
    other = _file(users['solo'], tool_input={'role_name': 'eksNodeRole'})
    assert again.id == first.id
    assert other.id != first.id


def test_cancelled_request_is_not_reused(users):
    from models import db
    first = _file(users['solo'])
    first.status = 'rejected'
    db.session.commit()
    assert _file(users['solo']).id != first.id


def test_admins_own_request_counts_and_shows_on_approvals(app, users):
    _file(users['admin'])
    client = _login(app, users['admin'].email)
    data = client.get('/api/approvals/count').get_json()
    assert data['own'] == 1 and data['count'] >= 1
    page = client.get('/approvals').get_data(as_text=True)
    assert 'Waiting for your confirmation' in page and 'js/my_requests.js' in page


def test_regular_user_gets_a_count_not_a_403(app, users):
    _file(users['solo'])
    client = _login(app, users['solo'].email)
    resp = client.get('/api/approvals/count')
    assert resp.status_code == 200
    assert resp.get_json() == {'count': 1, 'reviewing': 0, 'own': 1}


def test_approvals_link_is_shown_to_every_signed_in_user():
    base = (ROOT / 'templates/base.html').read_text()
    index = (ROOT / 'templates/index.html').read_text()
    assert 'id="approvalsNavBtn"' in base
    assert "role in ('approver', 'admin')" not in base
    assert "role in ('approver', 'admin')" not in index


def test_notifications_are_clickable():
    index = (ROOT / 'templates/index.html').read_text()
    assert 'onclick="handleNotifClick(' not in index
    assert 'data-notif-link=' in index
    assert "closest('.notif-item[data-notif-id]')" in index


def test_non_streaming_chat_returns_approval_cards():
    core = (ROOT / 'src/agent/core.py').read_text()
    app_src = (ROOT / 'app.py').read_text()
    index = (ROOT / 'templates/index.html').read_text()
    assert 'self._filed_approvals.append(' in core
    assert "response_data['approvals'] = _agent_result['approvals']" in app_src
    assert '(data.approvals || []).forEach(a => renderApprovalCard(textDiv, a));' in index
    assert index.count('function renderApprovalCard(') == 1


def test_my_requests_script_parses_and_uses_no_inline_handlers():
    import shutil
    import subprocess
    js = (ROOT / 'static/js/my_requests.js').read_text()
    assert 'onclick=' not in js
    if shutil.which('node'):
        subprocess.run(['node', '--check', str(ROOT / 'static/js/my_requests.js')], check=True)


def test_prompt_lists_real_request_statuses(app, users):
    from models import db
    from src.agent.core import DevOpsAgent
    req = _file(users['solo'])
    req.status = 'executed'
    db.session.commit()
    agent = DevOpsAgent.__new__(DevOpsAgent)
    import logging
    import threading
    agent._local = threading.local()
    agent.logger = logging.getLogger('test')
    agent._current_user_id = users['solo'].id
    text = agent._approval_status_context()
    assert f'#{req.id} create_iam_role: executed' in text
    assert "typing 'approve' does nothing" in text
    agent._current_user_id = users['admin'].id
    assert agent._approval_status_context() == ''
