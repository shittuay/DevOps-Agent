# Netlify Deployment Guide for DevOps Agent

## ⚠️ Important Limitations

Before deploying to Netlify, be aware of these limitations:

1. **Function Timeout**: 10 seconds (free tier) or 26 seconds (paid tier)
   - Claude API calls may timeout on complex operations
   - Some DevOps tasks may fail if they take longer than 26 seconds

2. **Database**: SQLite won't work on Netlify (read-only filesystem)
   - **Required**: Set up external PostgreSQL database (see below)

3. **File Uploads**: Limited to 10MB per function invocation

4. **Stateless Functions**: Each request is independent
   - Session management requires external storage or JWT tokens

## 📋 Prerequisites

### 1. External PostgreSQL Database

You MUST set up an external PostgreSQL database. Options:

**Option A: Supabase (Recommended - Free Tier)**
1. Go to https://supabase.com
2. Create a new project
3. Get your PostgreSQL connection string from Settings > Database
4. Format: `postgresql://[user]:[password]@[host]:[port]/[database]`

**Option B: ElephantSQL (Free Tier)**
1. Go to https://www.elephantsql.com
2. Create a new instance (Tiny Turtle - Free)
3. Copy the database URL

**Option C: Neon (Free Tier)**
1. Go to https://neon.tech
2. Create new database
3. Copy connection string

### 2. Netlify Account
- Sign up at https://netlify.com

## 🚀 Deployment Steps

### Step 1: Set Environment Variables in Netlify

After connecting your repository, configure these environment variables in Netlify:

**Required Variables:**
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxx
DATABASE_URL=postgresql://user:password@host:port/database
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
```

**AWS Configuration (if using AWS tools):**
```
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_DEFAULT_REGION=us-east-1
```

**Azure Configuration (if using Azure tools):**
```
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret
```

**GCP Configuration (if using GCP tools):**
```
GCP_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS_JSON={"type":"service_account",...}
```

**Stripe (Optional):**
```
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx
```

### Step 2: Deploy to Netlify

**Option A: Connect via Netlify Dashboard**

1. Log in to Netlify: https://app.netlify.com
2. Click "Add new site" > "Import an existing project"
3. Choose GitHub and select your `DevOps-Agent` repository
4. Netlify will auto-detect the `netlify.toml` configuration
5. Click "Deploy site"

**Option B: Using Netlify CLI**

```bash
# Install Netlify CLI
npm install -g netlify-cli

# Login to Netlify
netlify login

# Initialize site
cd devops-agent
netlify init

# Deploy
netlify deploy --prod
```

### Step 3: Initialize Database

After first deployment, you need to initialize the database:

1. Open your Netlify site URL
2. The app will automatically create database tables on first run
3. Go to `/signup` to create your first user account

## ⚙️ Configuration Files

The following files have been created for Netlify deployment:

- `netlify.toml` - Netlify build configuration
- `functions/app.py` - Serverless function wrapper for Flask
- `static/index.html` - Static redirect page
- `requirements.txt` - Updated with `serverless-wsgi`

## 🔧 Database Migration from SQLite to PostgreSQL

If you were using SQLite locally, you'll need to:

1. Export your data from SQLite
2. Import into PostgreSQL

Or simply start fresh with PostgreSQL (recommended for new deployments).

## ⚠️ Known Issues & Workarounds

### Issue 1: Function Timeouts

**Problem**: Claude API calls or long-running DevOps operations timeout

**Workaround**:
- Break complex operations into smaller steps
- Use Netlify Pro plan for 26-second timeout
- Consider hybrid deployment (see below)

### Issue 2: File Downloads

**Problem**: Keypair download may not work reliably across function invocations

**Workaround**:
- Downloads will work but tokens expire quickly
- Consider storing in S3 for more reliable downloads

### Issue 3: Session Management

**Problem**: Flask sessions may not persist

**Workaround**:
- The app uses server-side sessions which should work
- If issues persist, consider JWT tokens

## 🔄 Alternative: Hybrid Deployment

If you experience too many timeouts:

1. **Backend**: Deploy on Render/Railway/AWS EC2
2. **Frontend**: Create static frontend on Netlify
3. **Connect**: API calls from Netlify frontend to backend

## 📊 Monitoring

Monitor your deployment:

1. Netlify Dashboard: https://app.netlify.com
2. Function logs: Site > Functions > View logs
3. Deploy logs: Site > Deploys > [latest deploy] > Deploy log

## 🆘 Troubleshooting

### Build Fails

1. Check build log in Netlify dashboard
2. Ensure all environment variables are set
3. Verify `requirements.txt` is complete

### Database Connection Errors

1. Verify `DATABASE_URL` environment variable
2. Check database is accessible from internet
3. Ensure connection string format is correct

### Function Timeout

1. Check function logs
2. Consider upgrading to Netlify Pro
3. Optimize code to reduce execution time

### Keypair Download Not Working

1. Downloads should work but may be less reliable
2. Check browser console for errors
3. Verify download token hasn't expired (5-minute limit)

## 📚 Additional Resources

- Netlify Functions: https://docs.netlify.com/functions/overview/
- Netlify Environment Variables: https://docs.netlify.com/environment-variables/overview/
- Supabase: https://supabase.com/docs
- Flask on Netlify: https://docs.netlify.com/integrations/frameworks/

## ✅ Post-Deployment Checklist

- [ ] Site is accessible
- [ ] Environment variables configured
- [ ] Database connected
- [ ] User signup works
- [ ] Login/logout works
- [ ] AWS/Azure/GCP tools configured
- [ ] Test creating a keypair
- [ ] Verify download works
- [ ] Monitor for timeout errors
- [ ] Set up custom domain (optional)

## 🎯 Success!

Your DevOps Agent should now be running on Netlify!

Access it at: `https://your-site-name.netlify.app`

**Important**: Due to Netlify's 26-second timeout limit, some long-running operations may fail. Monitor your logs and consider the hybrid deployment approach if needed.
