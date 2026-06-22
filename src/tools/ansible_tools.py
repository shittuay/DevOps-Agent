"""Ansible tools for DevOps Agent."""
import os
import subprocess
import json
import tempfile
from typing import Dict, Any, Optional, List
from ..utils import get_logger

logger = get_logger(__name__)

# Modules that execute arbitrary OS commands on remote hosts are excluded.
# Specifically: shell, command, raw, script.
_ALLOWED_ANSIBLE_MODULES: frozenset = frozenset({
    'ping', 'setup', 'gather_facts',
    'file', 'copy', 'fetch', 'template', 'lineinfile', 'blockinfile',
    'replace', 'assemble',
    'apt', 'yum', 'dnf', 'zypper', 'package', 'pip',
    'service', 'systemd',
    'user', 'group',
    'cron',
    'git',
    'stat', 'find',
    'debug', 'assert', 'fail', 'set_fact',
    'wait_for', 'wait_for_connection', 'pause',
    'uri', 'get_url',
    'unarchive', 'archive',
    'mount',
    'authorized_key', 'known_hosts',
    'firewalld', 'iptables',
    'docker_container', 'docker_image',
    'k8s', 'helm',
})


def _run_ansible_command(
    command: List[str],
    working_dir: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Run an Ansible command.

    Args:
        command: Ansible command as list
        working_dir: Working directory
        env: Environment variables
        timeout: Command timeout in seconds

    Returns:
        Dictionary with command result
    """
    try:
        # Check if ansible is installed
        try:
            subprocess.run(['ansible', '--version'], capture_output=True, check=True)
        except FileNotFoundError:
            return {
                'success': False,
                'error': 'Ansible not installed. Install with: pip install ansible'
            }

        # Merge environment variables
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        result = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=run_env
        )

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'return_code': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': f'Command timed out after {timeout} seconds'}
    except Exception as e:
        logger.error(f"Error running Ansible command: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_playbook_run(
    playbook_path: str,
    inventory: Optional[str] = None,
    limit: Optional[str] = None,
    tags: Optional[List[str]] = None,
    skip_tags: Optional[List[str]] = None,
    extra_vars: Optional[Dict[str, Any]] = None,
    extra_vars_file: Optional[str] = None,
    become: bool = False,
    become_user: Optional[str] = None,
    check_mode: bool = False,
    diff: bool = False,
    verbosity: int = 0,
    forks: int = 5,
    timeout: int = 600,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run an Ansible playbook.

    Args:
        playbook_path: Path to the playbook file
        inventory: Inventory file or host pattern
        limit: Limit to specific hosts/groups
        tags: Only run plays and tasks tagged with these values
        skip_tags: Skip plays and tasks tagged with these values
        extra_vars: Extra variables as dictionary
        extra_vars_file: Path to extra variables file
        become: Run operations with become (privilege escalation)
        become_user: User to become
        check_mode: Run in check mode (dry run)
        diff: Show differences in changed files
        verbosity: Verbosity level (0-4)
        forks: Number of parallel processes
        timeout: Command timeout in seconds
        working_dir: Working directory

    Returns:
        Dictionary with playbook execution result
    """
    try:
        command = ['ansible-playbook', playbook_path]

        if inventory:
            command.extend(['-i', inventory])

        if limit:
            command.extend(['--limit', limit])

        if tags:
            command.extend(['--tags', ','.join(tags)])

        if skip_tags:
            command.extend(['--skip-tags', ','.join(skip_tags)])

        if extra_vars:
            command.extend(['--extra-vars', json.dumps(extra_vars)])

        if extra_vars_file:
            command.extend(['--extra-vars', f'@{extra_vars_file}'])

        if become:
            command.append('--become')

        if become_user:
            command.extend(['--become-user', become_user])

        if check_mode:
            command.append('--check')

        if diff:
            command.append('--diff')

        if verbosity > 0:
            command.append('-' + 'v' * min(verbosity, 4))

        command.extend(['--forks', str(forks)])

        result = _run_ansible_command(command, working_dir, timeout=timeout)

        return {
            'success': result['success'],
            'message': 'Playbook executed successfully' if result['success'] else 'Playbook execution failed',
            'playbook': playbook_path,
            'check_mode': check_mode,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error running Ansible playbook: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_adhoc_command(
    host_pattern: str,
    module: str,
    module_args: Optional[str] = None,
    inventory: Optional[str] = None,
    become: bool = False,
    become_user: Optional[str] = None,
    forks: int = 5,
    timeout: int = 300,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run an Ansible ad-hoc command.

    Args:
        host_pattern: Host pattern to target (e.g., 'all', 'webservers', '192.168.1.1')
        module: Ansible module to run (e.g., 'ping', 'shell', 'copy', 'apt')
        module_args: Module arguments
        inventory: Inventory file or comma-separated hosts
        become: Run with privilege escalation
        become_user: User to become
        forks: Number of parallel processes
        timeout: Command timeout in seconds
        working_dir: Working directory

    Returns:
        Dictionary with command result
    """
    try:
        if module not in _ALLOWED_ANSIBLE_MODULES:
            logger.warning(f"Blocked ansible ad-hoc call with non-allowlisted module: {module}")
            return {
                'success': False,
                'error': f"Module '{module}' is not permitted. "
                         f"Modules that execute arbitrary OS commands (shell, command, raw, script) are blocked. "
                         f"Allowed modules: {', '.join(sorted(_ALLOWED_ANSIBLE_MODULES))}",
            }

        command = ['ansible', host_pattern, '-m', module]

        if module_args:
            command.extend(['-a', module_args])

        if inventory:
            command.extend(['-i', inventory])

        if become:
            command.append('--become')

        if become_user:
            command.extend(['--become-user', become_user])

        command.extend(['--forks', str(forks)])

        result = _run_ansible_command(command, working_dir, timeout=timeout)

        return {
            'success': result['success'],
            'message': 'Command executed successfully' if result['success'] else 'Command execution failed',
            'host_pattern': host_pattern,
            'module': module,
            'module_args': module_args,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error running Ansible ad-hoc command: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_inventory_list(
    inventory: str,
    host: Optional[str] = None,
    graph: bool = False,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    List Ansible inventory.

    Args:
        inventory: Inventory file or directory
        host: Show info for specific host
        graph: Display inventory as graph
        working_dir: Working directory

    Returns:
        Dictionary with inventory information
    """
    try:
        command = ['ansible-inventory', '-i', inventory]

        if host:
            command.extend(['--host', host])
        elif graph:
            command.append('--graph')
        else:
            command.append('--list')

        result = _run_ansible_command(command, working_dir)

        if result['success']:
            try:
                if not graph:
                    inventory_data = json.loads(result['stdout'])
                    return {
                        'success': True,
                        'inventory': inventory_data
                    }
                else:
                    return {
                        'success': True,
                        'graph': result['stdout']
                    }
            except json.JSONDecodeError:
                return {
                    'success': True,
                    'output': result['stdout']
                }
        else:
            return {
                'success': False,
                'error': result.get('stderr', 'Failed to list inventory')
            }
    except Exception as e:
        logger.error(f"Error listing Ansible inventory: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_playbook_syntax_check(
    playbook_path: str,
    inventory: Optional[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check Ansible playbook syntax.

    Args:
        playbook_path: Path to the playbook file
        inventory: Inventory file (optional)
        working_dir: Working directory

    Returns:
        Dictionary with syntax check result
    """
    try:
        command = ['ansible-playbook', '--syntax-check', playbook_path]

        if inventory:
            command.extend(['-i', inventory])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Syntax check passed' if result['success'] else 'Syntax check failed',
            'playbook': playbook_path,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error checking playbook syntax: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_galaxy_install(
    requirements_file: Optional[str] = None,
    role_name: Optional[str] = None,
    collection_name: Optional[str] = None,
    roles_path: Optional[str] = None,
    collections_path: Optional[str] = None,
    force: bool = False,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install roles or collections from Ansible Galaxy.

    Args:
        requirements_file: Path to requirements.yml file
        role_name: Role name to install (e.g., 'geerlingguy.docker')
        collection_name: Collection name to install (e.g., 'community.general')
        roles_path: Path to install roles
        collections_path: Path to install collections
        force: Force overwrite existing roles/collections
        working_dir: Working directory

    Returns:
        Dictionary with installation result
    """
    try:
        if collection_name:
            command = ['ansible-galaxy', 'collection', 'install', collection_name]
            if collections_path:
                command.extend(['-p', collections_path])
        elif role_name:
            command = ['ansible-galaxy', 'role', 'install', role_name]
            if roles_path:
                command.extend(['-p', roles_path])
        elif requirements_file:
            command = ['ansible-galaxy', 'install', '-r', requirements_file]
            if roles_path:
                command.extend(['-p', roles_path])
        else:
            return {
                'success': False,
                'error': 'Must specify requirements_file, role_name, or collection_name'
            }

        if force:
            command.append('--force')

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'Installation completed successfully' if result['success'] else 'Installation failed',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error installing from Ansible Galaxy: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_galaxy_list(
    roles_path: Optional[str] = None,
    collections: bool = False,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    List installed Ansible roles or collections.

    Args:
        roles_path: Path to roles directory
        collections: List collections instead of roles
        working_dir: Working directory

    Returns:
        Dictionary with installed roles/collections
    """
    try:
        if collections:
            command = ['ansible-galaxy', 'collection', 'list']
        else:
            command = ['ansible-galaxy', 'role', 'list']
            if roles_path:
                command.extend(['-p', roles_path])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'type': 'collections' if collections else 'roles',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error listing Ansible Galaxy items: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_vault_encrypt(
    file_path: str,
    vault_password_file: Optional[str] = None,
    vault_id: Optional[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Encrypt a file with Ansible Vault.

    Args:
        file_path: Path to file to encrypt
        vault_password_file: Path to vault password file
        vault_id: Vault ID label
        working_dir: Working directory

    Returns:
        Dictionary with encryption result
    """
    try:
        command = ['ansible-vault', 'encrypt', file_path]

        if vault_password_file:
            command.extend(['--vault-password-file', vault_password_file])

        if vault_id:
            command.extend(['--vault-id', vault_id])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'File encrypted successfully' if result['success'] else 'Encryption failed',
            'file': file_path,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error encrypting with Ansible Vault: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_vault_decrypt(
    file_path: str,
    vault_password_file: Optional[str] = None,
    output_file: Optional[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Decrypt a file with Ansible Vault.

    Args:
        file_path: Path to encrypted file
        vault_password_file: Path to vault password file
        output_file: Output to different file (leaves original encrypted)
        working_dir: Working directory

    Returns:
        Dictionary with decryption result
    """
    try:
        if output_file:
            command = ['ansible-vault', 'decrypt', file_path, '--output', output_file]
        else:
            command = ['ansible-vault', 'decrypt', file_path]

        if vault_password_file:
            command.extend(['--vault-password-file', vault_password_file])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'message': 'File decrypted successfully' if result['success'] else 'Decryption failed',
            'file': file_path,
            'output_file': output_file,
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error decrypting with Ansible Vault: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_vault_view(
    file_path: str,
    vault_password_file: Optional[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    View contents of an Ansible Vault encrypted file.

    Args:
        file_path: Path to encrypted file
        vault_password_file: Path to vault password file
        working_dir: Working directory

    Returns:
        Dictionary with file contents
    """
    try:
        command = ['ansible-vault', 'view', file_path]

        if vault_password_file:
            command.extend(['--vault-password-file', vault_password_file])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'file': file_path,
            'content': result.get('stdout', '') if result['success'] else None,
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error viewing Ansible Vault file: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_config_dump(
    only_changed: bool = False,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dump Ansible configuration.

    Args:
        only_changed: Only show settings that differ from defaults
        working_dir: Working directory

    Returns:
        Dictionary with configuration
    """
    try:
        command = ['ansible-config', 'dump']

        if only_changed:
            command.append('--only-changed')

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'config': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error dumping Ansible config: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_doc(
    module_name: str,
    module_type: str = 'module',
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get documentation for an Ansible module or plugin.

    Args:
        module_name: Name of the module/plugin
        module_type: Type (module, callback, connection, lookup, etc.)
        working_dir: Working directory

    Returns:
        Dictionary with documentation
    """
    try:
        command = ['ansible-doc', '-t', module_type, module_name]

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'module': module_name,
            'type': module_type,
            'documentation': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error getting Ansible documentation: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_ping(
    host_pattern: str,
    inventory: Optional[str] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Ping hosts using Ansible to verify connectivity.

    Args:
        host_pattern: Host pattern to target
        inventory: Inventory file or comma-separated hosts
        working_dir: Working directory

    Returns:
        Dictionary with ping results
    """
    try:
        command = ['ansible', host_pattern, '-m', 'ping']

        if inventory:
            command.extend(['-i', inventory])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'host_pattern': host_pattern,
            'message': 'All hosts reachable' if result['success'] else 'Some hosts unreachable',
            'output': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error pinging hosts: {str(e)}")
        return {'success': False, 'error': str(e)}


def ansible_facts(
    host_pattern: str,
    inventory: Optional[str] = None,
    gather_subset: Optional[List[str]] = None,
    working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Gather facts from hosts using Ansible setup module.

    Args:
        host_pattern: Host pattern to target
        inventory: Inventory file
        gather_subset: Subset of facts to gather (e.g., ['network', 'hardware'])
        working_dir: Working directory

    Returns:
        Dictionary with gathered facts
    """
    try:
        if gather_subset:
            module_args = f'gather_subset={",".join(gather_subset)}'
        else:
            module_args = None

        command = ['ansible', host_pattern, '-m', 'setup']

        if module_args:
            command.extend(['-a', module_args])

        if inventory:
            command.extend(['-i', inventory])

        result = _run_ansible_command(command, working_dir)

        return {
            'success': result['success'],
            'host_pattern': host_pattern,
            'facts': result.get('stdout', ''),
            'errors': result.get('stderr', '')
        }
    except Exception as e:
        logger.error(f"Error gathering Ansible facts: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of Ansible tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        {
            'name': 'ansible_playbook_run',
            'description': 'Run an Ansible playbook to configure and manage infrastructure.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'playbook_path': {
                        'type': 'string',
                        'description': 'Path to the Ansible playbook file (.yml or .yaml)'
                    },
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file path or comma-separated host list'
                    },
                    'limit': {
                        'type': 'string',
                        'description': 'Limit execution to specific hosts or groups'
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Only run plays and tasks tagged with these values'
                    },
                    'skip_tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Skip plays and tasks tagged with these values'
                    },
                    'extra_vars': {
                        'type': 'object',
                        'description': 'Extra variables to pass to the playbook'
                    },
                    'extra_vars_file': {
                        'type': 'string',
                        'description': 'Path to extra variables file'
                    },
                    'become': {
                        'type': 'boolean',
                        'description': 'Run with privilege escalation (sudo)',
                        'default': False
                    },
                    'become_user': {
                        'type': 'string',
                        'description': 'User to become (default: root)'
                    },
                    'check_mode': {
                        'type': 'boolean',
                        'description': 'Run in check mode (dry run, no changes made)',
                        'default': False
                    },
                    'diff': {
                        'type': 'boolean',
                        'description': 'Show differences in changed files',
                        'default': False
                    },
                    'verbosity': {
                        'type': 'integer',
                        'description': 'Verbosity level (0-4)',
                        'default': 0
                    },
                    'forks': {
                        'type': 'integer',
                        'description': 'Number of parallel processes',
                        'default': 5
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': 'Command timeout in seconds',
                        'default': 600
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory for execution'
                    }
                },
                'required': ['playbook_path']
            },
            'handler': ansible_playbook_run
        },
        {
            'name': 'ansible_adhoc_command',
            'description': 'Run an Ansible ad-hoc command on remote hosts.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'host_pattern': {
                        'type': 'string',
                        'description': 'Host pattern (e.g., "all", "webservers", "192.168.1.1")'
                    },
                    'module': {
                        'type': 'string',
                        'description': 'Ansible module to run (e.g., "ping", "shell", "copy", "apt", "yum")'
                    },
                    'module_args': {
                        'type': 'string',
                        'description': 'Module arguments (e.g., "name=nginx state=present" for apt)'
                    },
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file or comma-separated hosts'
                    },
                    'become': {
                        'type': 'boolean',
                        'description': 'Run with privilege escalation',
                        'default': False
                    },
                    'become_user': {
                        'type': 'string',
                        'description': 'User to become'
                    },
                    'forks': {
                        'type': 'integer',
                        'description': 'Number of parallel processes',
                        'default': 5
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': 'Command timeout in seconds',
                        'default': 300
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['host_pattern', 'module']
            },
            'handler': ansible_adhoc_command
        },
        {
            'name': 'ansible_inventory_list',
            'description': 'List and display Ansible inventory hosts and groups.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file or directory path'
                    },
                    'host': {
                        'type': 'string',
                        'description': 'Show variables for a specific host'
                    },
                    'graph': {
                        'type': 'boolean',
                        'description': 'Display inventory as a tree graph',
                        'default': False
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['inventory']
            },
            'handler': ansible_inventory_list
        },
        {
            'name': 'ansible_playbook_syntax_check',
            'description': 'Check Ansible playbook syntax without executing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'playbook_path': {
                        'type': 'string',
                        'description': 'Path to the playbook file'
                    },
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file (optional)'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['playbook_path']
            },
            'handler': ansible_playbook_syntax_check
        },
        {
            'name': 'ansible_galaxy_install',
            'description': 'Install roles or collections from Ansible Galaxy.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'requirements_file': {
                        'type': 'string',
                        'description': 'Path to requirements.yml file'
                    },
                    'role_name': {
                        'type': 'string',
                        'description': 'Role name to install (e.g., "geerlingguy.docker")'
                    },
                    'collection_name': {
                        'type': 'string',
                        'description': 'Collection name to install (e.g., "community.general")'
                    },
                    'roles_path': {
                        'type': 'string',
                        'description': 'Path to install roles'
                    },
                    'collections_path': {
                        'type': 'string',
                        'description': 'Path to install collections'
                    },
                    'force': {
                        'type': 'boolean',
                        'description': 'Force overwrite existing',
                        'default': False
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                }
            },
            'handler': ansible_galaxy_install
        },
        {
            'name': 'ansible_galaxy_list',
            'description': 'List installed Ansible roles or collections.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'roles_path': {
                        'type': 'string',
                        'description': 'Path to roles directory'
                    },
                    'collections': {
                        'type': 'boolean',
                        'description': 'List collections instead of roles',
                        'default': False
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                }
            },
            'handler': ansible_galaxy_list
        },
        {
            'name': 'ansible_vault_encrypt',
            'description': 'Encrypt a file with Ansible Vault for secure storage of secrets.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'file_path': {
                        'type': 'string',
                        'description': 'Path to file to encrypt'
                    },
                    'vault_password_file': {
                        'type': 'string',
                        'description': 'Path to vault password file'
                    },
                    'vault_id': {
                        'type': 'string',
                        'description': 'Vault ID label'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['file_path']
            },
            'handler': ansible_vault_encrypt
        },
        {
            'name': 'ansible_vault_decrypt',
            'description': 'Decrypt an Ansible Vault encrypted file.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'file_path': {
                        'type': 'string',
                        'description': 'Path to encrypted file'
                    },
                    'vault_password_file': {
                        'type': 'string',
                        'description': 'Path to vault password file'
                    },
                    'output_file': {
                        'type': 'string',
                        'description': 'Output to different file (leaves original encrypted)'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['file_path']
            },
            'handler': ansible_vault_decrypt
        },
        {
            'name': 'ansible_vault_view',
            'description': 'View contents of an Ansible Vault encrypted file without decrypting it permanently.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'file_path': {
                        'type': 'string',
                        'description': 'Path to encrypted file'
                    },
                    'vault_password_file': {
                        'type': 'string',
                        'description': 'Path to vault password file'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['file_path']
            },
            'handler': ansible_vault_view
        },
        {
            'name': 'ansible_ping',
            'description': 'Ping hosts to verify Ansible connectivity and authentication.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'host_pattern': {
                        'type': 'string',
                        'description': 'Host pattern to target (e.g., "all", "webservers")'
                    },
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file or comma-separated hosts'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['host_pattern']
            },
            'handler': ansible_ping
        },
        {
            'name': 'ansible_facts',
            'description': 'Gather system facts from remote hosts (hardware, network, OS info).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'host_pattern': {
                        'type': 'string',
                        'description': 'Host pattern to target'
                    },
                    'inventory': {
                        'type': 'string',
                        'description': 'Inventory file'
                    },
                    'gather_subset': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Subset of facts to gather (e.g., ["network", "hardware", "virtual"])'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['host_pattern']
            },
            'handler': ansible_facts
        },
        {
            'name': 'ansible_doc',
            'description': 'Get documentation for an Ansible module or plugin.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'module_name': {
                        'type': 'string',
                        'description': 'Name of the module or plugin'
                    },
                    'module_type': {
                        'type': 'string',
                        'description': 'Type: module, callback, connection, lookup, etc.',
                        'default': 'module'
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                },
                'required': ['module_name']
            },
            'handler': ansible_doc
        },
        {
            'name': 'ansible_config_dump',
            'description': 'Dump current Ansible configuration settings.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'only_changed': {
                        'type': 'boolean',
                        'description': 'Only show settings that differ from defaults',
                        'default': False
                    },
                    'working_dir': {
                        'type': 'string',
                        'description': 'Working directory'
                    }
                }
            },
            'handler': ansible_config_dump
        }
    ]
