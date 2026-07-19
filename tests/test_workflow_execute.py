"""Regression test: executing a workflow must not 500.

execute_workflow() created the seed ChatMessage without user_id, but that
column is NOT NULL — so every "Execute" click died with
`NOT NULL constraint failed: chat_messages.user_id`.
"""


def test_execute_workflow_seeds_message_with_user_id(authenticated_client, test_user, app):
    from models import db, WorkflowTemplate, ChatMessage

    with app.app_context():
        tpl = WorkflowTemplate(
            name='Test workflow',
            description='does a thing',
            category='test',
            is_public=True,
            created_by=test_user.id,
            steps=[{'action': 'deploy'}, {'action': 'smoke_test'}],
        )
        db.session.add(tpl)
        db.session.commit()
        tid = tpl.id

    resp = authenticated_client.post(f'/api/workflows/{tid}/execute', json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data.get('conversation_id') and data.get('execution_id')

    # the seeded chat message must carry the user_id (the bug left it NULL)
    with app.app_context():
        msg = ChatMessage.query.filter_by(conversation_id=data['conversation_id']).first()
        assert msg is not None, "workflow execute should seed a chat message"
        assert msg.user_id == test_user.id, "seeded message must have the user's id"
