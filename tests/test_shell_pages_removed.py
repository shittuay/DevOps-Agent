"""Pages that did nothing for customers are gone, and nothing links to them (2026-10-14 audit).

- /notifications saved Slack/Teams settings in per-process memory that real alerts never read.
- /teams was a staff user list; customers saw only themselves. Teams live in Organizations.
- /templates (saved prompts) was linked from nowhere and overlapped Workflows.
- Admin > System settings showed fixed "Connected" badges (and its own link 500'd).
- ChatOps only had /help and /link left for customers.
- The incoming CI webhooks used one server-wide secret and fed nothing.
- AI Deployments / Recommendations / Optimize always returned nothing.
- Analytics > Performance failed to load and mislabelled its numbers.
"""
import importlib

import pytest

REMOVED_PAGES = [
    '/notifications/', '/teams', '/templates', '/admin/settings', '/chatops/', '/webhooks/',
    '/ai/deployments', '/ai/recommendations', '/analytics/performance',
]
REMOVED_APIS = [
    ('POST', '/api/team/invite'), ('GET', '/api/templates'), ('POST', '/api/templates'),
    ('POST', '/api/webhooks/github'), ('GET', '/api/webhooks'), ('POST', '/webhooks/github'),
    ('POST', '/notifications/api/configure/slack'), ('GET', '/ai/api/recommendations'),
    ('GET', '/ai/api/deployments'), ('POST', '/ai/api/optimize'), ('POST', '/chatops/slack/events'),
]


@pytest.mark.parametrize('path', REMOVED_PAGES)
def test_removed_pages_are_gone(authenticated_client, path):
    assert authenticated_client.get(path).status_code == 404


@pytest.mark.parametrize('method,path', REMOVED_APIS)
def test_removed_endpoints_are_gone(authenticated_client, method, path):
    resp = authenticated_client.open(path, method=method, json={})
    assert resp.status_code in (404, 405)


@pytest.mark.parametrize('module', [
    'routes.notifications', 'routes.webhooks', 'routes.chatops', 'services.chatops_service',
    'services.webhook_handler', 'services.webhook_integrations', 'services.audit_service',
    'services.websocket_service',
])
def test_removed_modules_are_gone(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)


def test_in_memory_notification_store_is_gone():
    import services.notification_service as ns
    assert not hasattr(ns, 'get_notification_service')
    assert not hasattr(ns, 'NotificationService')


def test_change_events_go_to_saved_channels(monkeypatch):
    import services.notification_service as ns
    sent = []
    monkeypatch.setattr(ns, '_send_async', lambda uid, kind, n: sent.append((uid, kind, n.title)))
    ns.notify_change_event(7, {'id': 3, 'title': 'Stop web-1', 'risk_level': 'high'}, 'approved')
    assert sent == [(7, 'changes', 'Change request approved: #3')]


@pytest.mark.parametrize('path', ['/chat', '/dashboard', '/settings', '/about', '/ai/', '/analytics/',
                                  '/analytics/costs', '/analytics/resources'])
def test_nothing_links_to_removed_pages(authenticated_client, monkeypatch, test_user, path):
    import app as appmod
    from models import db, User
    monkeypatch.setattr(appmod, 'check_api_key_configured', lambda: True)
    u = db.session.get(User, test_user.id)
    u.onboarding_completed = True
    db.session.commit()
    resp = authenticated_client.get(path, follow_redirects=True)
    assert resp.status_code == 200, path
    body = resp.get_data(as_text=True)
    for target in ['/notifications', '/teams', '/templates', '/chatops', '/webhooks',
                   '/ai/deployments', '/ai/recommendations', '/analytics/performance', '/admin/settings']:
        for q in ('"', "'"):
            assert f'href={q}{target}' not in body, f'{path} links to {target}'
            assert f"location.href={q}{target}" not in body, f'{path} links to {target}'
