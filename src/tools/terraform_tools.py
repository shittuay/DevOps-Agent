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
