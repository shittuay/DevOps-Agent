"""Executing a workflow must actually dispatch it, and must not 500.

History:
- execute_workflow() first created the seed ChatMessage without user_id, but that
  column is NOT NULL, so every "Execute" click died with
  `NOT NULL constraint failed: chat_messages.user_id`.
- Then it seeded the message *correctly* and still did nothing useful: writing a
  user message row does not run the agent (only /api/chat/stream does), so the
  run showed up in the sidebar, never in the chat window, and the execution sat
  at 'running' forever. The endpoint now returns the prompt for the chat page to
  send through the normal streaming path instead.
"""


def _make_template(app, user_id):
    from models import db, WorkflowTemplate

    with app.app_context():
        tpl = WorkflowTemplate(
            name='Test workflow',
            description='does a thing',
            category='test',
            is_public=True,
            created_by=user_id,
            steps=['deploy the app', 'run a smoke test'],
        )
        db.session.add(tpl)
        db.session.commit()
        return tpl.id


def test_execute_returns_prompt_for_dispatch(authenticated_client, test_user, app):
    from models import ChatMessage

    tid = _make_template(app, test_user.id)

    resp = authenticated_client.post(f'/api/workflows/{tid}/execute', json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data.get('conversation_id') and data.get('execution_id')

    # the prompt must come back — the chat page sends it as a real message
    assert data.get('prompt'), "execute must return the prompt, or nothing dispatches the run"
    for step in ('deploy the app', 'run a smoke test'):
        assert step in data['prompt'], "every step must reach the agent"

    # and must NOT be pre-persisted: a seeded row renders in the transcript but
    # never runs, and would duplicate once the page sends it for real
    with app.app_context():
        assert ChatMessage.query.filter_by(conversation_id=data['conversation_id']).count() == 0


def test_execute_starts_queued_not_running(authenticated_client, test_user, app):
    """It isn't 'running' until the chat page actually starts the stream."""
    from models import WorkflowExecution

    tid = _make_template(app, test_user.id)
    resp = authenticated_client.post(f'/api/workflows/{tid}/execute', json={})
    execution_id = resp.get_json()['execution_id']

    with app.app_context():
        assert WorkflowExecution.query.get(execution_id).status == 'queued'


def test_execution_status_can_be_marked_running(authenticated_client, test_user, app):
    from models import WorkflowExecution

    tid = _make_template(app, test_user.id)
    execution_id = authenticated_client.post(
        f'/api/workflows/{tid}/execute', json={}
    ).get_json()['execution_id']

    resp = authenticated_client.patch(
        f'/api/workflows/executions/{execution_id}', json={'status': 'running'}
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    with app.app_context():
        assert WorkflowExecution.query.get(execution_id).status == 'running'
