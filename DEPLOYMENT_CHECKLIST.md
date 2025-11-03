# Deployment Checklist for DevOps Agent

## Pre-Deployment Changes Required

### 1. Database Migration (Critical)
**Current:** SQLite (`devops_agent.db`)
**Required:** PostgreSQL or MySQL for production

**Changes needed in `app.py`:**
```python
# Change from:
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///devops_agent.db'

# To:
import os
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///devops_agent.db'
```

### 2. Environment Variables Setup
Create `.env` file with all secrets (DO NOT commit to git):
- ANTHROPIC_API_KEY
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- STRIPE_SECRET_KEY
- STRIPE_PUBLISHABLE_KEY
- SECRET_KEY (Flask session secret)
- DATABASE_URL (provided by hosting platform)

### 3. Add Requirements File
Create `requirements.txt`:
```bash
cd /c/Users/shitt/Downloads/devops-agent
pip freeze > requirements.txt
```

### 4. Add Procfile (for Railway/Render/Heroku)
```
web: gunicorn app:app
```

Install gunicorn:
```bash
pip install gunicorn
pip freeze > requirements.txt
```

### 5. Security Improvements
- [ ] Remove hardcoded API keys from config/.env (use platform environment variables)
- [ ] Set DEBUG=False for production
- [ ] Use strong SECRET_KEY
- [ ] Enable HTTPS only
- [ ] Add rate limiting

### 6. Add .gitignore
```
*.db
*.db-journal
__pycache__/
*.py[cod]
*$py.class
.env
config/.env
venv/
instance/
.DS_Store
*.log
```

### 7. Create Dockerfile (optional, for ECS/Cloud Run)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "app:app"]
```

## Deployment Steps

### Railway Deployment
1. Push code to GitHub
2. Go to https://railway.app
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repo
5. Add PostgreSQL database
6. Set environment variables
7. Deploy!

### Render Deployment
1. Push code to GitHub
2. Go to https://render.com
3. Click "New Web Service"
4. Connect GitHub repo
5. Set build command: `pip install -r requirements.txt`
6. Set start command: `gunicorn app:app`
7. Add PostgreSQL database
8. Set environment variables
9. Deploy!

### AWS Elastic Beanstalk
1. Install EB CLI: `pip install awsebcli`
2. Initialize: `eb init -p python-3.11 devops-agent`
3. Create environment: `eb create devops-agent-prod`
4. Set environment variables: `eb setenv KEY=VALUE`
5. Deploy: `eb deploy`

## Post-Deployment Testing
- [ ] Test user registration/login
- [ ] Test chat functionality
- [ ] Test AWS/GCP integrations
- [ ] Test Stripe billing
- [ ] Monitor logs for errors
- [ ] Test with real API keys
- [ ] Load testing

## Monitoring & Maintenance
- Set up error tracking (Sentry)
- Monitor API usage (Claude, Stripe)
- Database backups
- SSL certificate renewal (auto on most platforms)
- Regular security updates

## Estimated Costs

### Railway (Recommended for MVP)
- Starter: $5/month
- Pro: $20/month
- Includes: 8GB RAM, PostgreSQL, auto-scaling

### Render
- Free tier: $0/month (with limitations)
- Starter: $7/month
- Pro: $25/month

### AWS Elastic Beanstalk
- t3.small: ~$15/month (EC2)
- RDS db.t3.micro: ~$15/month
- Load Balancer: ~$20/month
- **Total: ~$50/month**

### Google Cloud Run
- Pay per use
- Low traffic: $0-5/month
- Medium traffic: $10-30/month

## Need Help?
Contact your DevOps team or refer to platform documentation.
