#!/bin/bash

# DevOps Agent - EC2 Ubuntu Deployment Script
# Run this on your Ubuntu EC2 instance

set -e

echo "============================================================"
echo "DevOps Agent - EC2 Deployment"
echo "============================================================"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "Please run as ubuntu user (not root)"
    exit 1
fi

# Configuration
APP_DIR="/var/www/devops-agent"
APP_USER="ubuntu"
PYTHON_VERSION="python3.11"

echo "Step 1: Updating system packages..."
sudo apt update && sudo apt upgrade -y

echo ""
echo "Step 2: Installing system dependencies..."
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
    python3-dev \
    certbot \
    python3-certbot-nginx

echo ""
echo "Step 3: Setting up PostgreSQL..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Prompt for database password
read -sp "Enter PostgreSQL password for devopsagent user: " DB_PASSWORD
echo ""

# Create database and user
sudo -u postgres psql << EOF
DROP DATABASE IF EXISTS devops_agent;
DROP USER IF EXISTS devopsagent;
CREATE DATABASE devops_agent;
CREATE USER devopsagent WITH PASSWORD '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON DATABASE devops_agent TO devopsagent;
ALTER DATABASE devops_agent OWNER TO devopsagent;
EOF

echo "Database created successfully!"

echo ""
echo "Step 4: Creating application directory..."
sudo mkdir -p $APP_DIR
sudo chown -R $APP_USER:$APP_USER $APP_DIR
cd $APP_DIR

echo ""
echo "Step 5: Cloning/Copying application code..."
echo "NOTE: Make sure your code is here: $APP_DIR"
echo "If not, clone it now or copy your files here."
echo ""
read -p "Is your application code in $APP_DIR? (y/n): " code_ready

if [ "$code_ready" != "y" ]; then
    echo "Please clone your repository or copy files to $APP_DIR first"
    echo "Example: git clone https://github.com/shittuay/DevOps-Agent.git $APP_DIR"
    exit 1
fi

echo ""
echo "Step 6: Creating Python virtual environment..."
$PYTHON_VERSION -m venv venv
source venv/bin/activate

echo ""
echo "Step 7: Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Step 8: Configuring environment variables..."
echo "Creating .env file..."

# Prompt for API keys
echo ""
read -p "Enter ANTHROPIC_API_KEY: " ANTHROPIC_KEY
read -p "Enter AWS_ACCESS_KEY_ID: " AWS_KEY
read -sp "Enter AWS_SECRET_ACCESS_KEY: " AWS_SECRET
echo ""
read -p "Enter AWS_DEFAULT_REGION (default: us-east-1): " AWS_REGION
AWS_REGION=${AWS_REGION:-us-east-1}

# Generate Flask secret key
FLASK_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Create .env file
cat > $APP_DIR/.env << EOF
# Flask Configuration
FLASK_ENV=production
SECRET_KEY=$FLASK_SECRET
DEBUG=False

# Database
DATABASE_URL=postgresql://devopsagent:$DB_PASSWORD@localhost/devops_agent

# API Keys
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
AWS_ACCESS_KEY_ID=$AWS_KEY
AWS_SECRET_ACCESS_KEY=$AWS_SECRET
AWS_DEFAULT_REGION=$AWS_REGION

# Optional: Add Stripe keys later if needed
# STRIPE_SECRET_KEY=
# STRIPE_PUBLISHABLE_KEY=
# STRIPE_WEBHOOK_SECRET=
EOF

chmod 600 $APP_DIR/.env
echo ".env file created!"

echo ""
echo "Step 9: Initializing database..."
python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Database tables created!')"

echo ""
echo "Step 10: Creating systemd service..."
sudo tee /etc/systemd/system/devops-agent.service > /dev/null << EOF
[Unit]
Description=DevOps Agent Gunicorn Service
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn --workers 4 --bind 127.0.0.1:8000 --timeout 300 app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable devops-agent
sudo systemctl start devops-agent

echo "Checking service status..."
sleep 3
sudo systemctl status devops-agent --no-pager

echo ""
echo "Step 11: Configuring Nginx..."

# Get server IP/domain
SERVER_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || hostname -I | awk '{print $1}')
echo "Server IP detected: $SERVER_IP"
read -p "Enter your domain name (or press Enter to use IP: $SERVER_IP): " DOMAIN
DOMAIN=${DOMAIN:-$SERVER_IP}

sudo tee /etc/nginx/sites-available/devops-agent > /dev/null << EOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }

    location /static {
        alias $APP_DIR/static;
        expires 30d;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/devops-agent /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "============================================================"
echo "✅ Deployment Complete!"
echo "============================================================"
echo ""
echo "Your application is now running at:"
echo "  http://$DOMAIN"
echo ""
echo "Useful commands:"
echo "  - Check app status: sudo systemctl status devops-agent"
echo "  - View app logs: sudo journalctl -u devops-agent -f"
echo "  - Restart app: sudo systemctl restart devops-agent"
echo "  - View nginx logs: sudo tail -f /var/log/nginx/error.log"
echo ""
echo "Optional: Setup SSL certificate (HTTPS)"
echo "  sudo certbot --nginx -d $DOMAIN"
echo ""
echo "============================================================"
