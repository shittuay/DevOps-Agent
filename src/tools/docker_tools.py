"""Docker tools for DevOps Agent."""
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
