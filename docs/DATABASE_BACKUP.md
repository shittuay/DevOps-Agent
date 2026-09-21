# Database Backup Guide

This guide covers setting up automated database backups for DevOps Agent in production.

## Quick Start

```bash
# Run a backup
python scripts/backup_database.py

# List available backups
python scripts/backup_database.py --list

# Restore from latest backup
python scripts/backup_database.py --restore latest
```

## Features

- **SQLite & PostgreSQL Support**: Automatically detects database type
- **Compression**: Backups are gzip compressed by default
- **Cloud Upload**: Optional upload to AWS S3 or Azure Blob Storage
- **Retention Policy**: Automatically removes old backups
- **Restore**: Easy restoration from any backup

## Configuration

### Environment Variables

Add these to your `config/.env` or system environment:

```bash
# Database connection (required)
DATABASE_URL=sqlite:///devops_agent.db
# or for PostgreSQL:
# DATABASE_URL=postgresql://user:password@localhost:5432/devops_agent

# Local backup directory (optional, default: backups/)
BACKUP_DIR=backups

# Retention period in days (optional, default: 30)
BACKUP_RETENTION_DAYS=30

# AWS S3 Configuration (optional)
BACKUP_S3_BUCKET=my-backup-bucket
BACKUP_S3_PREFIX=database-backups/
# Account that must own the bucket (optional; defaults to the uploading
# credentials' own account). Uploads are rejected with 403 if the bucket is
# owned by anyone else - see services/backup_upload.py.
BACKUP_S3_BUCKET_OWNER=123456789012
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# Azure Blob Configuration (optional)
BACKUP_AZURE_CONTAINER=backups
AZURE_STORAGE_CONNECTION_STRING=your_connection_string
```

## Usage Examples

### Basic Backup

```bash
# Simple backup (compressed, local only)
python scripts/backup_database.py

# Backup without compression
python scripts/backup_database.py --no-compress
```

### Cloud Upload

```bash
# Backup and upload to S3
python scripts/backup_database.py --upload-s3

# Backup and upload to Azure
python scripts/backup_database.py --upload-azure

# Upload to both
python scripts/backup_database.py --upload-s3 --upload-azure
```

### Retention Policy

```bash
# Keep only last 7 days of backups
python scripts/backup_database.py --retention 7

# Keep only last 90 days
python scripts/backup_database.py --retention 90
```

### List & Restore

```bash
# List all backups
python scripts/backup_database.py --list

# Restore from latest backup
python scripts/backup_database.py --restore latest

# Restore from specific backup
python scripts/backup_database.py --restore devops_agent_20260203_020000.db.gz
```

## Automated Backups (Cron)

### Linux/macOS

1. Make the script executable:
```bash
chmod +x scripts/backup_cron.sh
```

2. Edit crontab:
```bash
crontab -e
```

3. Add backup schedule:
```cron
# Daily backup at 2 AM
0 2 * * * /path/to/devops-agent/scripts/backup_cron.sh

# Every 6 hours
0 */6 * * * /path/to/devops-agent/scripts/backup_cron.sh

# Weekly on Sunday at 3 AM
0 3 * * 0 /path/to/devops-agent/scripts/backup_cron.sh
```

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (daily, weekly, etc.)
4. Action: Start a program
   - Program: `python`
   - Arguments: `scripts/backup_database.py --upload-s3 --retention 30`
   - Start in: `C:\path\to\devops-agent`

### Systemd Timer (Linux)

Create `/etc/systemd/system/devops-backup.service`:
```ini
[Unit]
Description=DevOps Agent Database Backup

[Service]
Type=oneshot
WorkingDirectory=/opt/devops-agent
ExecStart=/opt/devops-agent/venv/bin/python scripts/backup_database.py --upload-s3 --retention 30
User=devops
```

Create `/etc/systemd/system/devops-backup.timer`:
```ini
[Unit]
Description=Run DevOps Agent backup daily

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl enable devops-backup.timer
sudo systemctl start devops-backup.timer
```

## AWS S3 Setup

### 1. Create S3 Bucket

```bash
aws s3 mb s3://devops-agent-backups --region us-east-1
```

### 2. Create IAM Policy

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject"
            ],
            "Resource": [
                "arn:aws:s3:::devops-agent-backups",
                "arn:aws:s3:::devops-agent-backups/*"
            ]
        }
    ]
}
```

### 3. Enable Lifecycle Rules (Optional)

For automatic S3 cleanup, add lifecycle rule:
- Transition to Glacier after 30 days
- Delete after 365 days

## PostgreSQL Backups

For PostgreSQL, ensure `pg_dump` is installed:

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-client

# macOS
brew install postgresql

# Amazon Linux
sudo yum install postgresql
```

## Backup File Format

Backups are named: `devops_agent_YYYYMMDD_HHMMSS.db.gz`

Example: `devops_agent_20260203_020000.db.gz`

## Monitoring Backups

Check backup logs:
```bash
tail -f logs/backup.log
```

Verify backup integrity:
```bash
# List backup contents (SQLite)
sqlite3 backups/devops_agent_*.db ".tables"

# Check compressed backup
gzip -t backups/devops_agent_*.db.gz && echo "OK"
```

## Disaster Recovery

### Full Recovery Steps

1. Stop the application:
```bash
sudo systemctl stop devops-agent
```

2. Download latest backup from S3 (if using):
```bash
aws s3 cp s3://devops-agent-backups/database-backups/devops_agent_latest.db.gz backups/
```

3. Restore:
```bash
python scripts/backup_database.py --restore latest
```

4. Start the application:
```bash
sudo systemctl start devops-agent
```

### Test Your Backups

Regularly test restoration:
```bash
# Create test database
python scripts/backup_database.py --restore latest
# Verify application works with restored data
python -c "from app import app, db; app.app_context().push(); print('Tables:', db.engine.table_names())"
```

## Troubleshooting

### "Permission denied"
```bash
chmod +x scripts/backup_database.py
chmod +x scripts/backup_cron.sh
```

### "boto3 not installed"
```bash
pip install boto3
```

### "pg_dump not found"
Install PostgreSQL client tools for your OS.

### Backup too large
- Enable compression (default)
- Reduce retention period
- Archive old data to separate tables

## Best Practices

1. **Test restores regularly** - A backup is only good if it can be restored
2. **Use cloud storage** - Don't rely solely on local backups
3. **Monitor backup jobs** - Set up alerts for failed backups
4. **Encrypt sensitive backups** - Use S3 server-side encryption
5. **Document recovery procedures** - Keep this guide updated
6. **Backup before major changes** - Always backup before migrations
