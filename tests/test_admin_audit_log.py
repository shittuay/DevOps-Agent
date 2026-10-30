"""/admin/audit-log returned 500: it sorted by UsageLog.timestamp, which doesn't exist
(the column is created_at). Found 2026-10-30 when the owner clicked Audit log."""
import uuid


def test_audit_log_renders(app, db_session):
    from flask import g
    from models import User, UsageLog, db
    tag = uuid.uuid4().hex[:8]
    admin = User(email=f'aud-{tag}@example.com', username=f'aud_{tag}', role='admin')
    admin.set_password('Password123!x')
    db.session.add(admin)
    db.session.commit()
    log = UsageLog(user_id=admin.id, action_type='tool_use', tool_name='list_s3_buckets',
                   ai_model='kimi-k3', success=False, error_message='AccessDenied')
    db.session.add(log)
    db.session.commit()
    try:
        c = app.test_client()
        g.pop('_login_user', None)
        assert c.post('/login', data={'email': admin.email, 'password': 'Password123!x'}).status_code == 302
        g.pop('_login_user', None)
        resp = c.get('/admin/audit-log')
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200, body[:500]
        assert 'list_s3_buckets' in body and admin.email in body and 'AccessDenied' in body
    finally:
        g.pop('_login_user', None)
        db.session.delete(log)
        db.session.delete(admin)
        db.session.commit()
