"""Regression: deleting a conversation must not leave orphaned rows behind.

`delete_conversation()` (app.py) and its api/v1 counterpart only deleted
ChatMessage rows before deleting the Conversation itself. Five other models
(UsageLog, LearningSession, WorkflowExecution, ChatArtifact, ApprovalRequest)
FK to conversations.id but were never cleaned up. On Postgres (production),
the FK constraint rejects the Conversation delete outright -- the route
catches the IntegrityError and returns a 500, which the frontend swallows
silently (only console.error, no user-visible message), so from the user's
side the "Delete" button just does nothing.

A follow-up fix to the fix: the first version of the cascade deleted
ChatMessage rows BEFORE ChatArtifact rows, even though ChatArtifact.message_id
also FKs to chat_messages.id (no cascade). Any artifact saved against a real
message (the normal case -- see routes/artifacts.py) reproduced the exact
same IntegrityError one FK hop further out. `test_delete_conversation...`
below sets `message_id` on the fixture artifact and runs with SQLite FK
enforcement turned on (off by default -- see conftest.py) specifically so
this ordering regression fails loudly here instead of only in production.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models import (db, Conversation, ChatMessage, UsageLog, LearningSession,
                     WorkflowExecution, WorkflowTemplate, ChatArtifact,
                     ApprovalRequest)


@pytest.fixture
def sqlite_fk_enforced(app):
    """Turn on real FK enforcement for the shared test connection (SQLite
    defaults to none), so a bad delete order raises IntegrityError here the
    same way it would on production Postgres. Restored after the test so it
    can't change behavior for any other test sharing the StaticPool connection.
    """
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    db.session.commit()
    try:
        yield
    finally:
        db.session.execute(text('PRAGMA foreign_keys=OFF'))
        db.session.commit()


def _make_conversation_with_dependents(user_id):
    conv = Conversation(id='conv-delete-test', user_id=user_id, title='Test')
    db.session.add(conv)
    db.session.flush()

    message = ChatMessage(conversation_id=conv.id, user_id=user_id,
                           role='user', content='hi')
    db.session.add(message)
    db.session.flush()

    db.session.add(UsageLog(user_id=user_id, action_type='message',
                             conversation_id=conv.id))
    db.session.add(LearningSession(user_id=user_id, conversation_id=conv.id))
    # message_id set deliberately: this is what makes the artifact FK to
    # chat_messages.id, not just conversations.id.
    db.session.add(ChatArtifact(user_id=user_id, conversation_id=conv.id,
                                 message_id=message.id,
                                 artifact_type='runbook', title='t', content='c'))
    db.session.add(ApprovalRequest(requester_id=user_id, conversation_id=conv.id,
                                    tool_name='delete_pod', risk_level='high',
                                    risk_reason='test', status='pending',
                                    expires_at=datetime.utcnow() + timedelta(hours=1)))
    template = WorkflowTemplate(name='t', description='d', category='c')
    db.session.add(template)
    db.session.flush()
    db.session.add(WorkflowExecution(user_id=user_id, template_id=template.id,
                                      conversation_id=conv.id))
    db.session.commit()
    return conv


def test_delete_conversation_removes_all_dependent_rows(
        authenticated_client, test_user, sqlite_fk_enforced):
    conv = _make_conversation_with_dependents(test_user.id)

    resp = authenticated_client.delete(f'/api/conversations/{conv.id}')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    assert Conversation.query.get(conv.id) is None
    assert ChatMessage.query.filter_by(conversation_id=conv.id).count() == 0
    assert UsageLog.query.filter_by(conversation_id=conv.id).count() == 0
    assert LearningSession.query.filter_by(conversation_id=conv.id).count() == 0
    assert WorkflowExecution.query.filter_by(conversation_id=conv.id).count() == 0
    assert ChatArtifact.query.filter_by(conversation_id=conv.id).count() == 0
    assert ApprovalRequest.query.filter_by(conversation_id=conv.id).count() == 0


def test_api_v1_delete_conversation_removes_all_dependent_rows(
        client, test_user, api_headers, sqlite_fk_enforced):
    conv = _make_conversation_with_dependents(test_user.id)

    resp = client.delete(f'/api/v1/conversations/{conv.id}', headers=api_headers)
    assert resp.status_code == 200

    assert Conversation.query.get(conv.id) is None
    assert ChatMessage.query.filter_by(conversation_id=conv.id).count() == 0
    assert UsageLog.query.filter_by(conversation_id=conv.id).count() == 0
    assert LearningSession.query.filter_by(conversation_id=conv.id).count() == 0
    assert WorkflowExecution.query.filter_by(conversation_id=conv.id).count() == 0
    assert ChatArtifact.query.filter_by(conversation_id=conv.id).count() == 0
    assert ApprovalRequest.query.filter_by(conversation_id=conv.id).count() == 0
