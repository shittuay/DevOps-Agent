---
name: commit-push
description: Stage all changes, commit with a descriptive message, and push to origin/main. Use when you need to commit and push current work.
---

# Commit and Push

Commit all current changes and push to `origin/main`.

## Steps

1. **Check current state** (run in parallel):
   ```bash
   git status
   git diff --stat
   git log --oneline -5
   ```

2. **Review changes** and draft a commit message:
   - Analyze the diff to understand what changed
   - Use the project's commit style: `type: short description` (e.g. `feat:`, `fix:`, `improve:`)
   - Keep the summary line concise

3. **Stage files** — add modified and new files by name (do NOT use `git add -A`):
   - Do NOT stage files that contain secrets (`.env`, credentials, etc.)
   - Do NOT stage `DevOpsAgent_Analysis_Report.docx` unless explicitly asked

4. **Commit** using a HEREDOC for the message:
   ```bash
   git commit -m "$(cat <<'EOF'
   type: Short description of changes

   Optional longer description if needed.

   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
   EOF
   )"
   ```

5. **Push** to remote:
   ```bash
   git push origin main
   ```

6. **Report result** to the user:
   - Commit hash and message
   - Number of files changed
   - Any Dependabot alerts from the push output
