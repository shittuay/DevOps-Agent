# 🚀 Deploy to EC2 Ubuntu - Step by Step Guide

This guide walks you through deploying the DevOps Agent to a fresh Ubuntu EC2 instance.

---

## 📋 Prerequisites

### 1. Create EC2 Instance
- **AMI**: Ubuntu Server 22.04 LTS
- **Instance Type**: t3.small or larger (minimum 2GB RAM)
- **Storage**: 20GB+ GP3 EBS volume
- **Security Group**: Configure inbound rules:
  - SSH (22) - Your IP
  - HTTP (80) - 0.0.0.0/0
  - HTTPS (443) - 0.0.0.0/0

### 2. Get Your Keys Ready
- Anthropic API key
- AWS Access Key ID and Secret
- (Optional) Stripe keys

---

## 🎯 Quick Deployment (Automated Script)

### Step 1: Connect to EC2
```bash
# From your local machine
ssh -i your-key.pem ubuntu@your-ec2-ip
```

### Step 2: Upload Your Code
**Option A: Using Git (Recommended)**
```bash
cd /tmp
git clone https://github.com/shittuay/DevOps-Agent.git
sudo mkdir -p /var/www/devops-agent
sudo cp -r DevOps-Agent/* /var/www/devops-agent/
sudo chown -R ubuntu:ubuntu /var/www/devops-agent
cd /var/www/devops-agent
```

**Option B: Using SCP (from your local machine)**
```bash
# From your local machine (Windows Git Bash)
scp -i your-key.pem -r C:/Users/shitt/Downloads/devops-agent/* ubuntu@your-ec2-ip:/tmp/
```

Then on EC2:
```bash
sudo mkdir -p /var/www/devops-agent
sudo cp -r /tmp/devops-agent/* /var/www/devops-agent/
sudo chown -R ubuntu:ubuntu /var/www/devops-agent
```

### Step 3: Run Deployment Script
```bash
cd /var/www/devops-agent
chmod +x deploy_ec2.sh
./deploy_ec2.sh
```

The script will prompt you for:
- PostgreSQL password
- Anthropic API key
- AWS credentials
- Domain name (optional)

**That's it!** ✅ Your app will be running when the script completes.

---

## 🔧 Manual Deployment (Step by Step)

If you prefer to do it manually or need more control:

### Step 1: Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### Step 2: Install Dependencies
```bash
sudo apt install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    nginx \
    git \
    build-essential \
    python3-dev
```

### Step 3: Setup PostgreSQL
```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database
sudo -u postgres psql << EOF
CREATE DATABASE devops_agent;
CREATE USER devopsagent WITH PASSWORD 'your_strong_password_here';
GRANT ALL PRIVILEGES ON DATABASE devops_agent TO devopsagent;
ALTER DATABASE devops_agent OWNER TO devopsagent;
\q
EOF
```

### Step 4: Setup Application
```bash
# Create app directory
sudo mkdir -p /var/www/devops-agent
sudo chown -R ubuntu:ubuntu /var/www/devops-agent

# Copy/clone your code to /var/www/devops-agent

cd /var/www/devops-agent

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Configure Environment Variables
```bash
# Create .env file
nano /var/www/devops-agent/.env
```

Add this content (replace with your actual values):
```env
# Flask Configuration
FLASK_ENV=production
SECRET_KEY=your_generated_secret_key_here
DEBUG=False

# Database
DATABASE_URL=postgresql://devopsagent:your_db_password@localhost/devops_agent

# API Keys
ANTHROPIC_API_KEY=sk-ant-your_key_here
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_DEFAULT_REGION=us-east-1

# Optional: Stripe keys
# STRIPE_SECRET_KEY=
# STRIPE_PUBLISHABLE_KEY=
# STRIPE_WEBHOOK_SECRET=
```

Generate a secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 6: Initialize Database
```bash
cd /var/www/devops-agent
source venv/bin/activate
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database initialized!')"
```

### Step 7: Setup Systemd Service
```bash
sudo cp devops-agent.service /etc/systemd/system/

# Or create it manually
sudo nano /etc/systemd/system/devops-agent.service
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable devops-agent
sudo systemctl start devops-agent
sudo systemctl status devops-agent
```

### Step 8: Configure Nginx
```bash
sudo cp nginx.conf /etc/nginx/sites-available/devops-agent

# Edit and update server_name
sudo nano /etc/nginx/sites-available/devops-agent
# Change 'your_domain_or_ip' to your actual domain or EC2 public IP

# Enable site
sudo ln -s /etc/nginx/sites-available/devops-agent /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default  # Remove default site

# Test and restart
sudo nginx -t
sudo systemctl restart nginx
```

### Step 9: Access Your App
Open browser and go to:
```
http://your-ec2-public-ip
```

---

## 🔒 Setup SSL Certificate (HTTPS)

### Using Let's Encrypt (Free)
```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Get certificate (requires domain name)
sudo certbot --nginx -d yourdomain.com

# Auto-renewal is configured automatically
# Test renewal:
sudo certbot renew --dry-run
```

---

## 📊 Management Commands

### Check Application Status
```bash
sudo systemctl status devops-agent
```

### View Application Logs
```bash
# Live logs
sudo journalctl -u devops-agent -f

# Last 100 lines
sudo journalctl -u devops-agent -n 100

# Since today
sudo journalctl -u devops-agent --since today
```

### Restart Application
```bash
sudo systemctl restart devops-agent
```

### Update Application
```bash
cd /var/www/devops-agent
git pull  # or copy new files
source venv/bin/activate
pip install -r requirements.txt  # if dependencies changed
sudo systemctl restart devops-agent
```

### View Nginx Logs
```bash
# Error logs
sudo tail -f /var/log/nginx/error.log

# Access logs
sudo tail -f /var/log/nginx/access.log
```

### Database Backup
```bash
# Create backup
sudo -u postgres pg_dump devops_agent > backup_$(date +%Y%m%d).sql

# Restore backup
sudo -u postgres psql devops_agent < backup_20250108.sql
```

---

## 🐛 Troubleshooting

### Application Won't Start
```bash
# Check service status
sudo systemctl status devops-agent

# Check logs
sudo journalctl -u devops-agent -n 50

# Common issues:
# - Wrong file permissions: sudo chown -R ubuntu:ubuntu /var/www/devops-agent
# - Missing .env file: Check /var/www/devops-agent/.env exists
# - Database connection: Check DATABASE_URL in .env
```

### 502 Bad Gateway
```bash
# Check if gunicorn is running
ps aux | grep gunicorn

# Check application logs
sudo journalctl -u devops-agent -f

# Try restarting
sudo systemctl restart devops-agent
```

### Database Connection Error
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test database connection
psql -h localhost -U devopsagent -d devops_agent

# Check DATABASE_URL in .env
cat /var/www/devops-agent/.env | grep DATABASE_URL
```

### Port Already in Use
```bash
# Check what's using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 PID
```

---

## 💰 AWS Costs

### Monthly Estimate (Single Instance)
- **EC2 t3.small**: ~$15/month
- **EBS 20GB GP3**: ~$2/month
- **Data Transfer**: ~$5/month (1TB free outbound)
- **Elastic IP**: Free (if attached)
- **Total**: ~$22/month

### Cost Optimization
- Use **t3.micro** for testing ($7.5/month)
- Use **Reserved Instances** for production (save 40%)
- Enable **Auto Stop/Start** for dev environments
- Monitor with **AWS Cost Explorer**

---

## 🔥 Performance Tuning

### Increase Gunicorn Workers
Edit `/etc/systemd/system/devops-agent.service`:
```ini
ExecStart=/var/www/devops-agent/venv/bin/gunicorn --workers 8 --bind 127.0.0.1:8000 --timeout 300 app:app
```

Formula: `workers = (2 × CPU cores) + 1`

### Enable Nginx Caching
Add to nginx config:
```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m;

location / {
    proxy_cache my_cache;
    proxy_cache_valid 200 5m;
    # ... rest of config
}
```

### Database Connection Pooling
In `app.py`:
```python
app.config['SQLALCHEMY_POOL_SIZE'] = 10
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 30
app.config['SQLALCHEMY_POOL_RECYCLE'] = 3600
```

---

## 📈 Monitoring Setup

### Install Monitoring Tools
```bash
# Install htop for resource monitoring
sudo apt install -y htop

# View resources
htop
```

### Setup CloudWatch (Optional)
```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Configure with wizard
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard
```

---

## ✅ Post-Deployment Checklist

- [ ] Application accessible via browser
- [ ] User registration works
- [ ] User login works
- [ ] Chat functionality works
- [ ] AWS tools working (if configured)
- [ ] Database persists after restart
- [ ] SSL certificate installed (production)
- [ ] Backups configured
- [ ] Monitoring setup
- [ ] Logs rotating properly

---

## 🔐 Security Best Practices

1. **Firewall**: Restrict SSH to your IP only
2. **SSH Keys**: Disable password authentication
3. **Updates**: Setup automatic security updates
4. **Fail2ban**: Install to prevent brute force attacks
5. **SSL**: Always use HTTPS in production
6. **Environment Variables**: Never commit .env to git
7. **Database**: Use strong passwords
8. **Backups**: Schedule regular automated backups

---

## 📞 Need Help?

If you run into issues:
1. Check logs: `sudo journalctl -u devops-agent -f`
2. Check nginx: `sudo nginx -t`
3. Check database: `sudo systemctl status postgresql`
4. Review this guide's troubleshooting section

---

**You're all set! Your DevOps Agent is now running on EC2 Ubuntu.** 🎉
