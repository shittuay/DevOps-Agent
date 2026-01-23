# 🚀 DevOps Agent - Quick Start Guide

**Get up and running in 10 minutes**

---

## Prerequisites

- Python 3.8+
- Cloud account (AWS, GCP, or Azure)
- 10 minutes of your time

---

## Installation (5 minutes)

### Step 1: Clone and Install

```bash
# Clone repository
git clone https://github.com/yourusername/devops-agent.git
cd devops-agent

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

Create `.env` file:

```bash
# Copy template
cp .env.example .env

# Edit with your credentials
nano .env
```

**Minimum configuration:**
```env
SECRET_KEY=your-secret-key-change-this
FLASK_ENV=development

# Add at least ONE cloud provider:

# For AWS:
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=us-east-1

# For GCP (optional):
GCP_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json

# For Azure (optional):
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret

# For AI features (optional):
ANTHROPIC_API_KEY=your-anthropic-key
```

### Step 3: Initialize Database

```bash
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Step 4: Create Admin User

```bash
python
>>> from app import app, db
>>> from models import User
>>> app.app_context().push()
>>> admin = User(username='admin', email='admin@yourcompany.com', role='admin')
>>> admin.set_password('Admin123!')
>>> db.session.add(admin)
>>> db.session.commit()
>>> exit()
```

### Step 5: Start Application

```bash
python app.py
```

Visit: **http://localhost:5000**

---

## First Steps (5 minutes)

### 1. Login
```
Username: admin
Password: Admin123!
```

### 2. Sync Your Infrastructure
1. Click **Dashboard** in navigation
2. Click **"Sync Infrastructure"** button
3. Wait 30-60 seconds
4. See all your cloud resources!

### 3. Review Costs
- View **Total Monthly Cost** in dashboard
- See cost breakdown by cloud provider
- Identify most expensive resources

### 4. Check Security
1. Scroll to **Security** section
2. Click **"Run Security Scan"**
3. Review any critical findings
4. Fix security issues following the recommendations

### 5. Optimize Costs
1. View **Cost Optimization** recommendations
2. Start with "Quick Wins"
3. Click **"Apply"** or implement manually
4. Track savings over time

---

## Quick Actions

### Find Idle Resources
```
Dashboard → Cost Optimization → Filter: "Idle Resources"
→ Stop or delete to save 80-90% per resource
```

### Invite Team Member
```
Teams → Invite Team Member → Enter email and role → Send
```

### Set Up Cost Alert
```
Settings → Alerts → Create Alert →
  Trigger: "Monthly cost exceeds $X"
  Action: Email notification
```

### Export Cost Report
```
Dashboard → Export Report → Select format (PDF/CSV) → Download
```

### Use AI Chat
```
Click Chat button → Ask:
  "What are my most expensive resources?"
  "Show me security issues"
  "How can I reduce costs?"
```

---

## Common First Actions

### Scenario 1: "I want to save money immediately"

**Action Plan (15 minutes):**
```
1. Sync infrastructure
2. Go to Cost Optimization
3. Look for:
   - Idle EC2 instances → Stop them
   - Unattached EBS volumes → Delete them
   - Unused Elastic IPs → Release them
4. Apply recommendations
5. Expected savings: 20-40% immediately
```

### Scenario 2: "I need to secure my infrastructure"

**Action Plan (20 minutes):**
```
1. Run security scan
2. Fix CRITICAL issues first:
   - Public S3 buckets → Make private
   - Open security groups → Restrict to specific IPs
   - Unencrypted databases → Enable encryption
3. Schedule daily scans
4. Set up security alerts
```

### Scenario 3: "I want to add my team"

**Action Plan (10 minutes):**
```
1. Go to Teams page
2. Click "Invite Team Member" for each person:
   - Developers → Role: User
   - DevOps Lead → Role: Admin
   - Manager → Role: Viewer
3. Send them login credentials
4. They can access at http://your-server:5000
```

---

## Troubleshooting

### Problem: "Credentials not found"
**Solution:**
```bash
# Check .env file exists
ls -la .env

# Verify credentials are set
cat .env | grep AWS_ACCESS_KEY_ID

# Restart application
python app.py
```

### Problem: "No resources found after sync"
**Solution:**
```bash
# Verify credentials are correct
aws s3 ls  # Should list S3 buckets

# Check region is correct
# Your resources might be in different region
# Update AWS_REGION in .env

# Try syncing again
```

### Problem: "Port 5000 already in use"
**Solution:**
```bash
# Option 1: Kill existing process
lsof -ti:5000 | xargs kill -9

# Option 2: Use different port
python app.py --port 5001
```

---

## Next Steps

1. **Read Full Guide:** See [USER_GUIDE.md](USER_GUIDE.md) for comprehensive documentation

2. **Set Up Automation:**
   - Schedule daily infrastructure syncs
   - Enable automatic security scans
   - Configure cost alerts

3. **Optimize Costs:**
   - Review all recommendations
   - Implement right-sizing
   - Purchase reserved instances for steady workloads

4. **Secure Your Infrastructure:**
   - Fix all critical security issues
   - Enable MFA on cloud accounts
   - Implement least-privilege access

5. **Onboard Your Team:**
   - Invite team members
   - Share user guide
   - Schedule training session

---

## Getting Help

- 📖 **Full Documentation:** [USER_GUIDE.md](USER_GUIDE.md)
- 🔧 **Technical Details:** [MULTI_CLOUD_SYNC_SUMMARY.md](MULTI_CLOUD_SYNC_SUMMARY.md)
- 🐛 **Issues:** GitHub Issues
- 💬 **Community:** Slack Channel
- 📧 **Support:** support@devops-agent.com

---

## Key Commands Reference

```bash
# Start application
python app.py

# Initialize database
python -c "from app import app, db; app.app_context().push(); db.create_all()"

# Create user
python scripts/create_user.py --username=john --email=john@company.com --role=user

# Run tests
python test_new_features.py

# Export infrastructure as Terraform
python scripts/export_terraform.py --cloud=aws

# Generate monthly report
python scripts/generate_monthly_report.py --month=2026-01

# Backup database
cp devops_agent.db devops_agent.db.backup
```

---

## Success Checklist

**Day 1:**
- [x] Installed DevOps Agent
- [x] Configured cloud credentials
- [x] Synced infrastructure
- [x] Reviewed costs
- [x] Ran security scan

**Week 1:**
- [ ] Fixed critical security issues
- [ ] Stopped idle resources
- [ ] Deleted orphaned resources
- [ ] Invited team members
- [ ] Set up cost alerts

**Month 1:**
- [ ] Achieved 20%+ cost savings
- [ ] Zero critical security findings
- [ ] Team fully onboarded
- [ ] Automated daily operations

---

**Ready to save money and improve security? Start now! 🚀**

*Questions? See [USER_GUIDE.md](USER_GUIDE.md) or contact support@devops-agent.com*
