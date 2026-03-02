---
name: run-test-again
description: Run the full pytest test suite against the PostgreSQL test database. Use when you need to re-run tests to verify changes.
---

# Run Tests

Run the full pytest suite against the PostgreSQL test database (`devops_agent_test` on localhost:5432).

## Steps

1. **Verify PostgreSQL is running** via Docker:
   ```bash
   docker ps | grep devops-postgres
   ```
   If not running, start it:
   ```bash
   docker start devops-postgres
   ```

2. **Run the full test suite**:
   ```bash
   cd C:\Users\shitt\Downloads\devops-agent
   python -m pytest tests/ -v --tb=short
   ```

3. **Report results** to the user:
   - Total passed / failed / errors
   - If any failures, show the failing test names and short tracebacks
   - If all pass, confirm the count (e.g. "71 passed, 0 failed")
