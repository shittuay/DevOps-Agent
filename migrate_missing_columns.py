"""
Universal migration: add any columns present in SQLAlchemy models but missing from the DB.
Idempotent — safe to re-run on every deploy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from sqlalchemy import inspect, text
import models  # ensure all models are registered

# Column type mappings for ALTER TABLE
COLUMN_TYPE_MAP = {
    'Boolean':  'BOOLEAN',
    'Integer':  'INTEGER',
    'String':   'VARCHAR(255)',
    'Text':     'TEXT',
    'DateTime': 'TIMESTAMP',
    'Float':    'FLOAT',
    'JSON':     'TEXT',
}

def sql_type(col):
    type_name = type(col.type).__name__
    if type_name == 'String' and hasattr(col.type, 'length') and col.type.length:
        return f'VARCHAR({col.type.length})'
    return COLUMN_TYPE_MAP.get(type_name, 'TEXT')

def default_clause(col):
    if col.default is not None and col.default.is_scalar:
        val = col.default.arg
        if isinstance(val, bool):
            return ' DEFAULT ' + ('TRUE' if val else 'FALSE')
        if isinstance(val, int):
            return f' DEFAULT {val}'
    if col.nullable is False:
        type_name = type(col.type).__name__
        if type_name == 'Boolean':
            return ' DEFAULT FALSE'
        if type_name == 'Integer':
            return ' DEFAULT 0'
    return ''


def migrate():
    with app.app_context():
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        total_added = 0

        for mapper in db.Model.registry.mappers:
            cls = mapper.class_
            table = getattr(cls, '__tablename__', None)
            if not table or table not in existing_tables:
                continue

            db_cols = {col['name'] for col in inspector.get_columns(table)}
            missing = [
                col for col in cls.__table__.columns
                if col.key not in db_cols
            ]

            if not missing:
                continue

            with db.engine.connect() as conn:
                for col in missing:
                    col_sql = f'ALTER TABLE {table} ADD COLUMN {col.key} {sql_type(col)}{default_clause(col)}'
                    print(f"Adding {table}.{col.key} ...")
                    conn.execute(text(col_sql))
                    total_added += 1
                conn.commit()

        if total_added:
            print(f"\n{total_added} column(s) added successfully.")
        else:
            print("All columns present — nothing to do.")


if __name__ == '__main__':
    try:
        migrate()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
