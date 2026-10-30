"""Terraform tools for DevOps Agent."""
import os
import subprocess
import json
import uuid
import time
import tempfile
from typing import Dict, Any, Optional, List
from ..utils import get_logger

logger = get_logger(__name__)

# In-memory store for long-running terraform background jobs
# job_id -> {'proc': Popen, 'log_path': str, 'command': list, 'started_at': float}
_tf_jobs: Dict[str, Any] = {}


def _run_terraform_command(
    command: List[str],
    working_dir: str,
    async_threshold: int = 45,
) -> Dict[str, Any]:
    """
    Run a Terraform command. Waits up to async_threshold seconds; if still running,
    returns a background job_id the caller can poll with terraform_job_status().

    Args:
        command: Terraform command as list
        working_dir: Working directory
        async_threshold: Seconds to wait before returning a job handle (default 45)

    Returns:
        Dictionary with command result or background job handle
    """
    try:
        try:
            subprocess.run(['terraform', '-version'], capture_output=True, check=True)
        except FileNotFoundError:
            return {'success': False, 'error': 'Terraform not installed. Install from https://www.terraform.io/downloads.html'}

        log_fd, log_path = tempfile.mkstemp(prefix='tf_', suffix='.log')
        os.close(log_fd)

        with open(log_path, 'w') as log_file:
            proc = subprocess.Popen(
                command,
                cwd=working_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )

        job_id = uuid.uuid4().hex[:8]
        _tf_jobs[job_id] = {
            'proc': proc,
            'log_path': log_path,
            'command': ' '.join(command),
            'working_dir': working_dir,
            'started_at': time.time(),
        }

        try:
            proc.wait(timeout=async_threshold)
        except subprocess.TimeoutExpired:
            # Still running — return job handle
            partial = _read_tail(log_path, 3000)
            return {
                'success': True,
                'status': 'running',
                'job_id': job_id,
                'message': (
                    f'Terraform is still running (job_id: {job_id}). '
                    f'Call terraform_job_status("{job_id}") to check progress.'
                ),
                'partial_output': partial,
            }

        # Completed within threshold
        output = open(log_path).read()
        return {
            'success': proc.returncode == 0,
            'status': 'complete',
            'stdout': output,
            'stderr': '',
            'return_code': proc.returncode,
        }

    except Exception as e:
        logger.error(f"Error running Terraform command: {str(e)}")
        return {'success': False, 'error': str(e)}


def _read_tail(path: str, max_chars: int = 3000) -> str:
    """Read the last max_chars characters of a file."""
    try:
        with open(path) as f:
            content = f.read()
        return content[-max_chars:] if len(content) > max_chars else content
    except Exception:
        return ''


def terraform_job_status(job_id: str) -> Dict[str, Any]:
    """
    Check the status of a long-running Terraform background job.

    Use this after terraform_init / terraform_plan / terraform_apply / terraform_destroy
    returns status='running' with a job_id. Poll until status is 'complete' or 'failed'.

    Args:
        job_id: Job ID returned by the terraform command

    Returns:
        Dictionary with status ('running'|'complete'|'failed'), output so far, and return_code when done
    """
    job = _tf_jobs.get(job_id)
    if not job:
        return {'success': False, 'error': f'Job {job_id} not found. It may have expired or never existed.'}

    proc = job['proc']
    returncode = proc.poll()
    elapsed = round(time.time() - job['started_at'], 1)

    if returncode is None:
        partial = _read_tail(job['log_path'], 3000)
        return {
            'success': True,
            'status': 'running',
            'job_id': job_id,
            'elapsed_seconds': elapsed,
            'partial_output': partial,
            'message': f'Still running ({elapsed}s elapsed). Call terraform_job_status("{job_id}") again to check.',
        }

    output = open(job['log_path']).read()
    status = 'complete' if returncode == 0 else 'failed'
    # Clean up
    try:
        os.unlink(job['log_path'])
    except Exception:
        pass
    _tf_jobs.pop(job_id, None)

    return {
        'success': returncode == 0,
        'status': status,
        'job_id': job_id,
        'elapsed_seconds': elapsed,
        'return_code': returncode,
        'output': output,
    }


def terraform_init(
    working_dir: str,
    backend_config: Optional[Dict[str, str]] = None,
    upgrade: bool = False
) -> Dict[str, Any]:
    """
    Initialize Terraform configuration.

    Args:
        working_dir: Directory containing Terraform configuration
        backend_config: Backend configuration options
        upgrade: Upgrade modules and plugins

    Returns:
        Dictionary with init result
    """
    try:
        command = ['terraform', 'init']

        if upgrade:
            command.append('-upgrade')

        if backend_config:
            for key, value in backend_config.items():
                command.extend(['-backend-config', f'{key}={value}'])

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Terraform initialized successfully' if result['success'] else 'Initialization failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error initializing Terraform: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_plan(
    working_dir: str,
    var_file: Optional[str] = None,
    variables: Optional[Dict[str, str]] = None,
    out: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate Terraform execution plan.

    Args:
        working_dir: Directory containing Terraform configuration
        var_file: Path to variable file
        variables: Dictionary of variables
        out: Path to save plan file

    Returns:
        Dictionary with plan result
    """
    try:
        command = ['terraform', 'plan']

        if var_file:
            command.extend(['-var-file', var_file])

        if variables:
            for key, value in variables.items():
                command.extend(['-var', f'{key}={value}'])

        if out:
            command.extend(['-out', out])

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Plan generated successfully' if result['success'] else 'Plan generation failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', ''),
            'plan_file': out
        }
    except Exception as e:
        logger.error(f"Error generating Terraform plan: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_apply(
    working_dir: str,
    var_file: Optional[str] = None,
    variables: Optional[Dict[str, str]] = None,
    auto_approve: bool = False,
    plan_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Apply Terraform configuration.

    Args:
        working_dir: Directory containing Terraform configuration
        var_file: Path to variable file
        variables: Dictionary of variables
        auto_approve: Auto-approve changes
        plan_file: Path to plan file to apply

    Returns:
        Dictionary with apply result
    """
    try:
        command = ['terraform', 'apply']

        if plan_file:
            if plan_file.startswith('-'):
                return {'success': False, 'error': "plan_file must be a file path, not an option"}
            command.append(plan_file)
        else:
            if auto_approve:
                command.append('-auto-approve')

            if var_file:
                command.extend(['-var-file', var_file])

            if variables:
                for key, value in variables.items():
                    command.extend(['-var', f'{key}={value}'])

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Apply completed successfully' if result['success'] else 'Apply failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error applying Terraform configuration: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_destroy(
    working_dir: str,
    var_file: Optional[str] = None,
    variables: Optional[Dict[str, str]] = None,
    auto_approve: bool = False
) -> Dict[str, Any]:
    """
    Destroy Terraform-managed infrastructure.

    Args:
        working_dir: Directory containing Terraform configuration
        var_file: Path to variable file
        variables: Dictionary of variables
        auto_approve: Auto-approve destruction

    Returns:
        Dictionary with destroy result
    """
    try:
        command = ['terraform', 'destroy']

        if auto_approve:
            command.append('-auto-approve')

        if var_file:
            command.extend(['-var-file', var_file])

        if variables:
            for key, value in variables.items():
                command.extend(['-var', f'{key}={value}'])

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Destroy completed successfully' if result['success'] else 'Destroy failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error destroying Terraform infrastructure: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_show(working_dir: str, state_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Show Terraform state or plan.

    Args:
        working_dir: Directory containing Terraform configuration
        state_file: Optional path to state file

    Returns:
        Dictionary with state information
    """
    try:
        command = ['terraform', 'show', '-json']

        if state_file:
            command.append(state_file)

        result = _run_terraform_command(command, working_dir)

        if result['success']:
            try:
                state_data = json.loads(result['stdout'])
                return {
                    'success': True,
                    'state': state_data
                }
            except json.JSONDecodeError:
                return {
                    'success': True,
                    'output': result['stdout']
                }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Failed to show state')
            }
    except Exception as e:
        logger.error(f"Error showing Terraform state: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_output(
    working_dir: str,
    output_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Read Terraform outputs.

    Args:
        working_dir: Directory containing Terraform configuration
        output_name: Optional specific output name

    Returns:
        Dictionary with outputs
    """
    try:
        command = ['terraform', 'output', '-json']

        if output_name:
            command.append(output_name)

        result = _run_terraform_command(command, working_dir)

        if result['success']:
            try:
                outputs = json.loads(result['stdout'])
                return {
                    'success': True,
                    'outputs': outputs
                }
            except json.JSONDecodeError:
                return {
                    'success': True,
                    'output': result['stdout']
                }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Failed to read outputs')
            }
    except Exception as e:
        logger.error(f"Error reading Terraform outputs: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_validate(working_dir: str) -> Dict[str, Any]:
    """
    Validate Terraform configuration.

    Args:
        working_dir: Directory containing Terraform configuration

    Returns:
        Dictionary with validation result
    """
    try:
        command = ['terraform', 'validate', '-json']

        result = _run_terraform_command(command, working_dir)

        if result['success']:
            try:
                validation = json.loads(result['stdout'])
                return {
                    'success': validation.get('valid', False),
                    'validation': validation
                }
            except json.JSONDecodeError:
                return {
                    'success': True,
                    'message': 'Configuration is valid'
                }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Validation failed')
            }
    except Exception as e:
        logger.error(f"Error validating Terraform configuration: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_fmt(
    working_dir: str,
    check: bool = False,
    recursive: bool = False
) -> Dict[str, Any]:
    """
    Format Terraform configuration files.

    Args:
        working_dir: Directory containing Terraform configuration
        check: Check if files are formatted (don't write)
        recursive: Process subdirectories

    Returns:
        Dictionary with format result
    """
    try:
        command = ['terraform', 'fmt']

        if check:
            command.append('-check')

        if recursive:
            command.append('-recursive')

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Format completed' if result['success'] else 'Format failed',
            'modified_files': result.get('stdout', '').strip().split('\n') if result.get('stdout') else [],
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error formatting Terraform files: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_workspace_list(working_dir: str) -> Dict[str, Any]:
    """
    List Terraform workspaces.

    Args:
        working_dir: Directory containing Terraform configuration

    Returns:
        Dictionary with workspaces
    """
    try:
        command = ['terraform', 'workspace', 'list']

        result = _run_terraform_command(command, working_dir)

        if result['success']:
            workspaces = []
            current_workspace = None

            for line in result['stdout'].split('\n'):
                line = line.strip()
                if line:
                    if line.startswith('*'):
                        current_workspace = line[1:].strip()
                        workspaces.append(current_workspace)
                    else:
                        workspaces.append(line)

            return {
                'success': True,
                'workspaces': workspaces,
                'current': current_workspace
            }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Failed to list workspaces')
            }
    except Exception as e:
        logger.error(f"Error listing Terraform workspaces: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_workspace_select(working_dir: str, workspace: str) -> Dict[str, Any]:
    """
    Select Terraform workspace.

    Args:
        working_dir: Directory containing Terraform configuration
        workspace: Workspace name to select

    Returns:
        Dictionary with result
    """
    try:
        command = ['terraform', 'workspace', 'select', workspace]

        result = _run_terraform_command(command, working_dir)

        return {
            'success': result['success'],
            'message': f'Switched to workspace "{workspace}"' if result['success'] else 'Failed to switch workspace',
            'workspace': workspace,
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error selecting Terraform workspace: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_state_list(working_dir: str) -> Dict[str, Any]:
    """
    List resources in Terraform state.

    Args:
        working_dir: Directory containing Terraform configuration

    Returns:
        Dictionary with resources
    """
    try:
        command = ['terraform', 'state', 'list']

        result = _run_terraform_command(command, working_dir)

        if result['success']:
            resources = [line.strip() for line in result['stdout'].split('\n') if line.strip()]
            return {
                'success': True,
                'count': len(resources),
                'resources': resources
            }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Failed to list state resources')
            }
    except Exception as e:
        logger.error(f"Error listing Terraform state: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_import(
    working_dir: str,
    address: str,
    resource_id: str,
    var_file: Optional[str] = None
) -> Dict[str, Any]:
    """Import an existing real-world resource into Terraform state under the given address."""
    try:
        command = ['terraform', 'import']
        if var_file:
            command.extend(['-var-file', var_file])
        command.extend([address, resource_id])
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': f'Resource {resource_id} imported as {address}' if result['success'] else 'Import failed',
            'address': address,
            'resource_id': resource_id,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error importing Terraform resource: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_state_move(
    working_dir: str,
    source: str,
    destination: str
) -> Dict[str, Any]:
    """Move a resource within Terraform state from source address to destination address."""
    try:
        command = ['terraform', 'state', 'mv', source, destination]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': f'Moved {source} → {destination}' if result['success'] else 'State move failed',
            'source': source,
            'destination': destination,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error moving Terraform state: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_state_rm(
    working_dir: str,
    address: str
) -> Dict[str, Any]:
    """
    Remove a resource from Terraform state without destroying the real infrastructure.
    Use when you want Terraform to stop managing a resource.
    """
    try:
        command = ['terraform', 'state', 'rm', address]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': f'Resource {address} removed from state (infrastructure NOT destroyed)' if result['success'] else 'State remove failed',
            'address': address,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error removing from Terraform state: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_refresh(
    working_dir: str,
    var_file: Optional[str] = None,
    variables: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Update Terraform state to match real-world infrastructure without making any changes.
    Reads actual resource attributes and updates the state file.
    """
    try:
        command = ['terraform', 'refresh']
        if var_file:
            command.extend(['-var-file', var_file])
        if variables:
            for key, value in variables.items():
                command.extend(['-var', f'{key}={value}'])
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': 'State refreshed from real infrastructure' if result['success'] else 'Refresh failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error refreshing Terraform state: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_workspace_new(
    working_dir: str,
    workspace: str
) -> Dict[str, Any]:
    """Create a new Terraform workspace and switch to it."""
    try:
        command = ['terraform', 'workspace', 'new', workspace]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': f'Workspace "{workspace}" created and selected' if result['success'] else 'Failed to create workspace',
            'workspace': workspace,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error creating Terraform workspace: {str(e)}")
        return {'success': False, 'error': str(e)}


def terraform_workspace_delete(working_dir: str, workspace: str) -> Dict[str, Any]:
    """Delete a Terraform workspace (must not be the current workspace)."""
    try:
        command = ['terraform', 'workspace', 'delete', workspace]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'workspace': workspace,
            'message': f'Workspace "{workspace}" deleted' if result['success'] else 'Failed to delete workspace',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_state_show(working_dir: str, resource_address: str) -> Dict[str, Any]:
    """Display the attributes of a specific resource tracked in Terraform state."""
    try:
        command = ['terraform', 'state', 'show', resource_address]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'resource_address': resource_address,
            'attributes': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_state_pull(working_dir: str) -> Dict[str, Any]:
    """Download and print the current state file content."""
    try:
        command = ['terraform', 'state', 'pull']
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'state_json': result.get('stdout', ''),
            'errors': result.get('stderr', ''),
            'message': 'State pulled successfully' if result['success'] else 'Failed to pull state'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_state_push(working_dir: str, state_file: str, force: bool = False) -> Dict[str, Any]:
    """Upload a local state file to the configured backend."""
    try:
        command = ['terraform', 'state', 'push']
        if force:
            command.append('-force')
        command.append(state_file)
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'state_file': state_file,
            'message': 'State pushed successfully' if result['success'] else 'Failed to push state',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_force_unlock(working_dir: str, lock_id: str) -> Dict[str, Any]:
    """Release a stuck state lock. Use when a previous run was interrupted."""
    try:
        command = ['terraform', 'force-unlock', '-force', lock_id]
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'lock_id': lock_id,
            'message': f'Lock {lock_id} released' if result['success'] else 'Failed to release lock',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_get(working_dir: str, update: bool = False) -> Dict[str, Any]:
    """Download and update modules defined in the configuration."""
    try:
        command = ['terraform', 'get']
        if update:
            command.append('-update')
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': 'Modules downloaded' if result['success'] else 'Failed to get modules',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_providers(working_dir: str) -> Dict[str, Any]:
    """List all providers required by the Terraform configuration."""
    try:
        command = ['terraform', 'providers']
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'providers': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_providers_lock(working_dir: str, platforms: Optional[List[str]] = None) -> Dict[str, Any]:
    """Update the dependency lock file with provider checksums."""
    try:
        command = ['terraform', 'providers', 'lock']
        if platforms:
            for p in platforms:
                command.extend(['-platform', p])
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'message': 'Lock file updated' if result['success'] else 'Failed to update lock file',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def terraform_graph(working_dir: str, plan_file: Optional[str] = None) -> Dict[str, Any]:
    """Generate a DOT-format dependency graph of Terraform resources."""
    try:
        command = ['terraform', 'graph']
        if plan_file:
            command.extend(['-plan', plan_file])
        result = _run_terraform_command(command, working_dir)
        return {
            'success': result['success'],
            'graph_dot': result.get('stdout', ''),
            'message': 'Graph generated (DOT format)' if result['success'] else 'Failed to generate graph',
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of Terraform tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        {
            'name': 'terraform_job_status',
            'description': (
                'Check the status of a long-running Terraform background job. '
                'Call this after terraform_init/plan/apply/destroy returns status="running" with a job_id. '
                'Poll until status is "complete" or "failed".'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_id': {
                        'type': 'string',
                        'description': 'Job ID returned by the terraform command'
                    }
                },
                'required': ['job_id']
            },
            'handler': terraform_job_status,
        },
        {
            'name': 'terraform_init',
            'description': 'Initialize a Terraform working directory. Downloads providers and modules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'backend_config': {
                        'type': 'object',
                        'description': 'Backend configuration options as key-value pairs'
                    },
                    'upgrade': {
                        'type': 'boolean',
                        'description': 'Upgrade modules and plugins to latest versions',
                        'default': False
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_init
        },
        {
            'name': 'terraform_plan',
            'description': 'Generate a Terraform execution plan showing what changes will be made.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'var_file': {
                        'type': 'string',
                        'description': 'Path to a variable definitions file (.tfvars)'
                    },
                    'variables': {
                        'type': 'object',
                        'description': 'Variables to pass to Terraform as key-value pairs'
                    },
                    'out': {
                        'type': 'string',
                        'description': 'Path to save the plan file for later apply'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_plan
        },
        {
            'name': 'terraform_apply',
            'description': 'Apply Terraform configuration to create/update infrastructure. WARNING: This makes real changes!',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'var_file': {
                        'type': 'string',
                        'description': 'Path to a variable definitions file (.tfvars)'
                    },
                    'variables': {
                        'type': 'object',
                        'description': 'Variables to pass to Terraform as key-value pairs'
                    },
                    'auto_approve': {
                        'type': 'boolean',
                        'description': 'Skip interactive approval (use with caution)',
                        'default': False
                    },
                    'plan_file': {
                        'type': 'string',
                        'description': 'Path to a saved plan file to apply'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_apply
        },
        {
            'name': 'terraform_destroy',
            'description': 'Destroy Terraform-managed infrastructure. WARNING: This is destructive!',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'var_file': {
                        'type': 'string',
                        'description': 'Path to a variable definitions file (.tfvars)'
                    },
                    'variables': {
                        'type': 'object',
                        'description': 'Variables to pass to Terraform as key-value pairs'
                    },
                    'auto_approve': {
                        'type': 'boolean',
                        'description': 'Skip interactive approval (use with caution)',
                        'default': False
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_destroy
        },
        {
            'name': 'terraform_show',
            'description': 'Show the current Terraform state or a saved plan in JSON format.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'state_file': {
                        'type': 'string',
                        'description': 'Path to a specific state or plan file to show'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_show
        },
        {
            'name': 'terraform_output',
            'description': 'Read output values from Terraform state.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'output_name': {
                        'type': 'string',
                        'description': 'Specific output name to retrieve (optional, returns all if not specified)'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_output
        },
        {
            'name': 'terraform_validate',
            'description': 'Validate Terraform configuration files for syntax and consistency.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_validate
        },
        {
            'name': 'terraform_fmt',
            'description': 'Format Terraform configuration files to canonical style.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'check': {
                        'type': 'boolean',
                        'description': 'Check if files are formatted without modifying them',
                        'default': False
                    },
                    'recursive': {
                        'type': 'boolean',
                        'description': 'Process subdirectories recursively',
                        'default': False
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_fmt
        },
        {
            'name': 'terraform_workspace_list',
            'description': 'List all Terraform workspaces and show the current one.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    }
                },
                'required': ['working_dir']
            },
            'handler': terraform_workspace_list
        },
        {
            'name': 'terraform_workspace_select',
            'description': 'Switch to a different Terraform workspace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {
                        'type': 'string',
                        'description': 'Directory containing Terraform configuration files'
                    },
                    'workspace': {
                        'type': 'string',
                        'description': 'Name of the workspace to select'
                    }
                },
                'required': ['working_dir', 'workspace']
            },
            'handler': terraform_workspace_select
        },
        {
            'name': 'terraform_state_list',
            'description': 'List all resources tracked in Terraform state.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'}
                },
                'required': ['working_dir']
            },
            'handler': terraform_state_list
        },
        {
            'name': 'terraform_import',
            'description': 'Import an existing real-world resource into Terraform state so Terraform can manage it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'},
                    'address': {'type': 'string', 'description': 'Terraform resource address to import into (e.g. aws_instance.web)'},
                    'resource_id': {'type': 'string', 'description': 'Provider-specific resource ID (e.g. AWS instance ID i-1234567890abcdef0)'},
                    'var_file': {'type': 'string', 'description': 'Path to a variable definitions file (.tfvars)'},
                },
                'required': ['working_dir', 'address', 'resource_id']
            },
            'handler': terraform_import
        },
        {
            'name': 'terraform_state_move',
            'description': 'Move a resource within Terraform state from one address to another (e.g. after renaming a resource in .tf files).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'},
                    'source': {'type': 'string', 'description': 'Current resource address in state'},
                    'destination': {'type': 'string', 'description': 'New resource address in state'},
                },
                'required': ['working_dir', 'source', 'destination']
            },
            'handler': terraform_state_move
        },
        {
            'name': 'terraform_state_rm',
            'description': 'Remove a resource from Terraform state WITHOUT destroying the real infrastructure. Use when you want Terraform to stop managing a resource.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'},
                    'address': {'type': 'string', 'description': 'Resource address to remove from state (e.g. aws_instance.web)'},
                },
                'required': ['working_dir', 'address']
            },
            'handler': terraform_state_rm
        },
        {
            'name': 'terraform_refresh',
            'description': 'Update Terraform state to match real-world infrastructure without making any changes.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'},
                    'var_file': {'type': 'string', 'description': 'Path to a variable definitions file (.tfvars)'},
                    'variables': {'type': 'object', 'description': 'Variables to pass as key-value pairs'},
                },
                'required': ['working_dir']
            },
            'handler': terraform_refresh
        },
        {
            'name': 'terraform_workspace_new',
            'description': 'Create a new Terraform workspace and switch to it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Directory containing Terraform configuration files'},
                    'workspace': {'type': 'string', 'description': 'Name of the new workspace to create'},
                },
                'required': ['working_dir', 'workspace']
            },
            'handler': terraform_workspace_new
        },
        {
            'name': 'terraform_workspace_delete',
            'description': 'Delete a Terraform workspace. The workspace must not be the current active one.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'workspace': {'type': 'string', 'description': 'Workspace name to delete'}
                },
                'required': ['working_dir', 'workspace']
            },
            'handler': terraform_workspace_delete
        },
        {
            'name': 'terraform_state_show',
            'description': 'Display all attributes of a specific resource in Terraform state.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'resource_address': {'type': 'string', 'description': 'Resource address (e.g., "aws_instance.web")'}
                },
                'required': ['working_dir', 'resource_address']
            },
            'handler': terraform_state_show
        },
        {
            'name': 'terraform_state_pull',
            'description': 'Download and print the current Terraform state file as JSON.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'}
                },
                'required': ['working_dir']
            },
            'handler': terraform_state_pull
        },
        {
            'name': 'terraform_state_push',
            'description': 'Upload a local state file to the configured Terraform backend.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'state_file': {'type': 'string', 'description': 'Path to state file to push'},
                    'force': {'type': 'boolean', 'description': 'Force push even if serial is lower', 'default': False}
                },
                'required': ['working_dir', 'state_file']
            },
            'handler': terraform_state_push
        },
        {
            'name': 'terraform_force_unlock',
            'description': 'Release a stuck Terraform state lock (use when a previous run was interrupted).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'lock_id': {'type': 'string', 'description': 'Lock ID shown in the lock error message'}
                },
                'required': ['working_dir', 'lock_id']
            },
            'handler': terraform_force_unlock
        },
        {
            'name': 'terraform_get',
            'description': 'Download and update Terraform modules defined in the configuration.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'update': {'type': 'boolean', 'description': 'Update modules to latest versions', 'default': False}
                },
                'required': ['working_dir']
            },
            'handler': terraform_get
        },
        {
            'name': 'terraform_providers',
            'description': 'List all providers required by the current Terraform configuration.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'}
                },
                'required': ['working_dir']
            },
            'handler': terraform_providers
        },
        {
            'name': 'terraform_providers_lock',
            'description': 'Update the Terraform dependency lock file (.terraform.lock.hcl) with current provider checksums.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'platforms': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Target platforms (e.g., ["linux_amd64", "darwin_arm64"])'}
                },
                'required': ['working_dir']
            },
            'handler': terraform_providers_lock
        },
        {
            'name': 'terraform_graph',
            'description': 'Generate a DOT-format visual dependency graph of Terraform resources.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'working_dir': {'type': 'string', 'description': 'Terraform working directory'},
                    'plan_file': {'type': 'string', 'description': 'Optional plan file to visualize'}
                },
                'required': ['working_dir']
            },
            'handler': terraform_graph
        },
    ]
