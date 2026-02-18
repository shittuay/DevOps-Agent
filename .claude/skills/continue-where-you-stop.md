---
name: continue-where-you-stop
description: Automatically pick up and continue unfinished work after a session interruption, rate limit, or context reset. Unlike resume-work (which reports state), this skill actively resumes execution.
---

# Continue Where You Stopped

## When to Use

Run `/continue-where-you-stop` when:
- A rate limit, token reset, or crash interrupted mid-task
- You returned to a session and want to finish what was started
- Context was compressed and tasks were left incomplete
- You see uncommitted changes and want to finish the job

## Automatic Recovery Workflow

### Phase 1: Assess Current State

```bash
# Check for uncommitted work
git status

# See what was changed
git diff --stat

# Recent commits for context
git log --oneline -5
```

### Phase 2: Check Task List

Check for any pending or in-progress tasks from the previous session. Tasks marked `in_progress` were actively being worked on when the interruption happened — these are the priority.

### Phase 3: Read CLAUDE.md

Read CLAUDE.md to reload project architecture, patterns, resolved issues, and conventions. This is critical after context compression.

### Phase 4: Read Modified Files

For each file with uncommitted changes:
1. Read the file to understand the current state
2. Check if the change looks complete or partial
3. Identify what remains to be done

### Phase 5: Resume Execution

Based on the assessment:

**If tasks exist:** Pick up the first `in_progress` task, re-read the relevant files, and continue the implementation.

**If uncommitted changes exist but no tasks:** Analyze the diff to understand intent, then either:
- Complete the partial change if the intent is clear
- Ask the user to confirm what was being done if unclear

**If everything is committed and clean:** Check the last commit message and CLAUDE.md for planned next steps. Ask the user what to work on.

**If there are staged but uncommitted changes:** The previous session likely finished the work but didn't commit. Review the staged diff and commit if it looks complete.

## Decision Tree

```
git status clean?
├── YES → Check last commit + CLAUDE.md for next steps → Ask user
└── NO → Files modified?
    ├── YES → Read each modified file
    │   ├── Changes look complete → Test/lint, then commit
    │   └── Changes look partial → Check tasks → Continue implementation
    └── Staged only → Review staged diff → Commit if complete
```

## Key Rules

1. **Always re-read files before editing.** After context compression, file contents are lost from memory.
2. **Check tasks first.** If the task list has `in_progress` items, those take priority over guessing from git state.
3. **Don't ask unnecessary questions.** If the intent is clear from git state + tasks + CLAUDE.md, just continue working.
4. **Summarize briefly before continuing.** Tell the user what you found and what you're resuming, then get to work.
5. **Verify after completing.** Run relevant tests or checks before declaring the resumed work done.

## Example Output

```
Resuming from previous session:

**Last commit:** feat: Add free trial system (9beff99)
**In-progress tasks:** #6 - Add frontend upgrade CTA in index.html
**Uncommitted changes:** templates/index.html (partial edit)

Picking up task #6 — reading the file and continuing the implementation...
```
