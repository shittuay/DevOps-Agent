"""Docker tools for DevOps Agent."""
import os
import subprocess
from typing import Dict, Any, Optional, List
from ..utils import get_logger

logger = get_logger(__name__)


def _get_docker_client():
    """
    Get Docker client.

    Returns:
        Docker client instance
    """
    try:
        import docker
        return docker.from_env()
    except ImportError:
        raise Exception("Docker SDK not installed. Install with: pip install docker")
    except Exception as e:
        raise Exception(f"Failed to connect to Docker: {str(e)}")


def list_containers(all_containers: bool = False, filters: Optional[Dict] = None) -> Dict[str, Any]:
    """
    List Docker containers.

    Args:
        all_containers: Include stopped containers
        filters: Dictionary of filters

    Returns:
        Dictionary with container information
    """
    try:
        client = _get_docker_client()

        containers = client.containers.list(all=all_containers, filters=filters)

        container_list = []
        for container in containers:
            container_list.append({
                'id': container.id[:12],
                'name': container.name,
                'image': container.image.tags[0] if container.image.tags else container.image.id[:12],
                'status': container.status,
                'state': container.attrs['State']['Status'],
                'ports': container.ports,
                'labels': container.labels,
                'created': container.attrs['Created']
            })

        return {
            'success': True,
            'count': len(container_list),
            'containers': container_list
        }
    except Exception as e:
        logger.error(f"Error listing containers: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_container_details(container_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a container.

    Args:
        container_id: Container ID or name

    Returns:
        Dictionary with container details
    """
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)

        return {
            'success': True,
            'container': {
                'id': container.id,
                'name': container.name,
                'image': container.image.tags[0] if container.image.tags else container.image.id,
                'status': container.status,
                'state': container.attrs['State'],
                'network_settings': container.attrs['NetworkSettings'],
                'mounts': container.attrs['Mounts'],
                'config': {
                    'hostname': container.attrs['Config'].get('Hostname'),
                    'env': container.attrs['Config'].get('Env'),
                    'cmd': container.attrs['Config'].get('Cmd'),
                    'labels': container.attrs['Config'].get('Labels')
                }
            }
        }
    except Exception as e:
        logger.error(f"Error getting container details: {str(e)}")
        return {'success': False, 'error': str(e)}


def manage_container(container_id: str, action: str) -> Dict[str, Any]:
    """
    Manage container (start, stop, restart, pause, unpause, remove).

    Args:
        container_id: Container ID or name
        action: Action to perform

    Returns:
        Dictionary with result
    """
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)

        if action == 'start':
            container.start()
        elif action == 'stop':
            container.stop()
        elif action == 'restart':
            container.restart()
        elif action == 'pause':
            container.pause()
        elif action == 'unpause':
            container.unpause()
        elif action == 'remove':
            container.remove(force=True)
        else:
            return {'success': False, 'error': f'Invalid action: {action}'}

        return {
            'success': True,
            'message': f'Container {container_id} {action} completed',
            'container_id': container_id,
            'action': action
        }
    except Exception as e:
        logger.error(f"Error managing container: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_container_logs(
    container_id: str,
    tail: int = 100,
    follow: bool = False
) -> Dict[str, Any]:
    """
    Get container logs.

    Args:
        container_id: Container ID or name
        tail: Number of lines from the end
        follow: Follow log output

    Returns:
        Dictionary with logs
    """
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)

        logs = container.logs(tail=tail, follow=follow, timestamps=True).decode('utf-8')

        return {
            'success': True,
            'container_id': container_id,
            'logs': logs
        }
    except Exception as e:
        logger.error(f"Error getting container logs: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_images(all_images: bool = False) -> Dict[str, Any]:
    """
    List Docker images.

    Args:
        all_images: Include intermediate images

    Returns:
        Dictionary with image information
    """
    try:
        client = _get_docker_client()

        images = client.images.list(all=all_images)

        image_list = []
        for image in images:
            image_list.append({
                'id': image.id.split(':')[1][:12],
                'tags': image.tags,
                'size': image.attrs['Size'],
                'created': image.attrs['Created'],
                'labels': image.labels
            })

        return {
            'success': True,
            'count': len(image_list),
            'images': image_list
        }
    except Exception as e:
        logger.error(f"Error listing images: {str(e)}")
        return {'success': False, 'error': str(e)}


def pull_image(image_name: str, tag: str = 'latest') -> Dict[str, Any]:
    """
    Pull Docker image from registry.

    Args:
        image_name: Image name
        tag: Image tag

    Returns:
        Dictionary with result
    """
    try:
        client = _get_docker_client()

        full_image = f"{image_name}:{tag}"
        image = client.images.pull(image_name, tag=tag)

        return {
            'success': True,
            'message': f'Image {full_image} pulled successfully',
            'image_id': image.id,
            'tags': image.tags
        }
    except Exception as e:
        logger.error(f"Error pulling image: {str(e)}")
        return {'success': False, 'error': str(e)}


def remove_image(image_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Remove Docker image.

    Args:
        image_id: Image ID or name
        force: Force removal

    Returns:
        Dictionary with result
    """
    try:
        client = _get_docker_client()
        client.images.remove(image_id, force=force)

        return {
            'success': True,
            'message': f'Image {image_id} removed',
            'image_id': image_id
        }
    except Exception as e:
        logger.error(f"Error removing image: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_volumes() -> Dict[str, Any]:
    """
    List Docker volumes.

    Returns:
        Dictionary with volume information
    """
    try:
        client = _get_docker_client()

        volumes = client.volumes.list()

        volume_list = []
        for volume in volumes:
            volume_list.append({
                'name': volume.name,
                'driver': volume.attrs['Driver'],
                'mountpoint': volume.attrs['Mountpoint'],
                'created': volume.attrs.get('CreatedAt'),
                'labels': volume.attrs.get('Labels', {})
            })

        return {
            'success': True,
            'count': len(volume_list),
            'volumes': volume_list
        }
    except Exception as e:
        logger.error(f"Error listing volumes: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_networks() -> Dict[str, Any]:
    """
    List Docker networks.

    Returns:
        Dictionary with network information
    """
    try:
        client = _get_docker_client()

        networks = client.networks.list()

        network_list = []
        for network in networks:
            network_list.append({
                'id': network.id[:12],
                'name': network.name,
                'driver': network.attrs['Driver'],
                'scope': network.attrs['Scope'],
                'containers': len(network.attrs.get('Containers', {})),
                'labels': network.attrs.get('Labels', {})
            })

        return {
            'success': True,
            'count': len(network_list),
            'networks': network_list
        }
    except Exception as e:
        logger.error(f"Error listing networks: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_docker_stats(container_id: str) -> Dict[str, Any]:
    """
    Get container resource usage statistics.

    Args:
        container_id: Container ID or name

    Returns:
        Dictionary with stats
    """
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)

        stats = container.stats(stream=False)

        # Calculate CPU percentage
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                    stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                       stats['precpu_stats']['system_cpu_usage']
        cpu_percent = (cpu_delta / system_delta) * len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100.0 if system_delta > 0 else 0.0

        # Calculate memory usage
        memory_usage = stats['memory_stats']['usage']
        memory_limit = stats['memory_stats']['limit']
        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0.0

        return {
            'success': True,
            'container_id': container_id,
            'stats': {
                'cpu_percent': round(cpu_percent, 2),
                'memory_usage_mb': round(memory_usage / (1024 * 1024), 2),
                'memory_limit_mb': round(memory_limit / (1024 * 1024), 2),
                'memory_percent': round(memory_percent, 2),
                'network_rx_bytes': stats['networks']['eth0']['rx_bytes'] if 'eth0' in stats.get('networks', {}) else 0,
                'network_tx_bytes': stats['networks']['eth0']['tx_bytes'] if 'eth0' in stats.get('networks', {}) else 0,
            }
        }
    except Exception as e:
        logger.error(f"Error getting container stats: {str(e)}")
        return {'success': False, 'error': str(e)}


def docker_compose_up(compose_file: str, project_name: Optional[str] = None, detach: bool = True) -> Dict[str, Any]:
    """
    Run docker-compose up.

    Args:
        compose_file: Path to docker-compose.yml
        project_name: Project name
        detach: Run in detached mode

    Returns:
        Dictionary with result
    """
    try:
        import subprocess
        import os

        command = ['docker-compose', '-f', compose_file]

        if project_name:
            command.extend(['-p', project_name])

        command.append('up')

        if detach:
            command.append('-d')

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            'success': result.returncode == 0,
            'message': 'Docker Compose up completed' if result.returncode == 0 else 'Docker Compose up failed',
            'output': result.stdout,
            'errors': result.stderr
        }
    except Exception as e:
        logger.error(f"Error running docker-compose: {str(e)}")
        return {'success': False, 'error': str(e)}


def docker_compose_down(compose_file: str, project_name: Optional[str] = None, volumes: bool = False) -> Dict[str, Any]:
    """
    Run docker-compose down.

    Args:
        compose_file: Path to docker-compose.yml
        project_name: Project name
        volumes: Remove volumes

    Returns:
        Dictionary with result
    """
    try:
        import subprocess

        command = ['docker-compose', '-f', compose_file]

        if project_name:
            command.extend(['-p', project_name])

        command.append('down')

        if volumes:
            command.append('-v')

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300
        )

        return {
            'success': result.returncode == 0,
            'message': 'Docker Compose down completed' if result.returncode == 0 else 'Docker Compose down failed',
            'output': result.stdout,
            'errors': result.stderr
        }
    except Exception as e:
        logger.error(f"Error running docker-compose down: {str(e)}")
        return {'success': False, 'error': str(e)}


def build_image(path: str, tag: str, dockerfile: str = 'Dockerfile', build_args: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Build a Docker image from a Dockerfile."""
    try:
        client = _get_docker_client()
        buildargs = build_args or {}
        image, build_logs = client.images.build(
            path=path,
            tag=tag,
            dockerfile=dockerfile,
            buildargs=buildargs,
            rm=True
        )
        logs = []
        for chunk in build_logs:
            if 'stream' in chunk:
                logs.append(chunk['stream'].strip())
        return {
            'success': True,
            'message': f'Image {tag} built successfully',
            'image_id': image.id,
            'tags': image.tags,
            'build_log': '\n'.join(logs[-20:])
        }
    except Exception as e:
        logger.error(f"Error building image: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_container(image: str, name: Optional[str] = None, ports: Optional[Dict[str, str]] = None,
                     environment: Optional[Dict[str, str]] = None, volumes: Optional[Dict[str, Dict]] = None,
                     command: Optional[str] = None, detach: bool = True) -> Dict[str, Any]:
    """Create and start a new Docker container."""
    try:
        client = _get_docker_client()
        container = client.containers.run(
            image=image,
            name=name,
            ports=ports,
            environment=environment,
            volumes=volumes,
            command=command,
            detach=detach
        )
        return {
            'success': True,
            'message': f'Container {container.name} created and started',
            'container_id': container.id[:12],
            'name': container.name,
            'status': container.status
        }
    except Exception as e:
        logger.error(f"Error creating container: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_network(name: str, driver: str = 'bridge', internal: bool = False) -> Dict[str, Any]:
    """Create a Docker network."""
    try:
        client = _get_docker_client()
        network = client.networks.create(name=name, driver=driver, internal=internal)
        return {
            'success': True,
            'message': f'Network {name} created',
            'network_id': network.id[:12],
            'name': network.name,
            'driver': driver
        }
    except Exception as e:
        logger.error(f"Error creating network: {str(e)}")
        return {'success': False, 'error': str(e)}


def remove_network(network_id: str) -> Dict[str, Any]:
    """Remove a Docker network."""
    try:
        client = _get_docker_client()
        network = client.networks.get(network_id)
        name = network.name
        network.remove()
        return {'success': True, 'message': f'Network {name} removed'}
    except Exception as e:
        logger.error(f"Error removing network: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_volume(name: str, driver: str = 'local') -> Dict[str, Any]:
    """Create a Docker volume."""
    try:
        client = _get_docker_client()
        volume = client.volumes.create(name=name, driver=driver)
        return {
            'success': True,
            'message': f'Volume {name} created',
            'name': volume.name,
            'driver': volume.attrs['Driver'],
            'mountpoint': volume.attrs['Mountpoint']
        }
    except Exception as e:
        logger.error(f"Error creating volume: {str(e)}")
        return {'success': False, 'error': str(e)}


def remove_volume(name: str, force: bool = False) -> Dict[str, Any]:
    """Remove a Docker volume."""
    try:
        client = _get_docker_client()
        volume = client.volumes.get(name)
        volume.remove(force=force)
        return {'success': True, 'message': f'Volume {name} removed'}
    except Exception as e:
        logger.error(f"Error removing volume: {str(e)}")
        return {'success': False, 'error': str(e)}


def exec_in_container(container_id: str, command: str, workdir: Optional[str] = None) -> Dict[str, Any]:
    """Execute a command inside a running container."""
    import shlex as _shlex
    try:
        client = _get_docker_client()
        container = client.containers.get(container_id)
        # Split into a list so Docker passes args directly without invoking a shell.
        # A bare string causes Docker to run /bin/sh -c "<command>", enabling injection.
        try:
            command_args = _shlex.split(command)
        except ValueError as e:
            return {'success': False, 'error': f'Invalid command syntax: {e}'}
        exit_code, output = container.exec_run(command_args, workdir=workdir)
        return {
            'success': exit_code == 0,
            'container_id': container_id,
            'command': command,
            'exit_code': exit_code,
            'output': output.decode('utf-8', errors='replace')
        }
    except Exception as e:
        logger.error(f"Error executing in container: {str(e)}")
        return {'success': False, 'error': str(e)}


def tag_image(image_id: str, repository: str, tag: str = 'latest') -> Dict[str, Any]:
    """Tag a Docker image."""
    try:
        client = _get_docker_client()
        image = client.images.get(image_id)
        image.tag(repository, tag=tag)
        return {
            'success': True,
            'message': f'Image tagged as {repository}:{tag}',
            'image_id': image_id,
            'repository': repository,
            'tag': tag
        }
    except Exception as e:
        logger.error(f"Error tagging image: {str(e)}")
        return {'success': False, 'error': str(e)}


def push_image(repository: str, tag: str = 'latest') -> Dict[str, Any]:
    """Push a Docker image to a registry."""
    try:
        client = _get_docker_client()
        output = client.images.push(repository, tag=tag)
        return {
            'success': True,
            'message': f'Image {repository}:{tag} pushed',
            'output': output
        }
    except Exception as e:
        logger.error(f"Error pushing image: {str(e)}")
        return {'success': False, 'error': str(e)}


def docker_system_prune(volumes: bool = False) -> Dict[str, Any]:
    """Remove unused Docker data (stopped containers, dangling images, unused networks)."""
    try:
        client = _get_docker_client()
        result = client.containers.prune()
        containers_deleted = result.get('ContainersDeleted') or []
        result_images = client.images.prune(filters={'dangling': True})
        images_deleted = result_images.get('ImagesDeleted') or []
        result_networks = client.networks.prune()
        networks_deleted = result_networks.get('NetworksDeleted') or []
        volumes_deleted = []
        if volumes:
            result_volumes = client.volumes.prune()
            volumes_deleted = result_volumes.get('VolumesDeleted') or []
        return {
            'success': True,
            'message': 'Docker system prune completed',
            'containers_deleted': len(containers_deleted),
            'images_deleted': len(images_deleted),
            'networks_deleted': len(networks_deleted),
            'volumes_deleted': len(volumes_deleted)
        }
    except Exception as e:
        logger.error(f"Error during docker prune: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_tools() -> List[Dict[str, Any]]:
    """Get Docker tool definitions."""
    return [
        {
            'name': 'docker_list_containers',
            'description': 'List Docker containers (running or all including stopped)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'all_containers': {'type': 'boolean', 'description': 'Include stopped containers', 'default': False},
                },
                'required': []
            },
            'handler': list_containers
        },
        {
            'name': 'docker_get_container_details',
            'description': 'Get detailed information about a Docker container',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'container_id': {'type': 'string', 'description': 'Container ID or name'},
                },
                'required': ['container_id']
            },
            'handler': get_container_details
        },
        {
            'name': 'docker_manage_container',
            'description': 'Manage a Docker container: start, stop, restart, pause, unpause, or remove',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'container_id': {'type': 'string', 'description': 'Container ID or name'},
                    'action': {'type': 'string', 'enum': ['start', 'stop', 'restart', 'pause', 'unpause', 'remove'], 'description': 'Action to perform'},
                },
                'required': ['container_id', 'action']
            },
            'handler': manage_container
        },
        {
            'name': 'docker_get_container_logs',
            'description': 'Get logs from a Docker container',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'container_id': {'type': 'string', 'description': 'Container ID or name'},
                    'tail': {'type': 'integer', 'description': 'Number of lines from the end (default: 100)', 'default': 100},
                },
                'required': ['container_id']
            },
            'handler': get_container_logs
        },
        {
            'name': 'docker_list_images',
            'description': 'List Docker images on the system',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'all_images': {'type': 'boolean', 'description': 'Include intermediate images', 'default': False},
                },
                'required': []
            },
            'handler': list_images
        },
        {
            'name': 'docker_pull_image',
            'description': 'Pull a Docker image from a registry',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'image_name': {'type': 'string', 'description': 'Image name (e.g. nginx, ubuntu)'},
                    'tag': {'type': 'string', 'description': 'Image tag (default: latest)', 'default': 'latest'},
                },
                'required': ['image_name']
            },
            'handler': pull_image
        },
        {
            'name': 'docker_remove_image',
            'description': 'Remove a Docker image',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'image_id': {'type': 'string', 'description': 'Image ID or name'},
                    'force': {'type': 'boolean', 'description': 'Force removal', 'default': False},
                },
                'required': ['image_id']
            },
            'handler': remove_image
        },
        {
            'name': 'docker_list_volumes',
            'description': 'List Docker volumes',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': list_volumes
        },
        {
            'name': 'docker_list_networks',
            'description': 'List Docker networks',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': list_networks
        },
        {
            'name': 'docker_get_stats',
            'description': 'Get CPU, memory, and network stats for a running Docker container',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'container_id': {'type': 'string', 'description': 'Container ID or name'},
                },
                'required': ['container_id']
            },
            'handler': get_docker_stats
        },
        {
            'name': 'docker_compose_up',
            'description': 'Run docker-compose up to start services defined in a compose file',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'compose_file': {'type': 'string', 'description': 'Path to docker-compose.yml'},
                    'project_name': {'type': 'string', 'description': 'Project name'},
                    'detach': {'type': 'boolean', 'description': 'Run in detached mode', 'default': True},
                },
                'required': ['compose_file']
            },
            'handler': docker_compose_up
        },
        {
            'name': 'docker_compose_down',
            'description': 'Run docker-compose down to stop and remove services',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'compose_file': {'type': 'string', 'description': 'Path to docker-compose.yml'},
                    'project_name': {'type': 'string', 'description': 'Project name'},
                    'volumes': {'type': 'boolean', 'description': 'Remove volumes', 'default': False},
                },
                'required': ['compose_file']
            },
            'handler': docker_compose_down
        },
        {
            'name': 'docker_build_image',
            'description': 'Build a Docker image from a Dockerfile',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string', 'description': 'Path to build context directory'},
                    'tag': {'type': 'string', 'description': 'Image tag (e.g. myapp:v1)'},
                    'dockerfile': {'type': 'string', 'description': 'Dockerfile name', 'default': 'Dockerfile'},
                    'build_args': {'type': 'object', 'description': 'Build arguments as key-value pairs'},
                },
                'required': ['path', 'tag']
            },
            'handler': build_image
        },
        {
            'name': 'docker_create_container',
            'description': 'Create and start a new Docker container from an image',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'image': {'type': 'string', 'description': 'Image name to run'},
                    'name': {'type': 'string', 'description': 'Container name'},
                    'ports': {'type': 'object', 'description': 'Port mappings (e.g. {"80/tcp": "8080"})'},
                    'environment': {'type': 'object', 'description': 'Environment variables'},
                    'command': {'type': 'string', 'description': 'Command to run in container'},
                },
                'required': ['image']
            },
            'handler': create_container
        },
        {
            'name': 'docker_create_network',
            'description': 'Create a Docker network',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Network name'},
                    'driver': {'type': 'string', 'description': 'Network driver', 'default': 'bridge'},
                    'internal': {'type': 'boolean', 'description': 'Restrict external access', 'default': False},
                },
                'required': ['name']
            },
            'handler': create_network
        },
        {
            'name': 'docker_remove_network',
            'description': 'Remove a Docker network',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_id': {'type': 'string', 'description': 'Network ID or name'},
                },
                'required': ['network_id']
            },
            'handler': remove_network
        },
        {
            'name': 'docker_create_volume',
            'description': 'Create a Docker volume for persistent data storage',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Volume name'},
                    'driver': {'type': 'string', 'description': 'Volume driver', 'default': 'local'},
                },
                'required': ['name']
            },
            'handler': create_volume
        },
        {
            'name': 'docker_remove_volume',
            'description': 'Remove a Docker volume',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Volume name'},
                    'force': {'type': 'boolean', 'description': 'Force removal', 'default': False},
                },
                'required': ['name']
            },
            'handler': remove_volume
        },
        {
            'name': 'docker_exec',
            'description': 'Execute a command inside a running Docker container',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'container_id': {'type': 'string', 'description': 'Container ID or name'},
                    'command': {'type': 'string', 'description': 'Command to execute'},
                    'workdir': {'type': 'string', 'description': 'Working directory inside container'},
                },
                'required': ['container_id', 'command']
            },
            'handler': exec_in_container
        },
        {
            'name': 'docker_tag_image',
            'description': 'Tag a Docker image with a new repository and tag',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'image_id': {'type': 'string', 'description': 'Image ID or current tag'},
                    'repository': {'type': 'string', 'description': 'Target repository (e.g. myrepo/myapp)'},
                    'tag': {'type': 'string', 'description': 'Target tag', 'default': 'latest'},
                },
                'required': ['image_id', 'repository']
            },
            'handler': tag_image
        },
        {
            'name': 'docker_push_image',
            'description': 'Push a Docker image to a registry (Docker Hub, ECR, GCR, etc.)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repository': {'type': 'string', 'description': 'Repository name'},
                    'tag': {'type': 'string', 'description': 'Image tag', 'default': 'latest'},
                },
                'required': ['repository']
            },
            'handler': push_image
        },
        {
            'name': 'docker_system_prune',
            'description': 'Remove unused Docker data (stopped containers, dangling images, unused networks)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volumes': {'type': 'boolean', 'description': 'Also prune volumes', 'default': False},
                },
                'required': []
            },
            'handler': docker_system_prune
        },
    ]
