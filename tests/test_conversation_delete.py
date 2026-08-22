"""Regression: deleting a conversation must not leave orphaned rows behind.

`delete_conversation()` (app.py) and its api/v1 counterpart only deleted
ChatMessage rows before deleting the Conversation itself. Five other models
(UsageLog, LearningSession, WorkflowExecution, ChatArtifact, ApprovalRequest)
FK to conversations.id but were never cleaned up. On Postgres (production),
the FK constraint rejects the Conversation delete outright -- the route
catches the IntegrityError and returns a 500, which the frontend swallows
silently (only console.error, no user-visible message), so from the user's
side the "Delete" button just does nothing.
"""
from datetime import datetime, timedelta

from models import (db, Conversation, ChatMessage, UsageLog, LearningSession,
                     WorkflowExecution, WorkflowTemplate, ChatArtifact,
                     ApprovalRequest)


def _make_conversation_with_dependents(user_id):
    conv = Conversation(id='conv-delete-test', user_id=user_id, title='Test')
    db.session.add(conv)
    db.session.flush()

    db.session.add(ChatMessage(conversation_id=conv.id, user_id=user_id,
                                role='user', content='hi'))
    db.session.add(UsageLog(user_id=user_id, action_type='message',
                             conversation_id=conv.id))
    db.session.add(LearningSession(user_id=user_id, conversation_id=conv.id))
    db.session.add(ChatArtifact(user_id=user_id, conversation_id=conv.id,
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


def test_delete_conversation_removes_all_dependent_rows(authenticated_client, test_user):
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
