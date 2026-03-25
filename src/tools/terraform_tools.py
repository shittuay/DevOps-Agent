"""Terraform tools for DevOps Agent."""
import os
import subprocess
import json
from typing import Dict, Any, Optional, List
from ..utils import get_logger

logger = get_logger(__name__)


def _run_terraform_command(
    command: List[str],
    working_dir: str,
    capture_output: bool = True
) -> Dict[str, Any]:
    """
    Run a Terraform command.

    Args:
        command: Terraform command as list
        working_dir: Working directory
        capture_output: Whether to capture output

    Returns:
        Dictionary with command result
    """
    try:
        # Check if terraform is installed
        try:
            subprocess.run(['terraform', '-version'], capture_output=True, check=True)
        except FileNotFoundError:
            return {'success': False, 'error': 'Terraform not installed. Install from https://www.terraform.io/downloads.html'}

        result = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=capture_output,
            text=True,
            timeout=300  # 5 minute timeout
        )

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout if capture_output else '',
            'stderr': result.stderr if capture_output else '',
            'return_code': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Command timed out after 5 minutes'}
    except Exception as e:
        logger.error(f"Error running Terraform command: {str(e)}")
        return {'success': False, 'error': str(e)}


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


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of Terraform tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
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
    ]
