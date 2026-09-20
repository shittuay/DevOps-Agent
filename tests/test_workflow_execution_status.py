"""Recent Executions must not show "Running" for a run that stopped.

'completed'/'failed' were only ever written by the SSE done handler in the chat
page, so a closed tab (or a dispatch that never happened at all) stranded the row
at 'running' permanently. Listing executions now reconciles stale ones.
"""
from datetime import datetime, timedelta
from src.utils.timeutils import utcnow


def _execution(app, user_id, *, status, age_minutes, with_reply):
    from models import db, WorkflowTemplate, WorkflowExecution, Conversation, ChatMessage

    with app.app_context():
        tpl = WorkflowTemplate(
            name=f'Stale test {status} {age_minutes} {with_reply}',
            description='d', category='test', is_public=True,
            created_by=user_id, steps=['step one'],
        )
        db.session.add(tpl)
        db.session.flush()

        started = utcnow() - timedelta(minutes=age_minutes)
        conv_id = f'conv{tpl.id}'
        db.session.add(Conversation(id=conv_id, user_id=user_id, title='Workflow'))
        if with_reply:
            db.session.add(ChatMessage(
                conversation_id=conv_id, user_id=user_id,
                role='assistant', content='done', timestamp=started + timedelta(minutes=1),
            ))

        ex = WorkflowExecution(
            user_id=user_id, template_id=tpl.id, conversation_id=conv_id,
            status=status, started_at=started, created_at=started,
        )
        db.session.add(ex)
        db.session.commit()
        return ex.id


def _status_of(client, execution_id):
    execs = client.get('/api/workflows/executions').get_json()['executions']
    return next(e['status'] for e in execs if e['id'] == execution_id)


def test_stale_running_with_reply_becomes_completed(authenticated_client, test_user, app):
    eid = _execution(app, test_user.id, status='running', age_minutes=120, with_reply=True)
    assert _status_of(authenticated_client, eid) == 'completed'


def test_stale_running_without_reply_times_out(authenticated_client, test_user, app):
    eid = _execution(app, test_user.id, status='running', age_minutes=120, with_reply=False)
    assert _status_of(authenticated_client, eid) == 'timed_out'


def test_recent_running_is_left_alone(authenticated_client, test_user, app):
    """A run genuinely in flight must not be reaped mid-stream."""
    eid = _execution(app, test_user.id, status='running', age_minutes=1, with_reply=False)
    assert _status_of(authenticated_client, eid) == 'running'


def test_stale_queued_that_never_dispatched_times_out(authenticated_client, test_user, app):
    eid = _execution(app, test_user.id, status='queued', age_minutes=120, with_reply=False)
    assert _status_of(authenticated_client, eid) == 'timed_out'


def test_completed_execution_is_not_rewritten(authenticated_client, test_user, app):
    from models import db, WorkflowExecution

    eid = _execution(app, test_user.id, status='completed', age_minutes=500, with_reply=False)
    assert _status_of(authenticated_client, eid) == 'completed'

    with app.app_context():
        assert WorkflowExecution.query.get(eid).status == 'completed'
        db.session.rollback()
