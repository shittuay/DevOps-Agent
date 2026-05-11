"""Tests for stateless Slack notification helpers."""
import pytest
from unittest.mock import patch, MagicMock
from services.notification_service import (
    notify_incident, notify_security, notify_cost, notify_changes,
    _send_async, Notification, NotificationPriority
)


@pytest.fixture
def mock_app():
    app = MagicMock()
    app.app_context.return_value.__enter__ = MagicMock(return_value=None)
    app.app_context.return_value.__exit__ = MagicMock(return_value=False)
    return app


@pytest.fixture
def slack_channel():
    ch = MagicMock()
    ch.channel_type = 'slack'
    ch.webhook_url = 'https://hooks.slack.com/services/TEST'
    ch.is_active = True
    ch.notify_incidents = True
    ch.notify_security = True
    ch.notify_cost = True
    ch.notify_changes = True
    return ch


def _make_sync_thread(target, daemon=True):
    """Side-effect for threading.Thread mock: makes .start() call target() synchronously."""
    m = MagicMock()
    m.start.side_effect = target
    return m


def test_notify_incident_created_sends_slack(mock_app, slack_channel):
    """notify_incident fires SlackClient.send_webhook for active channels."""
    incident = {
        'id': 'abc123', 'title': 'High CPU', 'severity': 'high',
        'status': 'detected', 'source': 'cloudwatch'
    }
    with patch('services.notification_service.current_app') as mock_ca, \
         patch('services.notification_service.UserNotificationChannel') as MockCh, \
         patch('services.notification_service.SlackClient') as MockSlack, \
         patch('services.notification_service.threading.Thread') as MockThread:

        mock_ca._get_current_object.return_value = mock_app
        MockCh.query.filter_by.return_value.filter.return_value.all.return_value = [slack_channel]
        MockThread.side_effect = _make_sync_thread
        mock_client = MagicMock()
        mock_client.send_webhook.return_value = True
        MockSlack.return_value = mock_client

        notify_incident(1, incident, 'created', 'https://devopsagent.io')

        MockSlack.assert_called_once_with(webhook_url='https://hooks.slack.com/services/TEST')
        mock_client.send_webhook.assert_called_once()
        notification_arg = mock_client.send_webhook.call_args[0][0]
        assert 'High CPU' in notification_arg.message
        assert notification_arg.priority == NotificationPriority.HIGH


def test_notify_security_skips_when_no_critical_or_high():
    """notify_security does not fire when only low/medium findings exist."""
    results = {'critical': 0, 'high': 0, 'medium': 2, 'low': 5, 'total': 7}
    with patch('services.notification_service.threading.Thread') as MockThread:
        notify_security(1, results, 'https://devopsagent.io')
        MockThread.assert_not_called()


def test_notify_security_fires_when_critical(mock_app, slack_channel):
    """notify_security fires when critical > 0."""
    results = {'critical': 3, 'high': 0, 'medium': 0, 'low': 0, 'total': 3}
    with patch('services.notification_service.current_app') as mock_ca, \
         patch('services.notification_service.UserNotificationChannel') as MockCh, \
         patch('services.notification_service.SlackClient') as MockSlack, \
         patch('services.notification_service.threading.Thread') as MockThread:
        mock_ca._get_current_object.return_value = mock_app
        MockCh.query.filter_by.return_value.filter.return_value.all.return_value = [slack_channel]
        MockThread.side_effect = _make_sync_thread
        mock_client = MagicMock()
        MockSlack.return_value = mock_client
        notify_security(1, results, 'https://devopsagent.io')
        mock_client.send_webhook.assert_called_once()


def test_notify_cost_skips_when_zero_new():
    """notify_cost does not fire when new_count is 0."""
    with patch('services.notification_service.threading.Thread') as MockThread:
        notify_cost(1, new_count=0, total_savings=0.0, base_url='https://devopsagent.io')
        MockThread.assert_not_called()


def test_notify_changes_skips_when_zero():
    """notify_changes does not fire when rec_count is 0."""
    with patch('services.notification_service.threading.Thread') as MockThread:
        notify_changes(1, rec_count=0, base_url='https://devopsagent.io')
        MockThread.assert_not_called()


def test_send_async_no_app_context_silently_skips():
    """_send_async returns silently when no Flask app context is available."""
    notification = Notification(title='T', message='M')
    with patch('services.notification_service.current_app') as mock_ca, \
         patch('services.notification_service.threading.Thread') as MockThread:
        mock_ca._get_current_object.side_effect = RuntimeError('no app context')
        _send_async(1, 'incidents', notification)
        MockThread.assert_not_called()
