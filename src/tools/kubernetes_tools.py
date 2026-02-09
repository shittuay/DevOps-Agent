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
        }
    ]
