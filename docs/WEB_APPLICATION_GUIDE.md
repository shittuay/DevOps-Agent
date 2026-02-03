# DevOps Agent Web Application Guide

A comprehensive guide to using the DevOps Agent web interface and all its features.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard Overview](#dashboard-overview)
3. [Chat Interface](#chat-interface)
4. [Cloud Configuration](#cloud-configuration)
5. [Monitoring & Alerts](#monitoring--alerts)
6. [Incident Management](#incident-management)
7. [Root Cause Analysis](#root-cause-analysis)
8. [Optimization](#optimization)
9. [Predictive Scaling](#predictive-scaling)
10. [Drift Detection](#drift-detection)
11. [AI Infrastructure](#ai-infrastructure)
12. [Analytics & Reporting](#analytics--reporting)
13. [Notifications](#notifications)
14. [Webhooks](#webhooks)
15. [ChatOps](#chatops)
16. [API Gateway](#api-gateway)
17. [Compliance](#compliance)
18. [Organizations & Teams](#organizations--teams)
19. [Billing](#billing)
20. [Administration](#administration)
21. [Profile & Settings](#profile--settings)
22. [Security](#security)
23. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the Application

Start the server and navigate to `http://localhost:5000`:

```bash
python app.py
```

### Creating an Account

1. Click **Sign Up** on the login page
2. Fill in your details:
   - **Email**: Valid email address (required for notifications)
   - **Username**: 3-20 characters (alphanumeric and underscore only)
   - **Password**: Minimum 8 characters with uppercase, lowercase, and numbers
3. Click **Create Account**

### Logging In

1. Enter your email or username
2. Enter your password
3. Click **Sign In**

**Security Features:**
- Account locks after 5 failed attempts (15-minute cooldown)
- Login IP addresses are recorded
- Session timeout after 24 hours of inactivity

### First-Time Setup

After logging in:

1. **Configure API Key** (`/setup`): Enter your Anthropic API key
2. **Set Up Cloud Credentials** (`/settings`): Add AWS, Azure, or GCP credentials
3. **Explore Features**: Use the navigation to explore available tools

---

## Dashboard Overview

The dashboard (`/dashboard`) provides a real-time view of your infrastructure.

### Key Metrics

| Metric | Description |
|--------|-------------|
| Resource Health | Status of all monitored resources |
| Active Alerts | Number of currently firing alerts |
| Open Incidents | Unresolved incident count |
| Cost Today | Current day's cloud spending |

### Quick Actions

- **New Chat**: Start a conversation with the AI agent
- **View Alerts**: Jump to active alerts
- **Check Incidents**: Review open incidents

### Navigation Bar

| Button | Destination |
|--------|-------------|
| Dashboard | Infrastructure overview |
| Monitoring | Alert rules and metrics |
| Incidents | Incident management |
| Optimize | Recommendations |
| Analysis | Root cause analysis |
| Credits | Billing page |
| Export | Download chat history |
| Clear | Start new conversation |
| Profile | User menu and settings |

---

## Chat Interface

The AI-powered chat is the primary way to interact with DevOps Agent.

### Sending Messages

1. Type your request in the input field
2. Press **Enter** or click **Send**
3. Wait for the AI response

### Example Requests

**Infrastructure Queries:**
```
List all EC2 instances in us-east-1
Show me pods in the production namespace
What S3 buckets have public access?
```

**Operations:**
```
Scale the web-app deployment to 5 replicas
Stop EC2 instance i-0abc123def
Restart the nginx pod
```

**Analysis:**
```
Why is CPU usage high on the database server?
Analyze the recent deployment failure
What's causing the latency spike?
```

### Conversation Management

**Sidebar Features:**
- View conversation history
- Click any conversation to load it
- Delete conversations (hover and click Delete)
- Start new sessions

**Menu Options (Profile Button):**
- **View Tools**: See all 173+ available tools
- **Statistics**: Current session metrics
- **About**: Version information

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter | Send message |
| Shift+Enter | New line |

---

## Cloud Configuration

Access via **Settings** (`/settings`).

### AWS Configuration

| Field | Description |
|-------|-------------|
| Access Key ID | Your AWS access key |
| Secret Access Key | Your AWS secret (stored encrypted) |
| Default Region | Default AWS region (e.g., us-east-1) |

**Required IAM Permissions:**
- EC2: Describe, Start, Stop, Reboot
- S3: List, Get, Put
- RDS: Describe
- CloudWatch: Get metrics, Describe alarms
- IAM: List (for auditing)

### Azure Configuration

| Field | Description |
|-------|-------------|
| Subscription ID | Azure subscription identifier |
| Tenant ID | Azure AD tenant |
| Client ID | Application client ID |
| Client Secret | Application secret |
| Default Location | Default region (e.g., eastus) |

### GCP Configuration

| Field | Description |
|-------|-------------|
| Project ID | GCP project identifier |
| Service Account | JSON key file upload |
| Default Region | Default region (e.g., us-central1) |
| Default Zone | Default zone (e.g., us-central1-a) |

---

## Monitoring & Alerts

Access via **Monitoring** (`/monitoring`).

### Dashboard Overview

- **Active Alerts**: Currently firing alerts
- **Total Rules**: Number of monitoring rules
- **Rule Status**: Enabled/disabled breakdown

### Creating Monitoring Rules

1. Click **Create Rule**
2. Configure:

| Field | Description | Example |
|-------|-------------|---------|
| Name | Rule identifier | High CPU Alert |
| Metric Source | Data source | Prometheus |
| Metric Name | Metric to monitor | cpu_usage_percent |
| Condition | Comparison operator | Greater than |
| Threshold | Trigger value | 80 |
| Duration | How long before alerting | 5 minutes |
| Severity | Alert importance | Critical |

3. Add labels (optional)
4. Click **Save**

### Managing Rules

| Action | Description |
|--------|-------------|
| Enable/Disable | Toggle rule without deleting |
| Edit | Modify rule parameters |
| Delete | Permanently remove rule |
| Test | Manually check if rule fires |

### Viewing Alerts

**Active Alerts Tab:**
- List of currently firing alerts
- Severity indicators
- Timestamp of when alert started
- Quick acknowledge button

**Alert History Tab:**
- Historical alerts
- Filter by date range
- Filter by severity

### Service Control

- **Start Monitoring**: Begin rule evaluation
- **Stop Monitoring**: Pause all monitoring
- **Status**: Current monitoring state

---

## Incident Management

Access via **Incidents** (`/incidents`).

### Incident Dashboard

**Statistics:**
- Total incidents
- By status (Open, Acknowledged, Resolved)
- By severity (Critical, High, Medium, Low)

**Filters:**
- Status
- Severity
- Date range
- Source

### Incident Lifecycle

```
Unacknowledged -> Acknowledged -> Resolved
```

**Acknowledge:**
1. Click on incident
2. Click **Acknowledge**
3. Optionally add notes

**Resolve:**
1. Open incident details
2. Click **Resolve**
3. Document resolution

### Incident Details

Each incident shows:
- Title and description
- Severity and status
- Source system
- Timeline of events
- Actions taken
- Related alerts

### Playbooks

Playbooks automate incident response.

**Creating a Playbook:**

1. Go to **Playbooks** tab
2. Click **Create Playbook**
3. Configure:

| Field | Description |
|-------|-------------|
| Name | Playbook identifier |
| Description | What it handles |
| Trigger Conditions | When to activate |
| Actions | Steps to execute |
| Auto-Execute | Run automatically |
| Require Approval | Need human approval |
| Notifications | Where to send alerts |

**Built-in Playbooks:**
- High CPU Usage Response
- Memory Pressure Handling
- Disk Full Remediation
- Pod Crash Loop Recovery
- High Error Rate Response
- Latency Spike Resolution

### Receiving External Alerts

Configure webhooks to receive alerts from:
- Prometheus/Alertmanager
- Datadog
- PagerDuty
- OpsGenie
- Grafana

---

## Root Cause Analysis

Access via **Analysis** (`/analysis`).

### Running Analysis

1. Select an incident to analyze
2. Click **Analyze**
3. Wait for AI analysis

### Analysis Components

| Component | Description |
|-----------|-------------|
| Root Cause | Primary cause identified |
| Contributing Factors | Secondary issues |
| Evidence | Supporting logs/metrics |
| Recommendations | Suggested fixes |
| Prevention | How to avoid recurrence |

### Analysis History

- View past analyses
- Compare similar incidents
- Track recurring issues

---

## Optimization

Access via **Optimize** (`/optimization`).

### Recommendation Types

| Type | Description |
|------|-------------|
| CPU | Right-size CPU allocation |
| Memory | Adjust memory settings |
| Disk I/O | Storage optimization |
| Network | Bandwidth improvements |
| Cost | Reduce unnecessary spending |

### Working with Recommendations

**View Details:**
- Current configuration
- Recommended changes
- Estimated impact
- Potential savings

**Actions:**
- **Implement**: Mark as done after applying
- **Dismiss**: Dismiss with reason
- **Auto-Fix**: Apply automatically (if supported)

### Filtering

| Filter | Options |
|--------|---------|
| Type | CPU, Memory, Disk, Network, Cost |
| Category | Compute, Storage, Database, Network |
| Priority | High, Medium, Low |
| Status | New, Reviewed, Implemented, Dismissed |

---

## Predictive Scaling

Access via **Scaling** (`/scaling`).

### Predictions Dashboard

View scaling predictions with:
- Resource identification
- Direction (up/down)
- Current vs recommended capacity
- Confidence level
- Risk assessment

### Prediction Details

| Field | Description |
|-------|-------------|
| Resource | What to scale |
| Direction | Scale up or down |
| Current | Existing capacity |
| Recommended | Suggested capacity |
| Peak Prediction | Expected max load |
| Confidence | Prediction certainty |
| Savings | Potential cost impact |

### Pattern Analysis

The system detects:
- Peak usage hours
- Peak days of week
- Growth trends
- Utilization patterns

### Historical Metrics

View 48-hour history:
- Usage graphs
- Anomaly detection
- Trend visualization

---

## Drift Detection

Access via **Drift** (`/drift`).

### Understanding Drift

Infrastructure drift occurs when actual configurations differ from expected baselines.

### Setting Up Baselines

1. Go to **Baselines** tab
2. Click **Add Baseline**
3. Choose method:
   - **From Terraform**: Import state file
   - **Manual**: Define manually
   - **Sample**: Use test data

### Running Drift Scans

1. Select resources to scan
2. Click **Scan for Drift**
3. Review results:
   - Changed properties
   - Added resources
   - Removed resources

### Drift Reports

Each report includes:
- Scan timestamp
- Resources scanned
- Drift items found
- Severity classification
- Remediation suggestions

### Supported Resources

- EC2 instances
- Security groups
- S3 buckets
- RDS instances
- Load balancers
- VPCs and subnets

---

## AI Infrastructure

Access via **AI** (`/ai`).

### Natural Language Provisioning

Describe infrastructure in plain English:

```
Create a web application with:
- 3 t3.medium EC2 instances
- Application Load Balancer
- RDS PostgreSQL database
- S3 bucket for assets
- CloudFront CDN
```

The AI will:
1. Parse requirements
2. Generate specifications
3. Create Terraform/CloudFormation code
4. Estimate costs

### Templates

Browse pre-built templates:
- Web Application Stack
- Microservices Architecture
- Data Pipeline
- Serverless Application

### Deployments

Track AI-assisted deployments:
- Deployment status
- Resources created
- Cost tracking
- Rollback options

---

## Analytics & Reporting

Access via **Analytics** (`/analytics`).

### Cost Analytics

| Report | Description |
|--------|-------------|
| Daily Breakdown | Day-by-day spending |
| By Service | Cost per AWS/Azure/GCP service |
| By Resource | Cost per individual resource |
| Forecast | 30-day prediction |

### Performance Analytics

Available metrics:
- CPU utilization
- Memory usage
- Disk I/O
- Network throughput

Time ranges:
- Last hour
- Last 24 hours
- Last 7 days
- Last 30 days
- Custom

### Export Options

| Format | Use Case |
|--------|----------|
| CSV | Spreadsheet analysis |
| JSON | Programmatic processing |

---

## Notifications

Access via **Notifications** (`/notifications`).

### Supported Channels

| Channel | Configuration |
|---------|---------------|
| Slack | Webhook URL or API token |
| Microsoft Teams | Webhook URL |
| Email | SMTP settings |

### Setting Up Slack

1. Click **Add Channel** > **Slack**
2. Enter webhook URL (from Slack app)
3. Set default channel
4. Test connection
5. Save

### Setting Up Teams

1. Click **Add Channel** > **Teams**
2. Enter incoming webhook URL
3. Configure options
4. Test and save

### Sending Notifications

**Priority Levels:**
- Low
- Normal
- High
- Critical

**Options:**
- Custom message
- Action buttons
- Custom fields

---

## Webhooks

Access via **Webhooks** (`/webhooks`).

### Receiving Git Events

**GitHub:**
- Push events
- Pull request events
- Release events
- Workflow events

**GitLab:**
- Push events
- Merge request events
- Pipeline events

**Bitbucket:**
- Push events
- Pull request events

### Webhook Security

| Provider | Security Method |
|----------|-----------------|
| GitHub | HMAC signature validation |
| GitLab | Secret token |
| Bitbucket | IP allowlisting |

### Event History

View:
- All received events
- Payloads
- Processing status
- Timestamps

---

## ChatOps

Access via **ChatOps** (`/chatops`).

### Slack Commands

| Command | Description |
|---------|-------------|
| `/devops status` | System status |
| `/devops incidents` | Active incidents |
| `/devops alerts` | Firing alerts |
| `/devops deploy <app>` | Deploy app |
| `/devops scale <app> <n>` | Scale app |
| `/devops help` | Show commands |

### Teams Integration

- Direct messages to bot
- Channel @mentions
- Adaptive cards for rich responses

---

## API Gateway

Access via **API Gateway** (`/api-gateway`).

### API Key Management

**Creating Keys:**

1. Click **Create API Key**
2. Configure:
   - Name
   - Scopes
   - Rate limit
   - Expiration (optional)
3. Copy key (shown only once)

**Scopes:**

| Scope | Permission |
|-------|------------|
| `read:resources` | View infrastructure |
| `write:resources` | Modify infrastructure |
| `read:analytics` | View analytics |
| `write:incidents` | Manage incidents |
| `admin` | Full access |

### Using the API

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  https://your-domain.com/api/v1/resources
```

### Rate Limits

- Default: 100 requests/minute
- Customizable per key
- Rate limit headers in responses

---

## Compliance

Access via **Compliance** (`/compliance`).

### Supported Frameworks

| Framework | Full Name |
|-----------|-----------|
| SOC 2 | Service Organization Control 2 |
| ISO 27001 | Information Security Management |
| HIPAA | Health Insurance Portability |
| PCI-DSS | Payment Card Industry |
| GDPR | General Data Protection Regulation |
| CIS | Center for Internet Security |

### Running Compliance Checks

1. Enable desired frameworks
2. Click **Run Compliance Check**
3. Review results:
   - Passing controls
   - Failing controls
   - Recommendations

### Evidence Management

For each control:
- Upload evidence documents
- Link external evidence
- Track review status

### Audit Logging

All actions are logged:
- User actions
- Resource changes
- Configuration changes

**Filters:**
- Action type
- Resource type
- User
- Date range

---

## Organizations & Teams

### Organizations (`/organizations`)

**Creating Organization:**
1. Click **Create Organization**
2. Enter name and description
3. Upload logo (optional)
4. Save

**Roles:**

| Role | Permissions |
|------|-------------|
| Owner | Full control, can delete org |
| Admin | Manage members and settings |
| Member | Standard access |

**Managing Members:**
1. Go to **Members** tab
2. Click **Invite Member**
3. Enter email and select role
4. Send invitation

### Teams (`/teams`)

**Creating Teams:**
1. Go to **Teams** tab
2. Click **Create Team**
3. Add members
4. Set permissions

**Team Roles:**

| Role | Permissions |
|------|-------------|
| Admin | Manage team |
| Approver | Approve actions |
| User | Standard operations |
| Viewer | Read-only |

---

## Billing

Access via **Billing** (`/billing`).

### Credit System

- Credits consumed per AI interaction
- Different operations cost different amounts
- View remaining credits in header

### Purchasing Credits

1. Select credit package
2. Complete payment (Stripe)
3. Credits added immediately

### Subscription Tiers

| Tier | Credits/Month | Features |
|------|---------------|----------|
| Free | 100 | Basic |
| Pro | 1,000 | All features |
| Enterprise | Unlimited | Custom |

### Usage Tracking

- Credit history
- Usage by feature
- Projected usage
- Invoices

---

## Administration

Access via **Admin** (`/admin`) - requires admin role.

### User Management

**Dashboard:**
- Total users
- Active users (30 days)
- Role distribution

**Operations:**
- Search users
- View details
- Change roles
- Lock/unlock accounts
- Delete accounts

### System Statistics

- Real-time metrics
- API usage
- Error rates

### Audit Log

System-wide activity:
- Login events
- Configuration changes
- Security events

---

## Profile & Settings

### Profile (`/profile`)

Edit:
- Full name
- Bio
- Avatar color
- Theme preference
- Language

### Settings (`/settings`)

Configure:
- Cloud credentials
- API keys
- Notification preferences

---

## Security

### Best Practices

1. **Strong Passwords**: 12+ characters, mixed types
2. **Unique Credentials**: Don't reuse passwords
3. **API Key Security**: Limit scopes, set expiration
4. **Credential Rotation**: Regularly rotate all secrets
5. **Session Management**: Log out when done

### Security Features

- CSRF protection
- Rate limiting
- Account lockout
- IP logging
- Encrypted credential storage
- Audit logging

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Can't log in | Wait 15 min if locked, or reset password |
| API key not working | Check expiration, scopes, rate limit |
| Cloud operations failing | Verify credentials and permissions |
| Monitoring not working | Ensure service is started |

### Error Messages

| Error | Meaning |
|-------|---------|
| "Invalid credentials" | Wrong username/password |
| "Account locked" | Too many failed attempts |
| "Insufficient credits" | Need to purchase credits |
| "Permission denied" | Missing required role |
| "Rate limit exceeded" | Too many requests |

### Getting Help

1. **Chat Interface**: Ask the AI for help
2. **Documentation**: Check docs folder
3. **Support**: Contact support team

---

## Quick Reference

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter | Send message |
| Shift+Enter | New line |
| Esc | Close modal |

### URL Reference

| Path | Feature |
|------|---------|
| / | Main chat interface |
| /dashboard | Infrastructure dashboard |
| /monitoring | Alert rules and metrics |
| /incidents | Incident management |
| /optimization | Recommendations |
| /analysis | Root cause analysis |
| /scaling | Predictive scaling |
| /drift | Drift detection |
| /ai | AI infrastructure |
| /analytics | Reports and analytics |
| /notifications | Notification channels |
| /webhooks | Webhook management |
| /chatops | ChatOps integration |
| /api-gateway | API key management |
| /compliance | Compliance frameworks |
| /organizations | Organization management |
| /teams | Team management |
| /billing | Credits and billing |
| /admin | Administration |
| /profile | User profile |
| /settings | Cloud configuration |

---

*For CLI usage, see [USER_GUIDE.md](USER_GUIDE.md)*
