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
        }
    ]
