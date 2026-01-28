"""
Migration script to add new columns for 2FA, API keys, and audit logging.
"""

import sqlite3
import os

def migrate():
    # Get database path
    db_path = os.environ.get('DATABASE_URL', 'sqlite:///devops_agent.db')
    if db_path.startswith('sqlite:///'):
        db_path = db_path.replace('sqlite:///', '')

    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get existing columns in users table
    cursor.execute("PRAGMA table_info(users)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    print(f"Existing user columns: {existing_columns}")

    # Add 2FA columns to users table
    new_user_columns = [
        ("two_factor_enabled", "BOOLEAN DEFAULT 0"),
        ("two_factor_secret", "VARCHAR(32)"),
        ("backup_codes", "TEXT"),  # JSON stored as text
        ("two_factor_verified_at", "DATETIME"),
        ("two_factor_attempts", "INTEGER DEFAULT 0"),
        ("two_factor_locked_until", "DATETIME"),
    ]

    for col_name, col_type in new_user_columns:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                print(f"Added column: users.{col_name}")
            except sqlite3.OperationalError as e:
                print(f"Column {col_name} may already exist: {e}")

    # Create api_keys table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            key_prefix VARCHAR(8) NOT NULL,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            scopes TEXT,
            allowed_ips TEXT,
            rate_limit INTEGER DEFAULT 1000,
            requests_today INTEGER DEFAULT 0,
            last_request_date DATE,
            last_used_at DATETIME,
            last_used_ip VARCHAR(45),
            total_requests INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            expires_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            revoked_at DATETIME,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    print("Created/verified api_keys table")

    # Create index on api_keys
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)")
    except:
        pass

    # Create audit_logs table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action VARCHAR(100) NOT NULL,
            action_category VARCHAR(50) NOT NULL,
            resource_type VARCHAR(50),
            resource_id VARCHAR(200),
            ip_address VARCHAR(45),
            user_agent VARCHAR(500),
            request_method VARCHAR(10),
            request_path VARCHAR(500),
            api_key_id INTEGER,
            description TEXT,
            old_value TEXT,
            new_value TEXT,
            extra_data TEXT,
            status VARCHAR(20) DEFAULT 'success',
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
        )
    """)
    print("Created/verified audit_logs table")

    # Create indexes on audit_logs
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_action ON audit_logs(user_id, action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_logs(action_category)")
    except:
        pass

    conn.commit()
    conn.close()

    print("\nMigration completed successfully!")
    print("You can now restart the application.")

if __name__ == "__main__":
    migrate()
