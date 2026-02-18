# AWS Secrets Manager Setup Guide

## Overview

This guide shows how to migrate from `.env` files to AWS Secrets Manager for better security in production.

## Benefits of AWS Secrets Manager

✅ **Secure Storage** - Encrypted at rest with AWS KMS
✅ **Access Control** - IAM policies control who can access secrets
✅ **Audit Trail** - CloudTrail logs all secret access
✅ **Automatic Rotation** - Built-in rotation for RDS, etc.
✅ **No Local Files** - Secrets never stored in files or code
✅ **Environment Separation** - Different secrets per environment

## Setup Instructions

### Step 1: Create Secrets in AWS Secrets Manager

#### Option A: Individual Secrets (Simple)

```bash
# Create secret for Anthropic API key
aws secretsmanager create-secret \
  --name ANTHROPIC_API_KEY \
  --description "Anthropic Claude API key for DevOps Agent" \
  --secret-string "sk-ant-api03-..." \
  --region us-east-1

# Create secret for Flask secret key
aws secretsmanager create-secret \
  --name SECRET_KEY \
  --secret-string "your-random-secret-key-here" \
  --region us-east-1

# Create secret for Stripe
aws secretsmanager create-secret \
  --name STRIPE_SECRET_KEY \
  --secret-string "sk_live_..." \
  --region us-east-1
```

#### Option B: Single JSON Secret (Recommended)

Store all secrets in one JSON object:

```bash
aws secretsmanager create-secret \
  --name devops-agent/secrets \
  --description "All secrets for DevOps Agent application" \
  --secret-string '{
    "ANTHROPIC_API_KEY": "sk-ant-api03-...",
    "SECRET_KEY": "your-flask-secret-key",
    "AWS_ACCESS_KEY_ID": "AKIA...",
    "AWS_SECRET_ACCESS_KEY": "...",
    "STRIPE_SECRET_KEY": "sk_live_...",
    "STRIPE_PUBLISHABLE_KEY": "pk_live_...",
    "GITHUB_TOKEN": "ghp_...",
    "DATABASE_URL": "postgresql://user:pass@host:5432/db"
  }' \
  --region us-east-1
```

### Step 2: Set Up IAM Permissions

Create an IAM policy that allows reading secrets:

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
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:devops-agent/*",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:ANTHROPIC_API_KEY*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "kms:Decrypt"
      ],
      "Resource": "arn:aws:kms:us-east-1:123456789012:key/your-kms-key-id"
    }
  ]
}
```

Attach this policy to:
- EC2 instance role (if running on EC2)
- ECS task role (if running on ECS)
- Lambda execution role (if running on Lambda)
- Your IAM user (for local testing)

```bash
# Create policy
aws iam create-policy \
  --policy-name DevOpsAgentSecretsAccess \
  --policy-document file://secrets-policy.json

# Attach to role
aws iam attach-role-policy \
  --role-name your-ec2-role \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess
```

### Step 3: Update Application Code

#### Modify app.py

Add this at the top of `app.py`:

```python
import os
from services.secrets_manager import init_secrets

# Initialize secrets from AWS Secrets Manager (production)
# or use .env file (local development)
if os.environ.get('FLASK_ENV') == 'production':
    print("Loading secrets from AWS Secrets Manager...")
    init_secrets()
else:
    print("Loading secrets from .env file...")
    from dotenv import load_dotenv
    load_dotenv()

# Now all secrets are available in os.environ
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
SECRET_KEY = os.environ.get('SECRET_KEY')
```

#### Alternative: Direct Usage

```python
from services.secrets_manager import get_anthropic_api_key, get_secrets_manager

# Get a single secret
api_key = get_anthropic_api_key()

# Get a specific secret
sm = get_secrets_manager()
stripe_key = sm.get_secret('STRIPE_SECRET_KEY')

# Get JSON secret
secrets = sm.get_secret_json('devops-agent/secrets')
api_key = secrets['ANTHROPIC_API_KEY']
```

### Step 4: Configure Environment

Set environment variable to use AWS Secrets Manager:

```bash
# For production
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# For local development (still use .env)
export FLASK_ENV=development
export USE_ENV_SECRETS=true
```

### Step 5: Deploy and Test

#### Test Locally First

```bash
# Set up AWS credentials
aws configure

# Test secrets retrieval
python services/secrets_manager.py

# Run the app
export FLASK_ENV=production
python app.py
```

#### Deploy to EC2

1. **Attach IAM role to EC2 instance**

```bash
# Create instance profile
aws iam create-instance-profile --instance-profile-name DevOpsAgentProfile

# Add role to profile
aws iam add-role-to-instance-profile \
  --instance-profile-name DevOpsAgentProfile \
  --role-name DevOpsAgentRole

# Attach to EC2 instance
aws ec2 associate-iam-instance-profile \
  --instance-id i-xxxxx \
  --iam-instance-profile Name=DevOpsAgentProfile
```

2. **Update deployment script**

In `deploy_ec2.sh`, add:

```bash
# Set environment for production
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# Don't copy .env file to production
# Secrets will be loaded from AWS Secrets Manager
```

3. **Restart application**

```bash
sudo systemctl restart devops-agent
```

#### Deploy to Elastic Beanstalk

```bash
# Set environment property
eb setenv FLASK_ENV=production AWS_DEFAULT_REGION=us-east-1

# Ensure instance profile has secrets access
# EB creates this automatically, just add the policy
aws iam attach-role-policy \
  --role-name aws-elasticbeanstalk-ec2-role \
  --policy-arn arn:aws:iam::123456789012:policy/DevOpsAgentSecretsAccess

# Deploy
eb deploy
```

## Managing Secrets

### View Secrets

```bash
# List all secrets
aws secretsmanager list-secrets --region us-east-1

# Get secret value
aws secretsmanager get-secret-value \
  --secret-id ANTHROPIC_API_KEY \
  --region us-east-1
```

### Update Secrets

```bash
# Update individual secret
aws secretsmanager update-secret \
  --secret-id ANTHROPIC_API_KEY \
  --secret-string "new-api-key-value" \
  --region us-east-1

# Update JSON secret
aws secretsmanager update-secret \
  --secret-id devops-agent/secrets \
  --secret-string '{"ANTHROPIC_API_KEY":"new-value","SECRET_KEY":"..."}' \
  --region us-east-1
```

### Delete Secrets

```bash
# Schedule deletion (7-30 days recovery window)
aws secretsmanager delete-secret \
  --secret-id ANTHROPIC_API_KEY \
  --recovery-window-in-days 7 \
  --region us-east-1

# Cancel deletion
aws secretsmanager restore-secret \
  --secret-id ANTHROPIC_API_KEY \
  --region us-east-1

# Force delete (no recovery)
aws secretsmanager delete-secret \
  --secret-id ANTHROPIC_API_KEY \
  --force-delete-without-recovery \
  --region us-east-1
```

### Rotate Secrets

```bash
# Enable automatic rotation (for supported services)
aws secretsmanager rotate-secret \
  --secret-id rds-database-password \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:SecretsManagerRotation \
  --rotation-rules AutomaticallyAfterDays=30 \
  --region us-east-1
```

## Best Practices

### 1. Use Different Secrets Per Environment

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

Then in code:

```python
env = os.environ.get('ENVIRONMENT', 'dev')
secret_name = f'devops-agent/{env}/secrets'
secrets = sm.get_secret_json(secret_name)
```

### 2. Use Least Privilege IAM Policies

Only grant access to secrets that the application needs:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:devops-agent/prod/*"
}
```

### 3. Enable CloudTrail Logging

Monitor who accesses secrets:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=devops-agent/secrets \
  --region us-east-1
```

### 4. Tag Secrets for Organization

```bash
aws secretsmanager tag-resource \
  --secret-id devops-agent/secrets \
  --tags Key=Environment,Value=production Key=Application,Value=DevOpsAgent \
  --region us-east-1
```

### 5. Enable Versioning

Secrets Manager automatically versions secrets. To rollback:

```bash
# List versions
aws secretsmanager list-secret-version-ids \
  --secret-id devops-agent/secrets

# Get previous version
aws secretsmanager get-secret-value \
  --secret-id devops-agent/secrets \
  --version-id <version-id>
```

## Migration Checklist

- [ ] Create secrets in AWS Secrets Manager
- [ ] Set up IAM roles and policies
- [ ] Add `services/secrets_manager.py` to project
- [ ] Update `app.py` to use secrets manager
- [ ] Test locally with AWS credentials
- [ ] Update deployment scripts
- [ ] Deploy to staging environment
- [ ] Test application functionality
- [ ] Deploy to production
- [ ] Remove `.env` file from production servers
- [ ] Update documentation
- [ ] Set up CloudWatch alarms for secret access
- [ ] Configure secret rotation (if applicable)

## Troubleshooting

### "Access Denied" Error

```bash
# Check IAM permissions
aws sts get-caller-identity
aws secretsmanager get-secret-value --secret-id ANTHROPIC_API_KEY

# Verify instance profile
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

### "Secret Not Found"

```bash
# Check region
aws secretsmanager list-secrets --region us-east-1

# Verify secret name
aws secretsmanager describe-secret --secret-id devops-agent/secrets
```

### Application Not Loading Secrets

Check logs:

```bash
# In app startup logs, you should see:
# "Loading secrets from AWS Secrets Manager..."
# "✓ Loaded secret: ANTHROPIC_API_KEY"

# If not, check:
tail -f logs/agent.log
python -c "from services.secrets_manager import get_anthropic_api_key; print(get_anthropic_api_key())"
```

## Cost Considerations

AWS Secrets Manager pricing:
- $0.40 per secret per month
- $0.05 per 10,000 API calls

For a typical application with 5 secrets and 1000 API calls/day:
- Storage: 5 × $0.40 = $2.00/month
- API calls: 30,000 × $0.05/10,000 = $0.15/month
- **Total: ~$2.15/month**

To reduce costs, use caching (already implemented in `SecretsManager` class).

## References

- [AWS Secrets Manager Documentation](https://docs.aws.amazon.com/secretsmanager/)
- [Boto3 Secrets Manager API](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/secretsmanager.html)
- [Best Practices for AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
