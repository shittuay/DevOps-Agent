"""Command execution tools for DevOps Agent."""
import os
import subprocess
import shlex
import time
from typing import Dict, Any, List, Optional
from ..utils import get_logger


logger = get_logger(__name__)

# Only binaries in this set may be invoked.  Execution environments (sh, bash,
# python, perl, nc, …) are intentionally excluded to prevent RCE via the AI.
#
# NOTE: 'ansible', 'ansible-playbook', 'ansible-galaxy' are intentionally
# excluded — they must go through src/tools/ansible_tools.py, which enforces
# a module allowlist (_ALLOWED_ANSIBLE_MODULES). Allowing them here would let
# a caller bypass that allowlist entirely (e.g. `ansible all -m shell -a ...`
# or a raw `ansible-playbook` running a `shell`/`command` task).
_ALLOWED_BINARIES: frozenset = frozenset({
    # File / text inspection
    'cat', 'ls', 'find', 'grep', 'awk', 'sed', 'head', 'tail', 'wc',
    'sort', 'uniq', 'cut', 'tr', 'echo', 'printf', 'date', 'hostname',
    'uname', 'whoami', 'id', 'env', 'printenv', 'pwd', 'which',
    # System info
    'ps', 'df', 'du', 'free', 'uptime', 'netstat', 'ss',
    # DevOps / cloud CLIs
    'kubectl', 'helm', 'docker', 'docker-compose',
    'terraform',
    'git', 'make', 'jq', 'yq',
    'aws', 'gcloud', 'az',
    # Network diagnostics (read-only)
    'ping', 'nslookup', 'dig', 'host', 'traceroute',
    # Service management
    'systemctl', 'service',
})

# Per-binary argument denylist. Several allowlisted binaries have built-in
# features that spawn a shell / execute arbitrary code or files, which would
# otherwise defeat the binary allowlist above (e.g. `awk 'BEGIN{system(...)}'`,
# `find . -exec sh -c ... \;`, `git -c alias.x=!... x`, `docker run -v /:/mnt
# ... chroot`, `terraform apply` running a `local-exec` provisioner).
# Returns (is_blocked, reason) for the given binary + its argv (excluding argv[0]).
def _check_binary_args(binary: str, args: List[str]) -> Optional[str]:
    joined = ' '.join(args)

    if binary == 'find':
        for flag in ('-exec', '-execdir', '-ok', '-okdir'):
            if flag in args:
                return f"'{flag}' spawns arbitrary processes and is not permitted"

    if binary == 'awk':
        if 'system(' in joined.replace(' ', ''):
            return "awk's system() function is not permitted (spawns a shell)"

    if binary in ('git',):
        if '-c' in args:
            return "'git -c' (arbitrary config override) is not permitted"
        if 'alias.' in joined and '!' in joined:
            return "git alias shell-escapes ('!...') are not permitted"

    if binary in ('docker', 'docker-compose'):
        for flag in ('--privileged', '--cap-add', '--device', '-v', '--volume',
                     '--mount', '--entrypoint', '--pid'):
            if any(a == flag or a.startswith(flag + '=') for a in args):
                return f"docker flag '{flag}' is not permitted via execute_command"
        if binary == 'docker' and args and args[0] in ('run', 'create'):
            return "'docker run'/'docker create' are not permitted via execute_command; use the dedicated docker tools instead"

    if binary == 'terraform':
        if args and args[0] in ('apply', 'destroy'):
            return "'terraform apply'/'terraform destroy' are not permitted via execute_command (they can run local-exec provisioners); use the dedicated terraform tools instead"

    return None


def execute_command(
    command: str,
    timeout: Optional[int] = None,
    dry_run: bool = False,
    working_directory: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a shell command safely with timeout protection.

    Args:
        command: Command to execute
        timeout: Timeout in seconds (default from config)
        dry_run: If True, don't actually execute
        working_directory: Working directory for command execution

    Returns:
        Dictionary with execution results
    """
    start_time = time.time()

    logger.info(f"Executing command: {command}")

    if dry_run:
        return {
            'success': True,
            'command': command,
            'stdout': '',
            'stderr': '',
            'exit_code': 0,
            'execution_time_ms': 0,
            'dry_run': True,
            'message': 'Dry run - command not executed'
        }

    try:
        # Split command string into list to avoid shell=True injection risk
        try:
            command_args = shlex.split(command)
        except ValueError as e:
            return {
                'success': False,
                'command': command,
                'stdout': '',
                'stderr': f'Invalid command syntax: {e}',
                'exit_code': -1,
                'execution_time_ms': 0,
                'dry_run': False,
                'error': str(e)
            }

        binary = os.path.basename(command_args[0])
        if binary not in _ALLOWED_BINARIES:
            logger.warning(f"Blocked execution of non-allowlisted binary: {binary}")
            return {
                'success': False,
                'command': command,
                'stdout': '',
                'stderr': f"Binary '{binary}' is not permitted. Allowed tools: {', '.join(sorted(_ALLOWED_BINARIES))}",
                'exit_code': -1,
                'execution_time_ms': 0,
                'dry_run': False,
                'error': 'binary_not_allowed'
            }

        block_reason = _check_binary_args(binary, command_args[1:])
        if block_reason:
            logger.warning(f"Blocked '{binary}' invocation: {block_reason}")
            return {
                'success': False,
                'command': command,
                'stdout': '',
                'stderr': block_reason,
                'exit_code': -1,
                'execution_time_ms': 0,
                'dry_run': False,
                'error': 'argument_not_allowed'
            }

        # GNU sed's 'e', 'w', 'r' commands can execute/read/write arbitrary
        # files; --sandbox disables them. Harmless no-op on non-GNU sed builds
        # that reject the flag (falls through to the normal error path below).
        if binary == 'sed' and '--sandbox' not in command_args:
            command_args = [command_args[0], '--sandbox'] + command_args[1:]

        result = subprocess.run(
            command_args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout or 300,
            cwd=working_directory
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        response = {
            'success': result.returncode == 0,
            'command': command,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode,
            'execution_time_ms': execution_time_ms,
            'dry_run': False
        }

        if result.returncode == 0:
            response['message'] = 'Command executed successfully'
            logger.info(f"Command succeeded in {execution_time_ms}ms")
        else:
            response['message'] = f'Command failed with exit code {result.returncode}'
            logger.error(f"Command failed with exit code {result.returncode}")

        return response

    except subprocess.TimeoutExpired:
        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Command timed out after {timeout}s")
        return {
            'success': False,
            'command': command,
            'stdout': '',
            'stderr': f'Command timed out after {timeout} seconds',
            'exit_code': -1,
            'execution_time_ms': execution_time_ms,
            'dry_run': False,
            'error': 'timeout'
        }

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Command execution failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'command': command,
            'stdout': '',
            'stderr': str(e),
            'exit_code': -1,
            'execution_time_ms': execution_time_ms,
            'dry_run': False,
            'error': str(e)
        }


def execute_script(
    script_path: str,
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    working_directory: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a script file with arguments.

    Args:
        script_path: Path to script file
        args: List of arguments to pass to script
        timeout: Timeout in seconds
        working_directory: Working directory for script execution

    Returns:
        Dictionary with execution results
    """
    # Build command
    command_parts = [script_path]
    if args:
        command_parts.extend(args)

    command = ' '.join(shlex.quote(part) for part in command_parts)

    logger.info(f"Executing script: {script_path} with args: {args}")

    return execute_command(
        command=command,
        timeout=timeout,
        working_directory=working_directory
    )


def get_command_history(limit: int = 10) -> Dict[str, Any]:
    """
    Get command execution history from logs.

    Args:
        limit: Number of recent commands to return

    Returns:
        Dictionary with command history
    """
    # This is a placeholder - in a real implementation,
    # you would query the structured logs
    return {
        'success': True,
        'message': 'Command history feature coming soon',
        'history': []
    }


def get_tools() -> List[Dict[str, Any]]:
    """
    Get tool definitions for command execution.

    Returns:
        List of tool definitions
    """
    return [
        {
            'name': 'execute_command',
            'description': (
                'Execute a shell command safely with timeout protection. '
                'Use this for running system commands, checking status, '
                'or performing operations that don\'t have dedicated tools. '
                'The command will be executed with a timeout to prevent hanging.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'command': {
                        'type': 'string',
                        'description': 'The shell command to execute'
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': 'Timeout in seconds (default: 300)',
                        'default': 300
                    },
                    'dry_run': {
                        'type': 'boolean',
                        'description': 'If true, show what would be executed without running it',
                        'default': False
                    },
                    'working_directory': {
                        'type': 'string',
                        'description': 'Working directory for command execution'
                    }
                },
                'required': ['command']
            },
            'handler': execute_command
        },
        {
            'name': 'execute_script',
            'description': (
                'Execute a script file (bash, python, etc.) with arguments. '
                'The script must exist and be executable.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'script_path': {
                        'type': 'string',
                        'description': 'Path to the script file'
                    },
                    'args': {
                        'type': 'array',
                        'description': 'List of arguments to pass to the script',
                        'items': {'type': 'string'}
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': 'Timeout in seconds (default: 300)',
                        'default': 300
                    },
                    'working_directory': {
                        'type': 'string',
                        'description': 'Working directory for script execution'
                    }
                },
                'required': ['script_path']
            },
            'handler': execute_script
        }
    ]
