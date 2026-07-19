"""Regression tests: email send failures must not be silent (Jul 2026).

An invalid Brevo API key silently broke ALL transactional email for ~3 weeks
because send_email returned False and every caller treated it as success. These
tests lock in that a delivery failure is logged at ERROR (and thus alertable),
while a success stays quiet.
"""
import logging
from services.email_service import EmailService


def _svc():
    return EmailService()


def test_failed_send_logs_error(caplog):
    svc = _svc()
    # Force the provider dispatch to report failure, like a bad API key would.
    svc._dispatch = lambda *a, **k: False
    with caplog.at_level(logging.ERROR, logger='services.email_service'):
        result = svc.send_email('user@example.com', 'Verify your email', '<p>hi</p>')
    assert result is False
    assert any('EMAIL DELIVERY FAILED' in r.message for r in caplog.records), \
        "a failed send must log an ERROR so it can be alerted on"


def test_successful_send_is_quiet(caplog):
    svc = _svc()
    svc._dispatch = lambda *a, **k: True
    with caplog.at_level(logging.ERROR, logger='services.email_service'):
        result = svc.send_email('user@example.com', 'Welcome', '<p>hi</p>')
    assert result is True
    assert not any('EMAIL DELIVERY FAILED' in r.message for r in caplog.records), \
        "a successful send must not log a delivery-failure error"


def test_dispatch_still_routes_by_provider(monkeypatch):
    """The extracted _dispatch keeps the original provider routing intact."""
    svc = _svc()
    calls = []
    svc.provider = 'smtp'
    monkeypatch.setattr(svc, '_send_smtp', lambda *a, **k: calls.append('smtp') or True)
    svc.send_email('u@example.com', 's', '<p>b</p>')
    assert calls == ['smtp']
