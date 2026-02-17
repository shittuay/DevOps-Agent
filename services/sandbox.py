"""
Docker Sandbox Service

Provides secure, isolated execution environments for running commands
and scripts via Docker containers. Prevents untrusted operations from
affecting the host system.
"""

import os
import logging
import subprocess
import tempfile
import uuid
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Default sandbox image (Alpine-based, minimal attack surface)
DEFAULT_IMAGE = os.environ.get('SANDBOX_IMAGE', 'alpine:3.19')

# Resource limits
DEFAULT_MEMORY_LIMIT = '256m'
DEFAULT_CPU_LIMIT = '0.5'
DEFAULT_TIMEOUT = 30  # seconds
MAX_OUTPUT_LENGTH = 50000  # chars


def is_docker_available() -> bool:
    """Check if Docker is available on the host."""
    try:
        result = subprocess.run(
            ['docker', 'info'],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_sandboxed(
    command: str,
    image: str = DEFAULT_IMAGE,
    timeout: int = DEFAULT_TIMEOUT,
    memory_limit: str = DEFAULT_MEMORY_LIMIT,
    cpu_limit: str = DEFAULT_CPU_LIMIT,
    env_vars: Optional[Dict[str, str]] = None,
    workdir: Optional[str] = None,
    network: bool = False,
) -> Dict[str, Any]:
    """
    Execute a command inside a Docker container sandbox.

    Args:
        command: Shell command to execute
        image: Docker image to use
        timeout: Max execution time in seconds
        memory_limit: Memory limit (e.g., '256m', '1g')
        cpu_limit: CPU limit (e.g., '0.5', '1.0')
        env_vars: Environment variables to pass
        workdir: Working directory inside container
        network: Whether to allow network access (default: disabled)

    Returns:
        Dict with exit_code, stdout, stderr, timed_out
    """
    if not is_docker_available():
        return {
            'success': False,
            'error': 'Docker is not available on this system',
            'exit_code': -1,
            'stdout': '',
            'stderr': '',
            'timed_out': False,
        }

    container_name = f'sandbox-{uuid.uuid4().hex[:12]}'

    docker_cmd = [
        'docker', 'run',
        '--rm',
        '--name', container_name,
        '--memory', memory_limit,
        '--cpus', cpu_limit,
        '--pids-limit', '100',
        '--read-only',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
        '--security-opt', 'no-new-privileges',
    ]

    # Disable network unless explicitly allowed
    if not network:
        docker_cmd.extend(['--network', 'none'])

    # Set working directory
    if workdir:
        docker_cmd.extend(['-w', workdir])

    # Add environment variables
    if env_vars:
        for key, value in env_vars.items():
            docker_cmd.extend(['-e', f'{key}={value}'])

    docker_cmd.extend([image, 'sh', '-c', command])

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,  # Docker overhead buffer
        )

        stdout = result.stdout[:MAX_OUTPUT_LENGTH]
        stderr = result.stderr[:MAX_OUTPUT_LENGTH]

        return {
            'success': result.returncode == 0,
            'exit_code': result.returncode,
            'stdout': stdout,
            'stderr': stderr,
            'timed_out': False,
            'container': container_name,
        }

    except subprocess.TimeoutExpired:
        # Force-kill the container
        try:
            subprocess.run(
                ['docker', 'kill', container_name],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

        return {
            'success': False,
            'exit_code': -1,
            'stdout': '',
            'stderr': f'Command timed out after {timeout} seconds',
            'timed_out': True,
            'container': container_name,
        }

    except Exception as e:
        logger.error(f"Sandbox execution error: {e}")
        return {
            'success': False,
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e),
            'timed_out': False,
        }


def run_script_sandboxed(
    script: str,
    language: str = 'sh',
    image: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> Dict[str, Any]:
    """
    Execute a script inside a Docker container sandbox.

    Args:
        script: Script content
        language: Script language (sh, python, node)
        image: Docker image (auto-selected if None)
        timeout: Max execution time

    Returns:
        Dict with execution results
    """
    # Auto-select image based on language
    if image is None:
        image = {
            'sh': 'alpine:3.19',
            'bash': 'bash:5',
            'python': 'python:3.12-alpine',
            'node': 'node:20-alpine',
        }.get(language, DEFAULT_IMAGE)

    # Interpreter for the script
    interpreter = {
        'sh': 'sh',
        'bash': 'bash',
        'python': 'python3',
        'node': 'node',
    }.get(language, 'sh')

    # Write script to a temp file and mount it
    with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{language}', delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        container_name = f'sandbox-{uuid.uuid4().hex[:12]}'

        docker_cmd = [
            'docker', 'run',
            '--rm',
            '--name', container_name,
            '--memory', kwargs.get('memory_limit', DEFAULT_MEMORY_LIMIT),
            '--cpus', kwargs.get('cpu_limit', DEFAULT_CPU_LIMIT),
            '--pids-limit', '100',
            '--security-opt', 'no-new-privileges',
            '--network', 'none',
            '-v', f'{script_path}:/sandbox/script:ro',
            image,
            interpreter, '/sandbox/script',
        ]

        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )

        return {
            'success': result.returncode == 0,
            'exit_code': result.returncode,
            'stdout': result.stdout[:MAX_OUTPUT_LENGTH],
            'stderr': result.stderr[:MAX_OUTPUT_LENGTH],
            'timed_out': False,
        }

    except subprocess.TimeoutExpired:
        try:
            subprocess.run(['docker', 'kill', container_name], capture_output=True, timeout=5)
        except Exception:
            pass
        return {
            'success': False,
            'exit_code': -1,
            'stdout': '',
            'stderr': f'Script timed out after {timeout} seconds',
            'timed_out': True,
        }

    except Exception as e:
        return {
            'success': False,
            'exit_code': -1,
            'stdout': '',
            'stderr': str(e),
            'timed_out': False,
        }

    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def get_sandbox_status() -> Dict[str, Any]:
    """Get Docker sandbox availability status."""
    docker_available = is_docker_available()

    result = {
        'available': docker_available,
        'image': DEFAULT_IMAGE,
        'memory_limit': DEFAULT_MEMORY_LIMIT,
        'cpu_limit': DEFAULT_CPU_LIMIT,
        'timeout': DEFAULT_TIMEOUT,
    }

    if docker_available:
        try:
            version = subprocess.run(
                ['docker', 'version', '--format', '{{.Server.Version}}'],
                capture_output=True, text=True, timeout=5,
            )
            result['docker_version'] = version.stdout.strip()
        except Exception:
            result['docker_version'] = 'unknown'

    return result
