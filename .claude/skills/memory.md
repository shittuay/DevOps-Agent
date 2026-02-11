---
name: memory
description: Maintain a persistent work log (WORKLOG.md) that tracks session activity, recent changes, pending tasks, and current state. Use proactively at the end of work sessions or when the user says to remember something. Also use at the start of new sessions to reload context.
---

# Memory - Persistent Work Log

## Overview

This skill maintains `WORKLOG.md` at the project root as a living memory file. It tracks what was worked on, what's pending, recent decisions, and the current deployment state. This file survives token resets and session boundaries.

## When to Use

### Writing Memory (update WORKLOG.md)
- After completing a significant task or fix
- Before a likely token reset (large context)
- When the user says "remember this" or "save progress"
- After deployments
- When important decisions are made

### Reading Memory (start of session)
- At the beginning of every new session
- After a token reset or rate limit disruption
- When the user asks "what were we doing?" or "pick up where we left off"

## WORKLOG.md Format

```markdown
# DevOps Agent - Work Log

> Auto-maintained by Claude Code `/memory` skill. Last updated: [timestamp]

## Current State
- **Last Session:** [date and brief summary]
- **Deploy Status:** [last deploy result and URL]
- **Branch:** [current branch]
- **Uncommitted Work:** [yes/no + description if yes]

## Recent Changes (last 5 sessions)

### [Date] - [Brief Title]
- What was done: [summary]
- Files changed: [list]
- Deployed: [yes/no]
- Commit: [hash + message]

## Pending / In Progress
- [ ] [Task description]
- [ ] [Task description]

## Important Decisions
- [Date]: [Decision and reasoning]

## Known Issues
- [Issue description and workaround if any]

## User Preferences
- [Any stated preferences about workflow, style, approach]
```

## Workflow

### Saving Memory

1. Read current WORKLOG.md (create if doesn't exist)
2. Update the "Current State" section with latest info
3. Add entry to "Recent Changes" (keep last 5, archive older ones)
4. Update "Pending / In Progress" based on task list
5. Add any new decisions or known issues
6. Write the updated file

### Loading Memory

1. Read WORKLOG.md
2. Read CLAUDE.md for architecture context
3. Run `git status` and `git log --oneline -5` for current state
4. Cross-reference WORKLOG.md with actual git state
5. Summarize current state to user

### Quick Commands

```bash
# Check what's in the work log
cat WORKLOG.md

# See recent git activity to cross-reference
git log --oneline -10
git status
```

## Rules

- Keep entries concise (1-2 lines each)
- Never store secrets, credentials, or API keys
- Maximum 5 recent sessions in the log (archive older)
- Always include commit hashes for traceability
- Update deploy status after every deployment
- Flag any uncommitted work prominently
