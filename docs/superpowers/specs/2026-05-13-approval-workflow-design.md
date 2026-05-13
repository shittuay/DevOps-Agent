# Approval Workflow Design

**Date:** 2026-05-13  
**Scope:** Gate high-risk agent tool calls behind an approver sign-off before execution  
**Status:** Approved, ready for implementation

---

## Problem

When a user asks the DevOps Agent to run a destructive or high-risk operation (terminate EC2 instance, delete S3 bucket, drop RDS database, etc.), it executes immediately after a client-side confirmation prompt. There is no second human in the loop. A misclick, a confused request, or a junior engineer working in the wrong environment can cause irreversible damage.

## Solution

Introduce a two-phase execution model for high-risk tool calls:

1. **Request phase** — agent intercepts the tool call, saves it as a pending `ApprovalRequest`, notifies approvers, and ends the stream with a "waiting for approval" state.
2. **Execution phase** — an approver reviews and approves; the tool executes automatically and the result is appended to the original conversation.

Users with `role='approver'` or `role='admin'` are exempt and self-approve (their tool calls execute immediately, unchanged).

---

## Data Model

### `ApprovalRequest` (new table: `approval_requests`)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `requester_id` | FK → users.id | Who triggered the tool call |
| `conversation_id` | FK → conversations.id | Original conversation context |
| `tool_name` | String(100) | e.g. `terminate_ec2_instance` |
| `tool_input` | JSON | Exact kwargs to re-run on approval |
| `risk_level` | String(20) | `'high'` or `'critical'` |
| `risk_reason` | Text | Human-readable: "This will permanently terminate i-0abc123 (prod-web-01)" |
| `status` | String(20) | `pending` → `approved`/`rejected` → `executed`/`expired` |
| `expires_at` | DateTime | `created_at + 24h`; stale requests auto-expire |
| `approver_id` | FK → users.id | Nullable until decided |
| `decided_at` | DateTime | Nullable until decided |
| `approver_note` | Text | Optional note from approver |
| `execution_result` | JSON | Stored after auto-run on approval |
| `executed_at` | DateTime | Nullable until executed |
| `created_at` | DateTime | |

**No changes to existing models.** Auto-migration at app startup will add the new table via `db.create_all()`.

---

## Agent Loop Changes (`src/agent/core.py`)

### Current flow
```
LLM returns tool_call
  → SafetyValidator.validate_tool_call()
  → if high_risk: prompt user for confirmation
  → execute tool
```

### New flow
```
LLM returns tool_call
  → SafetyValidator.validate_tool_call()
  → if high_risk AND current_user.role NOT IN ('approver', 'admin'):
      → ApprovalService.create_request(tool_name, tool_input, risk_level, risk_reason, user_id, conversation_id)
      → yield SSE event: { type: "approval_required", approval_id, tool_name, risk_level, risk_reason }
      → return early (do not execute)
  → else (approver/admin OR low/medium risk):
      → execute tool (unchanged)
```

### SSE event shape
```json
{
  "type": "approval_required",
  "approval_id": 42,
  "tool_name": "terminate_ec2_instance",
  "risk_level": "critical",
  "risk_reason": "This will permanently terminate i-0abc123 (prod-web-01)"
}
```

The stream ends after this event. The tool input stored in `ApprovalRequest.tool_input` is the exact payload that will re-run on approval — no re-prompting.

**Note on `risk_reason`:** `SafetyValidator` returns a risk level only, not a prose description. The agent loop generates `risk_reason` at intercept time by formatting the tool name and key input fields (e.g. `instance_id`, `bucket_name`) into a human-readable string.

---

## Approval Service (`services/approval_service.py`)

New file. Five functions:

### `create_request(tool_name, tool_input, risk_level, risk_reason, requester_id, conversation_id) → ApprovalRequest`
- Creates and commits `ApprovalRequest` with `status='pending'` and `expires_at = now + 24h`
- Calls `notify_approvers(request)` after commit
- Returns the saved request

### `notify_approvers(request)`
- Queries `User.query.filter(User.role.in_(['approver', 'admin']))`
- Creates one `AppNotification` per approver (reuses existing model): `"[username] requested approval for [tool_name]"`
- Sends one Brevo transactional email per approver with:
  - Subject: `"Approval required: [tool_name]"`
  - Body: requester name, tool name, risk reason, direct link to `/approvals`

### `approve(approval_id, approver_id, note=None) → dict`
- Validates `approver.role in ('approver', 'admin')` and `approver_id != request.requester_id`
- Sets `status='approved'`, `approver_id`, `decided_at`, `approver_note`
- Calls `_execute_tool(request)` immediately
- On success: sets `status='executed'`, stores `execution_result`, sets `executed_at`
- Appends result as a new `ChatMessage` to the original conversation (`role='assistant'`)
- Notifies requester via `AppNotification` + Brevo email (result summary)
- Returns `{'success': True, 'result': execution_result}`

### `reject(approval_id, approver_id, note=None) → dict`
- Validates approver role; sets `status='rejected'`, stores note
- Notifies requester via `AppNotification` + Brevo email (rejection + note)
- Returns `{'success': True}`

### `get_pending_for_approver() → list[ApprovalRequest]`
- Returns all requests where `status='pending'` and `expires_at > now`
- Calls `_expire_stale()` first (lazy expiry — no background job needed)
- Ordered by `created_at DESC`

### `_execute_tool(request) → dict` (private)
- Looks up the tool handler by `request.tool_name` from the registered agent tools
- Calls handler with `**request.tool_input`
- Returns the result dict

### `_expire_stale()` (private)
- Sets `status='expired'` on all requests where `status='pending'` and `expires_at <= now`

---

## Routes (`routes/approvals.py`)

New blueprint, registered at no prefix (routes use `/approvals` and `/api/approvals`):

| Method | Path | Access | Description |
|---|---|---|---|
| `GET` | `/approvals` | approver/admin | Approver queue page (HTML) |
| `GET` | `/api/approvals/pending` | approver/admin | List pending requests (JSON) |
| `GET` | `/api/approvals/count` | approver/admin | Count of pending (for nav badge) |
| `GET` | `/api/approvals/<id>/status` | requester OR approver/admin | Poll status of one request |
| `POST` | `/api/approvals/<id>/approve` | approver/admin | Approve + auto-execute |
| `POST` | `/api/approvals/<id>/reject` | approver/admin | Reject with optional note |

**Access rules:**
- `/api/approvals/pending`, `/approve`, `/reject` → 403 if `current_user.role not in ('approver', 'admin')`
- `/api/approvals/<id>/status` → 403 unless `current_user.id == request.requester_id` OR approver/admin
- A requester cannot approve their own request → 403

---

## Frontend

### Chat UI (`templates/index.html`)

**On `approval_required` SSE event:**
Replace the in-progress message bubble with a pending approval card:
```
┌─────────────────────────────────────────────────┐
│ ⏳  Approval Required                            │
│ terminate_ec2_instance                           │
│ This will permanently terminate i-0abc123        │
│ (prod-web-01)                                    │
│                                                  │
│ Waiting for an approver...  ●●●                  │
└─────────────────────────────────────────────────┘
```

JS polls `/api/approvals/<id>/status` every 4 seconds.

**On status change:**
- `executed` → replace card with formatted tool result (same style as normal tool output)
- `rejected` → replace card with: `Request rejected by [approver]. Note: [note if any]`
- `expired` → replace card with: `Request expired — no approver acted within 24 hours`

### Approver Queue (`templates/approvals/queue.html`)

Table in terminal aesthetic, styled consistent with the rest of the app:

```
PENDING APPROVALS  (3)

 Requester  Tool                     Risk      Age        Actions
 ─────────────────────────────────────────────────────────────────
 alice      terminate_ec2_instance   CRITICAL  2m ago     [Approve] [Reject]
 bob        delete_s3_bucket         HIGH      14m ago    [Approve] [Reject]
 carol      terraform_destroy        HIGH      1h ago     [Approve] [Reject]
```

Approve/Reject open an inline note field before submitting. Table refreshes on action.

### Nav badge

On pages where user is approver/admin, the existing bell icon (`🔔` in `base.html`) gets a red count badge populated by `/api/approvals/count`. Fetched once on page load.

---

## What Is Not In Scope

- Medium-risk tool calls (`update_*`, `restart_*`, IAM changes) — these continue to use the existing client-side confirmation prompt unchanged
- Approval delegation or escalation
- Approval expiry notifications (email reminder before 24h expires)
- Multi-approver quorum (one approver is sufficient)
- SSO or org-level approver assignment

---

## File Checklist

| File | Change |
|---|---|
| `models.py` | Add `ApprovalRequest` class |
| `src/agent/core.py` | Intercept high-risk tool calls; yield `approval_required` SSE event |
| `services/approval_service.py` | New file — create, notify, approve, reject, execute |
| `routes/approvals.py` | New file — queue page + 5 API endpoints |
| `app.py` | Import and register `approvals_bp` |
| `templates/approvals/queue.html` | New file — approver queue page |
| `templates/index.html` | Handle `approval_required` SSE event; polling logic; result/rejection display |
| `templates/base.html` | Nav badge on bell icon for approvers |
