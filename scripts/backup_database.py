#!/usr/bin/env python3
"""
Database Backup Script for DevOps Agent

Features:
- SQLite and PostgreSQL support
- Local backup with compression
- Optional S3/Azure Blob upload
- Retention policy (auto-delete old backups)
- Scheduled backup support (cron-compatible)

Usage:
    python scripts/backup_database.py                    # Run backup
    python scripts/backup_database.py --upload-s3       # Backup + upload to S3
    python scripts/backup_database.py --retention 7     # Keep only 7 days of backups
    python scripts/backup_database.py --restore latest  # Restore latest backup
"""

import os
import sys
import shutil
import gzip
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configuration
BACKUP_DIR = Path(os.getenv('BACKUP_DIR', 'backups'))
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///devops_agent.db')
S3_BUCKET = os.getenv('BACKUP_S3_BUCKET', '')
S3_PREFIX = os.getenv('BACKUP_S3_PREFIX', 'database-backups/')
AZURE_CONTAINER = os.getenv('BACKUP_AZURE_CONTAINER', '')
RETENTION_DAYS = int(os.getenv('BACKUP_RETENTION_DAYS', '30'))


def get_timestamp():
    """Get formatted timestamp for backup filename."""
    return datetime.now().strftime('%Y%m%d_%H%M%S')


def get_database_path():
    """Extract database path from DATABASE_URL."""
    if DATABASE_URL.startswith('sqlite:///'):
        return DATABASE_URL.replace('sqlite:///', '')
    return None


def backup_sqlite(backup_path: Path) -> bool:
    """Backup SQLite database."""
    db_path = get_database_path()
    if not db_path:
        print("Error: Could not determine SQLite database path")
        return False

    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        return False

    try:
        # Copy database file
        shutil.copy2(db_path, backup_path)
        print(f"SQLite backup created: {backup_path}")
        return True
    except Exception as e:
        print(f"Error backing up SQLite: {e}")
        return False


def backup_postgresql(backup_path: Path) -> bool:
    """Backup PostgreSQL database using pg_dump."""
    import subprocess

    # Parse DATABASE_URL for PostgreSQL
    # Format: postgresql://user:password@host:port/database
    try:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)

        env = os.environ.copy()
        env['PGPASSWORD'] = parsed.password or ''

        cmd = [
            'pg_dump',
            '-h', parsed.hostname or 'localhost',
            '-p', str(parsed.port or 5432),
            '-U', parsed.username or 'postgres',
            '-d', parsed.path.lstrip('/'),
            '-F', 'c',  # Custom format (compressed)
            '-f', str(backup_path)
        ]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"PostgreSQL backup created: {backup_path}")
            return True
        else:
            print(f"pg_dump error: {result.stderr}")
            return False

    except Exception as e:
        print(f"Error backing up PostgreSQL: {e}")
        return False


def compress_backup(backup_path: Path) -> Path:
    """Compress backup file using gzip."""
    compressed_path = backup_path.with_suffix(backup_path.suffix + '.gz')

    try:
        with open(backup_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove uncompressed file
        backup_path.unlink()
        print(f"Compressed backup: {compressed_path}")
        return compressed_path

    except Exception as e:
        print(f"Error compressing backup: {e}")
        return backup_path


def upload_to_s3(backup_path: Path) -> bool:
    """Upload backup to AWS S3."""
    if not S3_BUCKET:
        print("S3 bucket not configured (BACKUP_S3_BUCKET)")
        return False

    try:
        from services.backup_upload import upload_backup_to_s3

        s3_key = f"{S3_PREFIX}{backup_path.name}"

        upload_backup_to_s3(backup_path, S3_BUCKET, s3_key)
        print(f"Uploaded to S3: s3://{S3_BUCKET}/{s3_key}")
        return True

    except ImportError:
        print("boto3 not installed. Run: pip install boto3")
        return False
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False


def upload_to_azure(backup_path: Path) -> bool:
    """Upload backup to Azure Blob Storage."""
    if not AZURE_CONTAINER:
        print("Azure container not configured (BACKUP_AZURE_CONTAINER)")
        return False

    try:
        from azure.storage.blob import BlobServiceClient

        connection_string = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
        if not connection_string:
            print("AZURE_STORAGE_CONNECTION_STRING not set")
            return False

        blob_service = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service.get_container_client(AZURE_CONTAINER)

        blob_name = f"database-backups/{backup_path.name}"
        with open(backup_path, 'rb') as data:
            container_client.upload_blob(blob_name, data, overwrite=True)

        print(f"Uploaded to Azure: {AZURE_CONTAINER}/{blob_name}")
        return True

    except ImportError:
        print("azure-storage-blob not installed. Run: pip install azure-storage-blob")
        return False
    except Exception as e:
        print(f"Error uploading to Azure: {e}")
        return False


def cleanup_old_backups(retention_days: int):
    """Remove backups older than retention period."""
    if not BACKUP_DIR.exists():
        return

    cutoff_date = datetime.now() - timedelta(days=retention_days)
    removed_count = 0

    for backup_file in BACKUP_DIR.glob('devops_agent_*.db*'):
        try:
            # Extract date from filename
            filename = backup_file.stem.replace('.db', '')
            date_str = filename.split('_')[2] + '_' + filename.split('_')[3].split('.')[0]
            file_date = datetime.strptime(date_str, '%Y%m%d_%H%M%S')

            if file_date < cutoff_date:
                backup_file.unlink()
                removed_count += 1
                print(f"Removed old backup: {backup_file.name}")

        except (ValueError, IndexError):
            continue

    if removed_count > 0:
        print(f"Cleaned up {removed_count} old backup(s)")


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        print("No backups found")
        return []

    backups = sorted(BACKUP_DIR.glob('devops_agent_*.db*'), reverse=True)

    if not backups:
        print("No backups found")
        return []

    print("\nAvailable backups:")
    print("-" * 60)

    for i, backup in enumerate(backups):
        size_mb = backup.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        print(f"{i+1}. {backup.name}")
        print(f"   Size: {size_mb:.2f} MB | Created: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

    return backups


def restore_backup(backup_name: str) -> bool:
    """Restore database from backup."""
    if backup_name == 'latest':
        backups = list_backups()
        if not backups:
            return False
        backup_path = backups[0]
    else:
        backup_path = BACKUP_DIR / backup_name
        if not backup_path.exists():
            print(f"Backup not found: {backup_path}")
            return False

    db_path = get_database_path()
    if not db_path:
        print("Error: Could not determine database path for restore")
        return False

    # Confirm restore
    response = input(f"\nRestore {backup_path.name} to {db_path}? This will overwrite current data! [y/N]: ")
    if response.lower() != 'y':
        print("Restore cancelled")
        return False

    try:
        # Decompress if needed
        if backup_path.suffix == '.gz':
            print("Decompressing backup...")
            with gzip.open(backup_path, 'rb') as f_in:
                with open(db_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy2(backup_path, db_path)

        print(f"Database restored from: {backup_path.name}")
        return True

    except Exception as e:
        print(f"Error restoring backup: {e}")
        return False


def run_backup(upload_s3: bool = False, upload_azure: bool = False,
               compress: bool = True, retention_days: int = None):
    """Run the backup process."""
    print("=" * 60)
    print("DevOps Agent - Database Backup")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Database: {DATABASE_URL[:50]}...")
    print()

    # Create backup directory
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Determine backup filename
    timestamp = get_timestamp()

    if DATABASE_URL.startswith('sqlite'):
        backup_filename = f"devops_agent_{timestamp}.db"
        backup_path = BACKUP_DIR / backup_filename
        success = backup_sqlite(backup_path)
    elif DATABASE_URL.startswith('postgresql'):
        backup_filename = f"devops_agent_{timestamp}.dump"
        backup_path = BACKUP_DIR / backup_filename
        success = backup_postgresql(backup_path)
    else:
        print(f"Unsupported database type: {DATABASE_URL}")
        return False

    if not success:
        return False

    # Compress backup
    if compress and backup_path.exists():
        backup_path = compress_backup(backup_path)

    # Get backup size
    if backup_path.exists():
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print(f"Backup size: {size_mb:.2f} MB")

    # Upload to cloud storage
    if upload_s3:
        upload_to_s3(backup_path)

    if upload_azure:
        upload_to_azure(backup_path)

    # Cleanup old backups
    if retention_days:
        print(f"\nApplying retention policy: {retention_days} days")
        cleanup_old_backups(retention_days)

    print("\n" + "=" * 60)
    print("Backup completed successfully!")
    print("=" * 60)

    return True


def main():
    parser = argparse.ArgumentParser(description='DevOps Agent Database Backup')
    parser.add_argument('--upload-s3', action='store_true', help='Upload backup to S3')
    parser.add_argument('--upload-azure', action='store_true', help='Upload backup to Azure Blob')
    parser.add_argument('--no-compress', action='store_true', help='Skip compression')
    parser.add_argument('--retention', type=int, help='Retention period in days')
    parser.add_argument('--list', action='store_true', help='List available backups')
    parser.add_argument('--restore', type=str, help='Restore from backup (use "latest" for most recent)')

    args = parser.parse_args()

    if args.list:
        list_backups()
        return

    if args.restore:
        restore_backup(args.restore)
        return

    retention = args.retention or RETENTION_DAYS

    success = run_backup(
        upload_s3=args.upload_s3,
        upload_azure=args.upload_azure,
        compress=not args.no_compress,
        retention_days=retention
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
