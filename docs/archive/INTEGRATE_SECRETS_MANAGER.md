# Integrating AWS Secrets Manager into app.py

## Quick Integration Guide

This guide shows how to modify `app.py` to use AWS Secrets Manager for production deployments.

## Step 1: Add Import at Top of app.py

Add this code near the top of `app.py`, right after the imports:

```python
import os
import sys

# ... existing imports ...

# Initialize secrets based on environment
def init_app_secrets():
    """Initialize application secrets from AWS Secrets Manager or .env"""
    flask_env = os.environ.get('FLASK_ENV', 'development')

    if flask_env == 'production':
        print("🔐 Loading secrets from AWS Secrets Manager...")
        try:
            from services.secrets_manager import init_secrets
            init_secrets()
            print("✅ Secrets loaded from AWS Secrets Manager")
        except Exception as e:
            print(f"⚠️  Failed to load from AWS Secrets Manager: {str(e)}")
            print("   Falling back to environment variables...")
    else:
        print("🔐 Loading secrets from .env file (development mode)...")
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Secrets loaded from .env file")

# Initialize secrets before creating Flask app
init_app_secrets()

# Now create Flask app
app = Flask(__name__)
```

## Step 2: Update Configuration Section

Find the configuration section in `app.py` and update it:

```python
# Before (loading from environment):
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')

# After (secrets already loaded by init_app_secrets):
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY not found in environment or Secrets Manager")

# Do the same for other secrets:
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found")

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')
```

## Step 3: Test the Integration

### Local Testing (Development Mode)

```bash
# Make sure FLASK_ENV is not set to production
unset FLASK_ENV

# Run the app
python app.py

# Should see:
# 🔐 Loading secrets from .env file (development mode)...
# ✅ Secrets loaded from .env file
```

### Production Mode Testing (with AWS Secrets Manager)

```bash
# Set production mode
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# Make sure AWS credentials are configured
aws configure

# Run the app
python app.py

# Should see:
# 🔐 Loading secrets from AWS Secrets Manager...
# ✓ Loaded secret: ANTHROPIC_API_KEY
# ✓ Loaded secret: SECRET_KEY
# ... more secrets ...
# ✅ Secrets loaded from AWS Secrets Manager
```

## Complete Example

Here's a complete example of the modified section in `app.py`:

```python
"""
Flask Web Interface for DevOps Agent with API Key Configuration and Authentication
"""
import os
import sys
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
import secrets
import logging

# ============================================================================
# SECRETS INITIALIZATION
# ============================================================================

def init_app_secrets():
    """
    Initialize application secrets from AWS Secrets Manager (production)
    or .env file (development)
    """
    flask_env = os.environ.get('FLASK_ENV', 'development')

    if flask_env == 'production':
        print("🔐 Loading secrets from AWS Secrets Manager...")
        try:
            from services.secrets_manager import init_secrets
            init_secrets()
            print("✅ Secrets loaded successfully from AWS Secrets Manager")
            return True
        except Exception as e:
            print(f"⚠️  Failed to load from AWS Secrets Manager: {str(e)}")
            print("   Falling back to environment variables...")
            return False
    else:
        print("🔐 Loading secrets from .env file (development mode)...")
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Secrets loaded from .env file")
        return True

# Initialize secrets before creating Flask app
init_app_secrets()

# ============================================================================
# FLASK APP INITIALIZATION
# ============================================================================

app = Flask(__name__)

# Security configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    # Generate a random secret key for development only
    if os.environ.get('FLASK_ENV') != 'production':
        app.config['SECRET_KEY'] = secrets.token_hex(32)
        print("⚠️  Using generated SECRET_KEY (development only)")
    else:
        raise ValueError("SECRET_KEY not found in environment or Secrets Manager")

# Anthropic API configuration
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    print("⚠️  ANTHROPIC_API_KEY not found. Chat functionality will not work.")

# Stripe configuration (optional)
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY')

if STRIPE_SECRET_KEY:
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        STRIPE_ENABLED = True
        print("✅ Stripe integration enabled")
    except ImportError:
        STRIPE_ENABLED = False
        print("⚠️  Stripe not installed")
else:
    STRIPE_ENABLED = False
    print("⚠️  Stripe not configured")

# Database configuration
if os.environ.get('FLASK_ENV') == 'production':
    # Production: Use PostgreSQL from DATABASE_URL
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Fix for Heroku postgres:// -> postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        raise ValueError("DATABASE_URL not found in production environment")
else:
    # Development: Use SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/devops.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ... rest of app.py continues ...
```

## Step 4: Update Deployment Scripts

### For EC2 Deployment

Update `deploy_ec2.sh` to set environment variables:

```bash
#!/bin/bash

# Set production environment
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# Don't copy .env file to production
# (Secrets will be loaded from AWS Secrets Manager)

# Rest of deployment script...
```

### For Elastic Beanstalk

```bash
# Set environment variables
eb setenv FLASK_ENV=production AWS_DEFAULT_REGION=us-east-1

# Deploy
eb deploy
```

### For systemd Service

Update `/etc/systemd/system/devops-agent.service`:

```ini
[Unit]
Description=DevOps Agent Flask Application
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/devops-agent
Environment="FLASK_ENV=production"
Environment="AWS_DEFAULT_REGION=us-east-1"
ExecStart=/opt/devops-agent/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart devops-agent
```

## Step 5: Verify Integration

### Run Test Script

```bash
python test_secrets_manager.py
```

Expected output:
```
============================================================
AWS Secrets Manager Integration Test
============================================================

============================================================
Prerequisites Check
============================================================
✅ AWS credentials configured
   Account: 123456789012
   User/Role: arn:aws:iam::123456789012:user/your-user
✅ AWS region: us-east-1
   FLASK_ENV: production

============================================================
Test 1: Individual Secret Retrieval
============================================================
✅ Successfully retrieved ANTHROPIC_API_KEY: sk-ant-api...

... more tests ...

🎉 All tests passed!
```

### Check Application Startup

```bash
python app.py
```

Look for these messages:
```
🔐 Loading secrets from AWS Secrets Manager...
✓ Loaded secret: ANTHROPIC_API_KEY
✓ Loaded secret: SECRET_KEY
✓ Loaded secret: STRIPE_SECRET_KEY
✓ Loaded secret: DATABASE_URL
✅ Secrets loaded successfully from AWS Secrets Manager
✅ Stripe integration enabled
 * Running on http://127.0.0.1:5000
```

## Troubleshooting

### "Failed to load from AWS Secrets Manager"

1. Check AWS credentials:
   ```bash
   aws sts get-caller-identity
   ```

2. Check IAM permissions:
   ```bash
   aws secretsmanager get-secret-value --secret-id devops-agent/prod/secrets
   ```

3. Check region:
   ```bash
   echo $AWS_DEFAULT_REGION
   ```

### "SECRET_KEY not found"

Make sure the secret exists in AWS Secrets Manager:

```bash
aws secretsmanager list-secrets --region us-east-1 | grep SECRET_KEY
```

If using JSON secret, make sure it includes SECRET_KEY:

```bash
aws secretsmanager get-secret-value \
  --secret-id devops-agent/prod/secrets \
  --query SecretString \
  --output text | jq
```

### Application Falls Back to .env

This happens when:
- FLASK_ENV is not set to "production"
- AWS credentials are not available
- IAM permissions are insufficient
- Secrets don't exist in Secrets Manager

Check the startup logs to see which condition is causing the fallback.

## Best Practices

1. **Use different secrets for each environment:**
   - `devops-agent/dev/secrets`
   - `devops-agent/staging/secrets`
   - `devops-agent/prod/secrets`

2. **Never commit .env to git:**
   ```bash
   echo ".env" >> .gitignore
   ```

3. **Rotate secrets regularly:**
   ```bash
   aws secretsmanager update-secret \
     --secret-id devops-agent/prod/secrets \
     --secret-string "$(cat new-secrets.json)"
   ```

4. **Monitor secret access:**
   ```bash
   aws cloudtrail lookup-events \
     --lookup-attributes AttributeKey=ResourceName,AttributeValue=devops-agent/prod/secrets
   ```

5. **Use caching to reduce API calls:**
   The `SecretsManager` class already implements caching by default.

## Next Steps

1. ✅ Create secrets in AWS Secrets Manager
2. ✅ Configure IAM permissions
3. ✅ Add `services/secrets_manager.py` to project
4. ✅ Modify `app.py` with the code above
5. ✅ Test locally with AWS credentials
6. ✅ Deploy to staging
7. ✅ Verify in staging
8. ✅ Deploy to production
9. ✅ Remove .env from production servers
10. ✅ Document the setup for your team

## References

- Full setup guide: `AWS_SECRETS_MANAGER_SETUP.md`
- Secrets manager code: `services/secrets_manager.py`
- Test script: `test_secrets_manager.py`
- Skills guide: `.claude/skills/secrets-mgmt.md`
