# 🚀 Deploy to Render - Quick Guide

## Why Render?
- Free tier available (750 hours/month free)
- Automatic HTTPS
- Easy PostgreSQL setup
- Auto-deploy from GitHub
- Great performance

---

## ✅ Prerequisites (Already Done!)

Your app is deployment-ready with:
- ✅ `Procfile` - Tells Render how to run your app
- ✅ `requirements.txt` - All Python dependencies
- ✅ `runtime.txt` - Python version specification
- ✅ `.gitignore` - Protects secrets
- ✅ PostgreSQL support in app.py
- ✅ Code pushed to GitHub: https://github.com/shittuay/DevOps-Agent

---

## 🎯 Deployment Steps (15 minutes)

### Step 1: Sign Up for Render

1. Go to **https://render.com**
2. Click **"Get Started"**
3. Sign up with your **GitHub account** (recommended for easy integration)
4. Authorize Render to access your repositories

---

### Step 2: Create a New Web Service

1. Click **"New +"** in the top right
2. Select **"Web Service"**
3. Connect your GitHub repository:
   - Click **"Connect account"** if needed
   - Find and select **"DevOps-Agent"** repository
4. Click **"Connect"**

---

### Step 3: Configure Your Web Service

Fill in the following settings:

**Basic Settings:**
- **Name**: `devops-agent` (or your preferred name)
- **Region**: Choose closest to you (e.g., Oregon, Frankfurt, Singapore)
- **Branch**: `main`
- **Root Directory**: (leave blank)
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: (leave as auto-detected from Procfile)

**Instance Type:**
- **Free** (for testing)
- **Starter** ($7/month) - recommended for production

Click **"Advanced"** to set environment variables (next step)

---

### Step 4: Add Environment Variables

Click **"Add Environment Variable"** and add these one by one:

```bash
# Required - Anthropic API
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Required - Flask Secret Key
SECRET_KEY=your_secret_key_here

# Required - AWS Credentials
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
AWS_DEFAULT_REGION=us-east-1

# Optional - Stripe (if using payments)
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_PUBLISHABLE_KEY=your_stripe_publishable_key
STRIPE_WEBHOOK_SECRET=your_webhook_secret

# Stripe Price IDs (copy from config/.env)
STRIPE_PRICE_STARTER=price_xxxxx
STRIPE_PRICE_PROFESSIONAL=price_xxxxx
STRIPE_PRICE_BUSINESS=price_xxxxx
STRIPE_PRICE_PACK_100=price_xxxxx
STRIPE_PRICE_PACK_250=price_xxxxx
STRIPE_PRICE_PACK_500=price_xxxxx
STRIPE_PRICE_PACK_1000=price_xxxxx

# Flask Environment
FLASK_ENV=production
```

**To generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

### Step 5: Add PostgreSQL Database

1. Click **"New +"** in the dashboard
2. Select **"PostgreSQL"**
3. Configure:
   - **Name**: `devops-agent-db`
   - **Database**: `devops_agent`
   - **User**: `devops_agent_user`
   - **Region**: Same as your web service
   - **Plan**: **Free** (for testing) or **Starter** ($7/month)
4. Click **"Create Database"**

Wait 1-2 minutes for database creation.

---

### Step 6: Link Database to Web Service

1. Go back to your **Web Service** settings
2. Scroll to **Environment Variables**
3. Click **"Add Environment Variable"**
4. Add:
   - **Key**: `DATABASE_URL`
   - **Value**: Click the **link icon** and select your PostgreSQL database
   - This will auto-populate with: `postgresql://user:pass@host/database`
5. Click **"Save Changes"**

---

### Step 7: Deploy!

1. Click **"Create Web Service"** at the bottom
2. Render will automatically:
   - Pull your code from GitHub
   - Install dependencies from `requirements.txt`
   - Start your app with gunicorn
3. **Wait 3-5 minutes** for the first deployment

You'll see build logs in real-time. Look for:
```
==> Build successful!
==> Deploying...
==> Your service is live 🎉
```

Your app URL will be: `https://devops-agent.onrender.com` (or your chosen name)

---

### Step 8: Initialize Database Tables

After successful deployment, you need to create database tables.

**Option 1: Using Render Shell** (Recommended)

1. Go to your web service dashboard
2. Click **"Shell"** in the top right
3. Run:
```bash
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized!')"
```

**Option 2: Add Temporary Endpoint**

Add this to `app.py` temporarily (remove after use):
```python
@app.route('/init-db-secret-endpoint-12345')
def init_db():
    db.create_all()
    return 'Database initialized!'
```

Then visit: `https://your-app.onrender.com/init-db-secret-endpoint-12345`

---

## 🎉 Your App is Live!

Visit your Render URL and test:
- ✅ User registration
- ✅ Login
- ✅ Chat with Claude
- ✅ AWS/GCP operations
- ✅ Billing (if Stripe configured)

---

## 💰 Render Pricing

### Free Tier
- **Web Service**: 750 hours/month free (enough for 1 app)
- **PostgreSQL**: 90 days free, then $7/month
- **Limitations**:
  - Spins down after 15 min of inactivity
  - Takes ~30 seconds to wake up
  - 512 MB RAM

### Paid Tier (Recommended for Production)
- **Starter**: $7/month per service
- **PostgreSQL**: $7/month
- **Total**: ~$14/month
- **Benefits**:
  - Always on (no spin down)
  - 512 MB RAM
  - Better performance
  - Custom domains

---

## 🔄 Auto-Deploy on Push

Render automatically redeploys when you push to GitHub:

```bash
# Make changes to your code
git add .
git commit -m "Add new feature"
git push

# Render automatically deploys! 🚀
```

You can disable auto-deploy in service settings if needed.

---

## 📊 Monitoring & Logs

Render provides:

1. **Logs**: Real-time application logs
   - Click **"Logs"** in your service dashboard
   - Filter by date/time
   - Download logs

2. **Metrics**: CPU, memory, network
   - Click **"Metrics"** tab
   - View graphs and statistics

3. **Events**: Deployment history
   - See all deployments
   - Rollback if needed

---

## 🐛 Troubleshooting

### Deployment fails?
1. Check **Logs** in Render dashboard
2. Verify all environment variables are set correctly
3. Ensure `requirements.txt` is complete
4. Check that Python version in `runtime.txt` matches

### Database errors?
1. Make sure you ran database initialization (Step 8)
2. Check `DATABASE_URL` environment variable is set
3. Verify PostgreSQL service is running
4. Check database connection in logs

### App not responding?
1. Check if service is "Live" (green dot)
2. View logs for errors
3. Ensure `Procfile` is correct
4. Try manual deploy: Click **"Manual Deploy"** → **"Deploy latest commit"**

### Free tier sleep issues?
- Free tier apps sleep after 15 min inactivity
- First request takes ~30 seconds to wake up
- Upgrade to **Starter** ($7/month) to stay always-on
- Or use a uptime monitor to ping every 10 minutes

---

## 🔐 Security Checklist

Before going live:

- [ ] All environment variables set correctly
- [ ] Using production API keys (not test keys)
- [ ] SECRET_KEY is strong and random
- [ ] DATABASE_URL is from Render PostgreSQL
- [ ] `.gitignore` includes `config/.env`
- [ ] Stripe webhooks configured to Render URL
- [ ] Custom domain with HTTPS (optional)

---

## 🌐 Custom Domain (Optional)

To use your own domain:

1. Go to your web service → **"Settings"**
2. Scroll to **"Custom Domain"**
3. Click **"Add Custom Domain"**
4. Enter your domain: `app.yourdomain.com`
5. Add DNS records (Render provides instructions):
   - **CNAME**: Point to your Render URL
6. Wait for DNS propagation (~1 hour)
7. Render auto-provisions **free HTTPS**!

---

## 🔧 Advanced Configuration

### Health Check Endpoint

Render can monitor your app health. Your app already has `/health`:

1. Go to **Settings** → **"Health & Alerts"**
2. Set **Health Check Path**: `/health`
3. Render will monitor and alert if down

### Background Workers

If you need background jobs (optional):

1. Create new **Background Worker** service
2. Use same repo
3. Set **Start Command**: `python worker.py` (you'd need to create this)

### Redis (Optional)

For caching or sessions:

1. Click **"New +"** → **"Redis"**
2. Link to your web service via environment variable

---

## 📝 Next Steps After Deployment

1. **Test all features** thoroughly
2. **Set up monitoring**: Consider Sentry for error tracking
3. **Configure Stripe webhooks** to Render URL
4. **Add custom domain** (optional)
5. **Set up backups**: Render provides automatic PostgreSQL backups
6. **Monitor costs**: Check Render dashboard

---

## 🆘 Need Help?

- **Render Docs**: https://render.com/docs
- **Render Community**: https://community.render.com
- **Support**: support@render.com
- **Status Page**: https://status.render.com

---

## 📋 Quick Reference

**Your URLs:**
- **App**: `https://devops-agent.onrender.com`
- **Dashboard**: https://dashboard.render.com
- **Logs**: Dashboard → Your Service → Logs
- **Shell**: Dashboard → Your Service → Shell

**Important Files:**
- `Procfile` - How to run the app
- `requirements.txt` - Dependencies
- `runtime.txt` - Python version
- `.gitignore` - Protected files

---

## ✅ Deployment Checklist

- [ ] Render account created
- [ ] GitHub repository connected
- [ ] Web service created
- [ ] PostgreSQL database created
- [ ] All environment variables set
- [ ] Database linked to web service
- [ ] App deployed successfully
- [ ] Database tables initialized
- [ ] App accessible via Render URL
- [ ] Test user registration
- [ ] Test login
- [ ] Test chat functionality
- [ ] (Optional) Stripe configured
- [ ] (Optional) Custom domain added

---

**You're ready to deploy! 🚀**

The deployment should take about 15 minutes total. Follow the steps carefully, and you'll have your DevOps Agent running on Render!
