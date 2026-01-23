# AWS Secrets Manager Setup - Complete! ✓

## Your Current Setup

### IAM Configuration ✓
- **AWS Account**: 336670698034
- **IAM User**: abi
- **Permissions**:
  - EC2 Full Access (attached policy)
  - Secrets Manager Access (inline policy)
- **Status**: Verified and working!

### Existing Secrets ✓
- **Secret Name**: `ANTHROPIC_API_KEY`
- **Format**: JSON (recommended format)
- **Region**: us-east-1
- **Current Keys**:
  - ✓ ANTHROPIC_API_KEY (configured)

### Missing Keys (Optional)
You may want to add these to your JSON secret:
- SECRET_KEY (Flask secret key) - **Recommended**
- STRIPE_SECRET_KEY (if using Stripe)
- STRIPE_PUBLISHABLE_KEY (if using Stripe)
- DATABASE_URL (database connection string)
- GITHUB_TOKEN (if using GitHub API)

## Quick Start Guide

### Option 1: Interactive Setup (Recommended)

Run the helper script:

```bash
python update_secrets.py
```

This will:
1. Show your current secrets
2. Help you add missing secrets
3. Generate a secure SECRET_KEY for you
4. Update AWS Secrets Manager

### Option 2: Manual Setup

#### Step 1: Generate a SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output (64 characters).

#### Step 2: Update Your Secret in AWS

```bash
# Method A: Use AWS CLI with inline JSON
aws secretsmanager update-secret ^
  --secret-id ANTHROPIC_API_KEY ^
  --secret-string "{\"ANTHROPIC_API_KEY\":\"sk-ant-api03-your-key\",\"SECRET_KEY\":\"paste-generated-key-here\",\"DATABASE_URL\":\"sqlite:///instance/devops.db\"}" ^
  --region us-east-1

# Method B: Create a secrets.json file and use it
# 1. Create secrets.json:
{
  "ANTHROPIC_API_KEY": "sk-ant-api03-your-actual-key",
  "SECRET_KEY": "your-generated-64-char-key",
  "DATABASE_URL": "sqlite:///instance/devops.db"
}

# 2. Update from file:
aws secretsmanager update-secret --secret-id ANTHROPIC_API_KEY --secret-string file://secrets.json --region us-east-1
```

### Option 3: AWS Console

1. Go to AWS Secrets Manager: https://us-east-1.console.aws.amazon.com/secretsmanager/
2. Click on `ANTHROPIC_API_KEY`
3. Click "Retrieve secret value"
4. Click "Edit"
5. Update the JSON to include all secrets
6. Click "Save"

## Integration Steps

### Step 1: Test Current Integration

```bash
# Test retrieval
python -c "from services.secrets_manager import get_anthropic_api_key; print(get_anthropic_api_key()[:20] + '...')"

# Run full test suite
python test_secrets_manager.py
```

### Step 2: Update app.py

Add this code at the top of `app.py` (after imports, before creating Flask app):

```python
import os

def init_app_secrets():
    """Initialize secrets from AWS Secrets Manager or .env"""
    flask_env = os.environ.get('FLASK_ENV', 'development')

    if flask_env == 'production':
        print("Loading secrets from AWS Secrets Manager...")
        try:
            from services.secrets_manager import get_secrets_manager
            sm = get_secrets_manager(region_name='us-east-1')
            secrets = sm.get_secret_json('ANTHROPIC_API_KEY')

            if secrets:
                for key, value in secrets.items():
                    if value:
                        os.environ[key] = value
                        print(f"  Loaded: {key}")
                print("Secrets loaded successfully!")
            else:
                print("Warning: No secrets found")
                from dotenv import load_dotenv
                load_dotenv()
        except Exception as e:
            print(f"Warning: {e}")
            print("Falling back to .env file...")
            from dotenv import load_dotenv
            load_dotenv()
    else:
        print("Development mode: Loading from .env file...")
        from dotenv import load_dotenv
        load_dotenv()

# Initialize secrets
init_app_secrets()

# Now create Flask app
app = Flask(__name__)

# Rest of your configuration...
```

### Step 3: Test Locally

```bash
# Test development mode (uses .env)
python app.py
# Should output: "Development mode: Loading from .env file..."

# Test production mode (uses AWS Secrets Manager)
set FLASK_ENV=production
python app.py
# Should output: "Loading secrets from AWS Secrets Manager..."
# Should output: "  Loaded: ANTHROPIC_API_KEY"
# Should output: "  Loaded: SECRET_KEY" (if added)
# Should output: "Secrets loaded successfully!"
```

## Production Deployment

### For EC2 Deployment

1. **Ensure EC2 Instance Has IAM Role**
   - Attach the same Secrets Manager policy to the EC2 instance role
   - Or use your IAM credentials on the instance

2. **Update Environment Variables**
   ```bash
   export FLASK_ENV=production
   export AWS_DEFAULT_REGION=us-east-1
   ```

3. **Deploy**
   ```bash
   cd /opt/devops-agent
   git pull
   sudo systemctl restart devops-agent
   ```

### For Elastic Beanstalk

```bash
eb setenv FLASK_ENV=production AWS_DEFAULT_REGION=us-east-1
eb deploy
```

## Verification Checklist

- [x] IAM user/role has Secrets Manager permissions
- [x] Secret exists in AWS Secrets Manager
- [x] Secret is in JSON format
- [x] Can retrieve secret from AWS
- [ ] SECRET_KEY added to secret (run `python update_secrets.py`)
- [ ] Tested with `python test_secrets_manager.py`
- [ ] Updated `app.py` with initialization code
- [ ] Tested locally in development mode
- [ ] Tested locally in production mode
- [ ] Ready for production deployment

## Useful Commands

```bash
# View current secrets (masked)
python update_secrets.py

# List secrets in AWS
aws secretsmanager list-secrets --region us-east-1

# Get secret value
aws secretsmanager get-secret-value --secret-id ANTHROPIC_API_KEY --region us-east-1

# Test Python integration
python -c "from services.secrets_manager import get_all_secrets; import json; print(json.dumps(get_all_secrets(), indent=2))"

# Generate new SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

## Files Created

```
devops-agent/
├── services/
│   └── secrets_manager.py          # Core secrets management (✓ Working)
├── test_secrets_manager.py          # Test suite
├── update_secrets.py                # Helper to add secrets (run this!)
├── verify_iam_setup.py              # IAM verification
├── AWS_SECRETS_MANAGER_SETUP.md     # Full setup guide
├── INTEGRATE_SECRETS_MANAGER.md     # Integration guide
├── NEXT_STEPS_SECRETS.md            # Next steps guide
├── SECRETS_SETUP_COMPLETE.md        # This file
└── .claude/skills/
    └── secrets-mgmt.md              # Claude skill for secrets management
```

## Next Steps

1. **Add missing secrets** (recommended):
   ```bash
   python update_secrets.py
   ```
   Choose option 1 to add all required secrets.

2. **Test the integration**:
   ```bash
   python test_secrets_manager.py
   ```

3. **Update app.py** with the initialization code above.

4. **Test locally**:
   ```bash
   python app.py
   ```

5. **Deploy to production** when ready.

## Support

- Full setup guide: `AWS_SECRETS_MANAGER_SETUP.md`
- Integration guide: `INTEGRATE_SECRETS_MANAGER.md`
- Use the skill: "Use secrets-mgmt to help with AWS Secrets Manager"

Your IAM setup is perfect! Just run `python update_secrets.py` to complete the configuration.
