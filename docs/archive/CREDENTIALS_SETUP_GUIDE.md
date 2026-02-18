# 🔐 DevOps Agent - Credentials Setup Guide

## Overview

Your DevOps Agent supports multi-cloud infrastructure management, but requires proper credentials to access your cloud resources. This guide shows you how to configure credentials securely.

---

## 🚀 Quick Start (Recommended Path)

### Phase 1: Essential Setup (Start Here!)

#### 1. Anthropic API Key (Required)
Your agent uses Claude AI for intelligent automation.

**Setup:**
```bash
# Get your API key from: https://console.anthropic.com/
export ANTHROPIC_API_KEY="sk-ant-xxxxx"
```

**Cost:** Pay-per-use (~$0.05 per agent action with current pricing model)

#### 2. AWS Credentials (Recommended First Cloud)
Most users start with AWS as it's the most popular cloud platform.

**Setup:**
```bash
# Option A: Using AWS CLI (recommended)
aws configure
# Enter:
# - AWS Access Key ID
# - AWS Secret Access Key
# - Default region (e.g., us-east-1)

# Option B: Environment variables
export AWS_ACCESS_KEY_ID="AKIAXXXXX"
export AWS_SECRET_ACCESS_KEY="xxxxx"
export AWS_DEFAULT_REGION="us-east-1"
```

**How to get credentials:**
1. Go to AWS Console → IAM → Users
2. Create a new user with programmatic access
3. Attach policy: `ReadOnlyAccess` (to start safely)
4. Download the access key

**What this enables:**
- View all EC2 instances, RDS databases, S3 buckets
- Monitor costs in real-time
- Get cost optimization recommendations
- Security vulnerability scanning

---

### Phase 2: Expand Cloud Coverage

#### 3. Google Cloud Platform (GCP)

**Setup:**
```bash
# Create service account in GCP Console
# Download JSON key file

# Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
export GCP_PROJECT_ID="your-project-id"
```

**How to get credentials:**
1. Go to GCP Console → IAM & Admin → Service Accounts
2. Create service account with "Viewer" role
3. Create JSON key
4. Download and save securely

**What this enables:**
- Manage Compute Engine VMs
- Monitor Cloud Storage buckets
- GKE cluster management
- BigQuery access

#### 4. Microsoft Azure

**Setup:**
```bash
# Using Azure CLI (recommended)
az login

# Or using service principal
export AZURE_CLIENT_ID="xxxxx"
export AZURE_CLIENT_SECRET="xxxxx"
export AZURE_TENANT_ID="xxxxx"
export AZURE_SUBSCRIPTION_ID="xxxxx"
```

**How to get credentials:**
1. Go to Azure Portal → Azure Active Directory → App Registrations
2. Create new app registration
3. Create client secret
4. Assign "Reader" role to subscription

**What this enables:**
- Manage Virtual Machines
- Monitor Storage Accounts
- AKS cluster operations
- Cost analysis

---

### Phase 3: CI/CD Integration

#### 5. GitHub Access

**Setup:**
```bash
export GITHUB_TOKEN="ghp_xxxxx"
```

**How to get token:**
1. GitHub → Settings → Developer settings → Personal access tokens
2. Create token with scopes: `repo`, `workflow`, `admin:org`
3. Copy token immediately (shown only once!)

**What this enables:**
- Repository management
- GitHub Actions automation
- Pull request automation
- Release management

#### 6. GitLab Access (Optional)

**Setup:**
```bash
export GITLAB_TOKEN="xxxxx"
export GITLAB_URL="https://gitlab.com"  # or your self-hosted URL
```

**What this enables:**
- GitLab CI/CD pipeline management
- Merge request automation
- Project management

#### 7. Jenkins (Optional)

**Setup:**
```bash
export JENKINS_URL="https://jenkins.yourcompany.com"
export JENKINS_USER="your-username"
export JENKINS_TOKEN="xxxxx"
```

**What this enables:**
- Trigger builds
- Monitor job status
- Pipeline automation

---

### Phase 4: Container Orchestration

#### 8. Kubernetes Access

**Setup:**
```bash
# If you have kubectl configured, agent will use your ~/.kube/config automatically

# Or set specific kubeconfig
export KUBECONFIG="/path/to/kubeconfig"
```

**What this enables:**
- Deploy applications to Kubernetes
- Monitor pods, services, deployments
- Auto-scaling management
- Troubleshooting and logs

---

## 🔒 Secure Configuration

### Create .env File (Recommended)

Create a `.env` file in your project root:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-xxxxx

# AWS (optional but recommended)
AWS_ACCESS_KEY_ID=AKIAXXXXX
AWS_SECRET_ACCESS_KEY=xxxxx
AWS_DEFAULT_REGION=us-east-1

# GCP (optional)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-service-account.json
GCP_PROJECT_ID=your-project-id

# Azure (optional)
AZURE_CLIENT_ID=xxxxx
AZURE_CLIENT_SECRET=xxxxx
AZURE_TENANT_ID=xxxxx
AZURE_SUBSCRIPTION_ID=xxxxx

# GitHub (optional)
GITHUB_TOKEN=ghp_xxxxx

# GitLab (optional)
GITLAB_TOKEN=xxxxx
GITLAB_URL=https://gitlab.com

# Jenkins (optional)
JENKINS_URL=https://jenkins.example.com
JENKINS_USER=username
JENKINS_TOKEN=xxxxx

# Kubernetes (optional - uses ~/.kube/config by default)
# KUBECONFIG=/path/to/kubeconfig

# Database (already configured)
DATABASE_URL=sqlite:///devops_agent.db

# Flask Secret Key (already configured)
SECRET_KEY=your-secret-key-here

# Stripe (for payments - optional)
STRIPE_PUBLISHABLE_KEY=pk_xxxxx
STRIPE_SECRET_KEY=sk_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

### Important Security Notes:

1. **Never commit .env to git:**
   ```bash
   # Add to .gitignore
   echo ".env" >> .gitignore
   ```

2. **Use least privilege:**
   - Start with read-only access
   - Grant write permissions only when needed
   - Use service accounts, not personal accounts

3. **Rotate credentials regularly:**
   - Set reminders to rotate every 90 days
   - Use secret managers in production

4. **Enable MFA:**
   - Enable MFA on all cloud accounts
   - Use temporary credentials when possible

5. **Monitor usage:**
   - Check CloudTrail (AWS), Activity Log (Azure), Audit Logs (GCP)
   - Set up billing alerts

---

## ✅ Testing Your Setup

After configuring credentials, test each integration:

### Test AWS Connection:
```bash
python -c "import boto3; ec2 = boto3.client('ec2'); print(f'Connected! Found {len(ec2.describe_instances()[\"Reservations\"])} EC2 reservations')"
```

### Test GCP Connection:
```bash
python -c "from google.cloud import compute_v1; print('GCP connection successful!')"
```

### Test Azure Connection:
```bash
python -c "from azure.identity import DefaultAzureCredential; from azure.mgmt.compute import ComputeManagementClient; cred = DefaultAzureCredential(); print('Azure connection successful!')"
```

### Test in DevOps Agent:
1. Login to http://localhost:5000
2. Go to Dashboard
3. Click "🔄 Sync Now"
4. You should see your cloud resources appear!

---

## 📊 What You'll Get After Setup

### With AWS Configured:
- ✅ Real-time view of all EC2 instances
- ✅ S3 bucket monitoring and cost analysis
- ✅ RDS database tracking
- ✅ Lambda function monitoring
- ✅ Cost optimization recommendations
- ✅ Security vulnerability scanning
- ✅ Idle resource detection (save $$!)

### With GCP Configured:
- ✅ Compute Engine VM management
- ✅ GCS bucket monitoring
- ✅ GKE cluster overview
- ✅ Cost analysis and optimization

### With Azure Configured:
- ✅ Virtual Machine monitoring
- ✅ Storage account tracking
- ✅ AKS cluster management
- ✅ Cost optimization

### With Kubernetes Configured:
- ✅ Deploy applications with natural language
- ✅ Monitor pod health
- ✅ Auto-scaling recommendations
- ✅ Resource optimization
- ✅ Troubleshooting assistance

### With GitHub Configured:
- ✅ Automated repository management
- ✅ Pull request automation
- ✅ CI/CD pipeline triggers
- ✅ Release management

---

## 🎯 Recommended Setup Order

**For Most Users:**
1. ✅ Anthropic API Key (Required)
2. ✅ AWS Credentials (Most common)
3. ✅ GitHub Token (If using GitHub)
4. ⏭️ GCP/Azure (Add if you use multi-cloud)
5. ⏭️ Kubernetes (If using K8s)
6. ⏭️ Jenkins/GitLab (If using these tools)

**Time Investment:**
- Phase 1 (Essential): 15 minutes
- Phase 2 (Multi-cloud): 30 minutes
- Phase 3 (CI/CD): 15 minutes
- Phase 4 (K8s): 10 minutes

**Total: ~1 hour to unlock full potential!**

---

## 🚨 Common Issues & Solutions

### Issue: "No credentials found"
**Solution:** Make sure .env file is in project root and Flask server was restarted after creating it.

### Issue: "Access Denied"
**Solution:** Check IAM permissions. Start with ReadOnlyAccess, then add specific permissions as needed.

### Issue: "Invalid API key"
**Solution:** Verify API key is correct and hasn't expired. Check for extra spaces.

### Issue: "Resources not syncing"
**Solution:** Click "🔄 Sync Now" on dashboard. Check browser console for errors.

---

## 💡 Pro Tips

1. **Start Small:** Configure AWS first, see it work, then add others
2. **Use IAM Roles:** In production, use IAM roles instead of access keys
3. **Set Billing Alerts:** Configure cloud billing alerts before automation
4. **Test in Staging:** Try commands in a test environment first
5. **Monitor Costs:** The agent helps you save money, but monitor usage
6. **Backup Credentials:** Store credentials securely (password manager)

---

## 🎉 You're Ready!

Once credentials are configured:
1. Restart Flask server: `python app.py`
2. Visit: http://localhost:5000
3. Go to Dashboard → Click "Sync Now"
4. Watch your infrastructure appear!
5. Ask the AI: "What can you help me optimize?"

---

## 📞 Need Help?

- Check logs: `logs/agent.log`
- Test individual cloud connections first
- Start with read-only permissions
- Verify .env file location and format

**Your DevOps Agent is ready to save you time and money!** 🚀
