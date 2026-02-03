#!/bin/bash
# Database Backup Cron Script for DevOps Agent
#
# Add to crontab with: crontab -e
#
# Examples:
#   # Daily backup at 2 AM
#   0 2 * * * /path/to/devops-agent/scripts/backup_cron.sh
#
#   # Every 6 hours
#   0 */6 * * * /path/to/devops-agent/scripts/backup_cron.sh
#
#   # Weekly backup on Sunday at 3 AM
#   0 3 * * 0 /path/to/devops-agent/scripts/backup_cron.sh

# Change to project directory
cd "$(dirname "$0")/.." || exit 1

# Activate virtual environment if exists
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Load environment variables
if [ -f "config/.env" ]; then
    export $(grep -v '^#' config/.env | xargs)
fi

# Run backup with S3 upload and 30-day retention
python scripts/backup_database.py --upload-s3 --retention 30

# Log result
if [ $? -eq 0 ]; then
    echo "[$(date)] Backup completed successfully" >> logs/backup.log
else
    echo "[$(date)] Backup FAILED" >> logs/backup.log
fi
