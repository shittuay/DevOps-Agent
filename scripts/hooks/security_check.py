#!/usr/bin/env python3
"""
Security check hook for Claude Code.

This hook runs before dangerous Bash commands to validate they're safe.
Exit code 0 = allow, non-zero = block.
"""
import sys
import re
import json

# Patterns that should ALWAYS be blocked
BLOCKED_PATTERNS = [
    r'rm\s+-rf\s+/',
    r'rm\s+-rf\s+\*',
    r'DROP\s+DATABASE',
    r'DELETE\s+FROM.*WHERE\s+1\s*=\s*1',
    r'TRUNCATE\s+TABLE',
    r'>\s*/dev/sd[a-z]',
    r'mkfs\.',
    r'dd\s+if=.*of=/dev/',
    r'chmod\s+-R\s+777\s+/',
    r'curl.*\|\s*sh',
    r'wget.*\|\s*sh',
]

# Patterns that need confirmation (warning only)
WARN_PATTERNS = [
    r'git\s+push\s+--force',
    r'git\s+reset\s+--hard',
    r'DROP\s+TABLE',
    r'DELETE\s+FROM',
    r'pip\s+uninstall',
    r'npm\s+uninstall',
    r'rm\s+-rf',
]

def check_command(command: str) -> tuple[bool, str]:
    """
    Check if a command is safe to execute.

    Returns:
        (is_safe, message)
    """
    command_lower = command.lower()

    # Check blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"BLOCKED: Command matches dangerous pattern '{pattern}'"

    # Check warning patterns (allow but warn)
    for pattern in WARN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            print(f"WARNING: Command matches pattern '{pattern}' - use caution", file=sys.stderr)

    return True, "OK"


def main():
    """Main entry point for the hook."""
    # Read command from stdin or args
    if len(sys.argv) > 1:
        command = ' '.join(sys.argv[1:])
    else:
        command = sys.stdin.read().strip()

    if not command:
        print("No command provided", file=sys.stderr)
        sys.exit(0)  # Allow empty commands

    is_safe, message = check_command(command)

    if not is_safe:
        print(f"Security check failed: {message}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
