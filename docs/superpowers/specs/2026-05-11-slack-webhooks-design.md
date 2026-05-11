# Slack Webhook Notifications — Design Spec

**Date:** 2026-05-11  
**Status:** Approved

---

## Problem

`UserNotificationChannel` model, API endpoints, settings UI, and `NotificationService` (Slack Block Kit) already exist but are not connected. Two bugs exist in `app.py`: `configure_slack()` is called without `user_id`, and `send()` is called without `user_id`. The service uses an in-memory singleton that breaks across gunicorn workers and on server restart. No trigger points in the codebase actually call the notification service.

---

## Design

### Approach: Stateless helper (Option B)

Replace the broken in-memory singleton pattern with stateless public functions. Each function:
1. Queries `UserNotificationChannel` from DB for the user, filtered by event boolean
2. Builds a `Notification` object with Slack Block Kit blocks and a "View in DevOps Agent" action button
3. Sends to all matching active channels via `SlackClient(webhook_url).send_webhook()`
4. Fires in a `daemon` thread so it never blocks the calling request

---

## Files to Modify

### 1. `services/notification_service.py`

Add four public notify functions and a private `_send_async` helper:

```python
def _send_async(flask_app, user_id: int, event_type: str, notification: Notification) -> None:
    """Query DB and send to all matching channels. Runs in daemon thread."""
    def _run():
        with flask_app.app_context():
            from models import UserNotificationChannel
            flag_col = {
                'incidents': UserNotificationChannel.notify_incidents,
                'cost':      UserNotificationChannel.notify_cost,
                'security':  UserNotificationChannel.notify_security,
                'changes':   UserNotificationChannel.notify_changes,
            }.get(event_type)
            if flag_col is None:
                return
            channels = UserNotificationChannel.query.filter_by(
                user_id=user_id, is_active=True
            ).filter(flag_col == True).all()
            for ch in channels:
                if ch.channel_type == 'slack':
                    SlackClient(webhook_url=ch.webhook_url).send_webhook(notification)
    threading.Thread(target=_run, daemon=True).start()

def notify_incident(flask_app, user_id: int, incident: dict, event: str, base_url: str) -> None:
    """Fire Slack notification for incident lifecycle events."""
    # builds Notification with incident fields + "View Incident" button

def notify_security(flask_app, user_id: int, results: dict, base_url: str) -> None:
    """Fire Slack notification for security scan results (skip if 0 critical+high)."""

def notify_cost(flask_app, user_id: int, new_count: int, total_savings: float, base_url: str) -> None:
    """Fire Slack notification for new cost recommendations (skip if new_count == 0)."""

def notify_changes(flask_app, user_id: int, rec_count: int, base_url: str) -> None:
    """Fire Slack notification for new proactive recommendations (skip if rec_count == 0)."""
```

### 2. `services/incident_response.py`

After `db.session.commit()` in three places:
- `create_incident()` → `notify_incident(app, user_id, incident.to_dict(), 'created', BASE_URL)`
- `acknowledge_incident()` → `notify_incident(app, user_id, incident.to_dict(), 'acknowledged', BASE_URL)`
- `resolve_incident()` → `notify_incident(app, user_id, incident.to_dict(), 'resolved', BASE_URL)`

`BASE_URL = os.environ.get('BASE_URL', 'https://devopsagent.io')` at module level.

### 3. `services/security_scanner.py`

After `db.session.commit()` at end of `scan_aws_security()`:
```python
if results['critical'] > 0 or results['high'] > 0:
    notify_security(flask_app, user_id, results, BASE_URL)
```

Only fires if there are critical or high findings — no spam on clean scans.

### 4. `services/infrastructure_sync.py`

Track new cost recommendation count in the sync loop. After `db.session.commit()`:
```python
if new_cost_recs > 0:
    notify_cost(flask_app, user_id, new_cost_recs, total_new_savings, BASE_URL)
```

### 5. `routes/optimization.py`

After `ProactiveRecommendation` records are saved in the analyze endpoint:
```python
if new_count > 0:
    notify_changes(current_app._get_current_object(), current_user.id, new_count, BASE_URL)
```

### 6. `app.py` (bug fixes)

- **Remove** the broken `try: svc.configure_slack(...)` block in `notification_channels()` POST (lines 2372–2381) — it's dead code with the new approach
- **Rewrite** `test_notification_channel()` to use `SlackClient(webhook_url=channel.webhook_url).send_webhook(notification)` directly instead of the broken singleton

---

## What Does NOT Change

- `UserNotificationChannel` model — already correct
- Settings UI — already calls all required endpoints
- `GET/PUT/DELETE /api/notification-channels` routes — already correct
- `NotificationService` class, `Notification` dataclass, `to_slack_blocks()` — reused as-is
- All tool, safety, agent, billing, and auth code

---

## Action Buttons

Each notification includes a contextual action button:
- Incidents → `{BASE_URL}/incidents/{id}` labeled "View Incident"
- Security → `{BASE_URL}/optimization` labeled "View Findings"
- Cost → `{BASE_URL}/optimization` labeled "View Recommendations"
- Changes → `{BASE_URL}/optimization/prevention` labeled "View Analysis"

---

## Error Handling

- `SlackClient.send_webhook()` already wraps `requests.post` in `try/except requests.RequestException` and logs errors — no change needed
- Daemon threads are fire-and-forget; failures are logged but never surface to the user
- `UserNotificationChannel` DB query failure inside thread is caught by the `with flask_app.app_context()` block logging

---

## Security

- SSRF protection already implemented in the POST endpoint (private IP check before saving webhook URL)
- Webhook URLs are already validated as HTTPS-only before storage
- No new attack surface — notifications only fire server-side from trusted trigger points

---

## Notification Noise Reduction

- Security: only fires if `critical > 0 or high > 0`
- Cost: only fires if new recommendations were created (not on re-scan of existing)
- Changes: only fires if new proactive recommendations found
- Incidents: always fires (create/acknowledge/resolve are user-initiated or high-signal events)
