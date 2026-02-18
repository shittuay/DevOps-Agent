# 🚀 Deploy to AWS Elastic Beanstalk - Complete Guide

## Why AWS Elastic Beanstalk?
- **Reliable**: Enterprise-grade infrastructure
- **Scalable**: Auto-scaling built-in
- **Full Control**: Access to all AWS services
- **Cost-effective**: Pay only for what you use (~$15-30/month)
- **Production-ready**: Used by major companies

---

## ✅ Prerequisites

Your app is AWS-ready with:
- ✅ All deployment files configured
- ✅ Code on GitHub: https://github.com/shittuay/DevOps-Agent
- ✅ AWS credentials (you already have these!)

---

## 🎯 Deployment Steps (20 minutes)

### Step 1: Install AWS EB CLI

**Windows (Git Bash):**
```bash
pip install awsebcli --upgrade --user
```

**Verify installation:**
```bash
eb --version
```

Should show: `EB CLI 3.x.x`

---

### Step 2: Configure AWS Credentials

```bash
aws configure
```

Enter your credentials:
- **AWS Access Key ID**: `AKIAU4YZDFIZN3R5YFIG` (or your current one)
- **AWS Secret Access Key**: Your secret key
- **Default region**: `us-east-1` (or your preferred region)
- **Default output format**: `json`

---

### Step 3: Initialize Elastic Beanstalk

In your project directory:

```bash
cd /c/Users/shitt/Downloads/devops-agent

# Initialize EB application
eb init -p python-3.11 devops-agent --region us-east-1
```

When prompted:
- **Application name**: `devops-agent`
- **Use CodeCommit**: `n`
- **SSH**: `y` (recommended for debugging)
- **Keypair**: Create new or select existing

---

### Step 4: Create Environment with RDS PostgreSQL

This creates everything in one command:

```bash
eb create devops-agent-prod \
  --database.engine postgres \
  --database.username devopsagent \
  --database.password YOUR_STRONG_PASSWORD_HERE \
  --envvars FLASK_ENV=production,SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

**Important**: Replace `YOUR_STRONG_PASSWORD_HERE` with a strong password (save it!)

This will:
- ✅ Create an EC2 instance
- ✅ Set up PostgreSQL RDS database
- ✅ Configure load balancer
- ✅ Set up security groups
- ✅ Deploy your application

**Wait 10-15 minutes** for creation to complete.

---

### Step 5: Set Environment Variables

After environment is created, add your API keys:

```bash
eb setenv \
  ANTHROPIC_API_KEY=sk-ant-your_key_here \
  AWS_ACCESS_KEY_ID=your_aws_key \
  AWS_SECRET_ACCESS_KEY=your_aws_secret \
  AWS_DEFAULT_REGION=us-east-1
```

**Optional - Add Stripe keys:**
```bash
eb setenv \
  STRIPE_SECRET_KEY=your_stripe_secret \
  STRIPE_PUBLISHABLE_KEY=your_stripe_publishable \
  STRIPE_WEBHOOK_SECRET=your_webhook_secret \
  STRIPE_PRICE_STARTER=price_xxx \
  STRIPE_PRICE_PROFESSIONAL=price_xxx \
  STRIPE_PRICE_BUSINESS=price_xxx
```

---

### Step 6: Deploy!

```bash
eb deploy
```

This will:
1. Package your application
2. Upload to S3
3. Deploy to EC2
4. Restart the application

**Wait 3-5 minutes** for deployment.

---

### Step 7: Initialize Database

**Option 1: SSH into instance**
```bash
eb ssh

# Inside the instance
cd /var/app/current
source /var/app/venv/*/bin/activate
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized!')"
exit
```

**Option 2: Visit the init endpoint**
```bash
# Get your app URL
eb status

# Visit in browser
https://your-app-url.elasticbeanstalk.com/init-database-secret-endpoint-12345
```

---

### Step 8: Open Your App!

```bash
eb open
```

Your app will open in the browser! 🎉

---

## 📊 Managing Your App

### View Logs
```bash
eb logs
```

### Check Status
```bash
eb status
```

### SSH into Server
```bash
eb ssh
```

### Monitor Health
```bash
eb health
```

### Update Environment Variables
```bash
eb setenv KEY=value
```

### Deploy Updates
```bash
git add .
git commit -m "Update"
git push
eb deploy
```

---

## 💰 AWS Costs (Estimate)

### Development Environment
- **EC2 t3.small**: ~$15/month
- **RDS db.t3.micro**: ~$15/month
- **Data transfer**: ~$5/month
- **Total**: ~$35/month

### Production Environment (Recommended)
- **EC2 t3.medium**: ~$30/month
- **RDS db.t3.small**: ~$30/month
- **Load balancer**: ~$20/month
- **Total**: ~$80/month

### Free Tier (First 12 months)
If your AWS account is new (<12 months old):
- 750 hours EC2 t2.micro (free)
- 750 hours RDS db.t2.micro (free)
- **Total**: ~$0-10/month

---

## 🔧 Advanced Configuration

### Enable HTTPS (SSL)

1. **Request SSL Certificate in AWS Certificate Manager**:
   - Go to AWS Console → Certificate Manager
   - Request public certificate
   - Enter your domain: `app.yourdomain.com`
   - Validate via DNS or email

2. **Configure Load Balancer**:
```bash
eb config
```

Add under `aws:elbv2:listener:443`:
```yaml
aws:elbv2:listener:443:
  Protocol: HTTPS
  SSLCertificateArns: arn:aws:acm:us-east-1:ACCOUNT:certificate/CERT-ID
```

### Auto-Scaling

Configure auto-scaling in `.ebextensions/03_autoscaling.config`:

```yaml
option_settings:
  aws:autoscaling:asg:
    MinSize: 2
    MaxSize: 10
  aws:autoscaling:trigger:
    MeasureName: CPUUtilization
    Unit: Percent
    UpperThreshold: 80
    LowerThreshold: 20
```

### Custom Domain

1. In Route 53, create a CNAME record:
   - Name: `app.yourdomain.com`
   - Value: Your EB environment URL

2. Update in EB console: Environment → Configuration → Load Balancer

---

## 🐛 Troubleshooting

### Deployment Fails

**Check logs:**
```bash
eb logs
```

**Common issues:**
- Missing environment variables
- Database connection failed
- Wrong Python version

### App Not Starting

**Check health:**
```bash
eb health --refresh
```

**View detailed logs:**
```bash
eb logs --all
```

### Database Connection Error

**Verify RDS_HOSTNAME is set:**
```bash
eb printenv
```

Should show `RDS_HOSTNAME`, `RDS_DB_NAME`, etc.

**Test connection:**
```bash
eb ssh
psql -h $RDS_HOSTNAME -U $RDS_USERNAME -d $RDS_DB_NAME
```

### 502 Bad Gateway

Usually means app isn't starting. Check:
1. Application logs: `eb logs`
2. Environment variables: `eb printenv`
3. Health status: `eb health`

---

## 📝 EB CLI Quick Reference

```bash
# Create new environment
eb create environment-name

# Deploy code changes
eb deploy

# Set environment variables
eb setenv KEY=value

# View logs
eb logs

# SSH into instance
eb ssh

# Check status
eb status

# Open app in browser
eb open

# Terminate environment
eb terminate environment-name

# List environments
eb list

# Configure environment
eb config
```

---

## 🔐 Security Best Practices

1. **Enable HTTPS** (SSL certificate)
2. **Use RDS encryption** at rest
3. **Restrict security groups** (only allow port 80/443)
4. **Use IAM roles** for AWS service access
5. **Enable CloudWatch logs**
6. **Regular backups** (RDS automated backups)
7. **Use Secrets Manager** for sensitive data (optional)

---

## 🚀 Performance Optimization

### Enable CloudFront CDN

1. Create CloudFront distribution
2. Origin: Your EB environment URL
3. Update DNS to point to CloudFront

### Use ElastiCache for Sessions

Add Redis for session storage:
```bash
eb create --database --envvars REDIS_URL=your-redis-endpoint
```

### Database Performance

1. **Enable RDS Performance Insights**
2. **Use read replicas** for heavy traffic
3. **Configure connection pooling** in SQLAlchemy

---

## 📋 Deployment Checklist

- [ ] EB CLI installed
- [ ] AWS credentials configured
- [ ] EB application initialized
- [ ] Environment created with RDS
- [ ] All environment variables set
- [ ] Application deployed
- [ ] Database initialized
- [ ] App accessible via URL
- [ ] Test user registration
- [ ] Test login
- [ ] Test chat functionality
- [ ] (Optional) SSL certificate configured
- [ ] (Optional) Custom domain configured

---

## 🆘 Need Help?

- **AWS Documentation**: https://docs.aws.amazon.com/elasticbeanstalk/
- **EB CLI Guide**: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/eb-cli3.html
- **AWS Support**: Submit ticket in AWS Console
- **Status Page**: https://status.aws.amazon.com/

---

## 🔄 Rolling Back

If deployment fails:

```bash
# View deployment history
eb history

# Rollback to previous version
eb deploy --version VERSION_NUMBER
```

---

## ✨ Benefits Over Render

1. **Better Performance**: Dedicated EC2 instances
2. **More Control**: Full access to infrastructure
3. **Scalability**: Auto-scaling built-in
4. **Integration**: Direct access to all AWS services (S3, CloudWatch, etc.)
5. **Reliability**: 99.95% SLA
6. **Security**: VPC, security groups, IAM roles
7. **Monitoring**: CloudWatch metrics and alarms

---

**You're ready to deploy to AWS! 🚀**

Follow the steps above and your app will be running on production-grade AWS infrastructure in ~20 minutes.
