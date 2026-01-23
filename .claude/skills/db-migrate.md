---
name: db-migrate
description: Database migration and schema management for the DevOps Agent application. Use when creating migrations, updating database schema, or managing database changes.
---

# Database Migration Management

## Overview

This skill guides you through creating, testing, and applying database migrations for the DevOps Agent Flask application using SQLAlchemy.

## Migration Workflow

### Phase 1: Planning the Migration

1. **Identify Changes Needed**
   - Review models.py for current schema
   - Determine what needs to change (add column, new table, modify relationship)
   - Check for breaking changes

2. **Review Existing Migrations**
   - Check migration scripts in the project root
   - Pattern: `migrate_*.py` or `add_*.py`
   - Examples: `migrate_add_tier_columns.py`, `migrate_security_fields.py`

3. **Plan Data Migration**
   - Will existing data need to be transformed?
   - Default values for new columns?
   - Backwards compatibility considerations?

### Phase 2: Creating Migration Script

#### Migration Script Template

```python
"""
Migration: [Description of changes]
Date: [Current date]
"""
from models import db, User, Conversation, ChatMessage  # Import relevant models
from app import app

def migrate():
    """Perform the migration"""
    with app.app_context():
        try:
            # Example 1: Add new column
            with db.engine.connect() as conn:
                # Check if column exists first
                result = conn.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='users' AND column_name='new_field'
                """)
                if not result.fetchone():
                    conn.execute("""
                        ALTER TABLE users ADD COLUMN new_field VARCHAR(255)
                    """)
                    print("✓ Added new_field column to users table")

            # Example 2: Create new table
            db.create_all()
            print("✓ Created all new tables")

            # Example 3: Migrate existing data
            users = User.query.all()
            for user in users:
                if not hasattr(user, 'subscription_tier_id'):
                    user.subscription_tier_id = 1  # Default to free tier
            db.session.commit()
            print(f"✓ Migrated {len(users)} users")

            print("\n✅ Migration completed successfully!")

        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {str(e)}")
            raise

def rollback():
    """Rollback the migration if needed"""
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                conn.execute("ALTER TABLE users DROP COLUMN new_field")
            print("✅ Rollback completed successfully!")
        except Exception as e:
            print(f"❌ Rollback failed: {str(e)}")
            raise

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'rollback':
        rollback()
    else:
        migrate()
```

### Phase 3: Testing the Migration

#### Pre-Migration Checks

```bash
# 1. Backup database
cp instance/devops.db instance/devops.db.backup

# 2. Verify current schema
python -c "from models import db, User; from app import app; app.app_context().push(); print(User.__table__.columns.keys())"

# 3. Check for pending migrations
ls -la migrate_*.py
```

#### Run Migration in Test Environment

```bash
# 1. Run migration
python migrate_new_feature.py

# 2. Verify changes
python -c "from models import db; from app import app; app.app_context().push(); print(db.engine.table_names())"

# 3. Test application
python app.py
# Visit http://localhost:5000 and test affected features

# 4. If issues found, rollback
python migrate_new_feature.py rollback
cp instance/devops.db.backup instance/devops.db
```

### Phase 4: Common Migration Patterns

#### Adding a Column

```python
from sqlalchemy import Column, String, Integer, Boolean, DateTime

# In models.py, add to relevant model:
class User(db.Model):
    # ... existing fields ...
    new_field = db.Column(db.String(255), nullable=True)

# In migration script:
with db.engine.connect() as conn:
    conn.execute("ALTER TABLE users ADD COLUMN new_field VARCHAR(255)")
```

#### Adding a Table

```python
# In models.py, create new model:
class NewFeature(db.Model):
    __tablename__ = 'new_features'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

# In migration script:
from models import NewFeature
db.create_all()  # Creates all missing tables
```

#### Adding Foreign Key Relationship

```python
# In models.py:
class User(db.Model):
    subscriptions = db.relationship('UserSubscription', backref='user', lazy=True)

class UserSubscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

# Migration:
db.create_all()  # SQLAlchemy handles FK creation
```

#### Modifying Column Type

```python
# SQLite doesn't support ALTER COLUMN, need to recreate table
with db.engine.connect() as conn:
    # Create new table with correct schema
    conn.execute("""
        CREATE TABLE users_new AS SELECT * FROM users
    """)
    # Drop old table
    conn.execute("DROP TABLE users")
    # Rename new table
    conn.execute("ALTER TABLE users_new RENAME TO users")
```

#### Migrating Data

```python
# Update existing records
users = User.query.filter_by(subscription_tier_id=None).all()
for user in users:
    user.subscription_tier_id = 1  # Free tier
db.session.commit()
```

### Phase 5: Production Migration

#### Pre-Production Checklist

- [ ] Migration tested in development
- [ ] Database backup created
- [ ] Rollback script tested
- [ ] Downtime window planned (if needed)
- [ ] Users notified (if applicable)
- [ ] Monitoring in place

#### Production Migration Steps

```bash
# 1. Backup production database
# For SQLite:
cp /path/to/production/devops.db /path/to/backup/devops.db.$(date +%Y%m%d_%H%M%S)

# For PostgreSQL:
pg_dump dbname > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. Run migration
python migrate_new_feature.py

# 3. Verify migration
python verify_migration.py

# 4. Monitor application
tail -f logs/app.log

# 5. If issues, rollback immediately
python migrate_new_feature.py rollback
# Restore from backup if needed
```

### Phase 6: Verification

#### Verification Script Template

```python
"""Verify migration was successful"""
from models import db, User
from app import app

def verify():
    with app.app_context():
        # Check schema
        columns = User.__table__.columns.keys()
        assert 'new_field' in columns, "new_field column not found"

        # Check data
        count = User.query.count()
        users_with_field = User.query.filter(User.new_field.isnot(None)).count()
        print(f"Total users: {count}")
        print(f"Users with new_field: {users_with_field}")

        # Test functionality
        test_user = User.query.first()
        if test_user:
            print(f"Sample user new_field: {test_user.new_field}")

        print("✅ Verification passed!")

if __name__ == '__main__':
    verify()
```

## Available Migration Scripts

Based on the project, these migrations exist:
- `migrate_add_tier_columns.py` - Adds subscription tier columns
- `migrate_security_fields.py` - Adds security-related fields
- `init_subscription_system.py` - Initializes subscription tiers
- `update_pricing_tiers.py` - Updates pricing tier data
- `verify_tiers.py` - Verifies tier configuration

## Troubleshooting

**"Table already exists" error:**
- Use `IF NOT EXISTS` in CREATE TABLE
- Check existing schema before creating

**"Column already exists" error:**
- Check if column exists before adding
- Use information_schema to verify

**Data loss during migration:**
- Always backup first
- Test in development
- Use transactions

**Foreign key constraint violation:**
- Ensure referenced records exist
- Add foreign keys after data migration
- Use CASCADE options carefully

## Best Practices

1. **Always backup before migration** - Create timestamped backups
2. **Test migrations thoroughly** - Use copy of production data
3. **Make migrations reversible** - Include rollback functionality
4. **Use transactions** - Wrap migrations in try/except with rollback
5. **Document changes** - Add clear comments in migration scripts
6. **Version control** - Commit migrations to git
7. **Keep migrations small** - One logical change per migration
8. **Check existing data** - Verify column/table doesn't exist
9. **Use idempotent migrations** - Safe to run multiple times

## Quick Commands

```bash
# List all migration files
ls -la migrate_*.py

# Run a migration
python migrate_add_tier_columns.py

# Rollback a migration
python migrate_add_tier_columns.py rollback

# Check database schema
python -c "from models import db; from app import app; app.app_context().push(); print(db.engine.table_names())"

# Backup database
cp instance/devops.db instance/devops.db.backup

# Create all tables from models
python -c "from models import db; from app import app; app.app_context().push(); db.create_all(); print('Tables created')"

# Drop all tables (DANGEROUS!)
python -c "from models import db; from app import app; app.app_context().push(); db.drop_all(); print('Tables dropped')"
```
