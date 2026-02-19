---
name: resume-work
description: Recover context and resume work after a rate limit disruption, token reset, or context compression. Use at the start of a new session to pick up where you left off.
---

# Resume Work After Disruption

## When to Use

Run `/resume-work` when:
- A rate limit or token reset interrupted your session
- Context was compressed and you lost track of what you were doing
- Starting a new session and need to continue previous work
- You need to understand what was recently changed

## Recovery Workflow

### Step 1: Check Git State

Understand what was recently modified, staged, or committed:

```bash
# What files have uncommitted changes?
git status

# What was changed but not yet committed?
git diff --stat

# What are the staged changes?
git diff --cached --stat

# What were the last 10 commits?
git log --oneline -10

# What was the last commit about?
git log -1 --format="%H %s%n%n%b"
```

### Step 2: Identify In-Progress Work

Look for signs of incomplete work:

```bash
# Files modified but not committed (likely in-progress)
git diff --name-only

# Check if there are any TODO/FIXME markers recently added
git diff | grep -E "TODO|FIXME|HACK|XXX" || true

# Check for any partial changes in key files
git diff app.py --stat 2>/dev/null
git diff models.py --stat 2>/dev/null
```

### Step 3: Read CLAUDE.md for Context

CLAUDE.md contains the project's persistent memory. Read it to understand:
- Project architecture and patterns
- Recently resolved issues (check the Resolved Issues table)
- Available skills and tools
- Security patterns that must be followed

### Step 4: Check Task List

If tasks were created in a previous session, check for any pending work:
- Review any pending or in-progress tasks
- Identify what was completed vs what remains

### Step 5: Reconstruct What Was Happening

Based on the git state, determine:
1. **What was the goal?** — Look at the most recent commit messages and diff
2. **What's done?** — Committed changes are complete
3. **What's in progress?** — Uncommitted changes are likely mid-work
4. **What's next?** — Check if the uncommitted changes look complete or partial

### Step 6: Report Findings

Summarize for the user:
- What the last session was working on
- What was completed (committed)
- What's still in progress (uncommitted changes)
- What likely needs to be done next
- Any files that were being modified

## Quick Recovery Checklist

- [ ] Run `git status` to see current state
- [ ] Run `git log --oneline -5` for recent commits
- [ ] Run `git diff --stat` for uncommitted changes
- [ ] Read CLAUDE.md for project context
- [ ] Check for pending tasks
- [ ] Summarize state to the user
- [ ] Ask user to confirm what they want to continue with

## Common Scenarios

### Scenario: Mid-edit disruption
Signs: Modified files in `git diff`, no recent commit for the work
Action: Read the modified files, understand the partial change, continue the edit

### Scenario: Code written but not tested
Signs: Recent commit with new code, no test-related commits after
Action: Run tests, verify the code works

### Scenario: Multiple files changed, unclear purpose
Signs: Several modified files with no commit
Action: Read each modified file's diff, piece together the intent, ask user to confirm

### Scenario: Clean state, nothing in progress
Signs: `git status` shows clean working tree
Action: Check last commit message, ask user what they want to work on next
