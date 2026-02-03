# DevOps Agent Quick Start Guide

Get up and running in 5 minutes.

---

## Step 1: Start the Application

```bash
cd devops-agent
python app.py
```

Open `http://localhost:5000` in your browser.

---

## Step 2: Create an Account

1. Click **Sign Up**
2. Enter email, username (3-20 chars), and password (8+ chars with upper, lower, numbers)
3. Click **Create Account**
4. Log in with your credentials

---

## Step 3: Configure API Key

1. Go to `/setup`
2. Enter your Anthropic API key
3. Click **Save**

Get your key at: https://console.anthropic.com/

---

## Step 4: Set Up Cloud Credentials (Optional)

Go to **Settings** (`/settings`) and add:

**AWS:**
- Access Key ID
- Secret Access Key
- Default Region

**Azure:**
- Subscription ID
- Tenant ID
- Client ID
- Client Secret

**GCP:**
- Project ID
- Service Account JSON

---

## Step 5: Start Using the Agent

Type in the chat to interact:

```
List all EC2 instances
Show me pods in production namespace
What S3 buckets do I have?
Help me troubleshoot high CPU
```

---

## Key Features

| Feature | URL | Description |
|---------|-----|-------------|
| Chat | `/` | AI-powered DevOps assistant |
| Dashboard | `/dashboard` | Infrastructure overview |
| Monitoring | `/monitoring` | Alert rules and metrics |
| Incidents | `/incidents` | Incident management |
| Optimize | `/optimization` | Cost & performance recommendations |
| Analysis | `/analysis` | Root cause analysis |
| Scaling | `/scaling` | Predictive scaling |
| Drift | `/drift` | Configuration drift detection |
| AI | `/ai` | Natural language infrastructure |
| Analytics | `/analytics` | Reports and cost analysis |
| Compliance | `/compliance` | Security frameworks |

---

## Quick Commands

**AWS:**
```
List EC2 instances in us-east-1
Show S3 buckets
Get RDS database status
```

**Kubernetes:**
```
Show pods in default namespace
Scale deployment web-app to 3 replicas
Get logs from pod nginx-123
```

**Monitoring:**
```
What alerts are firing?
Create alert for high CPU usage
Show monitoring rules
```

**Analysis:**
```
Why is the server slow?
Analyze the deployment failure
What's causing the error rate spike?
```

---

## Navigation Shortcuts

- **Profile Menu**: Click the profile button in top-right
- **View Tools**: Profile > View Tools
- **Statistics**: Profile > Statistics
- **Settings**: Profile > Settings
- **New Chat**: Sidebar > New Session

---

## Next Steps

1. **Explore Features**: Try each section from the navigation
2. **Set Up Monitoring**: Create alert rules for your infrastructure
3. **Configure Notifications**: Add Slack or Teams webhooks
4. **Read Full Guide**: See [WEB_APPLICATION_GUIDE.md](WEB_APPLICATION_GUIDE.md)

---

## Need Help?

- Ask the AI: Type "help" or "what can you do?"
- View tools: Profile menu > View Tools
- Documentation: Check the `docs/` folder

---

*Full documentation: [WEB_APPLICATION_GUIDE.md](WEB_APPLICATION_GUIDE.md) | [USER_GUIDE.md](USER_GUIDE.md)*
