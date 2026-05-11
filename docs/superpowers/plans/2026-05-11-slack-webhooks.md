# Slack Webhook Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Slack notification infrastructure to actual trigger points so users receive real-time Slack messages when incidents are created/acknowledged/resolved, security scans find critical findings, cost recommendations are generated, and proactive analysis finds new issues.

**Architecture:** Add stateless `notify_*` public functions to `notification_service.py` that load `UserNotificationChannel` rows from DB on each call, build Slack Block Kit messages with action buttons, and fire in daemon threads. Wire these functions into the four event trigger points. Fix two existing bugs in `app.py`.

**Tech Stack:** Flask + SQLAlchemy, Python `threading`, `requests` (already used by `SlackClient`), `os.environ` for `BASE_URL`.

---

## File Map

| File | Change |
|---|---|
| `services/notification_service.py` | Add `import threading`, `import os`. Add `_send_async()` private helper + `notify_incident()`, `notify_security()`, `notify_cost()`, `notify_changes()` public functions. |
| `services/incident_response.py` | Add import of `notify_incident`. Call it after `_save_incident_to_db()` in `create_incident()`, `acknowledge_incident()`, `resolve_incident()`. |
| `services/security_scanner.py` | Add import of `notify_security`. Call it after `db.session.commit()` in `scan_aws_security()` when `critical > 0 or high > 0`. |
| `services/infrastructure_sync.py` | Modify `generate_cost_recommendations()` to return `(new_count, total_new_savings)`. Wire `notify_cost()` at the end of `sync_user_infrastructure()`. |
| `routes/optimization.py` | Add import of `notify_changes`. Call it after `db.session.commit()` in `api_run_analysis()` when `saved > 0`. |
| `app.py` | Remove dead `configure_slack()` try/except in `notification_channels()` POST (lines 2372–2381). Rewrite `test_notification_channel()` to use stateless `SlackClient` directly. |

---

## Task 1: Add stateless notify functions to `notification_service.py`

**Files:**
- Modify: `services/notification_service.py`
- Test: `tests/test_slack_notifications.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_slack_notifications.py`:

```python
"""Tests for stateless Slack notification helpers."""
import pytest
from unittest.mock import patch, MagicMock, call
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


def _make_sync_thread(target, daemon):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_slack_notifications.py -v
```

Expected: ImportError — `notify_incident`, `notify_security`, etc. not yet defined.

- [ ] **Step 3: Add imports and functions to `notification_service.py`**

At the top of `services/notification_service.py`, add to existing imports:

```python
import os
import threading
from flask import current_app
from models import UserNotificationChannel
```

After the existing `configure_notifications()` function at the bottom of the file (line ~621), add:

```python
_BASE_URL = os.environ.get('BASE_URL', 'https://devopsagent.io')


def _send_async(user_id: int, event_type: str, notification: 'Notification') -> None:
    """Load matching channels from DB and send notification in a daemon thread.

    event_type must be one of: 'incidents', 'cost', 'security', 'changes'.
    Requires Flask app context at call site (request handler or scheduler task).
    Silently no-ops if no app context is available.
    """
    try:
        flask_app = current_app._get_current_object()
    except RuntimeError:
        logger.debug("_send_async called outside app context — skipping")
        return

    flag_map = {
        'incidents': UserNotificationChannel.notify_incidents,
        'cost':      UserNotificationChannel.notify_cost,
        'security':  UserNotificationChannel.notify_security,
        'changes':   UserNotificationChannel.notify_changes,
    }
    flag_col = flag_map.get(event_type)
    if flag_col is None:
        logger.warning(f"_send_async: unknown event_type '{event_type}'")
        return

    def _run():
        with flask_app.app_context():
            try:
                # Use UserNotificationChannel from outer scope (captured in closure).
                # Do NOT reimport — that would break the mock in tests.
                channels = (
                    UserNotificationChannel.query
                    .filter_by(user_id=user_id, is_active=True)
                    .filter(flag_col == True)
                    .all()
                )
                for ch in channels:
                    if ch.channel_type == 'slack':
                        SlackClient(webhook_url=ch.webhook_url).send_webhook(notification)
            except Exception:
                logger.exception(f"Error sending {event_type} notification for user {user_id}")

    threading.Thread(target=_run, daemon=True).start()


def notify_incident(user_id: int, incident: dict, event: str, base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for an incident lifecycle event.

    Args:
        user_id:  Owner of the incident.
        incident: Dict with keys: id, title, severity, status, source.
        event:    One of 'created', 'acknowledged', 'resolved'.
        base_url: App base URL for the "View Incident" button.
    """
    event_label = {'created': 'New Incident', 'acknowledged': 'Incident Acknowledged',
                   'resolved': 'Incident Resolved'}.get(event, 'Incident Update')
    severity = incident.get('severity', 'medium')
    priority_map = {
        'low':      NotificationPriority.LOW,
        'medium':   NotificationPriority.NORMAL,
        'high':     NotificationPriority.HIGH,
        'critical': NotificationPriority.CRITICAL,
    }
    notification = Notification(
        title=f"{event_label}: #{incident.get('id', 'N/A')}",
        message=incident.get('title', 'Incident notification'),
        priority=priority_map.get(severity, NotificationPriority.NORMAL),
        fields={
            'Severity': severity.upper(),
            'Status':   incident.get('status', 'unknown').upper(),
            'Source':   incident.get('source', 'N/A'),
        },
        actions=[{
            'text': 'View Incident',
            'url':  f"{base_url}/incidents/{incident.get('id', '')}",
            'primary': True,
        }],
    )
    _send_async(user_id, 'incidents', notification)


def notify_security(user_id: int, results: dict, base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for security scan results.

    Silently skips if critical + high == 0 to avoid noise on clean scans.

    Args:
        user_id:  Owner of the scan.
        results:  Dict with keys: critical, high, medium, low, total.
        base_url: App base URL for the "View Findings" button.
    """
    if results.get('critical', 0) == 0 and results.get('high', 0) == 0:
        return
    critical = results.get('critical', 0)
    high = results.get('high', 0)
    priority = NotificationPriority.CRITICAL if critical > 0 else NotificationPriority.HIGH
    notification = Notification(
        title=f"Security Scan: {results.get('total', 0)} findings",
        message=f"Security scan found {critical} critical and {high} high severity issues that need attention.",
        priority=priority,
        fields={
            'Critical': str(critical),
            'High':     str(high),
            'Medium':   str(results.get('medium', 0)),
            'Low':      str(results.get('low', 0)),
        },
        actions=[{
            'text': 'View Findings',
            'url':  f"{base_url}/optimization",
            'primary': True,
        }],
    )
    _send_async(user_id, 'security', notification)


def notify_cost(user_id: int, new_count: int, total_savings: float,
                base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for new cost optimization recommendations.

    Silently skips when new_count == 0.

    Args:
        user_id:       Owner of the recommendations.
        new_count:     Number of newly created recommendations (not updates).
        total_savings: Combined potential monthly savings across all new recs.
        base_url:      App base URL for the "View Recommendations" button.
    """
    if new_count == 0:
        return
    notification = Notification(
        title=f"Cost Alert: {new_count} new recommendation{'s' if new_count > 1 else ''}",
        message=f"DevOps Agent found {new_count} new cost optimization opportunities totalling ${total_savings:.2f}/month in potential savings.",
        priority=NotificationPriority.NORMAL,
        fields={
            'New Recommendations': str(new_count),
            'Potential Savings':   f"${total_savings:.2f}/mo",
        },
        actions=[{
            'text': 'View Recommendations',
            'url':  f"{base_url}/optimization",
            'primary': True,
        }],
    )
    _send_async(user_id, 'cost', notification)


def notify_changes(user_id: int, rec_count: int, base_url: str = _BASE_URL) -> None:
    """Fire a Slack notification for new proactive infrastructure recommendations.

    Silently skips when rec_count == 0.

    Args:
        user_id:   Owner of the recommendations.
        rec_count: Number of newly saved ProactiveRecommendation records.
        base_url:  App base URL for the "View Analysis" button.
    """
    if rec_count == 0:
        return
    notification = Notification(
        title=f"Infrastructure Analysis: {rec_count} new finding{'s' if rec_count > 1 else ''}",
        message=f"Proactive analysis found {rec_count} new infrastructure recommendation{'s' if rec_count > 1 else ''} across observability, governance, and optimization.",
        priority=NotificationPriority.NORMAL,
        fields={'New Findings': str(rec_count)},
        actions=[{
            'text': 'View Analysis',
            'url':  f"{base_url}/optimization/prevention",
            'primary': True,
        }],
    )
    _send_async(user_id, 'changes', notification)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_slack_notifications.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add services/notification_service.py tests/test_slack_notifications.py
git commit -m "feat: add stateless Slack notify helpers to notification_service"
```

---

## Task 2: Wire incident lifecycle notifications

**Files:**
- Modify: `services/incident_response.py:677-718` (create_incident), `866-883` (acknowledge_incident), `885-901` (resolve_incident)

- [ ] **Step 1: Add import at top of `incident_response.py`**

Locate the existing imports block (line ~17). Add:

```python
from services.notification_service import notify_incident as _notify_incident
```

- [ ] **Step 2: Wire `create_incident()`**

After line 717 (`logger.info(f"Created incident {incident_id}...")`), add:

```python
        import os
        _notify_incident(
            user_id, 
            {'id': incident.id, 'title': incident.title, 'severity': incident.severity.value,
             'status': incident.status.value, 'source': incident.source},
            'created',
            os.environ.get('BASE_URL', 'https://devopsagent.io')
        )
```

- [ ] **Step 3: Wire `acknowledge_incident()`**

After line 882 (`self._write_journal_entry(...)`), before the `return`:

```python
        import os
        _notify_incident(
            user_id,
            {'id': incident_id, 'title': incident.title, 'severity': incident.severity.value,
             'status': incident.status.value, 'source': incident.source,
             'assigned_to': incident.assigned_to},
            'acknowledged',
            os.environ.get('BASE_URL', 'https://devopsagent.io')
        )
```

- [ ] **Step 4: Wire `resolve_incident()`**

After line 900 (`self._write_journal_entry(...)`), before the `return`:

```python
        import os
        _notify_incident(
            user_id,
            {'id': incident_id, 'title': incident.title, 'severity': incident.severity.value,
             'status': incident.status.value, 'source': incident.source},
            'resolved',
            os.environ.get('BASE_URL', 'https://devopsagent.io')
        )
```

- [ ] **Step 5: Smoke-test**

```
python -c "from services.incident_response import IncidentResponseService; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 6: Commit**

```bash
git add services/incident_response.py
git commit -m "feat: fire Slack notifications on incident create/acknowledge/resolve"
```

---

## Task 3: Wire security scan notifications

**Files:**
- Modify: `services/security_scanner.py:16-77` (scan_aws_security)

- [ ] **Step 1: Add import at top of `security_scanner.py`**

After the existing imports (line ~4), add:

```python
from services.notification_service import notify_security as _notify_security
```

- [ ] **Step 2: Wire notify call at end of `scan_aws_security()`**

`scan_aws_security()` ends at line ~77 with `return results`. Before the return, add:

```python
    import os
    _notify_security(
        user_id,
        results,
        os.environ.get('BASE_URL', 'https://devopsagent.io')
    )
    return results
```

(Replace the existing bare `return results` on line ~77.)

- [ ] **Step 3: Smoke-test**

```
python -c "from services.security_scanner import scan_aws_security; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add services/security_scanner.py
git commit -m "feat: fire Slack notification after security scan when critical/high findings exist"
```

---

## Task 4: Wire cost recommendation notifications

**Files:**
- Modify: `services/infrastructure_sync.py:1212-1290` (generate_cost_recommendations), `134-180` (sync_user_infrastructure)

- [ ] **Step 1: Modify `generate_cost_recommendations()` to return a count**

`generate_cost_recommendations()` at line 1212 currently returns nothing. Modify it to track and return `(new_count, total_new_savings)`.

At the start of the function body (after line 1213 docstring), add:

```python
    new_count = 0
    total_new_savings = 0.0
```

`create_or_update_recommendation()` creates a new row only when `not existing` (line 1343). Modify that function to return a boolean indicating whether a new row was created:

Find `create_or_update_recommendation()` at line 1326 and change its body:

```python
def create_or_update_recommendation(
    user_id: int,
    resource_id: int,
    rec_type: str,
    title: str,
    description: str,
    savings: float
) -> bool:
    """Create or update a cost optimization recommendation. Returns True if new row created."""
    existing = CostOptimization.query.filter_by(
        user_id=user_id,
        resource_id=resource_id,
        recommendation_type=rec_type,
        status='pending'
    ).first()

    if not existing:
        recommendation = CostOptimization(
            user_id=user_id,
            resource_id=resource_id,
            recommendation_type=rec_type,
            title=title,
            description=description,
            potential_monthly_savings=savings
        )
        db.session.add(recommendation)
        return True
    return False
```

Then in `generate_cost_recommendations()`, update every `create_or_update_recommendation(...)` call to:

```python
            if create_or_update_recommendation(...):
                new_count += 1
                total_new_savings += <savings_variable>
```

There are three call sites in the EC2 running block (lines ~1221, 1235, 1247) and one in the stopped block (~1260). For each, wrap with the `if` and add the savings to `total_new_savings`. Use the same `savings` value that was passed as the last positional arg.

At the very end of `generate_cost_recommendations()`, replace `(implicit None return)` with:

```python
    db.session.commit()
    return new_count, total_new_savings
```

(Note: `db.session.commit()` was not in the original function — it was left to the caller. Check if the caller `sync_user_infrastructure()` commits separately. It does not explicitly commit after `generate_cost_recommendations()` — the session is committed inside `_save_incident_to_db` patterns elsewhere. Add `db.session.commit()` here to ensure recs are persisted before notifying.)

- [ ] **Step 2: Wire notify call in `sync_user_infrastructure()`**

`sync_user_infrastructure()` at line 134 calls `generate_cost_recommendations(user_id)` at line 178. Change it to:

```python
    # Generate cost optimization recommendations
    import os
    from services.notification_service import notify_cost as _notify_cost
    new_cost_count, new_cost_savings = generate_cost_recommendations(user_id)
    _notify_cost(
        user_id, new_cost_count, new_cost_savings,
        os.environ.get('BASE_URL', 'https://devopsagent.io')
    )
```

- [ ] **Step 3: Smoke-test**

```
python -c "from services.infrastructure_sync import generate_cost_recommendations; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add services/infrastructure_sync.py
git commit -m "feat: fire Slack notification when new cost recommendations are generated"
```

---

## Task 5: Wire proactive analysis notifications

**Files:**
- Modify: `routes/optimization.py:232-269` (api_run_analysis)

- [ ] **Step 1: Add import at top of `routes/optimization.py`**

Locate the existing imports. Add:

```python
import os
```

- [ ] **Step 2: Wire notify after `db.session.commit()` in `api_run_analysis()`**

`api_run_analysis()` ends at line ~269:

```python
    db.session.commit()
    return jsonify({'success': True, 'analyzed': len(recs_data), 'saved': saved})
```

Change it to:

```python
    db.session.commit()
    if saved > 0:
        from services.notification_service import notify_changes as _notify_changes
        _notify_changes(
            current_user.id,
            saved,
            os.environ.get('BASE_URL', 'https://devopsagent.io')
        )
    return jsonify({'success': True, 'analyzed': len(recs_data), 'saved': saved})
```

- [ ] **Step 3: Smoke-test**

```
python -c "from routes.optimization import optimization_bp; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add routes/optimization.py
git commit -m "feat: fire Slack notification when proactive analysis finds new recommendations"
```

---

## Task 6: Fix bugs in `app.py`

**Files:**
- Modify: `app.py:2372-2381` (notification_channels POST), `app.py:2418-2446` (test_notification_channel)

- [ ] **Step 1: Remove dead `configure_slack()` block from `notification_channels()` POST**

Find lines 2372–2381 in `app.py`:

```python
    # Wire into the notification service
    try:
        from services.notification_service import get_notification_service
        svc = get_notification_service()
        if channel_type == 'slack':
            svc.configure_slack(webhook_url=webhook_url)
        elif channel_type == 'teams':
            svc.configure_teams(webhook_url=webhook_url)
    except Exception:
        pass
```

Delete this entire block. The stateless approach doesn't need in-memory configuration. The function should end at the `return jsonify(...)` immediately after `db.session.commit()`.

- [ ] **Step 2: Rewrite `test_notification_channel()`**

Replace the entire body of `test_notification_channel()` (lines 2418–2446) with:

```python
@app.route('/api/notification-channels/<int:channel_id>/test', methods=['POST'])
@login_required
def test_notification_channel(channel_id):
    """Send a test notification to a channel."""
    from models import UserNotificationChannel
    from services.notification_service import SlackClient, Notification, NotificationPriority

    channel = UserNotificationChannel.query.get_or_404(channel_id)
    if channel.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403

    if not channel.is_active:
        return jsonify({'success': False, 'error': 'Channel is disabled'}), 400

    notification = Notification(
        title='Test Notification from DevOps Agent',
        message='Your Slack integration is working correctly. You will receive alerts here for incidents, cost findings, security scans, and infrastructure analysis.',
        priority=NotificationPriority.NORMAL,
        fields={'Source': 'DevOps Agent', 'Type': 'Connection Test'},
    )

    try:
        if channel.channel_type == 'slack':
            success = SlackClient(webhook_url=channel.webhook_url).send_webhook(notification)
        else:
            return jsonify({'success': False, 'error': f"Channel type '{channel.channel_type}' not supported for test"}), 400
        return jsonify({'success': success, 'message': 'Test notification sent' if success else 'Failed to send — check webhook URL'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

```
pytest tests/ -q --tb=short
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "fix: remove broken in-memory configure_slack, rewrite test endpoint to use stateless SlackClient"
```

---

## Task 7: Manual end-to-end smoke test

- [ ] **Step 1: Set up a real Slack webhook**

Create an Incoming Webhook in any Slack workspace (Apps → Incoming Webhooks → Add New Webhook to Workspace). Copy the URL.

- [ ] **Step 2: Add channel via settings UI**

Start app: `python app.py`

Navigate to `/settings`, scroll to "Notification Channels", add a Slack channel with the webhook URL.

- [ ] **Step 3: Test the connection**

Click "Test" on the newly added channel. Confirm the test message appears in Slack within 5 seconds.

- [ ] **Step 4: Trigger an incident**

In chat, ask: "Create a test incident for high CPU on web-01". Confirm a Slack message appears for the created incident.

- [ ] **Step 5: Confirm all 4 event types are wired**

Manually check each trigger:
- Incident: seen in step 4
- Security: from settings or chat, trigger `scan_aws_security()` — if credentials configured, confirm Slack message on critical findings
- Cost: trigger infrastructure sync — if new recs generated, confirm Slack message
- Changes: navigate to `/optimization/prevention`, click "Run Analysis" — if new findings, confirm Slack message
