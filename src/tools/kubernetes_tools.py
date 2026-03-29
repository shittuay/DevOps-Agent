"""Kubernetes tools for DevOps Agent."""
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Dict, Any, List, Optional
from ..utils import get_logger


logger = get_logger(__name__)


def _get_k8s_client(context: Optional[str] = None):
    """
    Get Kubernetes API client.

    Args:
        context: Kubernetes context to use

    Returns:
        Tuple of (CoreV1Api, AppsV1Api)
    """
    try:
        if context:
            config.load_kube_config(context=context)
        else:
            config.load_kube_config()

        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        return v1, apps_v1

    except Exception as e:
        raise Exception(f"Failed to load Kubernetes config: {str(e)}")


def get_pods(
    namespace: str = 'default',
    labels: Optional[str] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get list of pods in a namespace.

    Args:
        namespace: Kubernetes namespace
        labels: Label selector (e.g., 'app=nginx')
        context: Kubernetes context

    Returns:
        Dictionary with pod information
    """
    try:
        v1, _ = _get_k8s_client(context)

        # Get pods
        if labels:
            pods_list = v1.list_namespaced_pod(namespace=namespace, label_selector=labels)
        else:
            pods_list = v1.list_namespaced_pod(namespace=namespace)

        pods = []
        for pod in pods_list.items:
            # Get container statuses
            containers = []
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    containers.append({
                        'name': container.name,
                        'ready': container.ready,
                        'restart_count': container.restart_count,
                        'state': list(container.state.to_dict().keys())[0] if container.state else 'unknown'
                    })

            pods.append({
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace,
                'status': pod.status.phase,
                'node': pod.spec.node_name,
                'pod_ip': pod.status.pod_ip,
                'containers': containers,
                'created': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
            })

        return {
            'success': True,
            'count': len(pods),
            'pods': pods,
            'namespace': namespace,
            'context': context or 'current'
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting pods: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_pod_logs(
    pod_name: str,
    namespace: str = 'default',
    container: Optional[str] = None,
    tail_lines: int = 100,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get logs from a pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        container: Container name (for multi-container pods)
        tail_lines: Number of lines to retrieve from end
        context: Kubernetes context

    Returns:
        Dictionary with pod logs
    """
    try:
        v1, _ = _get_k8s_client(context)

        # Get logs
        kwargs = {
            'name': pod_name,
            'namespace': namespace,
            'tail_lines': tail_lines
        }
        if container:
            kwargs['container'] = container

        logs = v1.read_namespaced_pod_log(**kwargs)

        return {
            'success': True,
            'pod_name': pod_name,
            'namespace': namespace,
            'container': container or 'default',
            'logs': logs,
            'line_count': len(logs.split('\n'))
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting pod logs: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def describe_pod(
    pod_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get detailed information about a pod.

    Args:
        pod_name: Name of the pod
        namespace: Kubernetes namespace
        context: Kubernetes context

    Returns:
        Dictionary with detailed pod information
    """
    try:
        v1, _ = _get_k8s_client(context)
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        # Extract detailed info
        containers = []
        if pod.spec.containers:
            for container in pod.spec.containers:
                containers.append({
                    'name': container.name,
                    'image': container.image,
                    'ports': [p.container_port for p in container.ports] if container.ports else []
                })

        events = []
        try:
            events_list = v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f'involvedObject.name={pod_name}'
            )
            for event in events_list.items[:10]:  # Get last 10 events
                events.append({
                    'type': event.type,
                    'reason': event.reason,
                    'message': event.message,
                    'timestamp': event.last_timestamp.isoformat() if event.last_timestamp else None
                })
        except:
            pass

        return {
            'success': True,
            'pod': {
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace,
                'labels': pod.metadata.labels,
                'status': pod.status.phase,
                'node': pod.spec.node_name,
                'pod_ip': pod.status.pod_ip,
                'containers': containers,
                'conditions': [
                    {'type': c.type, 'status': c.status}
                    for c in pod.status.conditions
                ] if pod.status.conditions else [],
                'events': events
            }
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error describing pod: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_deployments(
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get list of deployments in a namespace.

    Args:
        namespace: Kubernetes namespace
        context: Kubernetes context

    Returns:
        Dictionary with deployment information
    """
    try:
        _, apps_v1 = _get_k8s_client(context)
        deployments_list = apps_v1.list_namespaced_deployment(namespace=namespace)

        deployments = []
        for deployment in deployments_list.items:
            deployments.append({
                'name': deployment.metadata.name,
                'namespace': deployment.metadata.namespace,
                'replicas': {
                    'desired': deployment.spec.replicas,
                    'ready': deployment.status.ready_replicas or 0,
                    'available': deployment.status.available_replicas or 0
                },
                'strategy': deployment.spec.strategy.type,
                'created': deployment.metadata.creation_timestamp.isoformat() if deployment.metadata.creation_timestamp else None
            })

        return {
            'success': True,
            'count': len(deployments),
            'deployments': deployments,
            'namespace': namespace
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting deployments: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def scale_deployment(
    deployment_name: str,
    replicas: int,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Scale a deployment to specified number of replicas.

    Args:
        deployment_name: Name of the deployment
        replicas: Number of replicas
        namespace: Kubernetes namespace
        context: Kubernetes context

    Returns:
        Dictionary with scaling result
    """
    try:
        _, apps_v1 = _get_k8s_client(context)

        # Update deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )
        deployment.spec.replicas = replicas

        apps_v1.patch_namespaced_deployment_scale(
            name=deployment_name,
            namespace=namespace,
            body={'spec': {'replicas': replicas}}
        )

        return {
            'success': True,
            'deployment': deployment_name,
            'namespace': namespace,
            'replicas': replicas,
            'message': f'Scaled deployment {deployment_name} to {replicas} replicas'
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error scaling deployment: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def restart_deployment(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Restart a deployment by updating its template annotation.

    Args:
        deployment_name: Name of the deployment
        namespace: Kubernetes namespace
        context: Kubernetes context

    Returns:
        Dictionary with restart result
    """
    try:
        _, apps_v1 = _get_k8s_client(context)

        # Update deployment with restart annotation
        from datetime import datetime
        now = datetime.utcnow().isoformat()

        body = {
            'spec': {
                'template': {
                    'metadata': {
                        'annotations': {
                            'kubectl.kubernetes.io/restartedAt': now
                        }
                    }
                }
            }
        }

        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=body
        )

        return {
            'success': True,
            'deployment': deployment_name,
            'namespace': namespace,
            'message': f'Restarted deployment {deployment_name}',
            'restarted_at': now
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error restarting deployment: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_services(
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get list of services in a namespace.

    Args:
        namespace: Kubernetes namespace
        context: Kubernetes context

    Returns:
        Dictionary with service information
    """
    try:
        v1, _ = _get_k8s_client(context)
        services_list = v1.list_namespaced_service(namespace=namespace)

        services = []
        for service in services_list.items:
            services.append({
                'name': service.metadata.name,
                'namespace': service.metadata.namespace,
                'type': service.spec.type,
                'cluster_ip': service.spec.cluster_ip,
                'external_ip': service.status.load_balancer.ingress[0].ip if service.status.load_balancer and service.status.load_balancer.ingress else None,
                'ports': [
                    {'port': p.port, 'target_port': p.target_port, 'protocol': p.protocol}
                    for p in service.spec.ports
                ] if service.spec.ports else []
            })

        return {
            'success': True,
            'count': len(services),
            'services': services,
            'namespace': namespace
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting services: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_nodes(context: Optional[str] = None) -> Dict[str, Any]:
    """
    Get list of cluster nodes.

    Args:
        context: Kubernetes context

    Returns:
        Dictionary with node information
    """
    try:
        v1, _ = _get_k8s_client(context)
        nodes_list = v1.list_node()

        nodes = []
        for node in nodes_list.items:
            # Get node conditions
            conditions = {}
            if node.status.conditions:
                for condition in node.status.conditions:
                    conditions[condition.type] = condition.status

            # Get node resources
            allocatable = node.status.allocatable
            capacity = node.status.capacity

            nodes.append({
                'name': node.metadata.name,
                'status': 'Ready' if conditions.get('Ready') == 'True' else 'NotReady',
                'roles': list(node.metadata.labels.get('kubernetes.io/role', 'worker')),
                'version': node.status.node_info.kubelet_version,
                'os': node.status.node_info.operating_system,
                'capacity': {
                    'cpu': capacity.get('cpu'),
                    'memory': capacity.get('memory')
                },
                'allocatable': {
                    'cpu': allocatable.get('cpu'),
                    'memory': allocatable.get('memory')
                }
            })

        return {
            'success': True,
            'count': len(nodes),
            'nodes': nodes
        }

    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'status_code': e.status
        }
    except Exception as e:
        logger.error(f"Error getting nodes: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


# ============================================================================
# POD OPERATIONS
# ============================================================================

def delete_pod(
    pod_name: str,
    namespace: str = 'default',
    grace_period: Optional[int] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a pod."""
    try:
        v1, _ = _get_k8s_client(context)
        body = client.V1DeleteOptions()
        if grace_period is not None:
            body.grace_period_seconds = grace_period

        v1.delete_namespaced_pod(name=pod_name, namespace=namespace, body=body)
        return {
            'success': True, 'pod_name': pod_name, 'namespace': namespace,
            'message': f'Successfully deleted pod {pod_name} in {namespace}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting pod: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def exec_pod_command(
    pod_name: str,
    command: str,
    namespace: str = 'default',
    container: Optional[str] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Execute a command inside a running pod."""
    try:
        from kubernetes.stream import stream
        v1, _ = _get_k8s_client(context)

        exec_command = ['/bin/sh', '-c', command]
        kwargs = {
            'name': pod_name,
            'namespace': namespace,
            'command': exec_command,
            'stderr': True,
            'stdin': False,
            'stdout': True,
            'tty': False,
        }
        if container:
            kwargs['container'] = container

        result = stream(v1.connect_get_namespaced_pod_exec, **kwargs)
        return {
            'success': True, 'pod_name': pod_name, 'namespace': namespace,
            'command': command, 'output': result,
            'message': f'Successfully executed command in pod {pod_name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error executing command in pod: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# DEPLOYMENT LIFECYCLE
# ============================================================================

def create_deployment(
    name: str,
    image: str,
    replicas: int = 1,
    port: Optional[int] = None,
    namespace: str = 'default',
    labels: Optional[Dict[str, str]] = None,
    env_vars: Optional[Dict[str, str]] = None,
    cpu_request: Optional[str] = None,
    memory_request: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    memory_limit: Optional[str] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes deployment."""
    try:
        _, apps_v1 = _get_k8s_client(context)

        app_labels = labels or {'app': name}

        container_ports = []
        if port:
            container_ports = [client.V1ContainerPort(container_port=port)]

        env_list = []
        if env_vars:
            env_list = [client.V1EnvVar(name=k, value=v) for k, v in env_vars.items()]

        resources = {}
        requests = {}
        limits = {}
        if cpu_request:
            requests['cpu'] = cpu_request
        if memory_request:
            requests['memory'] = memory_request
        if cpu_limit:
            limits['cpu'] = cpu_limit
        if memory_limit:
            limits['memory'] = memory_limit
        if requests or limits:
            resources = client.V1ResourceRequirements(requests=requests or None, limits=limits or None)

        container = client.V1Container(
            name=name,
            image=image,
            ports=container_ports or None,
            env=env_list or None,
            resources=resources or None,
        )

        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=app_labels),
            spec=client.V1PodSpec(containers=[container]),
        )

        spec = client.V1DeploymentSpec(
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels=app_labels),
            template=template,
        )

        deployment = client.V1Deployment(
            api_version='apps/v1',
            kind='Deployment',
            metadata=client.V1ObjectMeta(name=name, labels=app_labels),
            spec=spec,
        )

        result = apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'replicas': replicas, 'image': image,
            'message': f'Successfully created deployment {name} with {replicas} replicas'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating deployment: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_deployment_image(
    deployment_name: str,
    image: str,
    container_name: Optional[str] = None,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Update a deployment's container image (triggers rolling update)."""
    try:
        _, apps_v1 = _get_k8s_client(context)

        # Get current deployment to find container name if not specified
        if not container_name:
            deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            container_name = deployment.spec.template.spec.containers[0].name

        body = {
            'spec': {
                'template': {
                    'spec': {
                        'containers': [{'name': container_name, 'image': image}]
                    }
                }
            }
        }

        apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return {
            'success': True, 'deployment': deployment_name, 'namespace': namespace,
            'container': container_name, 'new_image': image,
            'message': f'Successfully updated {deployment_name} to image {image}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error updating deployment image: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_deployment(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes deployment."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        apps_v1.delete_namespaced_deployment(name=deployment_name, namespace=namespace)
        return {
            'success': True, 'deployment': deployment_name, 'namespace': namespace,
            'message': f'Successfully deleted deployment {deployment_name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting deployment: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SERVICE MANAGEMENT
# ============================================================================

def create_service(
    name: str,
    port: int,
    target_port: Optional[int] = None,
    service_type: str = 'ClusterIP',
    selector: Optional[Dict[str, str]] = None,
    namespace: str = 'default',
    protocol: str = 'TCP',
    node_port: Optional[int] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes service (ClusterIP, NodePort, or LoadBalancer)."""
    try:
        v1, _ = _get_k8s_client(context)

        svc_selector = selector or {'app': name}
        svc_port = client.V1ServicePort(
            port=port,
            target_port=target_port or port,
            protocol=protocol,
        )
        if node_port and service_type == 'NodePort':
            svc_port.node_port = node_port

        service = client.V1Service(
            api_version='v1',
            kind='Service',
            metadata=client.V1ObjectMeta(name=name),
            spec=client.V1ServiceSpec(
                type=service_type,
                selector=svc_selector,
                ports=[svc_port],
            ),
        )

        result = v1.create_namespaced_service(namespace=namespace, body=service)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'type': service_type, 'port': port, 'target_port': target_port or port,
            'cluster_ip': result.spec.cluster_ip,
            'message': f'Successfully created {service_type} service {name} on port {port}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating service: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_service(
    service_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes service."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespaced_service(name=service_name, namespace=namespace)
        return {
            'success': True, 'service': service_name, 'namespace': namespace,
            'message': f'Successfully deleted service {service_name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting service: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_namespaces(context: Optional[str] = None) -> Dict[str, Any]:
    """List all Kubernetes namespaces."""
    try:
        v1, _ = _get_k8s_client(context)
        ns_list = v1.list_namespace()

        namespaces = []
        for ns in ns_list.items:
            namespaces.append({
                'name': ns.metadata.name,
                'status': ns.status.phase,
                'labels': ns.metadata.labels,
                'created': ns.metadata.creation_timestamp.isoformat() if ns.metadata.creation_timestamp else None
            })

        return {
            'success': True, 'count': len(namespaces), 'namespaces': namespaces
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error listing namespaces: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# NAMESPACE MANAGEMENT
# ============================================================================

def create_namespace(
    name: str,
    labels: Optional[Dict[str, str]] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes namespace."""
    try:
        v1, _ = _get_k8s_client(context)

        metadata = client.V1ObjectMeta(name=name)
        if labels:
            metadata.labels = labels

        ns = client.V1Namespace(metadata=metadata)
        result = v1.create_namespace(body=ns)
        return {
            'success': True, 'name': result.metadata.name,
            'message': f'Successfully created namespace {name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating namespace: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_namespace(
    name: str,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes namespace and all resources within it."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespace(name=name)
        return {
            'success': True, 'name': name,
            'message': f'Successfully deleted namespace {name} (resources will be garbage collected)'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting namespace: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# CONFIGMAP & SECRET OPERATIONS
# ============================================================================

def create_configmap(
    name: str,
    data: Dict[str, str],
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a ConfigMap."""
    try:
        v1, _ = _get_k8s_client(context)

        configmap = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=name),
            data=data,
        )
        result = v1.create_namespaced_config_map(namespace=namespace, body=configmap)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'keys': list(data.keys()),
            'message': f'Successfully created ConfigMap {name} with {len(data)} keys'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating ConfigMap: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_configmap(
    name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a ConfigMap."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespaced_config_map(name=name, namespace=namespace)
        return {
            'success': True, 'name': name, 'namespace': namespace,
            'message': f'Successfully deleted ConfigMap {name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting ConfigMap: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_k8s_secret(
    name: str,
    data: Dict[str, str],
    namespace: str = 'default',
    secret_type: str = 'Opaque',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes Secret. Values are automatically base64-encoded."""
    try:
        import base64
        v1, _ = _get_k8s_client(context)

        encoded_data = {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}

        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name),
            data=encoded_data,
            type=secret_type,
        )
        result = v1.create_namespaced_secret(namespace=namespace, body=secret)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'type': secret_type, 'keys': list(data.keys()),
            'message': f'Successfully created Secret {name} with {len(data)} keys'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating Secret: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_k8s_secret(
    name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes Secret."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespaced_secret(name=name, namespace=namespace)
        return {
            'success': True, 'name': name, 'namespace': namespace,
            'message': f'Successfully deleted Secret {name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting Secret: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# INGRESS OPERATIONS
# ============================================================================

def create_ingress(
    name: str,
    host: str,
    service_name: str,
    service_port: int,
    path: str = '/',
    path_type: str = 'Prefix',
    tls_secret: Optional[str] = None,
    ingress_class: Optional[str] = None,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes Ingress for HTTP routing."""
    try:
        v1, _ = _get_k8s_client(context)
        networking_v1 = client.NetworkingV1Api()

        annotations = {}
        if ingress_class:
            annotations['kubernetes.io/ingress.class'] = ingress_class

        rule = client.V1IngressRule(
            host=host,
            http=client.V1HTTPIngressRuleValue(
                paths=[
                    client.V1HTTPIngressPath(
                        path=path,
                        path_type=path_type,
                        backend=client.V1IngressBackend(
                            service=client.V1IngressServiceBackend(
                                name=service_name,
                                port=client.V1ServiceBackendPort(number=service_port),
                            )
                        ),
                    )
                ]
            ),
        )

        spec = client.V1IngressSpec(rules=[rule])
        if tls_secret:
            spec.tls = [client.V1IngressTLS(hosts=[host], secret_name=tls_secret)]

        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(name=name, annotations=annotations or None),
            spec=spec,
        )

        result = networking_v1.create_namespaced_ingress(namespace=namespace, body=ingress)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'host': host, 'path': path, 'service': service_name,
            'message': f'Successfully created Ingress {name} routing {host}{path} to {service_name}:{service_port}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating Ingress: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ingress(
    ingress_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes Ingress."""
    try:
        v1, _ = _get_k8s_client(context)
        networking_v1 = client.NetworkingV1Api()
        networking_v1.delete_namespaced_ingress(name=ingress_name, namespace=namespace)
        return {
            'success': True, 'ingress': ingress_name, 'namespace': namespace,
            'message': f'Successfully deleted Ingress {ingress_name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting Ingress: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# NODE OPERATIONS
# ============================================================================

def cordon_node(
    node_name: str,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Cordon a node (mark as unschedulable for maintenance)."""
    try:
        v1, _ = _get_k8s_client(context)
        body = {'spec': {'unschedulable': True}}
        v1.patch_node(name=node_name, body=body)
        return {
            'success': True, 'node': node_name, 'unschedulable': True,
            'message': f'Successfully cordoned node {node_name} (marked unschedulable)'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error cordoning node: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def uncordon_node(
    node_name: str,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Uncordon a node (mark as schedulable again)."""
    try:
        v1, _ = _get_k8s_client(context)
        body = {'spec': {'unschedulable': False}}
        v1.patch_node(name=node_name, body=body)
        return {
            'success': True, 'node': node_name, 'unschedulable': False,
            'message': f'Successfully uncordoned node {node_name} (marked schedulable)'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error uncordoning node: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# JOB OPERATIONS
# ============================================================================

def create_job(
    name: str,
    image: str,
    command: Optional[List[str]] = None,
    namespace: str = 'default',
    restart_policy: str = 'Never',
    backoff_limit: int = 3,
    ttl_seconds: Optional[int] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kubernetes Job for one-off or batch workloads."""
    try:
        v1, _ = _get_k8s_client(context)
        batch_v1 = client.BatchV1Api()

        container = client.V1Container(name=name, image=image)
        if command:
            container.command = command

        job_spec = client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    containers=[container],
                    restart_policy=restart_policy,
                )
            ),
            backoff_limit=backoff_limit,
        )
        if ttl_seconds is not None:
            job_spec.ttl_seconds_after_finished = ttl_seconds

        job = client.V1Job(
            metadata=client.V1ObjectMeta(name=name),
            spec=job_spec,
        )

        result = batch_v1.create_namespaced_job(namespace=namespace, body=job)
        return {
            'success': True, 'name': result.metadata.name, 'namespace': namespace,
            'image': image,
            'message': f'Successfully created Job {name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error creating Job: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_job(
    job_name: str,
    namespace: str = 'default',
    propagation_policy: str = 'Background',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a Kubernetes Job and its pods."""
    try:
        v1, _ = _get_k8s_client(context)
        batch_v1 = client.BatchV1Api()
        batch_v1.delete_namespaced_job(
            name=job_name, namespace=namespace,
            body=client.V1DeleteOptions(propagation_policy=propagation_policy)
        )
        return {
            'success': True, 'job': job_name, 'namespace': namespace,
            'message': f'Successfully deleted Job {job_name}'
        }
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error deleting Job: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# KUBERNETES EXTENDED OPERATIONS
# ============================================================================

def get_previous_container_logs(
    pod_name: str,
    namespace: str = 'default',
    container: Optional[str] = None,
    tail_lines: int = 100,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve logs from a crashed or previously restarted container."""
    try:
        v1, _ = _get_k8s_client(context)
        kwargs = {
            'name': pod_name, 'namespace': namespace,
            'previous': True, 'tail_lines': tail_lines,
        }
        if container:
            kwargs['container'] = container
        logs = v1.read_namespaced_pod_log(**kwargs)
        return {'success': True, 'pod_name': pod_name, 'namespace': namespace,
                'logs': logs, 'previous_container': True}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def describe_deployment(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Get full details of a deployment including strategy, conditions, and rollout status."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        d = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        spec = d.spec or {}
        status = d.status or {}
        containers = [
            {
                'name': c.name,
                'image': c.image,
                'resources': {
                    'requests': {
                        'cpu': c.resources.requests.get('cpu') if c.resources and c.resources.requests else None,
                        'memory': c.resources.requests.get('memory') if c.resources and c.resources.requests else None,
                    } if c.resources else {},
                    'limits': {
                        'cpu': c.resources.limits.get('cpu') if c.resources and c.resources.limits else None,
                        'memory': c.resources.limits.get('memory') if c.resources and c.resources.limits else None,
                    } if c.resources else {},
                }
            }
            for c in (spec.template.spec.containers if spec.template and spec.template.spec else [])
        ]
        conditions = [
            {'type': c.type, 'status': c.status, 'reason': c.reason, 'message': c.message}
            for c in (status.conditions or [])
        ]
        return {
            'success': True,
            'name': d.metadata.name,
            'namespace': namespace,
            'replicas': spec.replicas,
            'ready_replicas': status.ready_replicas,
            'available_replicas': status.available_replicas,
            'strategy': d.spec.strategy.type if d.spec and d.spec.strategy else None,
            'selector': d.spec.selector.match_labels if d.spec and d.spec.selector else {},
            'containers': containers,
            'conditions': conditions,
            'labels': d.metadata.labels or {},
            'annotations': d.metadata.annotations or {},
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def rollout_status(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Check the progress of an ongoing deployment rollout."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        d = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        status = d.status
        spec_replicas = d.spec.replicas or 0
        ready = status.ready_replicas or 0
        updated = status.updated_replicas or 0
        available = status.available_replicas or 0
        complete = (ready == spec_replicas and updated == spec_replicas and available == spec_replicas)
        return {
            'success': True,
            'deployment_name': deployment_name,
            'namespace': namespace,
            'desired_replicas': spec_replicas,
            'updated_replicas': updated,
            'ready_replicas': ready,
            'available_replicas': available,
            'rollout_complete': complete,
            'message': f'deployment "{deployment_name}" successfully rolled out' if complete else f'Waiting: {ready}/{spec_replicas} ready'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def rollout_history(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """View previous deployment revisions via ReplicaSet annotations."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        rss = apps_v1.list_namespaced_replica_set(namespace=namespace)
        revisions = []
        for rs in rss.items:
            annotations = rs.metadata.annotations or {}
            owner_refs = rs.metadata.owner_references or []
            is_owned = any(o.name == deployment_name for o in owner_refs)
            if is_owned:
                revision = annotations.get('deployment.kubernetes.io/revision')
                change_cause = annotations.get('kubernetes.io/change-cause', '<none>')
                containers = rs.spec.template.spec.containers if rs.spec and rs.spec.template and rs.spec.template.spec else []
                revisions.append({
                    'revision': int(revision) if revision else 0,
                    'change_cause': change_cause,
                    'images': [c.image for c in containers],
                    'replicaset': rs.metadata.name,
                })
        revisions.sort(key=lambda r: r['revision'])
        return {
            'success': True,
            'deployment_name': deployment_name,
            'namespace': namespace,
            'revisions': revisions,
            'revision_count': len(revisions)
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def rollback_deployment(
    deployment_name: str,
    namespace: str = 'default',
    revision: Optional[int] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Revert a deployment to a previous revision by updating its image from a ReplicaSet."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        rss = apps_v1.list_namespaced_replica_set(namespace=namespace)
        target_rs = None
        if revision:
            for rs in rss.items:
                annotations = rs.metadata.annotations or {}
                owner_refs = rs.metadata.owner_references or []
                is_owned = any(o.name == deployment_name for o in owner_refs)
                rev = int(annotations.get('deployment.kubernetes.io/revision', 0))
                if is_owned and rev == revision:
                    target_rs = rs
                    break
        else:
            # Find second-highest revision (previous)
            candidates = []
            for rs in rss.items:
                annotations = rs.metadata.annotations or {}
                owner_refs = rs.metadata.owner_references or []
                is_owned = any(o.name == deployment_name for o in owner_refs)
                if is_owned:
                    rev = int(annotations.get('deployment.kubernetes.io/revision', 0))
                    candidates.append((rev, rs))
            candidates.sort(key=lambda x: x[0], reverse=True)
            if len(candidates) >= 2:
                target_rs = candidates[1][1]
        if not target_rs:
            return {'success': False, 'error': f'Could not find target revision for rollback'}
        containers = target_rs.spec.template.spec.containers if target_rs.spec and target_rs.spec.template and target_rs.spec.template.spec else []
        d = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        d.spec.template.spec.containers = containers
        apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=d)
        return {
            'success': True,
            'deployment_name': deployment_name,
            'namespace': namespace,
            'rolled_back_to_replicaset': target_rs.metadata.name,
            'images': [c.image for c in containers],
            'message': f'Deployment {deployment_name} rolled back'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def pause_rollout(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Pause an in-progress deployment rollout."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        apps_v1.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace,
            body={'spec': {'paused': True}}
        )
        return {'success': True, 'deployment_name': deployment_name,
                'namespace': namespace, 'paused': True,
                'message': f'Deployment {deployment_name} rollout paused'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def resume_rollout(
    deployment_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Resume a paused deployment rollout."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        apps_v1.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace,
            body={'spec': {'paused': False}}
        )
        return {'success': True, 'deployment_name': deployment_name,
                'namespace': namespace, 'paused': False,
                'message': f'Deployment {deployment_name} rollout resumed'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- StatefulSets ----

def list_statefulsets(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all StatefulSets in a namespace."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        response = apps_v1.list_namespaced_stateful_set(namespace=namespace)
        sets = []
        for ss in response.items:
            sets.append({
                'name': ss.metadata.name,
                'namespace': ss.metadata.namespace,
                'replicas': ss.spec.replicas,
                'ready_replicas': ss.status.ready_replicas or 0,
                'service_name': ss.spec.service_name,
                'labels': ss.metadata.labels or {},
            })
        return {'success': True, 'statefulsets': sets, 'count': len(sets)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def scale_statefulset(
    name: str,
    replicas: int,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Scale a StatefulSet to a desired number of replicas."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        apps_v1.patch_namespaced_stateful_set_scale(
            name=name, namespace=namespace,
            body={'spec': {'replicas': replicas}}
        )
        return {'success': True, 'name': name, 'namespace': namespace,
                'replicas': replicas, 'message': f'StatefulSet {name} scaled to {replicas} replicas'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_statefulset(
    name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a StatefulSet."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        apps_v1.delete_namespaced_stateful_set(name=name, namespace=namespace)
        return {'success': True, 'name': name, 'namespace': namespace,
                'message': f'StatefulSet {name} deleted'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_replicasets(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all ReplicaSets in a namespace."""
    try:
        _, apps_v1 = _get_k8s_client(context)
        response = apps_v1.list_namespaced_replica_set(namespace=namespace)
        rss = []
        for rs in response.items:
            annotations = rs.metadata.annotations or {}
            rss.append({
                'name': rs.metadata.name,
                'namespace': rs.metadata.namespace,
                'desired': rs.spec.replicas or 0,
                'ready': rs.status.ready_replicas or 0,
                'revision': annotations.get('deployment.kubernetes.io/revision', '?'),
                'owner': next((o.name for o in (rs.metadata.owner_references or [])), None),
                'labels': rs.metadata.labels or {},
            })
        return {'success': True, 'replicasets': rss, 'count': len(rss)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Services Extended ----

def describe_service(
    service_name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Get full details of a service including endpoints, selectors, and port mappings."""
    try:
        v1, _ = _get_k8s_client(context)
        svc = v1.read_namespaced_service(name=service_name, namespace=namespace)
        # Get endpoints
        try:
            ep = v1.read_namespaced_endpoints(name=service_name, namespace=namespace)
            endpoints = []
            for subset in (ep.subsets or []):
                for addr in (subset.addresses or []):
                    for port in (subset.ports or []):
                        endpoints.append({'ip': addr.ip, 'port': port.port, 'pod': addr.target_ref.name if addr.target_ref else None})
        except Exception:
            endpoints = []
        ports = [{'name': p.name, 'port': p.port, 'target_port': str(p.target_port), 'protocol': p.protocol,
                  'node_port': p.node_port} for p in (svc.spec.ports or [])]
        return {
            'success': True,
            'name': svc.metadata.name, 'namespace': namespace,
            'type': svc.spec.type,
            'cluster_ip': svc.spec.cluster_ip,
            'external_ip': svc.status.load_balancer.ingress[0].ip if svc.status.load_balancer and svc.status.load_balancer.ingress else None,
            'selector': svc.spec.selector or {},
            'ports': ports,
            'endpoints': endpoints,
            'labels': svc.metadata.labels or {},
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- ConfigMaps Extended ----

def list_configmaps(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all ConfigMaps in a namespace."""
    try:
        v1, _ = _get_k8s_client(context)
        response = v1.list_namespaced_config_map(namespace=namespace)
        cms = []
        for cm in response.items:
            cms.append({
                'name': cm.metadata.name,
                'namespace': cm.metadata.namespace,
                'data_keys': list((cm.data or {}).keys()),
                'key_count': len(cm.data or {}),
                'labels': cm.metadata.labels or {},
            })
        return {'success': True, 'configmaps': cms, 'count': len(cms)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_configmap(
    name: str,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Get the contents of a ConfigMap."""
    try:
        v1, _ = _get_k8s_client(context)
        cm = v1.read_namespaced_config_map(name=name, namespace=namespace)
        return {
            'success': True,
            'name': cm.metadata.name,
            'namespace': namespace,
            'data': cm.data or {},
            'labels': cm.metadata.labels or {},
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_configmap(
    name: str,
    data: Dict[str, str],
    namespace: str = 'default',
    merge: bool = True,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Update or replace keys in a ConfigMap. merge=True adds/updates keys; merge=False replaces all data."""
    try:
        v1, _ = _get_k8s_client(context)
        cm = v1.read_namespaced_config_map(name=name, namespace=namespace)
        if merge:
            existing = cm.data or {}
            existing.update(data)
            cm.data = existing
        else:
            cm.data = data
        v1.replace_namespaced_config_map(name=name, namespace=namespace, body=cm)
        return {
            'success': True, 'name': name, 'namespace': namespace,
            'keys_updated': list(data.keys()), 'merge': merge,
            'message': f'ConfigMap {name} updated'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Secrets Extended ----

def list_k8s_secrets(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all secrets in a namespace (keys only, values not exposed)."""
    try:
        v1, _ = _get_k8s_client(context)
        response = v1.list_namespaced_secret(namespace=namespace)
        secrets = []
        for s in response.items:
            secrets.append({
                'name': s.metadata.name,
                'namespace': s.metadata.namespace,
                'type': s.type,
                'data_keys': list((s.data or {}).keys()),
                'labels': s.metadata.labels or {},
            })
        return {'success': True, 'secrets': secrets, 'count': len(secrets)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_k8s_secret(
    name: str,
    data: Dict[str, str],
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Update keys in a Kubernetes secret (values are auto base64-encoded)."""
    try:
        import base64
        v1, _ = _get_k8s_client(context)
        secret = v1.read_namespaced_secret(name=name, namespace=namespace)
        existing = secret.data or {}
        for k, v in data.items():
            existing[k] = base64.b64encode(v.encode()).decode()
        secret.data = existing
        v1.replace_namespaced_secret(name=name, namespace=namespace, body=secret)
        return {
            'success': True, 'name': name, 'namespace': namespace,
            'keys_updated': list(data.keys()),
            'message': f'Secret {name} updated'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Nodes Extended ----

def describe_node(node_name: str, context: Optional[str] = None) -> Dict[str, Any]:
    """Get full details of a node including capacity, taints, conditions, and running pods."""
    try:
        v1, _ = _get_k8s_client(context)
        node = v1.read_node(name=node_name)
        capacity = {k: str(v) for k, v in (node.status.capacity or {}).items()}
        allocatable = {k: str(v) for k, v in (node.status.allocatable or {}).items()}
        conditions = [{'type': c.type, 'status': c.status, 'reason': c.reason} for c in (node.status.conditions or [])]
        taints = [{'key': t.key, 'value': t.value, 'effect': t.effect} for t in (node.spec.taints or [])]
        labels = node.metadata.labels or {}
        # Get pods on this node
        pods = v1.list_pod_for_all_namespaces(field_selector=f'spec.nodeName={node_name}')
        running_pods = [{'name': p.metadata.name, 'namespace': p.metadata.namespace, 'status': p.status.phase} for p in pods.items]
        return {
            'success': True,
            'name': node_name,
            'roles': [k.replace('node-role.kubernetes.io/', '') for k in labels if k.startswith('node-role.kubernetes.io/')],
            'capacity': capacity,
            'allocatable': allocatable,
            'conditions': conditions,
            'taints': taints,
            'unschedulable': node.spec.unschedulable or False,
            'running_pods': running_pods,
            'pod_count': len(running_pods),
            'labels': labels,
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def drain_node(
    node_name: str,
    ignore_daemonsets: bool = True,
    delete_emptydir_data: bool = False,
    grace_period: int = 30,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Evict all pods from a node for maintenance (cordon + evict)."""
    try:
        from kubernetes import client as k8s_client
        v1, _ = _get_k8s_client(context)
        # First cordon the node
        v1.patch_node(name=node_name, body={'spec': {'unschedulable': True}})
        # List pods on the node
        pods = v1.list_pod_for_all_namespaces(field_selector=f'spec.nodeName={node_name}')
        evicted = []
        skipped = []
        for pod in pods.items:
            # Skip DaemonSet pods if ignore_daemonsets
            owner_refs = pod.metadata.owner_references or []
            is_daemonset = any(o.kind == 'DaemonSet' for o in owner_refs)
            if is_daemonset and ignore_daemonsets:
                skipped.append({'name': pod.metadata.name, 'reason': 'DaemonSet'})
                continue
            # Skip pods with local storage if not delete_emptydir_data
            if not delete_emptydir_data:
                has_emptydir = any(v.empty_dir is not None for v in (pod.spec.volumes or []))
                if has_emptydir:
                    skipped.append({'name': pod.metadata.name, 'reason': 'emptyDir data'})
                    continue
            try:
                eviction = k8s_client.V1Eviction(
                    metadata=k8s_client.V1ObjectMeta(name=pod.metadata.name, namespace=pod.metadata.namespace),
                    delete_options=k8s_client.V1DeleteOptions(grace_period_seconds=grace_period)
                )
                v1.create_namespaced_pod_eviction(name=pod.metadata.name, namespace=pod.metadata.namespace, body=eviction)
                evicted.append(pod.metadata.name)
            except Exception as ev_err:
                skipped.append({'name': pod.metadata.name, 'reason': str(ev_err)})
        return {
            'success': True, 'node_name': node_name,
            'cordoned': True, 'evicted_pods': evicted, 'evicted_count': len(evicted),
            'skipped_pods': skipped,
            'message': f'Node {node_name} drained: {len(evicted)} pods evicted, {len(skipped)} skipped'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def taint_node(
    node_name: str,
    key: str,
    value: str,
    effect: str = 'NoSchedule',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Add a taint to a node to repel pods without matching tolerations."""
    try:
        from kubernetes import client as k8s_client
        v1, _ = _get_k8s_client(context)
        node = v1.read_node(name=node_name)
        taints = node.spec.taints or []
        # Remove existing taint with same key/effect if present
        taints = [t for t in taints if not (t.key == key and t.effect == effect)]
        taints.append(k8s_client.V1Taint(key=key, value=value, effect=effect))
        node.spec.taints = taints
        v1.patch_node(name=node_name, body={'spec': {'taints': [{'key': t.key, 'value': t.value, 'effect': t.effect} for t in taints]}})
        return {
            'success': True, 'node_name': node_name,
            'taint': {'key': key, 'value': value, 'effect': effect},
            'message': f'Taint {key}={value}:{effect} added to node {node_name}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def remove_node_taint(
    node_name: str,
    key: str,
    effect: Optional[str] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Remove a taint from a node."""
    try:
        v1, _ = _get_k8s_client(context)
        node = v1.read_node(name=node_name)
        taints = node.spec.taints or []
        before = len(taints)
        if effect:
            taints = [t for t in taints if not (t.key == key and t.effect == effect)]
        else:
            taints = [t for t in taints if t.key != key]
        removed = before - len(taints)
        v1.patch_node(name=node_name, body={'spec': {'taints': [{'key': t.key, 'value': t.value, 'effect': t.effect} for t in taints]}})
        return {
            'success': True, 'node_name': node_name, 'key_removed': key,
            'taints_removed': removed,
            'message': f'{removed} taint(s) with key={key} removed from node {node_name}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def label_node(
    node_name: str,
    labels: Dict[str, str],
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Add or update labels on a node for affinity scheduling."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.patch_node(name=node_name, body={'metadata': {'labels': labels}})
        return {
            'success': True, 'node_name': node_name, 'labels': labels,
            'message': f'Labels applied to node {node_name}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def top_nodes(context: Optional[str] = None) -> Dict[str, Any]:
    """Get CPU and memory usage across all nodes (requires metrics-server)."""
    try:
        from kubernetes import client as k8s_client
        v1, _ = _get_k8s_client(context)
        custom_api = k8s_client.CustomObjectsApi()
        metrics = custom_api.list_cluster_custom_object(
            group='metrics.k8s.io', version='v1beta1', plural='nodes'
        )
        nodes = []
        for item in metrics.get('items', []):
            usage = item.get('usage', {})
            nodes.append({
                'node': item['metadata']['name'],
                'cpu': usage.get('cpu'),
                'memory': usage.get('memory'),
            })
        return {'success': True, 'nodes': nodes, 'count': len(nodes)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def top_pods(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """Get CPU and memory usage per pod (requires metrics-server)."""
    try:
        from kubernetes import client as k8s_client
        _, _ = _get_k8s_client(context)
        custom_api = k8s_client.CustomObjectsApi()
        metrics = custom_api.list_namespaced_custom_object(
            group='metrics.k8s.io', version='v1beta1', plural='pods', namespace=namespace
        )
        pods = []
        for item in metrics.get('items', []):
            containers = [
                {'container': c['name'], 'cpu': c['usage'].get('cpu'), 'memory': c['usage'].get('memory')}
                for c in item.get('containers', [])
            ]
            pods.append({
                'pod': item['metadata']['name'],
                'namespace': item['metadata']['namespace'],
                'containers': containers,
            })
        return {'success': True, 'pods': pods, 'count': len(pods)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Jobs Extended ----

def list_jobs(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all Jobs in a namespace with their completion status."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        batch_v1 = k8s_client.BatchV1Api()
        response = batch_v1.list_namespaced_job(namespace=namespace)
        jobs = []
        for job in response.items:
            status = job.status
            jobs.append({
                'name': job.metadata.name,
                'namespace': job.metadata.namespace,
                'completions': job.spec.completions,
                'succeeded': status.succeeded or 0,
                'failed': status.failed or 0,
                'active': status.active or 0,
                'complete': bool(status.completion_time),
                'start_time': status.start_time.isoformat() if status.start_time else None,
                'completion_time': status.completion_time.isoformat() if status.completion_time else None,
            })
        return {'success': True, 'jobs': jobs, 'count': len(jobs)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- CronJobs ----

def create_cronjob(
    name: str,
    schedule: str,
    image: str,
    command: Optional[List[str]] = None,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a CronJob to run a container on a schedule."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        batch_v1 = k8s_client.BatchV1Api()
        container = k8s_client.V1Container(name=name, image=image, command=command)
        pod_spec = k8s_client.V1PodSpec(containers=[container], restart_policy='OnFailure')
        pod_template = k8s_client.V1PodTemplateSpec(
            metadata=k8s_client.V1ObjectMeta(name=name),
            spec=pod_spec
        )
        job_spec = k8s_client.V1JobSpec(template=pod_template)
        job_template = k8s_client.V1JobTemplateSpec(
            metadata=k8s_client.V1ObjectMeta(name=name),
            spec=job_spec
        )
        cron_spec = k8s_client.V1CronJobSpec(schedule=schedule, job_template=job_template)
        cronjob = k8s_client.V1CronJob(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=cron_spec
        )
        result = batch_v1.create_namespaced_cron_job(namespace=namespace, body=cronjob)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace, 'schedule': schedule,
            'message': f'CronJob {name} created with schedule {schedule}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_cronjobs(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all CronJobs in a namespace with their schedule and last run time."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        batch_v1 = k8s_client.BatchV1Api()
        response = batch_v1.list_namespaced_cron_job(namespace=namespace)
        cronjobs = []
        for cj in response.items:
            cronjobs.append({
                'name': cj.metadata.name,
                'namespace': cj.metadata.namespace,
                'schedule': cj.spec.schedule,
                'suspended': cj.spec.suspend or False,
                'active_jobs': len(cj.status.active or []),
                'last_schedule': cj.status.last_schedule_time.isoformat() if cj.status.last_schedule_time else None,
            })
        return {'success': True, 'cronjobs': cronjobs, 'count': len(cronjobs)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_cronjob(name: str, namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """Delete a CronJob."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        batch_v1 = k8s_client.BatchV1Api()
        batch_v1.delete_namespaced_cron_job(name=name, namespace=namespace)
        return {'success': True, 'name': name, 'namespace': namespace,
                'message': f'CronJob {name} deleted'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def suspend_cronjob(
    name: str,
    suspend: bool = True,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Suspend or resume a CronJob."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        batch_v1 = k8s_client.BatchV1Api()
        batch_v1.patch_namespaced_cron_job(
            name=name, namespace=namespace,
            body={'spec': {'suspend': suspend}}
        )
        action = 'suspended' if suspend else 'resumed'
        return {'success': True, 'name': name, 'namespace': namespace,
                'suspended': suspend, 'message': f'CronJob {name} {action}'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- HPA ----

def create_hpa(
    name: str,
    target_name: str,
    min_replicas: int,
    max_replicas: int,
    cpu_percent: int = 70,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Horizontal Pod Autoscaler based on CPU utilization."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        autoscaling_v2 = k8s_client.AutoscalingV2Api()
        metric = k8s_client.V2MetricSpec(
            type='Resource',
            resource=k8s_client.V2ResourceMetricSource(
                name='cpu',
                target=k8s_client.V2MetricTarget(type='Utilization', average_utilization=cpu_percent)
            )
        )
        hpa = k8s_client.V2HorizontalPodAutoscaler(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=k8s_client.V2HorizontalPodAutoscalerSpec(
                scale_target_ref=k8s_client.V2CrossVersionObjectReference(
                    api_version='apps/v1', kind='Deployment', name=target_name
                ),
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                metrics=[metric]
            )
        )
        result = autoscaling_v2.create_namespaced_horizontal_pod_autoscaler(namespace=namespace, body=hpa)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace, 'target': target_name,
            'min_replicas': min_replicas, 'max_replicas': max_replicas,
            'cpu_target_percent': cpu_percent,
            'message': f'HPA {name} created targeting {target_name}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_hpas(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all Horizontal Pod Autoscalers with current/desired replica counts."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        autoscaling_v2 = k8s_client.AutoscalingV2Api()
        response = autoscaling_v2.list_namespaced_horizontal_pod_autoscaler(namespace=namespace)
        hpas = []
        for hpa in response.items:
            hpas.append({
                'name': hpa.metadata.name,
                'namespace': hpa.metadata.namespace,
                'target': hpa.spec.scale_target_ref.name if hpa.spec else None,
                'min_replicas': hpa.spec.min_replicas if hpa.spec else None,
                'max_replicas': hpa.spec.max_replicas if hpa.spec else None,
                'current_replicas': hpa.status.current_replicas if hpa.status else None,
                'desired_replicas': hpa.status.desired_replicas if hpa.status else None,
            })
        return {'success': True, 'hpas': hpas, 'count': len(hpas)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_hpa(name: str, namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Horizontal Pod Autoscaler."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        autoscaling_v2 = k8s_client.AutoscalingV2Api()
        autoscaling_v2.delete_namespaced_horizontal_pod_autoscaler(name=name, namespace=namespace)
        return {'success': True, 'name': name, 'namespace': namespace,
                'message': f'HPA {name} deleted'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- PVs & PVCs ----

def list_pvs(context: Optional[str] = None) -> Dict[str, Any]:
    """List all PersistentVolumes in the cluster."""
    try:
        v1, _ = _get_k8s_client(context)
        response = v1.list_persistent_volume()
        pvs = []
        for pv in response.items:
            pvs.append({
                'name': pv.metadata.name,
                'capacity': pv.spec.capacity.get('storage') if pv.spec.capacity else None,
                'access_modes': pv.spec.access_modes,
                'reclaim_policy': pv.spec.persistent_volume_reclaim_policy,
                'storage_class': pv.spec.storage_class_name,
                'status': pv.status.phase if pv.status else None,
                'claim': f"{pv.spec.claim_ref.namespace}/{pv.spec.claim_ref.name}" if pv.spec.claim_ref else None,
            })
        return {'success': True, 'persistent_volumes': pvs, 'count': len(pvs)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_pvcs(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all PersistentVolumeClaims in a namespace."""
    try:
        v1, _ = _get_k8s_client(context)
        response = v1.list_namespaced_persistent_volume_claim(namespace=namespace)
        pvcs = []
        for pvc in response.items:
            pvcs.append({
                'name': pvc.metadata.name,
                'namespace': pvc.metadata.namespace,
                'status': pvc.status.phase if pvc.status else None,
                'capacity': pvc.status.capacity.get('storage') if pvc.status and pvc.status.capacity else None,
                'access_modes': pvc.spec.access_modes,
                'storage_class': pvc.spec.storage_class_name,
                'volume_name': pvc.spec.volume_name,
                'requested': pvc.spec.resources.requests.get('storage') if pvc.spec.resources and pvc.spec.resources.requests else None,
            })
        return {'success': True, 'persistent_volume_claims': pvcs, 'count': len(pvcs)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_pvc(
    name: str,
    storage: str,
    access_modes: Optional[List[str]] = None,
    storage_class: Optional[str] = None,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a PersistentVolumeClaim to request storage for a pod."""
    try:
        from kubernetes import client as k8s_client
        v1, _ = _get_k8s_client(context)
        pvc = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=access_modes or ['ReadWriteOnce'],
                resources=k8s_client.V1ResourceRequirements(requests={'storage': storage}),
                storage_class_name=storage_class,
            )
        )
        result = v1.create_namespaced_persistent_volume_claim(namespace=namespace, body=pvc)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace, 'storage': storage,
            'access_modes': access_modes or ['ReadWriteOnce'],
            'storage_class': storage_class,
            'message': f'PVC {name} created requesting {storage}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_pvc(name: str, namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """Delete a PersistentVolumeClaim."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespaced_persistent_volume_claim(name=name, namespace=namespace)
        return {'success': True, 'name': name, 'namespace': namespace,
                'message': f'PVC {name} deleted'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RBAC ----

def create_role(
    name: str,
    rules: List[Dict],
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a namespace-scoped RBAC Role.

    Rules format: [{"api_groups": [""], "resources": ["pods"], "verbs": ["get", "list"]}]
    """
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        rbac_v1 = k8s_client.RbacAuthorizationV1Api()
        policy_rules = [
            k8s_client.V1PolicyRule(
                api_groups=r.get('api_groups', ['']),
                resources=r['resources'],
                verbs=r['verbs']
            )
            for r in rules
        ]
        role = k8s_client.V1Role(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            rules=policy_rules
        )
        result = rbac_v1.create_namespaced_role(namespace=namespace, body=role)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace, 'rules_count': len(rules),
            'message': f'Role {name} created in namespace {namespace}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_role_binding(
    name: str,
    role_name: str,
    subjects: List[Dict],
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Bind a Role to users, groups, or ServiceAccounts.

    Subjects format: [{"kind": "ServiceAccount", "name": "mysa", "namespace": "default"}]
    """
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        rbac_v1 = k8s_client.RbacAuthorizationV1Api()
        k8s_subjects = [
            k8s_client.V1Subject(
                kind=s['kind'], name=s['name'],
                namespace=s.get('namespace', namespace)
            )
            for s in subjects
        ]
        binding = k8s_client.V1RoleBinding(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace),
            role_ref=k8s_client.V1RoleRef(api_group='rbac.authorization.k8s.io', kind='Role', name=role_name),
            subjects=k8s_subjects
        )
        result = rbac_v1.create_namespaced_role_binding(namespace=namespace, body=binding)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace, 'role': role_name,
            'subjects': [s['name'] for s in subjects],
            'message': f'RoleBinding {name} created binding role {role_name}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_roles(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all Roles and RoleBindings in a namespace."""
    try:
        from kubernetes import client as k8s_client
        _get_k8s_client(context)
        rbac_v1 = k8s_client.RbacAuthorizationV1Api()
        roles = rbac_v1.list_namespaced_role(namespace=namespace)
        bindings = rbac_v1.list_namespaced_role_binding(namespace=namespace)
        return {
            'success': True,
            'roles': [{'name': r.metadata.name, 'rules': len(r.rules or [])} for r in roles.items],
            'role_bindings': [
                {'name': b.metadata.name, 'role': b.role_ref.name,
                 'subjects': [s.name for s in (b.subjects or [])]}
                for b in bindings.items
            ],
            'roles_count': len(roles.items),
            'bindings_count': len(bindings.items),
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_service_account(
    name: str,
    namespace: str = 'default',
    labels: Optional[Dict[str, str]] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Create a ServiceAccount for pods to authenticate with the Kubernetes API."""
    try:
        from kubernetes import client as k8s_client
        v1, _ = _get_k8s_client(context)
        sa = k8s_client.V1ServiceAccount(
            metadata=k8s_client.V1ObjectMeta(name=name, namespace=namespace, labels=labels)
        )
        result = v1.create_namespaced_service_account(namespace=namespace, body=sa)
        return {
            'success': True, 'name': result.metadata.name,
            'namespace': namespace,
            'message': f'ServiceAccount {name} created in {namespace}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_service_accounts(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """List all ServiceAccounts in a namespace."""
    try:
        v1, _ = _get_k8s_client(context)
        response = v1.list_namespaced_service_account(namespace=namespace)
        sas = []
        for sa in response.items:
            sas.append({
                'name': sa.metadata.name,
                'namespace': sa.metadata.namespace,
                'secrets_count': len(sa.secrets or []),
                'labels': sa.metadata.labels or {},
            })
        return {'success': True, 'service_accounts': sas, 'count': len(sas)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_service_account(name: str, namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    """Delete a ServiceAccount."""
    try:
        v1, _ = _get_k8s_client(context)
        v1.delete_namespaced_service_account(name=name, namespace=namespace)
        return {'success': True, 'name': name, 'namespace': namespace,
                'message': f'ServiceAccount {name} deleted'}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Monitoring ----

def get_cluster_events(
    namespace: Optional[str] = None,
    event_type: Optional[str] = None,
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Get recent cluster events (warnings, errors, scheduling events)."""
    try:
        v1, _ = _get_k8s_client(context)
        if namespace:
            response = v1.list_namespaced_event(namespace=namespace)
        else:
            response = v1.list_event_for_all_namespaces()
        events = []
        for event in response.items:
            if event_type and event.type != event_type:
                continue
            events.append({
                'namespace': event.metadata.namespace,
                'name': event.metadata.name,
                'type': event.type,
                'reason': event.reason,
                'message': event.message,
                'object': f'{event.involved_object.kind}/{event.involved_object.name}',
                'count': event.count,
                'first_time': event.first_timestamp.isoformat() if event.first_timestamp else None,
                'last_time': event.last_timestamp.isoformat() if event.last_timestamp else None,
            })
        # Sort by last_time descending
        events.sort(key=lambda e: e['last_time'] or '', reverse=True)
        return {'success': True, 'events': events[:100], 'count': len(events)}
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Context & Cluster Management ----

def list_contexts(context: Optional[str] = None) -> Dict[str, Any]:
    """List all kubeconfig contexts."""
    try:
        from kubernetes import config as k8s_config
        contexts, active_context = k8s_config.list_kube_config_contexts()
        return {
            'success': True,
            'contexts': [{'name': c['name'], 'cluster': c['context'].get('cluster'), 'namespace': c['context'].get('namespace')} for c in contexts],
            'active_context': active_context['name'] if active_context else None,
            'count': len(contexts)
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_current_context(context: Optional[str] = None) -> Dict[str, Any]:
    """Get the currently active kubeconfig context."""
    try:
        from kubernetes import config as k8s_config
        contexts, active_context = k8s_config.list_kube_config_contexts()
        if not active_context:
            return {'success': False, 'error': 'No active context found'}
        return {
            'success': True,
            'current_context': active_context['name'],
            'cluster': active_context['context'].get('cluster'),
            'namespace': active_context['context'].get('namespace', 'default'),
            'user': active_context['context'].get('user'),
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def apply_manifest(
    manifest: Dict,
    namespace: str = 'default',
    context: Optional[str] = None
) -> Dict[str, Any]:
    """Apply (create) a Kubernetes resource manifest. Equivalent to kubectl create -f."""
    try:
        from kubernetes import client as k8s_client, utils as k8s_utils
        _get_k8s_client(context)
        api_client = k8s_client.ApiClient()
        kind = manifest.get('kind', 'Unknown')
        name = manifest.get('metadata', {}).get('name', 'unknown')
        # Inject namespace into metadata if not set
        if 'namespace' not in manifest.get('metadata', {}):
            manifest.setdefault('metadata', {})['namespace'] = namespace
        k8s_utils.create_from_dict(api_client, manifest, namespace=namespace)
        return {
            'success': True, 'kind': kind, 'name': name, 'namespace': namespace,
            'message': f'{kind}/{name} applied in namespace {namespace}'
        }
    except ApiException as e:
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_tools() -> List[Dict[str, Any]]:
    """
    Get Kubernetes tool definitions.

    Returns:
        List of tool definitions
    """
    return [
        {
            'name': 'get_pods',
            'description': 'List pods in a Kubernetes namespace with optional label filtering',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'labels': {
                        'type': 'string',
                        'description': 'Label selector (e.g., app=nginx)'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                }
            },
            'handler': get_pods
        },
        {
            'name': 'get_pod_logs',
            'description': 'Get logs from a Kubernetes pod',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pod_name': {
                        'type': 'string',
                        'description': 'Name of the pod'
                    },
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'container': {
                        'type': 'string',
                        'description': 'Container name (for multi-container pods)'
                    },
                    'tail_lines': {
                        'type': 'integer',
                        'description': 'Number of lines to retrieve (default: 100)',
                        'default': 100
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                },
                'required': ['pod_name']
            },
            'handler': get_pod_logs
        },
        {
            'name': 'describe_pod',
            'description': 'Get detailed information about a specific pod including events',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pod_name': {
                        'type': 'string',
                        'description': 'Name of the pod'
                    },
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                },
                'required': ['pod_name']
            },
            'handler': describe_pod
        },
        {
            'name': 'get_deployments',
            'description': 'List deployments in a Kubernetes namespace',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                }
            },
            'handler': get_deployments
        },
        {
            'name': 'scale_deployment',
            'description': 'Scale a Kubernetes deployment to specified number of replicas',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {
                        'type': 'string',
                        'description': 'Name of the deployment'
                    },
                    'replicas': {
                        'type': 'integer',
                        'description': 'Number of replicas'
                    },
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                },
                'required': ['deployment_name', 'replicas']
            },
            'handler': scale_deployment
        },
        {
            'name': 'restart_deployment',
            'description': 'Restart a Kubernetes deployment by triggering a rollout',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {
                        'type': 'string',
                        'description': 'Name of the deployment'
                    },
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                },
                'required': ['deployment_name']
            },
            'handler': restart_deployment
        },
        {
            'name': 'get_services',
            'description': 'List Kubernetes services in a namespace',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {
                        'type': 'string',
                        'description': 'Kubernetes namespace (default: default)',
                        'default': 'default'
                    },
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                }
            },
            'handler': get_services
        },
        {
            'name': 'get_nodes',
            'description': 'List Kubernetes cluster nodes with capacity and status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {
                        'type': 'string',
                        'description': 'Kubernetes context to use'
                    }
                }
            },
            'handler': get_nodes
        },
        # ---- Pod Operations ----
        {
            'name': 'delete_pod',
            'description': 'Delete a Kubernetes pod (force terminate a misbehaving or stuck pod).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pod_name': {'type': 'string', 'description': 'Name of the pod to delete'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'grace_period': {'type': 'integer', 'description': 'Grace period in seconds (0 for immediate)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['pod_name']
            },
            'handler': delete_pod
        },
        {
            'name': 'exec_pod_command',
            'description': 'Execute a command inside a running pod (like kubectl exec).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pod_name': {'type': 'string', 'description': 'Name of the pod'},
                    'command': {'type': 'string', 'description': 'Command to execute (e.g., "ls -la /app")'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'container': {'type': 'string', 'description': 'Container name (for multi-container pods)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['pod_name', 'command']
            },
            'handler': exec_pod_command
        },
        # ---- Deployment Lifecycle ----
        {
            'name': 'create_deployment',
            'description': 'Create a Kubernetes deployment with specified image, replicas, ports, env vars, and resource limits.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Deployment name'},
                    'image': {'type': 'string', 'description': 'Container image (e.g., "nginx:latest", "myapp:v1.2")'},
                    'replicas': {'type': 'integer', 'description': 'Number of replicas (default: 1)', 'default': 1},
                    'port': {'type': 'integer', 'description': 'Container port to expose'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'labels': {'type': 'object', 'description': 'Labels as key-value pairs'},
                    'env_vars': {'type': 'object', 'description': 'Environment variables as key-value pairs'},
                    'cpu_request': {'type': 'string', 'description': 'CPU request (e.g., "100m", "0.5")'},
                    'memory_request': {'type': 'string', 'description': 'Memory request (e.g., "128Mi", "1Gi")'},
                    'cpu_limit': {'type': 'string', 'description': 'CPU limit (e.g., "500m", "1")'},
                    'memory_limit': {'type': 'string', 'description': 'Memory limit (e.g., "256Mi", "2Gi")'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'image']
            },
            'handler': create_deployment
        },
        {
            'name': 'update_deployment_image',
            'description': 'Update a deployment container image (triggers rolling update).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'image': {'type': 'string', 'description': 'New container image (e.g., "myapp:v2.0")'},
                    'container_name': {'type': 'string', 'description': 'Container name (defaults to first container)'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name', 'image']
            },
            'handler': update_deployment_image
        },
        {
            'name': 'delete_deployment',
            'description': 'Delete a Kubernetes deployment and its pods.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': delete_deployment
        },
        # ---- Service Management ----
        {
            'name': 'create_service',
            'description': 'Create a Kubernetes service (ClusterIP, NodePort, or LoadBalancer) to expose a deployment.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Service name'},
                    'port': {'type': 'integer', 'description': 'Service port'},
                    'target_port': {'type': 'integer', 'description': 'Target port on pods (defaults to port)'},
                    'service_type': {'type': 'string', 'enum': ['ClusterIP', 'NodePort', 'LoadBalancer'], 'description': 'Service type', 'default': 'ClusterIP'},
                    'selector': {'type': 'object', 'description': 'Pod selector labels (defaults to {app: name})'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'protocol': {'type': 'string', 'enum': ['TCP', 'UDP'], 'default': 'TCP'},
                    'node_port': {'type': 'integer', 'description': 'Node port (only for NodePort type, 30000-32767)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'port']
            },
            'handler': create_service
        },
        {
            'name': 'delete_service',
            'description': 'Delete a Kubernetes service.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service_name': {'type': 'string', 'description': 'Service name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['service_name']
            },
            'handler': delete_service
        },
        {
            'name': 'get_namespaces',
            'description': 'List all Kubernetes namespaces in the cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': get_namespaces
        },
        # ---- Namespace Management ----
        {
            'name': 'create_namespace',
            'description': 'Create a Kubernetes namespace for workload isolation.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Namespace name'},
                    'labels': {'type': 'object', 'description': 'Labels as key-value pairs'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': create_namespace
        },
        {
            'name': 'delete_namespace',
            'description': 'Delete a Kubernetes namespace and ALL resources within it. This is destructive.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Namespace name'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_namespace
        },
        # ---- ConfigMap & Secret ----
        {
            'name': 'create_configmap',
            'description': 'Create a Kubernetes ConfigMap for storing application configuration data.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ConfigMap name'},
                    'data': {'type': 'object', 'description': 'Key-value pairs of configuration data'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'data']
            },
            'handler': create_configmap
        },
        {
            'name': 'delete_configmap',
            'description': 'Delete a Kubernetes ConfigMap.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ConfigMap name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_configmap
        },
        {
            'name': 'create_k8s_secret',
            'description': 'Create a Kubernetes Secret. Values are automatically base64-encoded.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Secret name'},
                    'data': {'type': 'object', 'description': 'Key-value pairs (values will be base64-encoded)'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'secret_type': {'type': 'string', 'description': 'Secret type (default: Opaque)', 'default': 'Opaque'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'data']
            },
            'handler': create_k8s_secret
        },
        {
            'name': 'delete_k8s_secret',
            'description': 'Delete a Kubernetes Secret.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Secret name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_k8s_secret
        },
        # ---- Ingress ----
        {
            'name': 'create_ingress',
            'description': 'Create a Kubernetes Ingress for HTTP routing to services.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Ingress name'},
                    'host': {'type': 'string', 'description': 'Hostname (e.g., "app.example.com")'},
                    'service_name': {'type': 'string', 'description': 'Backend service name'},
                    'service_port': {'type': 'integer', 'description': 'Backend service port'},
                    'path': {'type': 'string', 'description': 'URL path (default: "/")', 'default': '/'},
                    'path_type': {'type': 'string', 'enum': ['Prefix', 'Exact', 'ImplementationSpecific'], 'default': 'Prefix'},
                    'tls_secret': {'type': 'string', 'description': 'TLS secret name for HTTPS'},
                    'ingress_class': {'type': 'string', 'description': 'Ingress class (e.g., "nginx", "alb")'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'host', 'service_name', 'service_port']
            },
            'handler': create_ingress
        },
        {
            'name': 'delete_ingress',
            'description': 'Delete a Kubernetes Ingress.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'ingress_name': {'type': 'string', 'description': 'Ingress name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['ingress_name']
            },
            'handler': delete_ingress
        },
        # ---- Node Operations ----
        {
            'name': 'cordon_node',
            'description': 'Cordon a node (mark as unschedulable for maintenance). Existing pods continue running.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name']
            },
            'handler': cordon_node
        },
        {
            'name': 'uncordon_node',
            'description': 'Uncordon a node (mark as schedulable again after maintenance).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name']
            },
            'handler': uncordon_node
        },
        # ---- Job Operations ----
        {
            'name': 'create_job',
            'description': 'Create a Kubernetes Job for one-off or batch workloads.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Job name'},
                    'image': {'type': 'string', 'description': 'Container image'},
                    'command': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Command to run (e.g., ["python", "migrate.py"])'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'restart_policy': {'type': 'string', 'enum': ['Never', 'OnFailure'], 'default': 'Never'},
                    'backoff_limit': {'type': 'integer', 'description': 'Number of retries before marking failed (default: 3)', 'default': 3},
                    'ttl_seconds': {'type': 'integer', 'description': 'Auto-cleanup after completion (seconds)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'image']
            },
            'handler': create_job
        },
        {
            'name': 'delete_job',
            'description': 'Delete a Kubernetes Job and its associated pods.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'job_name': {'type': 'string', 'description': 'Job name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'propagation_policy': {'type': 'string', 'enum': ['Background', 'Foreground', 'Orphan'], 'default': 'Background'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['job_name']
            },
            'handler': delete_job
        },
        # ---- Pod Extended ----
        {
            'name': 'get_previous_container_logs',
            'description': 'Retrieve logs from a crashed or previously restarted container (like kubectl logs --previous).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'pod_name': {'type': 'string', 'description': 'Name of the pod'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'container': {'type': 'string', 'description': 'Container name (for multi-container pods)'},
                    'tail_lines': {'type': 'integer', 'description': 'Number of lines to retrieve (default: 100)', 'default': 100},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['pod_name']
            },
            'handler': get_previous_container_logs
        },
        # ---- Deployment Extended ----
        {
            'name': 'describe_deployment',
            'description': 'Get full details of a deployment including strategy, resource requests/limits, and rollout conditions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': describe_deployment
        },
        {
            'name': 'rollout_status',
            'description': 'Check the progress of an ongoing deployment rollout (like kubectl rollout status).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': rollout_status
        },
        {
            'name': 'rollout_history',
            'description': 'View previous deployment revisions with images and change causes (like kubectl rollout history).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': rollout_history
        },
        {
            'name': 'rollback_deployment',
            'description': 'Revert a deployment to a previous revision (like kubectl rollout undo).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'revision': {'type': 'integer', 'description': 'Revision number to roll back to (omit for previous revision)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': rollback_deployment
        },
        {
            'name': 'pause_rollout',
            'description': 'Pause an in-progress deployment rollout to safely make further changes.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': pause_rollout
        },
        {
            'name': 'resume_rollout',
            'description': 'Resume a paused deployment rollout.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'deployment_name': {'type': 'string', 'description': 'Deployment name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['deployment_name']
            },
            'handler': resume_rollout
        },
        # ---- StatefulSets ----
        {
            'name': 'list_statefulsets',
            'description': 'List all StatefulSets in a namespace with replica counts and service names.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_statefulsets
        },
        {
            'name': 'scale_statefulset',
            'description': 'Scale a StatefulSet to a desired number of replicas.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'StatefulSet name'},
                    'replicas': {'type': 'integer', 'description': 'Desired number of replicas'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'replicas']
            },
            'handler': scale_statefulset
        },
        {
            'name': 'delete_statefulset',
            'description': 'Delete a StatefulSet. Note: PVCs are NOT automatically deleted.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'StatefulSet name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_statefulset
        },
        # ---- ReplicaSets ----
        {
            'name': 'list_replicasets',
            'description': 'List ReplicaSets in a namespace with owner deployment references.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_replicasets
        },
        # ---- Service Extended ----
        {
            'name': 'describe_service',
            'description': 'Get detailed information about a Kubernetes service including endpoints and selectors.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service_name': {'type': 'string', 'description': 'Service name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['service_name']
            },
            'handler': describe_service
        },
        # ---- ConfigMap Extended ----
        {
            'name': 'list_configmaps',
            'description': 'List all ConfigMaps in a namespace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_configmaps
        },
        {
            'name': 'get_configmap',
            'description': 'Get the data contents of a specific ConfigMap.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ConfigMap name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': get_configmap
        },
        {
            'name': 'update_configmap',
            'description': 'Update or add keys in an existing ConfigMap (merges with existing data).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ConfigMap name'},
                    'data': {'type': 'object', 'description': 'Key-value pairs to update or add'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'data']
            },
            'handler': update_configmap
        },
        # ---- Secret Extended ----
        {
            'name': 'list_k8s_secrets',
            'description': 'List all Secrets in a namespace (shows names and types only, not values).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_k8s_secrets
        },
        {
            'name': 'update_k8s_secret',
            'description': 'Update or add keys in an existing Kubernetes Secret (values auto base64-encoded).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Secret name'},
                    'data': {'type': 'object', 'description': 'Key-value pairs to update (values will be base64-encoded)'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'data']
            },
            'handler': update_k8s_secret
        },
        # ---- Node Extended ----
        {
            'name': 'describe_node',
            'description': 'Get detailed node information including capacity, allocatable resources, conditions, and labels.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name']
            },
            'handler': describe_node
        },
        {
            'name': 'drain_node',
            'description': 'Drain a node by cordoning it and evicting all non-DaemonSet pods (for maintenance or decommissioning).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'ignore_daemonsets': {'type': 'boolean', 'description': 'Ignore DaemonSet-managed pods (default: true)', 'default': True},
                    'delete_emptydir_data': {'type': 'boolean', 'description': 'Delete pods using emptyDir volumes (default: false)', 'default': False},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name']
            },
            'handler': drain_node
        },
        {
            'name': 'taint_node',
            'description': 'Add a taint to a node to repel or tolerate certain pods (e.g., for dedicated workloads).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'key': {'type': 'string', 'description': 'Taint key (e.g., "dedicated")'},
                    'value': {'type': 'string', 'description': 'Taint value (e.g., "gpu")'},
                    'effect': {'type': 'string', 'enum': ['NoSchedule', 'PreferNoSchedule', 'NoExecute'], 'description': 'Taint effect', 'default': 'NoSchedule'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name', 'key']
            },
            'handler': taint_node
        },
        {
            'name': 'remove_node_taint',
            'description': 'Remove a taint from a node.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'key': {'type': 'string', 'description': 'Taint key to remove'},
                    'effect': {'type': 'string', 'enum': ['NoSchedule', 'PreferNoSchedule', 'NoExecute'], 'description': 'Taint effect to remove'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name', 'key']
            },
            'handler': remove_node_taint
        },
        {
            'name': 'label_node',
            'description': 'Add, update, or remove labels on a node (set value to empty string to remove).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'node_name': {'type': 'string', 'description': 'Node name'},
                    'labels': {'type': 'object', 'description': 'Labels to apply as key-value pairs (empty value removes the label)'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['node_name', 'labels']
            },
            'handler': label_node
        },
        {
            'name': 'top_nodes',
            'description': 'Get current CPU and memory usage for all cluster nodes (requires metrics-server).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': top_nodes
        },
        {
            'name': 'top_pods',
            'description': 'Get current CPU and memory usage for pods in a namespace (requires metrics-server).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': top_pods
        },
        # ---- Jobs Extended ----
        {
            'name': 'list_jobs',
            'description': 'List all Jobs in a namespace with status (active, succeeded, failed).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_jobs
        },
        # ---- CronJobs ----
        {
            'name': 'create_cronjob',
            'description': 'Create a Kubernetes CronJob to run scheduled workloads.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'CronJob name'},
                    'schedule': {'type': 'string', 'description': 'Cron schedule expression (e.g., "0 2 * * *" for 2am daily)'},
                    'image': {'type': 'string', 'description': 'Container image'},
                    'command': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Command to run'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'restart_policy': {'type': 'string', 'enum': ['Never', 'OnFailure'], 'default': 'Never'},
                    'concurrency_policy': {'type': 'string', 'enum': ['Allow', 'Forbid', 'Replace'], 'default': 'Allow'},
                    'suspend': {'type': 'boolean', 'description': 'Start in suspended state', 'default': False},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'schedule', 'image']
            },
            'handler': create_cronjob
        },
        {
            'name': 'list_cronjobs',
            'description': 'List all CronJobs in a namespace with schedule and last-run info.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_cronjobs
        },
        {
            'name': 'delete_cronjob',
            'description': 'Delete a CronJob and its associated Jobs.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'CronJob name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_cronjob
        },
        {
            'name': 'suspend_cronjob',
            'description': 'Suspend or resume a CronJob to temporarily pause scheduled executions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'CronJob name'},
                    'suspend': {'type': 'boolean', 'description': 'True to suspend, False to resume', 'default': True},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': suspend_cronjob
        },
        # ---- HPA ----
        {
            'name': 'create_hpa',
            'description': 'Create a HorizontalPodAutoscaler to automatically scale a deployment based on CPU/memory usage.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'HPA name'},
                    'target_deployment': {'type': 'string', 'description': 'Target deployment name to autoscale'},
                    'min_replicas': {'type': 'integer', 'description': 'Minimum replica count', 'default': 1},
                    'max_replicas': {'type': 'integer', 'description': 'Maximum replica count'},
                    'cpu_target_percent': {'type': 'integer', 'description': 'Target CPU utilization percentage (e.g., 70)'},
                    'memory_target_mi': {'type': 'integer', 'description': 'Target memory utilization in Mi (optional)'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'target_deployment', 'max_replicas']
            },
            'handler': create_hpa
        },
        {
            'name': 'list_hpas',
            'description': 'List all HorizontalPodAutoscalers in a namespace with current and desired replicas.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_hpas
        },
        {
            'name': 'delete_hpa',
            'description': 'Delete a HorizontalPodAutoscaler.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'HPA name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_hpa
        },
        # ---- PersistentVolumes / PVCs ----
        {
            'name': 'list_pvs',
            'description': 'List all PersistentVolumes in the cluster with capacity, access modes, and status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_pvs
        },
        {
            'name': 'list_pvcs',
            'description': 'List all PersistentVolumeClaims in a namespace with bound volume and storage class.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_pvcs
        },
        {
            'name': 'create_pvc',
            'description': 'Create a PersistentVolumeClaim to request storage for pods.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'PVC name'},
                    'storage': {'type': 'string', 'description': 'Storage size (e.g., "10Gi", "500Mi")'},
                    'access_modes': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Access modes (e.g., ["ReadWriteOnce"])', 'default': ['ReadWriteOnce']},
                    'storage_class': {'type': 'string', 'description': 'StorageClass name (omit for cluster default)'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'storage']
            },
            'handler': create_pvc
        },
        {
            'name': 'delete_pvc',
            'description': 'Delete a PersistentVolumeClaim. WARNING: may trigger PV deletion depending on reclaim policy.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'PVC name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_pvc
        },
        # ---- RBAC ----
        {
            'name': 'create_role',
            'description': 'Create a Kubernetes Role with specific permissions for resources in a namespace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Role name'},
                    'rules': {'type': 'array', 'description': 'List of policy rules [{apiGroups, resources, verbs}]', 'items': {'type': 'object'}},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'rules']
            },
            'handler': create_role
        },
        {
            'name': 'create_role_binding',
            'description': 'Bind a Role or ClusterRole to a user, group, or ServiceAccount within a namespace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'RoleBinding name'},
                    'role_name': {'type': 'string', 'description': 'Role or ClusterRole name to bind'},
                    'subjects': {'type': 'array', 'description': 'Subjects [{kind, name, namespace}] — kind is User, Group, or ServiceAccount', 'items': {'type': 'object'}},
                    'role_kind': {'type': 'string', 'enum': ['Role', 'ClusterRole'], 'description': 'Whether the role is a Role or ClusterRole', 'default': 'Role'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name', 'role_name', 'subjects']
            },
            'handler': create_role_binding
        },
        {
            'name': 'list_roles',
            'description': 'List all Roles in a namespace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_roles
        },
        {
            'name': 'create_service_account',
            'description': 'Create a Kubernetes ServiceAccount for pod identity and RBAC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ServiceAccount name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'annotations': {'type': 'object', 'description': 'Annotations (e.g., for IRSA: {"eks.amazonaws.com/role-arn": "arn:aws:iam::..."})'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': create_service_account
        },
        {
            'name': 'list_service_accounts',
            'description': 'List all ServiceAccounts in a namespace.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': list_service_accounts
        },
        {
            'name': 'delete_service_account',
            'description': 'Delete a Kubernetes ServiceAccount.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'ServiceAccount name'},
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['name']
            },
            'handler': delete_service_account
        },
        # ---- Cluster Monitoring ----
        {
            'name': 'get_cluster_events',
            'description': 'Get cluster events (warnings and normal) for a namespace to diagnose issues.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'namespace': {'type': 'string', 'description': 'Kubernetes namespace (omit for all namespaces)', 'default': 'default'},
                    'event_type': {'type': 'string', 'enum': ['Warning', 'Normal', 'all'], 'description': 'Filter by event type', 'default': 'all'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': get_cluster_events
        },
        # ---- Context / Manifest ----
        {
            'name': 'list_contexts',
            'description': 'List all available Kubernetes contexts from the kubeconfig file.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {'type': 'string', 'description': 'Kubernetes context to use for the request'}
                }
            },
            'handler': list_contexts
        },
        {
            'name': 'get_current_context',
            'description': 'Get the currently active Kubernetes context.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                }
            },
            'handler': get_current_context
        },
        {
            'name': 'apply_manifest',
            'description': 'Create a Kubernetes resource from a manifest dict. Equivalent to kubectl create -f. Returns an error if the resource already exists.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'manifest': {'type': 'object', 'description': 'Kubernetes manifest as a dictionary (parsed YAML/JSON)'},
                    'namespace': {'type': 'string', 'description': 'Namespace override (uses manifest namespace if set)', 'default': 'default'},
                    'context': {'type': 'string', 'description': 'Kubernetes context to use'}
                },
                'required': ['manifest']
            },
            'handler': apply_manifest
        }
    ]
