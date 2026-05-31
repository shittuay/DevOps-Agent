#!/usr/bin/env python3
"""
Docs-update routine hook for Claude Code (Stop hook).

Fires when Claude finishes a turn. Detects code-vs-docs drift: if code files
changed in the working tree but no documentation file was updated, it blocks
the stop and instructs the agent to auto-update the docs (CLAUDE.md and
friends) before finishing.

Behavior:
  - No code changes, or docs already updated -> exit 0 (allow stop).
  - Code changed but docs untouched         -> emit {"decision":"block",...}
    so the agent updates the docs, then re-runs and passes on the next stop.

Safety:
  - Honors `stop_hook_active` to avoid infinite loops.
  - Set DOCS_HOOK_DISABLE=1 to bypass entirely.
  - Fails open: any error -> exit 0 (never blocks finishing work).
"""
import sys
import os
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Source extensions that, when changed, are expected to be reflected in docs.
CODE_EXTENSIONS = ('.py', '.html', '.js', '.css', '.yaml', '.yml')

# Paths whose changes do NOT require a docs update (tests, hooks, config noise).
IGNORED_PREFIXES = (
    'tests/',
    'scripts/hooks/',
    '.claude/',
    'logs/',
    '.playwright-mcp/',
)

# Any change to one of these counts as "docs were updated".
DOC_SUFFIXES = ('.md',)


def changed_files():
    """Return list of changed (staged + unstaged + untracked) repo paths."""
    out = subprocess.run(
        ['git', 'status', '--porcelain'],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    files = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        # porcelain format: XY <path>  (or "XY orig -> new" for renames)
        path = line[3:].strip()
        if ' -> ' in path:
            path = path.split(' -> ', 1)[1]
        files.append(path)
    return files


def is_ignored(path: str) -> bool:
    return any(path.startswith(p) for p in IGNORED_PREFIXES)


def main():
    if os.environ.get('DOCS_HOOK_DISABLE') == '1':
        sys.exit(0)

    # Parse Claude Code Stop-hook payload from stdin.
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:
        payload = {}

    # Loop guard: if we already blocked once and the agent is re-running the
    # stop hook, do not block again.
    if payload.get('stop_hook_active'):
        sys.exit(0)

    try:
        files = changed_files()
    except Exception:
        # Fail open - never block on a git error.
        sys.exit(0)

    relevant = [f for f in files if not is_ignored(f)]
    code_changed = [f for f in relevant if f.endswith(CODE_EXTENSIONS)]
    docs_changed = [f for f in relevant if f.endswith(DOC_SUFFIXES)]

    if code_changed and not docs_changed:
        reason = (
            "Routine docs check: code changed but no documentation was updated.\n"
            f"Changed code files: {', '.join(code_changed[:15])}"
            f"{' ...' if len(code_changed) > 15 else ''}\n\n"
            "Before finishing, update the docs to reflect these changes:\n"
            "  - CLAUDE.md (architecture, tool inventory, safety rules, env vars)\n"
            "  - CLAUDE_RUNBOOK.md (if you fixed a bug or hit a gotcha)\n"
            "  - CLAUDE_BILLING.md (if billing/pricing/Stripe changed)\n"
            "  - README or feature docs as appropriate\n\n"
            "If the change genuinely needs no doc update (pure refactor, typo, "
            "test-only), say so explicitly in one line and stop."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)

    sys.exit(0)


if __name__ == '__main__':
    main()
