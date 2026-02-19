---
name: update-context
description: Update CLAUDE.md after significant codebase changes. Use after adding features, fixing bugs, changing architecture, adding tools, or modifying configuration patterns.
---

# Update CLAUDE.md Context

## When to Use

Run `/update-context` after any of these changes:
- New tools added to any provider (AWS/K8s/Azure/GCP)
- New routes or API endpoints added to app.py
- Architecture changes (new files, renamed modules, changed patterns)
- New environment variables introduced
- New resolved issues or gotchas discovered
- Security patterns changed
- New models added to models.py
- Billing, payment, or subscription changes
- New skills created

## Workflow

### Step 1: Identify What Changed

Check recent uncommitted changes and recent commits:

```bash
git diff --stat
git diff --name-only
git log --oneline -5
```

### Step 2: Read Current CLAUDE.md

Always read the full CLAUDE.md before editing to understand current state.

### Step 3: Determine Which Sections Need Updates

Map changes to CLAUDE.md sections:

| Change Type | CLAUDE.md Section |
|-------------|-------------------|
| New tool added | Tool Inventory, Verification Commands |
| New API endpoint | Key Architecture or relevant feature section |
| New env var | Environment Variables |
| Bug fix / gotcha found | Resolved Issues / Gotchas |
| New model | Adding a New Model |
| Security change | Critical Security Patterns |
| New file/module | Key Architecture |
| Payment/billing change | Billing & Stripe Payment Flow |
| New skill | Skills Available |
| Pattern change | Relevant pattern section (AWS/K8s/Azure/GCP) |

### Step 4: Apply Updates

Follow these rules:
- Keep entries concise (1-2 lines per item)
- Use the existing format and style of each section
- Update tool counts if tools were added
- Add to the Resolved Issues table if a non-obvious bug was fixed
- Add new env vars with a brief description
- Update the architecture tree if new top-level files were added

### Step 5: Verify

After editing, read back the modified sections to confirm correctness.

## Section Templates

### New Resolved Issue Entry
```
| **Issue name** | Brief solution description. |
```

### New Environment Variable
```
- `VAR_NAME` - Brief description of what it does
```

### Updated Tool Count
```
### AWS (N tools)
```

## Checklist

- [ ] Read CLAUDE.md before editing
- [ ] Updated all relevant sections
- [ ] Tool counts are accurate (verify with python commands)
- [ ] No duplicate entries
- [ ] New env vars documented
- [ ] New gotchas added to Resolved Issues table
- [ ] Skills Available list is current
- [ ] Architecture tree reflects current file structure
