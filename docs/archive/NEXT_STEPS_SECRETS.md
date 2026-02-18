# Next Steps: Complete AWS Secrets Manager Integration

## Current Status ✅

Your IAM setup is working correctly:
- ✅ AWS credentials configured (Account: 336670698034, User: abi)
- ✅ EC2 Full Access policy attached
- ✅ Secrets Manager inline policy configured
- ✅ Can list and retrieve secrets
- ✅ Secret `ANTHROPIC_API_KEY` exists with JSON format

## Step 1: Add More Secrets to Your JSON Object

Your current secret has:
```json
{
  "ANTHROPIC_API_KEY": "sk-ant-api03-jo..."
}
```

Update it to include all application secrets:

```bash
# Windows Command Prompt / PowerShell:
aws secretsmanager update-secret ^
  --secret-id ANTHROPIC_API_KEY ^
  --secret-string "{\"ANTHROPIC_API_KEY\":\"sk-ant-api03-your-key\",\"SECRET_KEY\":\"your-flask-secret-key-here\",\"STRIPE_SECRET_KEY\":\"sk_live_your-stripe-key\",\"STRIPE_PUBLISHABLE_KEY\":\"pk_live_your-stripe-key\",\"DATABASE_URL\":\"sqlite:///instance/devops.db\"}" ^
  --region us-east-1

# Or use a file:
# 1. Create secrets.json:
{
  "ANTHROPIC_API_KEY": "sk-ant-api03-your-actual-key-here",
  "SECRET_KEY": "generate-random-32-character-string",
  "STRIPE_SECRET_KEY": "sk_live_your-key-if-you-have-stripe",
  "STRIPE_PUBLISHABLE_KEY": "pk_live_your-key-if-you-have-stripe",
  "AWS_ACCESS_KEY_ID": "optional-if-different-from-profile",
  "AWS_SECRET_ACCESS_KEY": "optional-if-different-from-profile",
  "GITHUB_TOKEN": "ghp_your-github-token-if-needed",
  "DATABASE_URL": "sqlite:///instance/devops.db"
}

# 2. Update secret from file:
aws secretsmanager update-secret --secret-id ANTHROPIC_API_KEY --secret-string file://secrets.json --region us-east-1
```

### Generate a Secure SECRET_KEY

```bash
# Windows PowerShell:
python -c "import secrets; print(secrets.token_hex(32))"

# Or Windows Command Prompt:
python -c "import secrets; print(secrets.token_hex(32))"
```

Use the output as your SECRET_KEY value.

## Step 2: Update services/secrets_manager.py

The code needs a small modification to work with your secret name:

```python
# In services/secrets_manager.py, update get_all_secrets():

def get_all_secrets() -> Dict[str, str]:
    """
    Get all application secrets from AWS Secrets Manager
    """
    # Try environment variables first (local development)
    if os.environ.get('USE_ENV_SECRETS', 'false').lower() == 'true':
        return {
            'ANTHROPIC_API_KEY': os.environ.get('ANTHROPIC_API_KEY'),
            'SECRET_KEY': os.environ.get('SECRET_KEY'),
            # ... rest
        }

    # Try AWS Secrets Manager (production)
    try:
        sm = get_secrets_manager()
        # Use your actual secret name: ANTHROPIC_API_KEY (which contains all secrets)
        secrets = sm.get_secret_json('ANTHROPIC_API_KEY')
        return secrets or {}
    except ClientError:
        return {}
```

## Step 3: Test the Integration

```bash
# Navigate to project directory
cd /c/Users/shitt/Downloads/devops-agent

# Run test script
python test_secrets_manager.py
```

Expected output:
```
============================================================
Test 1: Individual Secret Retrieval
============================================================
[OK] Successfully retrieved ANTHROPIC_API_KEY: sk-ant-ap...

============================================================
Test 2: JSON Secret Retrieval
============================================================
[OK] Successfully retrieved JSON secret with 3 keys:
   - ANTHROPIC_API_KEY: sk-ant-api...
   - SECRET_KEY: 7a8f9b2c...
   - STRIPE_SECRET_KEY: sk_live_...

[SUCCESS] All tests passed!
```

## Step 4: Update app.py

Add this at the very top of `app.py` (after imports):

```python
import os
import sys

# Initialize secrets based on environment
def init_app_secrets():
    """Initialize application secrets from AWS Secrets Manager or .env"""
    flask_env = os.environ.get('FLASK_ENV', 'development')

    if flask_env == 'production':
        print("Loading secrets from AWS Secrets Manager...")
        try:
            from services.secrets_manager import get_secrets_manager
            sm = get_secrets_manager(region_name='us-east-1')
            secrets = sm.get_secret_json('ANTHROPIC_API_KEY')

            # Set secrets as environment variables
            for key, value in secrets.items():
                if value:
                    os.environ[key] = value
                    print(f"  Loaded: {key}")

            print("Secrets loaded successfully from AWS Secrets Manager")
        except Exception as e:
            print(f"Warning: Failed to load from AWS Secrets Manager: {e}")
            print("Falling back to .env file...")
            from dotenv import load_dotenv
            load_dotenv()
    else:
        print("Loading secrets from .env file (development mode)...")
        from dotenv import load_dotenv
        load_dotenv()

# Initialize secrets BEFORE creating Flask app
init_app_secrets()

# Now create Flask app
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY not found in environment")

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY not found")

# ... rest of app.py
```

## Step 5: Test Locally

```bash
# Test in development mode (uses .env)
python app.py
# Should see: "Loading secrets from .env file (development mode)..."

# Test in production mode (uses AWS Secrets Manager)
set FLASK_ENV=production
python app.py
# Should see: "Loading secrets from AWS Secrets Manager..."
```

## Step 6: Deploy to Production

When deploying to EC2:

```bash
# SSH to EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Update code
cd /opt/devops-agent
git pull

# Set environment variables
export FLASK_ENV=production
export AWS_DEFAULT_REGION=us-east-1

# Restart service
sudo systemctl restart devops-agent

# Check logs
sudo journalctl -u devops-agent -f
```

## Troubleshooting

### "Cannot retrieve secret"

Check permissions:
```bash
aws secretsmanager get-secret-value --secret-id ANTHROPIC_API_KEY --region us-east-1
```

### "JSON decode error"

Check secret format:
```bash
aws secretsmanager get-secret-value --secret-id ANTHROPIC_API_KEY --query SecretString --output text
```

Should be valid JSON like: `{"ANTHROPIC_API_KEY":"sk-ant-..."}`

### "Import error: No module named services.secrets_manager"

Make sure you're in the project root and `services/secrets_manager.py` exists.

## Quick Test Commands

```bash
# Test AWS access
aws sts get-caller-identity

# List secrets
aws secretsmanager list-secrets --region us-east-1

# Get secret value
aws secretsmanager get-secret-value --secret-id ANTHROPIC_API_KEY --region us-east-1

# Update secret
aws secretsmanager update-secret --secret-id ANTHROPIC_API_KEY --secret-string '{"key":"value"}' --region us-east-1

# Test Python integration
python -c "from services.secrets_manager import get_secrets_manager; sm = get_secrets_manager(); print(sm.get_secret_json('ANTHROPIC_API_KEY'))"
```

## Summary

You have:
- ✅ IAM user with proper permissions
- ✅ Secret created in AWS Secrets Manager
- ✅ Can retrieve secrets successfully

Next:
1. Add all required secrets to your JSON object
2. Update `services/secrets_manager.py` to use 'ANTHROPIC_API_KEY' as secret name
3. Test with `python test_secrets_manager.py`
4. Update `app.py` with initialization code
5. Test locally
6. Deploy to production

Your setup is solid! Just need to complete the integration steps above.
