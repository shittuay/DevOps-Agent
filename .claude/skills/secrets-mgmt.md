---
name: secrets-mgmt
description: Manage application secrets using AWS Secrets Manager. Use when setting up secrets, migrating from .env files, or troubleshooting secret access issues.
---

# Secrets Management with AWS Secrets Manager

## Overview

This skill guides you through managing application secrets using AWS Secrets Manager instead of `.env` files for better security in production.

## Why AWS Secrets Manager?

**Security Benefits:**
- ✅ Encrypted at rest with AWS KMS
- ✅ IAM-based access control
- ✅ CloudTrail audit logging
- ✅ Automatic secret rotation
- ✅ No secrets in code or files
- ✅ Environment separation

**vs .env Files:**
- ❌ .env files can be accidentally committed to git
- ❌ No access control on .env files
- ❌ No audit trail
- ❌ Manual rotation required
- ❌ Stored in plain text on disk

## Setup Workflow

### Phase 1: Create Secrets in AWS

#### Option A: Individual Secrets

```bash
# Create Anthropic API key secret
aws secretsmanager create-secret \
  --name ANTHROPIC_API_KEY \
  --description "Claude API key" \
  --secret-string "sk-ant-api03-your-key-here" \
  --region us-east-1

# Create Flask secret key
aws secretsmanager create-secret \
  --name SECRET_KEY \
  --secret-string "$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  --region us-east-1

# Create Stripe secret
aws secretsmanager create-secret \
  --name STRIPE_SECRET_KEY \
  --secret-string "sk_live_your-key" \
  --region us-east-1
```

#### Option B: Single JSON Secret (Recommended)

Store all secrets together:

```bash
aws secretsmanager create-secret \
  --name devops-agent/prod/secrets \
  --description "All DevOps Agent production secrets" \
  --secret-string '{
    "ANTHROPIC_API_KEY": "sk-ant-api03-...",
    "SECRET_KEY": "your-flask-secret",
    "AWS_ACCESS_KEY_ID": "AKIA...",
    "AWS_SECRET_ACCESS_KEY": "...",
    "STRIPE_SECRET_KEY": "sk_live_...",
    "STRIPE_PUBLISHABLE_KEY": "pk_live_...",
    "GITHUB_TOKEN": "ghp_...",
    "DATABASE_URL": "postgresql://..."
  }' \
  --region us-east-1
```

#### Create for Different Environments

```bash
# Development
aws secretsmanager create-secret \
  --name devops-agent/dev/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-dev-..."}'

# Staging
aws secretsmanager create-secret \
  --name devops-agent/staging/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-staging-..."}'

# Production
aws secretsmanager create-secret \
  --name devops-agent/prod/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"sk-ant-prod-..."}'
```

### Phase 2: Configure IAM Permissions

**Create IAM Policy:**

Save as `secrets-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:*:secret:devops-agent/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "secretsmanager.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
```

**Create and Attach Policy:**

```bash
# Create policy
aws iam create-policy \
  --policy-name DevOpsAgentSecretsAccess \
  --policy-document file://secrets-policy.json

# Attach to EC2 instance role
aws iam attach-role-policy \
  --role-name your-ec2-role \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess

# Or attach to your user (for testing)
aws iam attach-user-policy \
  --user-name your-username \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess
```

### Phase 3: Integrate into Application

**The code is already created in `services/secrets_manager.py`**

**Update app.py:**

Add at the top:

```python
import os

# Initialize secrets based on environment
if os.environ.get('FLASK_ENV') == 'production':
    print("🔐 Loading secrets from AWS Secrets Manager...")
    from services.secrets_manager import init_secrets
    init_secrets()
else:
    print("🔐 Loading secrets from .env file...")
    from dotenv import load_dotenv
    load_dotenv()

# All secrets now available in os.environ
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
SECRET_KEY = os.environ.get('SECRET_KEY')
```

### Phase 4: Test Integration

#### Local Testing

```bash
# Ensure AWS credentials are configured
aws configure

# Test secrets retrieval
python services/secrets_manager.py

# Expected output:
# ✅ Successfully retrieved ANTHROPIC_API_KEY: sk-ant-api...
```

#### Application Testing

```bash
# Set production mode
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# Run app
python app.py

# Check logs for:
# 🔐 Loading secrets from AWS Secrets Manager...
# ✓ Loaded secret: ANTHROPIC_API_KEY
# ✓ Loaded secret: SECRET_KEY
# ...
```

### Phase 5: Deploy to Production

#### EC2 Deployment

```bash
# 1. SSH to EC2
ssh -i key.pem ubuntu@your-ec2-ip

# 2. Pull latest code
cd /opt/devops-agent
git pull

# 3. Set environment variables
sudo tee -a /etc/environment > /dev/null <<EOF
FLASK_ENV=production
AWS_DEFAULT_REGION=us-east-1
EOF

# 4. Update systemd service
sudo systemctl edit devops-agent
# Add:
# [Service]
# Environment="FLASK_ENV=production"
# Environment="AWS_DEFAULT_REGION=us-east-1"

# 5. Restart service
sudo systemctl daemon-reload
sudo systemctl restart devops-agent

# 6. Check status
sudo systemctl status devops-agent
```

#### Elastic Beanstalk

```bash
# Set environment variables
eb setenv \
  FLASK_ENV=production \
  AWS_DEFAULT_REGION=us-east-1

# Deploy
eb deploy

# Check logs
eb logs
```

## Managing Secrets

### View Secrets

```bash
# List all secrets
aws secretsmanager list-secrets --region us-east-1

# Get secret value
aws secretsmanager get-secret-value \
  --secret-id devops-agent/prod/secrets \
  --region us-east-1 \
  --query SecretString \
  --output text | jq

# Describe secret (metadata only, no value)
aws secretsmanager describe-secret \
  --secret-id devops-agent/prod/secrets
```

### Update Secrets

```bash
# Update entire JSON secret
aws secretsmanager update-secret \
  --secret-id devops-agent/prod/secrets \
  --secret-string '{
    "ANTHROPIC_API_KEY": "new-key",
    "SECRET_KEY": "new-secret"
  }' \
  --region us-east-1

# Update single secret
aws secretsmanager update-secret \
  --secret-id ANTHROPIC_API_KEY \
  --secret-string "new-api-key" \
  --region us-east-1
```

**After updating, restart application:**

```bash
# EC2
sudo systemctl restart devops-agent

# Elastic Beanstalk
eb restart
```

### Rotate Secrets

```bash
# For manual rotation, just update the secret
aws secretsmanager update-secret \
  --secret-id ANTHROPIC_API_KEY \
  --secret-string "new-rotated-key"

# For automatic rotation (advanced)
aws secretsmanager rotate-secret \
  --secret-id database-password \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:RotateSecret \
  --rotation-rules AutomaticallyAfterDays=30
```

### Delete Secrets

```bash
# Schedule deletion (7-30 day recovery window)
aws secretsmanager delete-secret \
  --secret-id old-secret \
  --recovery-window-in-days 7

# Cancel deletion
aws secretsmanager restore-secret \
  --secret-id old-secret

# Force delete immediately (no recovery)
aws secretsmanager delete-secret \
  --secret-id old-secret \
  --force-delete-without-recovery
```

## Troubleshooting

### Access Denied Error

```bash
# Check who you are
aws sts get-caller-identity

# Test secret access
aws secretsmanager get-secret-value \
  --secret-id devops-agent/prod/secrets

# Check IAM permissions
aws iam list-attached-user-policies --user-name your-user
aws iam list-attached-role-policies --role-name your-role
```

**Fix:**

```bash
# Attach policy to user
aws iam attach-user-policy \
  --user-name your-user \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess

# Or attach to role
aws iam attach-role-policy \
  --role-name your-ec2-role \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess
```

### Secret Not Found

```bash
# Check secret exists
aws secretsmanager list-secrets --region us-east-1

# Check region matches
echo $AWS_DEFAULT_REGION

# Verify secret name
aws secretsmanager describe-secret \
  --secret-id devops-agent/prod/secrets
```

### Application Not Loading Secrets

**Check logs:**

```bash
tail -f logs/agent.log

# Look for:
# 🔐 Loading secrets from AWS Secrets Manager...
# ✓ Loaded secret: ANTHROPIC_API_KEY
```

**Test manually:**

```python
python -c "
from services.secrets_manager import get_anthropic_api_key
api_key = get_anthropic_api_key()
print(f'API Key: {api_key[:10]}...' if api_key else 'Not found')
"
```

**Debug steps:**

1. Check FLASK_ENV is set to "production"
2. Check AWS credentials are available
3. Check IAM permissions
4. Check secret exists in correct region
5. Check CloudTrail for access attempts

### KMS Decryption Error

```bash
# Check KMS key permissions
aws kms describe-key --key-id <key-id>

# Add decrypt permission
aws kms create-grant \
  --key-id <key-id> \
  --grantee-principal arn:aws:iam::123456789012:role/your-role \
  --operations Decrypt
```

## Best Practices

### 1. Environment Separation

Use different secrets per environment:

```python
# In app.py
env = os.environ.get('ENVIRONMENT', 'dev')
secret_name = f'devops-agent/{env}/secrets'
```

### 2. Caching

The `SecretsManager` class caches secrets by default:

```python
from services.secrets_manager import get_secrets_manager

sm = get_secrets_manager()
api_key = sm.get_secret('ANTHROPIC_API_KEY', use_cache=True)  # Cached

# Clear cache when needed
sm.clear_cache()
```

### 3. Least Privilege

Only grant access to required secrets:

```json
{
  "Resource": "arn:aws:secretsmanager:us-east-1:*:secret:devops-agent/prod/*"
}
```

### 4. Monitoring

Set up CloudWatch alarms:

```bash
# Track secret access in CloudTrail
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=devops-agent/prod/secrets \
  --max-results 10
```

### 5. Tagging

Tag secrets for organization:

```bash
aws secretsmanager tag-resource \
  --secret-id devops-agent/prod/secrets \
  --tags Key=Environment,Value=production \
         Key=Application,Value=DevOpsAgent \
         Key=ManagedBy,Value=Terraform
```

## Migration Checklist

- [ ] Create secrets in AWS Secrets Manager
- [ ] Create IAM policy for secret access
- [ ] Attach policy to EC2 role / ECS task role
- [ ] Add `services/secrets_manager.py` to project
- [ ] Update `app.py` to use secrets manager
- [ ] Test locally with AWS credentials
- [ ] Test in staging environment
- [ ] Deploy to production
- [ ] Verify application loads secrets correctly
- [ ] Remove `.env` from production servers
- [ ] Add `.env` to `.gitignore` (if not already)
- [ ] Document secret names and structure
- [ ] Set up CloudWatch monitoring

## Cost Optimization

**AWS Secrets Manager Pricing:**
- $0.40 per secret per month
- $0.05 per 10,000 API calls

**Reduce costs by:**
1. Using single JSON secret instead of individual secrets
2. Enabling caching (already implemented)
3. Consolidating secrets per environment

**Example cost:**
- 3 environments × 1 secret = 3 × $0.40 = $1.20/month
- 30,000 API calls/month = $0.15/month
- **Total: ~$1.35/month**

## Quick Commands

```bash
# Create secret
aws secretsmanager create-secret --name my-secret --secret-string "value"

# Get secret
aws secretsmanager get-secret-value --secret-id my-secret --query SecretString --output text

# Update secret
aws secretsmanager update-secret --secret-id my-secret --secret-string "new-value"

# List secrets
aws secretsmanager list-secrets

# Delete secret
aws secretsmanager delete-secret --secret-id my-secret --recovery-window-in-days 7

# Test from Python
python services/secrets_manager.py

# Check IAM
aws sts get-caller-identity
```

## References

- Reference guide: `AWS_SECRETS_MANAGER_SETUP.md`
- Code: `services/secrets_manager.py`
- AWS Docs: https://docs.aws.amazon.com/secretsmanager/
