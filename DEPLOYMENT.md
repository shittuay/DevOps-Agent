# DevOps Agent - EC2 Deployment Guide

## Current Setup

- **EC2 Instance**: `i-0acd1f2e6cf30f299` (t3.micro)
- **Public IP**: `3.91.154.244`
- **Domain**: `devopsagent.io` (Cloudflare)
- **Ports Open**: 22, 80, 443, 3000, 5000

## Deployment Status

✅ GitHub Actions workflow configured
✅ EC2 security group updated
✅ Port 5000 opened
⏳ Waiting for successful deployment

## Required GitHub Secrets

Make sure these secrets are configured in your GitHub repository:

1. **`EC2_HOST`**: `3.91.154.244`
2. **`EC2_USERNAME`**: `ec2-user` (or `ubuntu` depending on AMI)
3. **`EC2_SSH_KEY`**: Your private SSH key content
4. **`ANTHROPIC_API_KEY`**: Your Anthropic API key (Required!)
5. **`SECRET_KEY`**: Generate with: `python -c 'import secrets; print(secrets.token_hex(32))'`

### To add GitHub Secrets:

```bash
# Go to your repository on GitHub
https://github.com/shittuay/DevOps-Agent/settings/secrets/actions

# Click "New repository secret" for each of the above
```

## Deployment Process

### Option 1: Automatic Deployment via GitHub Actions

1. **Push changes to main branch**:
   ```bash
   git add .
   git commit -m "feat: Update deployment configuration"
   git push origin main
   ```

2. **Or manually trigger deployment**:
   - Go to: https://github.com/shittuay/DevOps-Agent/actions
   - Select "Deploy to EC2" workflow
   - Click "Run workflow"

### Option 2: Manual SSH Deployment

If you need to deploy manually or troubleshoot:

```bash
# SSH into EC2
ssh -i your-key.pem ec2-user@3.91.154.244

# Run the deployment script
cd /home/ec2-user/app
bash DevOps-Agent/deploy.sh

# Edit environment variables
nano /home/ec2-user/app/DevOps-Agent/config/.env

# Restart the app
pm2 restart devops-agent

# View logs
pm2 logs devops-agent

# Check status
pm2 status
```

## Accessing Your Application

After successful deployment:

- **Direct IP Access**: http://3.91.154.244:5000
- **Domain Access**: http://devopsagent.io (after DNS configuration)

## Next Steps

### 1. Verify Application is Running

```bash
# Check from your local machine
curl http://3.91.154.244:5000
```

### 2. Configure Cloudflare DNS

Point your domain to the EC2 instance:

1. Log in to Cloudflare Dashboard
2. Select `devopsagent.io` domain
3. Go to DNS settings
4. Add/Update A record:
   - **Type**: A
   - **Name**: @ (or subdomain like `app`)
   - **IPv4 address**: `3.91.154.244`
   - **TTL**: Auto
   - **Proxy status**: Proxied (orange cloud) for SSL

### 3. Set up SSL/TLS (Cloudflare)

Cloudflare provides free SSL when proxy is enabled:

1. Go to SSL/TLS settings in Cloudflare
2. Set SSL/TLS encryption mode to **"Flexible"** or **"Full"**
3. Enable "Always Use HTTPS"

### 4. Production Configuration

For production deployment, set up nginx as reverse proxy:

```bash
# SSH into EC2
ssh -i your-key.pem ec2-user@3.91.154.244

# Install nginx
sudo yum install nginx -y

# Create nginx configuration
sudo nano /etc/nginx/conf.d/devopsagent.conf
```

Add this configuration:

```nginx
server {
    listen 80;
    server_name devopsagent.io www.devopsagent.io;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Test nginx configuration
sudo nginx -t

# Start nginx
sudo systemctl start nginx
sudo systemctl enable nginx

# Restart your app
pm2 restart devops-agent
```

## Troubleshooting

### Application Not Accessible

```bash
# SSH into EC2
ssh -i your-key.pem ec2-user@3.91.154.244

# Check if app is running
pm2 status

# View logs
pm2 logs devops-agent --lines 50

# Restart app
pm2 restart devops-agent
```

### Database Issues

```bash
# Reinitialize database
cd /home/ec2-user/app/DevOps-Agent
python3 -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Check Security Group

```bash
# Verify port 5000 is open
aws ec2 describe-security-groups --group-ids sg-013fcac55bbdf7daa --region us-east-1
```

### View PM2 Logs

```bash
# Real-time logs
pm2 logs devops-agent

# Last 100 lines
pm2 logs devops-agent --lines 100

# Error logs only
pm2 logs devops-agent --err
```

## Monitoring

```bash
# PM2 monitoring
pm2 monit

# View resource usage
pm2 status

# View detailed info
pm2 info devops-agent
```

## Updating the Application

After making code changes:

```bash
# Option 1: Let GitHub Actions handle it
git push origin main

# Option 2: Manual update
ssh -i your-key.pem ec2-user@3.91.154.244
cd /home/ec2-user/app/DevOps-Agent
git pull
pip3 install --user -r requirements.txt
pm2 restart devops-agent
```

## Environment Variables

Required environment variables in `config/.env`:

```bash
SECRET_KEY=<generated-secret-key>
DATABASE_URL=sqlite:///devops_agent.db
FLASK_ENV=production
ANTHROPIC_API_KEY=<your-anthropic-api-key>
PORT=5000
HOST=0.0.0.0
LOG_LEVEL=INFO
```

## Support

If you encounter issues:

1. Check PM2 logs: `pm2 logs devops-agent`
2. Check application logs: `/home/ec2-user/app/DevOps-Agent/logs/`
3. Verify environment variables are set correctly
4. Ensure all GitHub secrets are configured
5. Check security group allows traffic on required ports
