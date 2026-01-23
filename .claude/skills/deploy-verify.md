---
name: deploy-verify
description: Deploy and verify the DevOps Agent application across different platforms (AWS EC2, Elastic Beanstalk, Railway, Render, Netlify). Use when deploying the application or verifying deployment health.
---

# Deployment and Verification Guide

## Overview

This skill guides you through deploying the DevOps Agent Flask application to various platforms and verifying the deployment is healthy.

## Supported Platforms

- AWS Elastic Beanstalk
- AWS EC2 (manual deployment)
- Railway
- Render
- Netlify Functions

## Pre-Deployment Checklist

### Configuration Checks

- [ ] Environment variables set in `.env`
- [ ] Secret key configured
- [ ] Database configured (SQLite for dev, PostgreSQL for prod)
- [ ] Anthropic API key set
- [ ] AWS credentials configured (if using AWS tools)
- [ ] Stripe keys set (if using payments)
- [ ] GitHub secrets configured (for CI/CD)

### Code Checks

```bash
# 1. Run tests
pytest tests/ -v

# 2. Check for syntax errors
python -m py_compile app.py

# 3. Verify dependencies
pip install -r requirements.txt

# 4. Test locally
python app.py
# Visit http://localhost:5000
```

### Security Checks

- [ ] CSRF protection enabled
- [ ] Rate limiting configured
- [ ] HTTPS enforced (production)
- [ ] Secrets not in version control
- [ ] Database backups configured

## Deployment Methods

### AWS Elastic Beanstalk

#### Initial Setup

```bash
# 1. Install EB CLI
pip install awsebcli

# 2. Initialize EB application
eb init -p python-3.10 devops-agent --region us-east-1

# 3. Configure environment
eb create devops-agent-prod --instance-type t3.small
```

#### Deploy

```bash
# 1. Set environment variables
eb setenv ANTHROPIC_API_KEY=your_key \
          SECRET_KEY=your_secret \
          FLASK_ENV=production

# 2. Deploy
eb deploy

# 3. Open application
eb open

# 4. Check logs
eb logs
```

#### Configuration Files

Ensure these files exist:
- `.ebextensions/` - EB configuration
- `.elasticbeanstalk/config.yml` - EB CLI config

### AWS EC2 Manual Deployment

Reference: `DEPLOY_TO_EC2.md`, `deploy_ec2.sh`

```bash
# 1. SSH to EC2 instance
ssh -i devops-agent-key.pem ubuntu@your-ec2-ip

# 2. Run deployment script
./deploy_ec2.sh

# 3. Check service status
sudo systemctl status devops-agent

# 4. View logs
sudo journalctl -u devops-agent -f
```

#### EC2 Deployment Script

The `deploy_ec2.sh` script handles:
- Installing dependencies
- Setting up virtual environment
- Configuring systemd service
- Setting up nginx reverse proxy
- SSL certificate setup

### Railway

Reference: `DEPLOY_TO_RAILWAY.md`

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Initialize project
railway init

# 4. Deploy
railway up

# 5. Set environment variables
railway variables set ANTHROPIC_API_KEY=your_key

# 6. Open application
railway open
```

Railway automatically:
- Detects Python and installs dependencies
- Runs the application
- Provides HTTPS domain

### Render

Reference: `DEPLOY_TO_RENDER.md`

1. **Create Render Account** at render.com

2. **Create Web Service**
   - Connect GitHub repository
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`

3. **Configure Environment**
   - Add environment variables in Render dashboard
   - Set PYTHON_VERSION=3.10

4. **Deploy**
   - Render auto-deploys on git push
   - Monitor build logs in dashboard

### Netlify Functions

Reference: `NETLIFY_DEPLOY.md`

```bash
# 1. Install Netlify CLI
npm install -g netlify-cli

# 2. Login
netlify login

# 3. Initialize
netlify init

# 4. Deploy
netlify deploy --prod

# 5. Set environment variables
netlify env:set ANTHROPIC_API_KEY your_key
```

Configuration file: `netlify.toml`

## Post-Deployment Verification

### Phase 1: Basic Health Checks

```bash
# 1. Check if app is running
curl -I https://your-app-url.com
# Should return 200 OK

# 2. Check home page loads
curl https://your-app-url.com
# Should return HTML

# 3. Check API endpoint
curl https://your-app-url.com/health
```

### Phase 2: Functionality Testing

#### Authentication
```bash
# Test signup endpoint
curl -X POST https://your-app-url.com/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test123!"}'

# Test login endpoint
curl -X POST https://your-app-url.com/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test123!"}'
```

#### Chat Functionality
```bash
# Test chat endpoint (requires authentication)
curl -X POST https://your-app-url.com/chat \
  -H "Content-Type: application/json" \
  -H "Cookie: session=..." \
  -d '{"message":"Hello","conversation_id":1}'
```

### Phase 3: Integration Testing

Run the integration test script:

```bash
python test_integration.py
```

This tests:
- User registration
- Login/logout
- Chat functionality
- Conversation management
- Subscription features
- AWS/GCP integrations

### Phase 4: Performance Testing

```bash
# 1. Test response time
time curl https://your-app-url.com

# 2. Load testing with Apache Bench
ab -n 100 -c 10 https://your-app-url.com/

# 3. Monitor resource usage
# On EC2:
htop
# Check CPU and memory usage
```

### Phase 5: Security Verification

```bash
# 1. Check HTTPS is enforced
curl -I http://your-app-url.com
# Should redirect to HTTPS

# 2. Check security headers
curl -I https://your-app-url.com
# Look for: X-Content-Type-Options, X-Frame-Options, etc.

# 3. Test rate limiting
for i in {1..150}; do
  curl https://your-app-url.com/login
done
# Should get rate limited after ~100 requests

# 4. Test CSRF protection
curl -X POST https://your-app-url.com/login \
  -d "email=test@test.com&password=test"
# Should fail without CSRF token
```

### Phase 6: Database Verification

```bash
# 1. Check database is accessible
python verify_deployment.py

# 2. Verify tables exist
python -c "from models import db; from app import app; app.app_context().push(); print(db.engine.table_names())"

# 3. Check data integrity
python verify_tiers.py
```

### Phase 7: Monitoring Setup

#### CloudWatch (AWS)

```bash
# 1. Check CloudWatch logs
aws logs tail /aws/elasticbeanstalk/devops-agent-prod/var/log/web.stdout.log --follow

# 2. Set up alarms
aws cloudwatch put-metric-alarm \
  --alarm-name high-cpu \
  --alarm-description "Alert when CPU exceeds 80%" \
  --metric-name CPUUtilization \
  --threshold 80
```

#### Application Logs

```bash
# On EC2:
tail -f /var/log/devops-agent/app.log

# With Railway:
railway logs

# With Render:
# View logs in Render dashboard
```

## Verification Checklist

### Application Level
- [ ] Home page loads without errors
- [ ] Login/signup works
- [ ] Chat functionality works
- [ ] Conversations are saved
- [ ] User preferences persist
- [ ] Subscription system works

### Infrastructure Level
- [ ] HTTPS is enabled and enforced
- [ ] Database is accessible
- [ ] Static files are served
- [ ] Sessions persist correctly
- [ ] Rate limiting is active
- [ ] CSRF protection is working

### Integration Level
- [ ] Anthropic API connection works
- [ ] AWS integration works (if configured)
- [ ] GCP integration works (if configured)
- [ ] Kubernetes tools work (if configured)
- [ ] Stripe payments work (if configured)
- [ ] GitHub Actions deploy successfully

### Performance Level
- [ ] Response time < 2 seconds for most requests
- [ ] Memory usage is stable
- [ ] CPU usage is reasonable
- [ ] No memory leaks
- [ ] Database queries are optimized

## Troubleshooting Deployment Issues

### Application Won't Start

```bash
# 1. Check logs
eb logs  # EB
railway logs  # Railway
# Or check platform-specific logs

# 2. Verify Python version
python --version

# 3. Check dependencies
pip list

# 4. Test locally first
python app.py
```

### Database Connection Errors

```bash
# 1. Verify DATABASE_URL
echo $DATABASE_URL

# 2. Test connection
python -c "from models import db; from app import app; app.app_context().push(); db.create_all()"

# 3. Check database credentials
# Ensure user/password are correct
```

### Environment Variables Not Set

```bash
# EB:
eb printenv

# Railway:
railway variables

# Render:
# Check dashboard > Environment tab

# Manual fix:
eb setenv KEY=value
railway variables set KEY=value
```

### Static Files Not Loading

```bash
# 1. Check static file path
ls -la static/

# 2. Verify Flask serves static files
curl https://your-app-url.com/static/css/style.css

# 3. Check nginx config (for EC2)
sudo nginx -t
```

### SSL Certificate Issues

```bash
# 1. Check certificate
openssl s_client -connect your-domain.com:443

# 2. Renew Let's Encrypt certificate
sudo certbot renew

# 3. Check nginx SSL config
sudo cat /etc/nginx/sites-available/devops-agent
```

## Rollback Procedures

### Elastic Beanstalk

```bash
# List previous versions
eb appversion

# Rollback to previous version
eb deploy --version v1
```

### Railway

```bash
# Railway keeps deployment history
# Rollback in dashboard or redeploy previous commit
git revert HEAD
git push
```

### EC2

```bash
# 1. SSH to instance
ssh -i key.pem ubuntu@ip

# 2. Checkout previous version
cd /opt/devops-agent
git log --oneline
git checkout <previous-commit>

# 3. Restart service
sudo systemctl restart devops-agent
```

## Deployment Documentation

Reference these files for platform-specific guides:
- `DEPLOY_TO_AWS.md` - AWS Elastic Beanstalk
- `DEPLOY_TO_EC2.md` - AWS EC2 manual
- `DEPLOY_TO_RAILWAY.md` - Railway platform
- `DEPLOY_TO_RENDER.md` - Render platform
- `NETLIFY_DEPLOY.md` - Netlify Functions
- `VERIFY_DEPLOYMENT.md` - Verification procedures
- `DEPLOYMENT.md` - General deployment guide
- `GITHUB_SECRETS_SETUP.md` - CI/CD secrets

## Quick Commands

```bash
# Deploy to EB
eb deploy

# Deploy to EC2
./deploy_ec2.sh

# Deploy to Railway
railway up

# Check logs
eb logs  # EB
railway logs  # Railway
sudo journalctl -u devops-agent -f  # EC2

# Verify deployment
curl -I https://your-app-url.com
python test_integration.py
python verify_deployment.py

# Rollback
eb deploy --version previous
git revert HEAD && git push
```
