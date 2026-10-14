# DevOps Agent API Reference

REST API documentation for integrating with DevOps Agent.

---

## Base URL

```
http://localhost:5000/api
```

---

## Authentication

All API requests require authentication via API key or session cookie.

### API Key Authentication

Include the API key in the Authorization header:

```
Authorization: Bearer YOUR_API_KEY
```

### Session Authentication

For browser-based requests, the session cookie from login is used automatically.

---

## Rate Limiting

Default rate limits:
- 100 requests per minute per API key
- 10 requests per minute for login attempts

Rate limit headers in responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640000000
```

---

## Response Format

All responses are JSON:

```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

Error responses:

```json
{
  "success": false,
  "error": "Error message",
  "code": "ERROR_CODE"
}
```

---

## Endpoints

### Chat

#### Send Message

```
POST /api/chat
```

Send a message to the AI agent.

**Request:**
```json
{
  "message": "List all EC2 instances"
}
```

**Response:**
```json
{
  "response": "Here are your EC2 instances...",
  "credits_remaining": 950,
  "conversation_id": "conv_123"
}
```

---

### Conversations

#### List Conversations

```
GET /api/conversations
```

Get all conversations for the current user.

**Response:**
```json
{
  "conversations": [
    {
      "id": "conv_123",
      "title": "AWS Instance Management",
      "preview": "List all EC2 instances...",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T11:45:00Z"
    }
  ]
}
```

#### Get Conversation

```
GET /api/conversations/:id
```

Get a specific conversation with messages.

**Response:**
```json
{
  "id": "conv_123",
  "title": "AWS Instance Management",
  "messages": [
    {
      "role": "user",
      "content": "List all EC2 instances",
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Here are your EC2 instances...",
      "timestamp": "2024-01-15T10:30:05Z"
    }
  ]
}
```

#### Create Conversation

```
POST /api/conversations/new
```

Start a new conversation.

**Response:**
```json
{
  "success": true,
  "conversation_id": "conv_456"
}
```

#### Delete Conversation

```
DELETE /api/conversations/:id
```

Delete a conversation.

**Response:**
```json
{
  "success": true
}
```

---

### Tools

#### List Tools

```
GET /api/tools
```

Get all available tools organized by category.

**Response:**
```json
{
  "categories": {
    "AWS": [
      "get_ec2_instances",
      "manage_ec2_instance",
      "list_s3_buckets"
    ],
    "Kubernetes": [
      "get_pods",
      "describe_pod",
      "scale_deployment"
    ]
  },
  "total": 173
}
```

---

### Statistics

#### Get Session Stats

```
GET /api/stats
```

Get statistics for the current session.

**Response:**
```json
{
  "total_messages": 24,
  "user_messages": 12,
  "assistant_messages": 12
}
```

---

### Playbooks

#### List Playbooks

```
GET /api/playbooks
```

Get all playbooks.

#### Get Playbook

```
GET /api/playbooks/:id
```

Get playbook details.

#### Create Playbook

```
POST /api/playbooks
```

Create a new playbook.

**Request:**
```json
{
  "name": "High CPU Response",
  "description": "Automated response to high CPU alerts",
  "trigger_conditions": {
    "severity": "critical",
    "metric": "cpu_usage"
  },
  "actions": [
    {
      "type": "scale_up",
      "target": "web-servers"
    }
  ],
  "auto_execute": false,
  "require_approval": true
}
```

#### Execute Playbook

```
POST /api/playbooks/:id/execute
```

Manually execute a playbook.

---

### Optimization

#### List Recommendations

```
GET /api/optimization/recommendations
```

Get optimization recommendations.

**Query Parameters:**
- `type`: Filter by type (cpu, memory, cost)
- `priority`: Filter by priority
- `status`: Filter by status

#### Get Recommendation

```
GET /api/optimization/recommendations/:id
```

Get recommendation details.

#### Dismiss Recommendation

```
POST /api/optimization/recommendations/:id/dismiss
```

Dismiss a recommendation.

**Request:**
```json
{
  "reason": "Not applicable to our use case"
}
```

#### Mark Implemented

```
POST /api/optimization/recommendations/:id/implement
```

Mark a recommendation as implemented.

---

### Scaling

#### List Predictions

```
GET /api/scaling/predictions
```

Get scaling predictions.

#### Get Prediction

```
GET /api/scaling/predictions/:id
```

Get prediction details.

#### List Patterns

```
GET /api/scaling/patterns
```

Get detected usage patterns.

---

### Drift Detection

#### List Baselines

```
GET /api/drift/baselines
```

Get infrastructure baselines.

#### Create Baseline

```
POST /api/drift/baselines
```

Create a new baseline.

**Request:**
```json
{
  "name": "Production Baseline",
  "resource_type": "ec2",
  "configuration": { ... }
}
```

#### Run Scan

```
POST /api/drift/scan
```

Run a drift scan.

**Request:**
```json
{
  "baseline_ids": ["baseline_123"]
}
```

#### List Reports

```
GET /api/drift/reports
```

Get drift reports.

---

### Analytics

#### Cost Analytics

```
GET /api/analytics/costs
```

Get cost analytics.

**Query Parameters:**
- `start_date`: Start date (YYYY-MM-DD)
- `end_date`: End date (YYYY-MM-DD)
- `group_by`: Group by (day, service, resource)

#### Performance Metrics

```
GET /api/analytics/performance
```

Get performance metrics.

**Query Parameters:**
- `metric`: Metric type (cpu, memory, disk, network)
- `resource_id`: Specific resource
- `period`: Time period (1h, 24h, 7d, 30d)

#### Export Data

```
GET /api/analytics/export
```

Export analytics data.

**Query Parameters:**
- `format`: Export format (csv, json)
- `type`: Data type (costs, performance, incidents)

---

### Notifications

#### List Channels

```
GET /api/notifications/channels
```

Get notification channels.

#### Create Channel

```
POST /api/notifications/channels
```

Create a notification channel.

**Request:**
```json
{
  "type": "slack",
  "name": "DevOps Alerts",
  "config": {
    "webhook_url": "https://hooks.slack.com/..."
  }
}
```

#### Send Notification

```
POST /api/notifications/send
```

Send a notification.

**Request:**
```json
{
  "channel_id": "channel_123",
  "message": "Deployment completed",
  "priority": "normal"
}
```

#### Test Channel

```
POST /api/notifications/channels/:id/test
```

Test a notification channel.

---

### Webhooks

#### List Events

```
GET /api/webhooks/events
```

Get received webhook events.

#### Get Event

```
GET /api/webhooks/events/:id
```

Get event details.

---

### API Keys

#### List Keys

```
GET /api/keys
```

Get API keys for the current user.

#### Create Key

```
POST /api/keys
```

Create a new API key.

**Request:**
```json
{
  "name": "CI/CD Integration",
  "scopes": ["read:resources", "write:resources"],
  "rate_limit": 100,
  "expires_at": "2024-12-31T23:59:59Z"
}
```

**Response:**
```json
{
  "id": "key_123",
  "key": "sk_live_abc123...",
  "name": "CI/CD Integration",
  "scopes": ["read:resources", "write:resources"]
}
```

Note: The full key is only shown once at creation.

#### Revoke Key

```
DELETE /api/keys/:id
```

Revoke an API key.

---

### Compliance

#### List Frameworks

```
GET /api/compliance/frameworks
```

Get compliance frameworks.

#### Run Check

```
POST /api/compliance/check
```

Run a compliance check.

**Request:**
```json
{
  "framework_ids": ["soc2", "iso27001"]
}
```

#### List Audit Logs

```
GET /api/compliance/audit
```

Get audit logs.

**Query Parameters:**
- `action_type`: Filter by action type
- `resource_type`: Filter by resource type
- `user_id`: Filter by user
- `start_date`: Start date
- `end_date`: End date

---

### Organizations

#### List Organizations

```
GET /api/organizations
```

Get user's organizations.

#### Create Organization

```
POST /api/organizations
```

Create an organization.

**Request:**
```json
{
  "name": "Acme Corp",
  "description": "Main organization"
}
```

#### Get Organization

```
GET /api/organizations/:id
```

Get organization details.

#### Update Organization

```
PUT /api/organizations/:id
```

Update organization settings.

#### List Members

```
GET /api/organizations/:id/members
```

Get organization members.

#### Invite Member

```
POST /api/organizations/:id/invite
```

Invite a user to the organization.

**Request:**
```json
{
  "email": "user@example.com",
  "role": "member"
}
```

---

### Teams

#### List Teams

```
GET /api/teams
```

Get teams for the current organization.

#### Create Team

```
POST /api/teams
```

Create a team.

**Request:**
```json
{
  "name": "Backend Team",
  "organization_id": "org_123"
}
```

---

### User

#### Get Profile

```
GET /api/user/profile
```

Get current user profile.

#### Update Profile

```
PUT /api/user/profile
```

Update user profile.

**Request:**
```json
{
  "full_name": "John Doe",
  "bio": "DevOps Engineer"
}
```

#### Get Credits

```
GET /api/user/credits
```

Get remaining credits.

---

### Admin

*Requires admin role*

#### List Users

```
GET /api/admin/users
```

Get all users.

**Query Parameters:**
- `search`: Search by email/username
- `role`: Filter by role
- `limit`: Maximum results
- `offset`: Pagination offset

#### Get User

```
GET /api/admin/users/:id
```

Get user details.

#### Update User Role

```
PUT /api/admin/users/:id/role
```

Change user role.

**Request:**
```json
{
  "role": "admin"
}
```

#### Lock User

```
POST /api/admin/users/:id/lock
```

Lock user account.

#### Unlock User

```
POST /api/admin/users/:id/unlock
```

Unlock user account.

#### Delete User

```
DELETE /api/admin/users/:id
```

Delete user account.

#### System Stats

```
GET /api/admin/stats
```

Get system statistics.

---

## Webhook Endpoints

### GitHub Webhook

```
POST /webhooks/github
```

Receive GitHub events.

**Headers:**
- `X-Hub-Signature-256`: HMAC signature
- `X-GitHub-Event`: Event type

### GitLab Webhook

```
POST /webhooks/gitlab
```

Receive GitLab events.

**Headers:**
- `X-Gitlab-Token`: Secret token
- `X-Gitlab-Event`: Event type

### Bitbucket Webhook

```
POST /webhooks/bitbucket
```

Receive Bitbucket events.

**Headers:**
- `X-Event-Key`: Event type

### Alert Webhooks

```
POST /webhooks/alerts/prometheus
POST /webhooks/alerts/datadog
POST /webhooks/alerts/pagerduty
POST /webhooks/alerts/opsgenie
POST /webhooks/alerts/grafana
```

Receive alerts from monitoring systems.

---

## Error Codes

| Code | Description |
|------|-------------|
| `UNAUTHORIZED` | Invalid or missing authentication |
| `FORBIDDEN` | Insufficient permissions |
| `NOT_FOUND` | Resource not found |
| `RATE_LIMITED` | Rate limit exceeded |
| `VALIDATION_ERROR` | Invalid request data |
| `INSUFFICIENT_CREDITS` | Not enough credits |
| `INTERNAL_ERROR` | Server error |

---

## SDKs

### Python

```python
from devops_agent import Client

client = Client(api_key="YOUR_API_KEY")

# Send a chat message
response = client.chat("List all EC2 instances")
print(response.text)

# Get incidents
incidents = client.incidents.list(status="unacknowledged")
for incident in incidents:
    print(f"{incident.title} - {incident.severity}")
```

### JavaScript

```javascript
import { DevOpsAgent } from 'devops-agent';

const client = new DevOpsAgent({ apiKey: 'YOUR_API_KEY' });

// Send a chat message
const response = await client.chat('List all EC2 instances');
console.log(response.text);

// Get incidents
const incidents = await client.incidents.list({ status: 'unacknowledged' });
incidents.forEach(i => console.log(`${i.title} - ${i.severity}`));
```

---

*For web interface usage, see [WEB_APPLICATION_GUIDE.md](WEB_APPLICATION_GUIDE.md)*
