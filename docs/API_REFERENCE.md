# DevOps Agent API Reference

DevOps Agent has three public interfaces:

| Interface | Base URL | Best for |
|-----------|----------|----------|
| [Developer API](#developer-api) | `https://devopsagent.io/api-gateway/v1` | Running the agent or a single tool from your own code |
| [Programmatic API](#programmatic-api) | `https://devopsagent.io/api/v1` | Managing conversations, resources, keys and your account; has an OpenAPI spec |
| [Claude.ai connector (MCP)](#claudeai-connector-mcp) | `https://devopsagent.io/mcp` | Using DevOps Agent tools from Claude |


The other `/api/...` endpoints the web app calls (chat, dashboard, settings) use your browser
session and CSRF protection. They are internal and can change without notice; don't build on them.

---

## API keys

Create keys in the app at **`/api-gateway/keys`** (or with `POST /api/v1/api-keys`). The key is
shown once; store it somewhere safe. Each key has:

- **Scopes:** `read`, `write`, `delete`, `admin`
- **A daily request limit** (default 1,000 requests a day). Responses carry `X-RateLimit-Limit`
  and `X-RateLimit-Remaining`; going over returns `429` with `Retry-After`.
- An optional expiry. Keys can be revoked or rotated at any time.

Every call runs as the key's owner, against that user's own connected accounts, and spends that
user's credits.

---

## Developer API

Base URL: `https://devopsagent.io/api-gateway/v1`

**Authentication:** send the key in the `X-API-Key` header.

```bash
curl -H "X-API-Key: $DEVOPS_AGENT_KEY" https://devopsagent.io/api-gateway/v1/health
```

(`?api_key=` in the query string also works, but headers don't end up in logs, so prefer them.)

`/agent`, `/agent/stream` and `/execute` need a **Professional or Business** plan and one credit
per call. Other plans get `403`; no credits left gets `402 insufficient_credits`.

### `POST /agent`

Run a chat turn. The agent picks and runs tools exactly as it does in the app.

```json
{ "message": "List all EC2 instances in us-east-1", "conversation_id": "optional" }
```

Response:

```json
{
  "response": "You have 3 running instances...",
  "tools_used": ["get_ec2_instances"],
  "credits_remaining": 942,
  "conversation_id": "..."
}
```

Pass the returned `conversation_id` back to continue the same conversation.

### `POST /agent/stream`

Same body; replies as Server-Sent Events (`text/event-stream`):

```
data: {"type": "chunk", "content": "..."}
data: {"type": "tool",  "name": "get_ec2_instances"}
data: {"type": "done",  "tools_used": [...], "credits_remaining": 941, "conversation_id": "..."}
data: {"type": "error", "message": "..."}
```

### `POST /execute`

Run one tool directly, with no AI in between.

```json
{ "tool": "get_ec2_instances", "params": { "region": "us-east-1" } }
```

Medium- and high-risk tools (deletes, terminations, stops, IAM changes and so on) follow the same
[approval rules](#risky-tools-and-approvals) as chat.

### Read endpoints

| Method and path | Returns |
|-----------------|---------|
| `GET /health` | Service status (no key needed) |
| `GET /tools?provider=aws&search=ec2` | Tool catalog with descriptions and input schemas (`total` = 749 when everything is enabled) |
| `GET /resources` | Your synced cloud resources |
| `GET /resources/<id>` | One resource |
| `GET /analytics/costs?period=30d` | Cost analytics from your cloud account |
| `GET /conversations?limit=20&offset=0` | Your conversations (limit up to 100) |

### Outgoing webhooks

Add endpoints under **Developer API → Webhooks**. Each one subscribes to any of:

| Event | Sent when |
|-------|-----------|
| `resource.created` | The agent created a resource in your account (chat, or an approved request) |
| `resource.deleted` | The agent deleted or terminated a resource |
| `cost.threshold` | One of your budget alerts (Settings → Budgets) went over its threshold |

Each delivery is a `POST` with a JSON body such as
`{"event": "resource.deleted", "timestamp": "...", "resource": {"type": "s3", "id": "logs-1", "name": "logs-1", "provider": "aws"}, "change_id": 42, "tool": "delete_s3_bucket"}`
and these headers:

- `X-DevOps-Agent-Event`: the event name.
- `X-DevOps-Agent-Delivery`: the delivery id.
- `X-DevOps-Agent-Signature`: `sha256=` + the HMAC-SHA256 of the raw request body, keyed with
  the endpoint's secret. Verify it against the body bytes you received.

Endpoints on private or internal addresses are refused. Calls made directly through `/execute`,
`/api/v1/tools/execute` or the MCP connector without an approval step don't send events yet.

---

## Programmatic API

Base URL: `https://devopsagent.io/api/v1`

- **OpenAPI spec:** `GET /api/v1/openapi.json`
- **Interactive docs:** `/api/v1/docs`

**Authentication:** `X-API-Key: <key>` or `Authorization: Bearer <key>`. Endpoints check the
key's scope.

| Area | Endpoints |
|------|-----------|
| Auth | `GET /auth/validate`, `GET /auth/me`, `GET /auth/usage` |
| API keys | `GET`/`POST /api-keys`; `GET`/`PATCH`/`DELETE /api-keys/<id>`; `POST /api-keys/<id>/rotate` |
| Conversations | `GET`/`POST /conversations`; `GET`/`DELETE /conversations/<id>`; `POST /conversations/<id>/messages` |
| Chat streaming | `POST /chat/stream` |
| Resources | `GET /resources`, `GET /resources/<id>`, `POST /resources/sync`, `GET /resources/stats`, `GET /resources/alerts`, `GET /resources/security` |
| Tools | `POST /tools/execute` |
| Account | `GET`/`PATCH /users/me`; `GET`/`PATCH /users/me/preferences`; `GET /users/me/subscription`; `GET /users/me/usage` |
| Health | `GET /health`, `GET /health/detailed`, `GET /status` |

### `POST /tools/execute` (scope `write`)

```json
{ "tool": "get_pods", "params": { "namespace": "default" } }
```

Medium- and high-risk tools follow the same [approval rules](#risky-tools-and-approvals) as chat.

---

## Risky tools and approvals

Both `POST /api-gateway/v1/execute` and `POST /api/v1/tools/execute` handle medium- and
high-risk tools the same way the chat and the Claude.ai connector do.

1. The first call doesn't run anything. It files an approval request and returns **`202`**:

   ```json
   {
     "status": "pending_approval",
     "approval_id": 123,
     "tool": "manage_ec2_instance",
     "risk_level": "medium",
     "can_confirm": true,
     "expires_at": "2026-10-15T08:00:00Z",
     "message": "..."
   }
   ```

2. **If `can_confirm` is `true`** (you aren't in an organization, you're the only owner or admin
   of yours, or it's your own high-risk call as an Approver or Admin), send the **same** call
   again with `"approval_id": 123` added. It runs and returns `200` with `"status": "executed"`
   and the `result`.
3. **If `can_confirm` is `false`**, an owner, admin or approver of your organization approves it
   on `/approvals`. Re-sending the call with the `approval_id` returns `202` while it waits and
   `200` with the result once it has run.

A request expires after 24 hours (`409` with `"status": "expired"`), and a rejected one returns
`409` with `"status": "rejected"`; send the call again to file a new one. An `approval_id` only
works for the exact tool and params it was issued for (`400` otherwise) and only for its own
user (`404`). Approvers and Admins run their own medium-risk calls directly.

The older `confirm_token` round trip and the `"confirm": true` flag no longer skip this.

---

## Claude.ai connector (MCP)

Add `https://devopsagent.io/mcp` as a custom connector in Claude. Claude opens a DevOps Agent
sign-in page; sign in with your DevOps Agent account (any email, it doesn't have to match your
Claude account) and, if you use 2FA, your code. 704 tools from 13 modules are exposed.

Other MCP clients can use the same endpoint with OAuth (discovery at
`/.well-known/oauth-authorization-server`) or an API key as a Bearer token. `GET /mcp/health`
reports the server status.

Risky tools called through the connector follow the same approval rules as chat (see
[Approvals](WEB_APPLICATION_GUIDE.md#approvals-and-change-requests)).

---

## Errors

| Status | Meaning |
|--------|---------|
| `400` | Missing or invalid field |
| `401` | Missing or invalid API key |
| `402` | Out of credits |
| `202` | A risky tool is waiting for approval (see [above](#risky-tools-and-approvals)) |
| `403` | Plan doesn't include this endpoint, the key lacks the scope, or the tool is blocked |
| `409` | The approval request was rejected or has expired |
| `404` | Unknown tool or resource |
| `429` | Daily rate limit reached |
| `503` | The safety check is unavailable, so nothing was run; retry later |
| `5xx` | Server error; retry later |

Error bodies are JSON with an `error` field.
