"""The Changes page's summary cards count every change, whatever filter tab is open (2026-10-17).

The Total card used to show the filtered list's size, so on the Pending tab it read 0 while
Executed still read 9.
"""
from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent / 'templates/changes.html').read_text()


def test_total_card_is_fetched_unfiltered():
    assert "fetchStatCount('', 'statTotal')" in PAGE
    assert "getElementById('statTotal').textContent = all" not in PAGE


def test_empty_pending_tab_points_to_approvals():
    assert '<a href="/approvals">Approvals</a>' in PAGE


def test_unfiltered_status_lists_every_change(app, db_session):
    from models import InfrastructureChange, User, db
    user = User(email='stats-total@example.com', username='stats_total', full_name='S',
                role='user', email_verified=True)
    user.set_password('TestPassword123!')
    db.session.add(user)
    db.session.commit()
    try:
        for status in ('executed', 'executed', 'pending'):
            db.session.add(InfrastructureChange(user_id=user.id, title='t', action_type='create',
                                                resource_type='ec2', status=status))
        db.session.commit()
        client = app.test_client()
        assert client.post('/login', data={'email': user.email,
                                           'password': 'TestPassword123!'}).status_code == 302
        assert client.get('/api/changes?status=&per_page=1').get_json()['total'] == 3
        assert client.get('/api/changes?status=executed&per_page=1').get_json()['total'] == 2
    finally:
        db.session.rollback()
        InfrastructureChange.query.filter_by(user_id=user.id).delete()
        db.session.delete(User.query.get(user.id))
        db.session.commit()
