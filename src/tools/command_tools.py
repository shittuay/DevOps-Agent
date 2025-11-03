"""Command execution tools for DevOps Agent."""
import subprocess
import shlex
import time
from typing import Dict, Any, List, Optional
from ..utils import get_logger


logger = get_logger(__name__)


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
        # Execute command with timeout
        result = subprocess.run(
            command,
            shell=True,
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
