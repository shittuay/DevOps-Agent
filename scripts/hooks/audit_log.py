#!/usr/bin/env python3
"""
Audit logging hook for Claude Code.

This hook runs after tool executions to log actions for compliance/audit.
"""
import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path

# Audit log file location
AUDIT_LOG_DIR = Path(__file__).parent.parent.parent / 'logs'
AUDIT_LOG_FILE = AUDIT_LOG_DIR / 'claude_audit.log'


def ensure_log_dir():
    """Ensure the log directory exists."""
    AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_action(tool_name: str, action: str, result: str = None):
    """
    Log a tool action to the audit log.

    Args:
        tool_name: Name of the tool executed
        action: The action/command that was run
        result: Optional result summary
    """
    ensure_log_dir()

    timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    log_entry = {
        'timestamp': timestamp,
        'tool': tool_name,
        'action': action[:500] if action else None,  # Truncate long actions
        'result_preview': result[:200] if result else None,  # Truncate results
        'user': os.environ.get('USER', os.environ.get('USERNAME', 'unknown')),
        'cwd': os.getcwd()
    }

    try:
        with open(AUDIT_LOG_FILE, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        print(f"Warning: Could not write to audit log: {e}", file=sys.stderr)


def main():
    """Main entry point for the hook."""
    # Parse hook input (typically JSON from Claude Code)
    try:
        if len(sys.argv) > 1:
            # Tool name and action as arguments
            tool_name = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
            action = sys.argv[2] if len(sys.argv) > 2 else ''
            result = sys.argv[3] if len(sys.argv) > 3 else None
        else:
            # Read from stdin
            input_data = sys.stdin.read().strip()
            if input_data:
                try:
                    data = json.loads(input_data)
                    tool_name = data.get('tool', 'unknown')
                    action = data.get('action', data.get('command', ''))
                    result = data.get('result', None)
                except json.JSONDecodeError:
                    tool_name = 'unknown'
                    action = input_data
                    result = None
            else:
                tool_name = 'unknown'
                action = ''
                result = None

        log_action(tool_name, action, result)

    except Exception as e:
        print(f"Audit hook error: {e}", file=sys.stderr)

    # Always exit 0 - audit logging should never block operations
    sys.exit(0)


if __name__ == '__main__':
    main()
