"""2026-11-26 scheduled review: a change request runs once and rolls back once.

execute_change and rollback_change checked the status and then acted, with no
claim in between, so a double click (or two reviewers) ran a delete/stop twice
and an executed change could be rolled back again and again.
"""
from unittest import mock

from tests.test_change_approvals_unified import _change, _login, team  # noqa: F401


def test_second_execute_of_a_running_change_is_refused(app, team):
    from models import db
    c = _change(team['solo'])
    c.status = 'approved'
    db.session.commit()
    client = _login(app, team['solo'].email)
    calls = []

    def run(change):
        calls.append(change.id)
        assert change.status == 'executing'
        # A second click while the first is still running.
        assert client.post(f'/api/changes/{change.id}/execute').status_code == 400
        return {'status': 'ok'}

    with mock.patch('routes.changes._capture_rollback_data', return_value={}), \
         mock.patch('routes.changes._execute_change', side_effect=run):
        assert client.post(f'/api/changes/{c.id}/execute').status_code == 200
    assert calls == [c.id]
    db.session.refresh(c)
    assert c.status == 'executed'


def test_no_action_puts_the_change_back_to_approved(app, team):
    from models import db
    c = _change(team['solo'])
    c.status = 'approved'
    db.session.commit()
    with mock.patch('routes.changes._capture_rollback_data', return_value={}), \
         mock.patch('routes.changes._execute_change', return_value={'status': 'no_action'}):
        assert _login(app, team['solo'].email).post(f'/api/changes/{c.id}/execute').status_code == 400
    db.session.refresh(c)
    assert c.status == 'approved'


def test_an_executed_change_rolls_back_once(app, team):
    from models import db
    c = _change(team['solo'])
    c.status = 'executed'
    c.rollback_data = {'previous_state': 'running'}
    db.session.commit()
    client = _login(app, team['solo'].email)
    with mock.patch('routes.changes._execute_rollback', return_value={'ok': True}) as rb:
        assert client.post(f'/api/changes/{c.id}/rollback').status_code == 200
        assert client.post(f'/api/changes/{c.id}/rollback').status_code == 400
    assert rb.call_count == 1
    db.session.refresh(c)
    assert c.status == 'rolled_back'


def test_failed_rollback_hides_the_error_and_can_be_retried(app, team):
    from models import db
    c = _change(team['solo'])
    c.status = 'executed'
    c.rollback_data = {'previous_state': 'running'}
    db.session.commit()
    with mock.patch('routes.changes._execute_rollback', side_effect=RuntimeError('secret-arn-xyz')):
        r = _login(app, team['solo'].email).post(f'/api/changes/{c.id}/rollback')
    assert r.status_code == 500
    assert 'secret-arn-xyz' not in r.get_data(as_text=True)
    db.session.refresh(c)
    assert c.status == 'executed'
