#!/bin/bash
set -e

echo "🚀 Starting DevOps Agent Deployment..."

# Set deployment directory
DEPLOY_DIR="/home/ec2-user/app/DevOps-Agent"

# Navigate to deployment directory
cd /home/ec2-user/app

# Stop existing PM2 processes
echo "⏸️  Stopping existing processes..."
pm2 stop devops-agent 2>/dev/null || true
pm2 delete devops-agent 2>/dev/null || true

# Remove old code
echo "🗑️  Removing old code..."
rm -rf DevOps-Agent

# Clone fresh code
echo "📥 Cloning latest code..."
git clone https://github.com/shittuay/DevOps-Agent.git
cd DevOps-Agent

# Install Python dependencies
echo "📦 Installing dependencies..."
pip3 install --user -r requirements.txt

# Create necessary directories
mkdir -p logs
mkdir -p instance
mkdir -p config

# Create .env file if it doesn't exist
if [ ! -f "config/.env" ]; then
    echo "⚙️  Creating environment configuration..."
    cat > config/.env << 'EOF'
# Flask Configuration
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
DATABASE_URL=sqlite:///devops_agent.db
FLASK_ENV=production

# Anthropic API (REQUIRED - Add your key here)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# AWS Credentials (Optional)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_DEFAULT_REGION=us-east-1

# Server Configuration
PORT=5000
HOST=0.0.0.0
EOF
    echo "⚠️  IMPORTANT: Edit config/.env and add your ANTHROPIC_API_KEY!"
    echo "   Run: nano $DEPLOY_DIR/config/.env"
fi

# Start the application with PM2
echo "🚀 Starting application..."
pm2 start app.py --name devops-agent --interpreter python3 --

# Save PM2 configuration
pm2 save

# Setup PM2 to start on boot
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u ec2-user --hp /home/ec2-user

echo "✅ Deployment completed!"
echo ""
echo "📍 Next steps:"
echo "1. Edit config/.env and add your ANTHROPIC_API_KEY:"
echo "   nano $DEPLOY_DIR/config/.env"
echo ""
echo "2. Restart the app:"
echo "   pm2 restart devops-agent"
echo ""
echo "3. View logs:"
echo "   pm2 logs devops-agent"
echo ""
echo "4. Check status:"
echo "   pm2 status"
echo ""
echo "🌐 Your app should be accessible at:"
echo "   http://3.91.154.244:5000"
echo "   http://devopsagent.io (after DNS configuration)"
