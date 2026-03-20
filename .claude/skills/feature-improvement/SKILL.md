---
name: feature-improvement
description: Systematically audit and improve existing features across the DevOps Agent app — performance, UX, error handling, security, and missing functionality. Use when you want to harden and polish the application.
---

# Feature Improvement Workflow

Audit existing features, identify gaps, and implement improvements immediately.

## How to Use

When invoked, ask the user which improvement area to focus on (or run all):

1. **Performance** — Query optimization, caching, lazy loading, connection pooling
2. **UX & Frontend** — Loading states, error messages, mobile responsiveness, accessibility
3. **Error Handling** — Missing try/catch, unhelpful error messages, silent failures
4. **Security Hardening** — Input validation gaps, missing rate limits, CSRF coverage, header security
5. **Missing Functionality** — Stub routes, placeholder endpoints, TODO comments
6. **API Consistency** — Response format standardization, pagination, error codes
7. **All of the above** — Full sweep

## Area 1: Performance Audit

### Database Queries
```bash
# Find N+1 query patterns — routes that query inside loops
grep -rn "\.query\." routes/ app.py | grep -c "for\|while" || true
```

Check for:
- Routes that call `db.session.query()` or `.query.` inside loops (N+1 problem)
- Missing `.joinedload()` or `.selectinload()` on relationships
- Missing database indexes on frequently filtered columns
- Unbounded queries without `.limit()` — risk of returning thousands of rows

### Caching Opportunities
- Identify expensive operations that could be cached:
  - Subscription tier lookups (already cached per-request — verify)
  - Tool list generation (`get_tools()` called on every chat request?)
  - User preference lookups
  - Dashboard summary aggregations
- Check if `services/cache_service.py` is being used effectively

### Response Size
- Find routes returning large payloads without pagination
- Ensure list endpoints use `page`/`per_page` params
- Check for unnecessary fields in API responses (over-fetching)

### Improvements to implement:
- Add `.limit()` to any unbounded list queries
- Add eager loading (`.options(joinedload(...))`) where relationships are always accessed
- Add `@cache_service.cached()` to expensive read-only endpoints
- Add pagination to any list endpoint missing it

## Area 2: UX & Frontend Audit

### Templates to Review
Scan all templates for common UX issues:

```bash
# Templates missing loading states
grep -rL "loading\|spinner\|skeleton" templates/ --include="*.html" | head -20

# Templates missing empty states
grep -rL "empty-state\|no-data\|no-results" templates/ --include="*.html" | head -20

# Templates missing error handling in JS
grep -rL "catch\|onerror\|error" templates/ --include="*.html" | head -20
```

Check for:
- Forms without client-side validation
- Buttons without loading/disabled state during API calls
- Missing empty states ("No incidents found", "No monitoring rules configured")
- Missing confirmation dialogs before destructive actions
- Mobile responsiveness issues (check `@media` queries)
- Accessibility: missing `aria-label`, `alt` text, `role` attributes
- Flash messages / toast notifications for success/failure feedback

### Improvements to implement:
- Add loading spinners to forms and buttons that trigger API calls
- Add empty state messages with call-to-action buttons
- Add confirmation modals for delete operations
- Add `aria-label` to icon-only buttons
- Ensure all `<img>` tags have `alt` attributes

## Area 3: Error Handling Audit

### Backend Error Handling
```bash
# Find bare except clauses (swallowing errors silently)
grep -rn "except:" routes/ services/ app.py --include="*.py" | grep -v "except Exception"

# Find empty except blocks
grep -rn -A1 "except" routes/ services/ app.py --include="*.py" | grep "pass$"

# Find routes without try/except around external API calls
grep -rn "requests\.\|client\.\|api_call" services/ --include="*.py" | head -20
```

Check for:
- Routes that don't catch database errors (IntegrityError, OperationalError)
- Services calling external APIs without timeout parameters
- Missing error responses — routes that crash instead of returning proper JSON errors
- Webhook handlers that don't handle malformed payloads
- Background tasks that fail silently without logging

### Frontend Error Handling
```bash
# Find fetch() calls without .catch()
grep -rn "fetch(" templates/ --include="*.html" | head -20
```

### Improvements to implement:
- Replace bare `except:` with specific exception types
- Add timeouts to all external HTTP calls (`requests.get(url, timeout=10)`)
- Add proper error responses (JSON with error code + message) to API routes
- Add `.catch()` to all frontend `fetch()` calls with user-friendly error display
- Add logging to all except blocks (`logger.error(...)`)

## Area 4: Security Hardening Audit

### Input Validation
```bash
# Find routes accepting user input without validation
grep -rn "request\.form\|request\.json\|request\.args" routes/ app.py --include="*.py" | head -30

# Find routes missing @login_required
grep -rn "@.*\.route\|@app\.route" routes/ app.py --include="*.py" | head -40
```

Check for:
- Routes accepting POST data without input validation or sanitization
- Missing `@login_required` on protected endpoints
- SQL injection vectors (raw SQL queries, string formatting in queries)
- XSS vectors (unescaped user content rendered in templates)
- Missing CSRF protection on form submissions
- File upload endpoints without file type/size validation
- API endpoints without rate limiting

### Header Security
```bash
# Check Talisman configuration
grep -rn "Talisman\|CSP\|Content-Security-Policy" app.py
```

### Improvements to implement:
- Add input length limits and type validation to all POST endpoints
- Ensure `@login_required` is on every protected route
- Add rate limiting to sensitive endpoints (login, signup, API chat)
- Add file type whitelisting and size limits to upload endpoints
- Verify CSP headers are properly configured

## Area 5: Missing Functionality Audit

### Find TODOs and Placeholders
```bash
# TODO/FIXME/HACK comments in code
grep -rn "TODO\|FIXME\|HACK\|XXX\|PLACEHOLDER\|NotImplemented" routes/ services/ app.py src/ --include="*.py"

# Routes that return static/placeholder responses
grep -rn "return jsonify.*placeholder\|pass$\|not_implemented\|501" routes/ services/ app.py --include="*.py"

# Empty route handlers
grep -rn -A2 "def .*():" routes/ --include="*.py" | grep -B1 "pass$"
```

### Check Known TODOs from CLAUDE.md
- `notifications.py` — device registration / push notification wiring
- WebSocket for real-time chat
- Rate limiting middleware

### Improvements to implement:
- Replace placeholder responses with meaningful "coming soon" messages or proper stubs
- Add logging to stub handlers so usage is tracked
- Implement any low-hanging fruit (features that are 80% done)
- Document remaining gaps as GitHub issues if they require significant work

## Area 6: API Consistency Audit

### Response Format
```bash
# Check for inconsistent response formats
grep -rn "return jsonify" routes/ app.py --include="*.py" | head -30
```

Check for:
- Inconsistent success response shapes (`{data: ...}` vs `{result: ...}` vs bare objects)
- Inconsistent error response shapes (`{error: ...}` vs `{message: ...}` vs `{detail: ...}`)
- Missing HTTP status codes (returning 200 for errors)
- Missing pagination metadata (`total`, `page`, `per_page`, `has_next`)
- Inconsistent date formats (ISO 8601 everywhere?)
- Missing `Content-Type` headers on responses

### Standard Response Envelope
All API endpoints should follow this pattern:
```python
# Success
return jsonify({'success': True, 'data': result}), 200

# Error
return jsonify({'success': False, 'error': 'description', 'code': 'ERROR_CODE'}), 4xx

# List with pagination
return jsonify({
    'success': True,
    'data': items,
    'pagination': {'page': page, 'per_page': per_page, 'total': total}
}), 200
```

### Improvements to implement:
- Standardize error response format across all routes
- Add pagination metadata to all list endpoints
- Ensure all dates use ISO 8601 format
- Add proper HTTP status codes to all error responses

## Execution Process

For each area:

1. **Audit** — Run the diagnostic commands and review output
2. **Prioritize** — Rank issues by severity (crash risk > data loss > UX > polish)
3. **Fix** — Implement the improvement directly in the code
4. **Verify** — Re-run the check to confirm the fix works
5. **Test** — Run `pytest tests/ -v --tb=short` after each batch of fixes
6. **Report** — Log what was found and fixed

## Final Report Format

After completing improvements, produce a summary:

| Area | Issues Found | Fixed | Skipped (needs discussion) |
|------|-------------|-------|---------------------------|
| Performance | count | count | count |
| UX & Frontend | count | count | count |
| Error Handling | count | count | count |
| Security | count | count | count |
| Missing Features | count | count | count |
| API Consistency | count | count | count |

For each fix, note:
- **File**: path and line number
- **Issue**: what was wrong
- **Fix**: what was changed
- **Risk**: low/medium/high (chance of regression)

## Rules

- Never break existing functionality — run tests after each change
- Don't over-engineer — keep fixes minimal and focused
- Don't refactor code that isn't broken — only fix actual issues
- Ask the user before making architectural changes
- Log but don't fix issues that require external service setup (e.g., "needs Redis" or "needs S3 bucket")
- Always preserve existing API contracts — don't change response shapes that frontends depend on
