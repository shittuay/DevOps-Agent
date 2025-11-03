# 🚀 Deploy to Railway - Step by Step Guide

## ✅ What We've Already Done

Your app is now **deployment-ready**! Here's what's been configured:

- ✅ **Procfile** created (tells Railway how to run your app)
- ✅ **requirements.txt** generated (all Python dependencies)
- ✅ **.gitignore** added (protects your secrets)
- ✅ **PostgreSQL support** added to app.py
- ✅ **psycopg2** installed (PostgreSQL driver)
- ✅ **gunicorn** installed (production server)

---

## 🎯 Deployment Steps (10 minutes)

### Step 1: Push to GitHub

```bash
cd /c/Users/shitt/Downloads/devops-agent

# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Prepare for Railway deployment"

# Create GitHub repo and push
# Go to https://github.com/new
# Create a new repository (e.g., "devops-agent")
# Then:
git remote add origin https://github.com/YOUR_USERNAME/devops-agent.git
git branch -M main
git push -u origin main
```

---

### Step 2: Deploy to Railway

1. **Go to Railway**: https://railway.app
2. **Sign up/Login** (use GitHub account for easier integration)
3. **Click "New Project"**
4. **Select "Deploy from GitHub repo"**
5. **Select your `devops-agent` repository**
6. Railway will automatically detect it's a Python app!

---

### Step 3: Add PostgreSQL Database

1. In your Railway project, click **"+ New"**
2. Select **"Database" → "PostgreSQL"**
3. Railway will automatically:
   - Create the database
   - Add `DATABASE_URL` to your environment variables
   - Link it to your app

---

### Step 4: Configure Environment Variables

In Railway, go to your web service → **Variables** tab and add:

```bash
# Required
ANTHROPIC_API_KEY=your_claude_api_key_here
SECRET_KEY=generate_random_secret_key_here

# AWS Credentials (get these from your AWS IAM console)
AWS_ACCESS_KEY_ID=your_aws_access_key_id_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key_here
AWS_DEFAULT_REGION=us-east-1

# Stripe (for payments)
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key
STRIPE_WEBHOOK_SECRET=your_webhook_secret

# All your Stripe price IDs from config/.env
STRIPE_PRICE_STARTER=price_1SOl4OBm973hpEK8LgG0oomP
STRIPE_PRICE_PROFESSIONAL=price_1SOl4PBm973hpEK8GVeHjUuH
# ... (add all other Stripe price IDs)

# Flask config
FLASK_ENV=production

# Database (automatically added by Railway)
# DATABASE_URL=postgresql://... (Railway adds this automatically)
```

**To generate SECRET_KEY:**
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### Step 5: Deploy!

1. Railway will automatically deploy when you push to GitHub
2. Click **"Deploy"** if it doesn't start automatically
3. Wait 2-3 minutes for deployment
4. You'll get a URL like: `https://devops-agent-production.up.railway.app`

---

### Step 6: Initialize Database

After first deployment, you need to create database tables:

**Option A: Railway CLI**
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to your project
railway link

# Run database initialization
railway run python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized!')"
```

**Option B: Add init endpoint** (temporary, remove after use)
Add this to app.py temporarily:
```python
@app.route('/init-db-secret-endpoint-12345')
def init_db():
    db.create_all()
    return 'Database initialized!'
```
Then visit: `https://your-app.railway.app/init-db-secret-endpoint-12345`

---

## 🎉 Your App is Live!

Visit your Railway URL and test:
- ✅ User registration
- ✅ Login
- ✅ Chat with Claude
- ✅ AWS/GCP operations
- ✅ Billing (if Stripe is configured)

---

## 💰 Railway Costs

- **Starter Plan**: $5/month
- **Pro Plan**: $20/month
- Includes: Web service + PostgreSQL + bandwidth

**Free Trial**: Railway gives you $5 credit to start!

---

## 🔄 Auto-Deploy on Push

Railway automatically redeploys when you push to GitHub:

```bash
# Make changes to your code
git add .
git commit -m "Add new feature"
git push

# Railway automatically deploys! 🚀
```

---

## 📊 Monitoring

Railway provides:
- **Logs**: Real-time application logs
- **Metrics**: CPU, memory, network usage
- **Deployments**: History of all deployments
- **Health checks**: Automatic uptime monitoring

Access these in your Railway dashboard.

---

## 🐛 Troubleshooting

### Deployment fails?
1. Check **Logs** in Railway dashboard
2. Verify all environment variables are set
3. Ensure `requirements.txt` is complete

### Database errors?
1. Make sure you ran `db.create_all()`
2. Check `DATABASE_URL` is set
3. Verify PostgreSQL service is running

### App not responding?
1. Check if service is running in Railway dashboard
2. View logs for errors
3. Ensure `Procfile` is correct: `web: gunicorn app:app`

---

## 🔐 Security Checklist

Before going live:
- [ ] Remove any test API keys
- [ ] Use production Stripe keys (not test keys)
- [ ] Set strong SECRET_KEY
- [ ] Enable HTTPS only (Railway does this automatically)
- [ ] Review .gitignore (ensure config/.env is ignored)
- [ ] Set up database backups in Railway
- [ ] Configure Stripe webhooks to Railway URL

---

## 📝 Next Steps

1. **Custom Domain**: Add your own domain in Railway settings
2. **Monitoring**: Set up error tracking (Sentry)
3. **Backups**: Configure automated database backups
4. **Scaling**: Increase resources if needed
5. **CDN**: Add Cloudflare for better performance

---

## 🆘 Need Help?

- **Railway Docs**: https://docs.railway.app
- **Railway Discord**: https://discord.gg/railway
- **Your deployment guide**: See `DEPLOYMENT_CHECKLIST.md`

---

**You're ready to deploy! 🎉**

Questions? Issues? Check the logs first, then Railway's excellent documentation.
