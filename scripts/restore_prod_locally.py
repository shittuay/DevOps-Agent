"""Restore prod SQL dump to local PostgreSQL.

Handles multi-line string literals, dollar-quoted strings, emoji/Unicode,
and psql meta-commands that break naive semicolon splitting.
"""
import sys
import io
import psycopg2

# Force UTF-8 stdout so emoji in error messages don't crash on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements, respecting quoted strings."""
    statements = []
    buf = []
    i = 0
    n = len(sql)

    while i < n:
        c = sql[i]

        # -- line comment: skip to end of line
        if c == '-' and i + 1 < n and sql[i + 1] == '-':
            while i < n and sql[i] != '\n':
                buf.append(sql[i])
                i += 1
            continue

        # /* block comment */
        if c == '/' and i + 1 < n and sql[i + 1] == '*':
            buf.append('/*')
            i += 2
            while i < n - 1:
                if sql[i] == '*' and sql[i + 1] == '/':
                    buf.append('*/')
                    i += 2
                    break
                buf.append(sql[i])
                i += 1
            continue

        # Dollar-quoted string: $tag$...$tag$
        if c == '$':
            j = i + 1
            while j < n and sql[j] != '$' and sql[j] not in (' ', '\t', '\n', '(', ')'):
                j += 1
            if j < n and sql[j] == '$':
                tag = sql[i:j + 1]       # e.g. "$$" or "$func$"
                end = sql.find(tag, j + 1)
                if end != -1:
                    chunk = sql[i:end + len(tag)]
                    buf.append(chunk)
                    i = end + len(tag)
                    continue
            # Not a dollar-quote — treat as literal $
            buf.append(c)
            i += 1
            continue

        # Single-quoted string: '...' with '' escaping
        if c == "'":
            buf.append(c)
            i += 1
            while i < n:
                ch = sql[i]
                buf.append(ch)
                i += 1
                if ch == "'":
                    # Escaped quote ''?
                    if i < n and sql[i] == "'":
                        buf.append(sql[i])
                        i += 1
                    else:
                        break   # End of string
            continue

        # Semicolon outside any quote = statement boundary
        if c == ';':
            stmt = ''.join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(c)
        i += 1

    # Trailing statement with no semicolon
    stmt = ''.join(buf).strip()
    if stmt:
        statements.append(stmt)

    return statements


def main():
    with open('prod_inserts.sql', 'r', encoding='utf-8') as f:
        raw = f.read()

    # Strip psql meta-commands (\connect, \set, etc.)
    lines = [l for l in raw.splitlines() if not l.strip().startswith('\\')]
    sql = '\n'.join(lines)

    conn = psycopg2.connect("postgresql://devops:devops_local@localhost:5432/devops_agent")
    conn.autocommit = True
    cur = conn.cursor()

    # Drop everything in the public schema
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = [row[0] for row in cur.fetchall()]
    if tables:
        cur.execute("DROP TABLE IF EXISTS " + ", ".join(f'"{t}"' for t in tables) + " CASCADE")
        print(f"Dropped {len(tables)} tables")

    cur.execute("SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public'")
    for (seq,) in cur.fetchall():
        cur.execute(f'DROP SEQUENCE IF EXISTS "{seq}" CASCADE')

    cur.execute("SELECT typname FROM pg_type WHERE typnamespace = (SELECT oid FROM pg_namespace WHERE nspname='public') AND typtype='e'")
    for (typ,) in cur.fetchall():
        cur.execute(f'DROP TYPE IF EXISTS "{typ}" CASCADE')

    print("Schema cleared. Parsing SQL...")

    statements = split_sql_statements(sql)
    print(f"Found {len(statements)} statements. Executing...")

    # autocommit=True: each statement is its own transaction.
    # This avoids a single failed statement rolling back everything.
    conn.autocommit = True
    ok = 0
    errors = 0
    for stmt in statements:
        try:
            cur.execute(stmt)
            ok += 1
        except Exception as e:
            errors += 1
            if errors <= 10:
                preview = stmt[:80].replace('\n', ' ')
                print(f"  Skip ({errors}): {str(e)[:120]}")
                print(f"    Stmt: {preview}")
    print(f"\nDone: {ok} executed, {errors} skipped")

    # Quick sanity check
    for table in ('users', 'conversations', 'chat_messages'):
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            print(f"  {table}: {cur.fetchone()[0]} rows")
        except Exception:
            pass

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
