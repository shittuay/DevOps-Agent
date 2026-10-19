"""Confirming or approving a request from the web runs it in the background.

Before this, /api/approvals/<id>/confirm ran the tool inside the HTTP request. A long
call (an EKS create, retries, a ~57s delete read-back) outlived Cloudflare's ~100s
limit, so the browser got an error page while the tool kept running. The row sat at
'approved' the whole time, a second click said "already approved", the chat card
stopped polling on 'approved' and never updated, and the result was saved as raw JSON
with nothing telling the agent to carry on.
"""
import re
from pathlib import Path

import pytest

from tests.test_approval_self_confirm import _login, _request_for, people  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def deferred(monkeypatch):
    """Capture background jobs instead of running them."""
    from services import approval_service
    jobs = []
    monkeypatch.setattr(approval_service, '_start_background', jobs.append)
    return jobs


@pytest.fixture
def executed(monkeypatch):
    calls = []

    def _fake(req):
        calls.append(req.id)
        return {'success': True, 'message': 'Instance i-0selfconfirm is terminating.'}

    from services import approval_service
    monkeypatch.setattr(approval_service, '_execute_tool', _fake)
    return calls


def test_confirm_returns_before_the_tool_runs(app, people, deferred, executed):
    from models import ApprovalRequest
    req = _request_for(people['solo'])
    client = _login(app, people['solo'].email)

    resp = client.post(f'/api/approvals/{req.id}/confirm', json={})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['status'] == 'running'
    assert executed == [], 'the tool must not run inside the request'

    status = client.get(f'/api/approvals/{req.id}/status').get_json()
    assert status['status'] == 'approved' and status['running'] is True

    deferred[0]()
    from models import db
    db.session.expire_all()
    assert executed == [req.id]
    done = client.get(f'/api/approvals/{req.id}/status').get_json()
    assert done['status'] == 'executed' and done['running'] is False
    assert 'is terminating' in done['summary']
    assert ApprovalRequest.query.get(req.id).executed_at is not None


def test_second_click_while_running_does_not_run_it_again(app, people, deferred, executed):
    req = _request_for(people['solo'])
    client = _login(app, people['solo'].email)
    assert client.post(f'/api/approvals/{req.id}/confirm', json={}).status_code == 200
    again = client.post(f'/api/approvals/{req.id}/confirm', json={})
    assert again.status_code == 400
    assert len(deferred) == 1
    deferred[0]()
    assert executed == [req.id]


def test_claim_is_atomic(app, people, deferred, executed):
    """A second run that skips the status check must still be refused by the UPDATE."""
    from services import approval_service
    req = _request_for(people['solo'])
    user = people['solo']
    first = approval_service._run_approved(req, user, None, self_confirmed=True, background=True)
    second = approval_service._run_approved(req, user, None, self_confirmed=True, background=True)
    assert first['success'] is True
    assert second['success'] is False
    assert len(deferred) == 1
    deferred[0]()
    assert executed == [req.id]


def test_org_approver_approve_also_runs_in_background(app, people, deferred, executed):
    req = _request_for(people['member'])  # org owner; the org's platform approver reviews it
    client = _login(app, people['org_approver'].email)
    resp = client.post(f'/api/approvals/{req.id}/approve', json={})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['status'] == 'running'
    assert executed == []
    deferred[0]()
    assert executed == [req.id]


def test_result_saved_to_chat_is_plain_language_first(app, people, executed):
    from models import db, ChatMessage, Conversation
    from services import approval_service
    conv = Conversation(id='conv-bg-run-test', user_id=people['solo'].id, title='t')
    db.session.add(conv)
    db.session.commit()
    req = _request_for(people['solo'])
    req.conversation_id = conv.id
    db.session.commit()

    approval_service.confirm_own(req.id, people['solo'].id)
    msg = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.id.desc()).first()
    first_line = msg.content.splitlines()[0]
    assert 'Terminate ec2 instance finished.' in first_line
    assert '{' not in first_line, 'the first line must be plain language, not JSON'
    ChatMessage.query.filter_by(conversation_id=conv.id).delete()
    db.session.delete(conv)
    db.session.commit()


def test_summaries():
    from services.approval_service import summarize_result, INTERRUPTED_RESULT
    assert summarize_result('create_eks_cluster', {'success': True}) == 'Create eks cluster finished.'
    assert summarize_result('x', {'success': False, 'error': 'AccessDenied'}) == 'X failed: AccessDenied'
    s = summarize_result('x', {'success': True, '_verification': {'status': 'unconfirmed'}})
    assert 'may still be in progress' in s
    assert 'cut off' in summarize_result('x', dict(INTERRUPTED_RESULT))


def test_run_cut_off_by_a_restart_is_reported_not_left_running(app, people):
    from datetime import timedelta
    from models import db, ApprovalRequest
    from services import approval_service
    from src.utils.timeutils import utcnow

    req = _request_for(people['solo'])
    req.status = 'approved'
    req.approver_id = people['solo'].id
    req.decided_at = utcnow() - timedelta(minutes=approval_service.RUN_STALE_MINUTES + 1)
    db.session.commit()

    client = _login(app, people['solo'].email)
    s = client.get(f'/api/approvals/{req.id}/status').get_json()
    assert s['status'] == 'executed'
    assert s['execution_result']['success'] is False
    assert s['execution_result'].get('interrupted') is True
    assert 'check your account' in s['summary']


def test_api_gate_still_runs_synchronously(app, people, executed):
    """The developer API returns the result in the same call; it must not go async."""
    src = (ROOT / 'services' / 'approval_service.py').read_text()
    gate = src[src.index('def gate_api_call'):]
    gate = gate[:gate.index('\ndef ', 1)]
    assert 'confirm_own(req.id, user.id)' in gate
    assert 'background=True' not in gate


def test_chat_card_keeps_polling_while_running_and_continues():
    html = (ROOT / 'templates' / 'index.html').read_text()
    card = html[html.index('function renderApprovalCard'):html.index('function renderNotifications')]
    assert "s.status === 'approved'" in card, 'the card must treat approved as running'
    assert 'Running in your account' in card
    assert 'continueAfterApproval(' in card
    assert 'JSON.stringify(res, null, 2).replace' not in card, 'raw JSON must not be the main result'
    # A lost reply must not just silently re-enable the buttons.
    assert "Couldn't reach the server" in card
    cont = html[html.index('function continueAfterApproval'):]
    cont = cont[:cont.index('\n        }\n') + 10]
    assert 'isProcessing' in cont and "input.value.trim()" in cont, \
        'never interrupt a reply or overwrite what the user is typing'


def test_my_requests_page_follows_the_run():
    js = (ROOT / 'static' / 'js' / 'my_requests.js').read_text()
    assert 'function watchMyRequest' in js
    assert "Done. The result is also in the chat." not in js
