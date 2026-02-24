"""
Learning Sandbox Service — generates realistic mock responses for tool calls
when sandbox mode is active. Allows learners to practice without touching
real cloud infrastructure.
"""
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any


def _rand_id(prefix: str = '', length: int = 17) -> str:
    return prefix + ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _rand_ip() -> str:
    return f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


def _rand_public_ip() -> str:
    return f"{random.randint(34,54)}.{random.randint(100,250)}.{random.randint(0,255)}.{random.randint(1,254)}"


def _recent_time(minutes_ago: int = 30) -> str:
    return (datetime.utcnow() - timedelta(minutes=random.randint(1, minutes_ago))).isoformat() + 'Z'


def _rand_arn(service: str, resource: str) -> str:
    return f"arn:aws:{service}:us-east-1:123456789012:{resource}/{_rand_id()}"


# ---------------------------------------------------------------------------
# AWS mock generators
# ---------------------------------------------------------------------------

def _mock_aws_list(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'ec2' in tool_name or 'instance' in tool_name:
        return {
            'success': True, 'simulated': True,
            'instances': [
                {'instance_id': 'i-' + _rand_id(length=17), 'name': 'web-server-1',
                 'state': 'running', 'type': 't3.medium', 'private_ip': _rand_ip(),
                 'public_ip': _rand_public_ip(), 'launch_time': _recent_time(1440)},
                {'instance_id': 'i-' + _rand_id(length=17), 'name': 'api-server-1',
                 'state': 'running', 'type': 't3.large', 'private_ip': _rand_ip(),
                 'public_ip': _rand_public_ip(), 'launch_time': _recent_time(2880)},
            ],
            'count': 2
        }
    if 's3' in tool_name or 'bucket' in tool_name:
        return {
            'success': True, 'simulated': True,
            'buckets': [
                {'name': 'my-app-assets', 'creation_date': _recent_time(10080), 'region': 'us-east-1'},
                {'name': 'my-app-logs', 'creation_date': _recent_time(10080), 'region': 'us-east-1'},
                {'name': 'backups-prod', 'creation_date': _recent_time(20160), 'region': 'us-west-2'},
            ],
            'count': 3
        }
    if 'security_group' in tool_name or 'sg' in tool_name:
        return {
            'success': True, 'simulated': True,
            'security_groups': [
                {'group_id': 'sg-' + _rand_id(length=8), 'name': 'web-sg', 'vpc_id': 'vpc-' + _rand_id(length=8),
                 'description': 'Web server security group', 'inbound_rules': 3, 'outbound_rules': 1},
                {'group_id': 'sg-' + _rand_id(length=8), 'name': 'db-sg', 'vpc_id': 'vpc-' + _rand_id(length=8),
                 'description': 'Database security group', 'inbound_rules': 1, 'outbound_rules': 1},
            ],
            'count': 2
        }
    if 'rds' in tool_name or 'database' in tool_name:
        return {
            'success': True, 'simulated': True,
            'instances': [
                {'db_instance_id': 'prod-db', 'engine': 'postgres', 'engine_version': '15.4',
                 'status': 'available', 'class': 'db.t3.medium', 'storage_gb': 100,
                 'endpoint': 'prod-db.abc123.us-east-1.rds.amazonaws.com'},
            ],
            'count': 1
        }
    if 'vpc' in tool_name:
        return {
            'success': True, 'simulated': True,
            'vpcs': [
                {'vpc_id': 'vpc-' + _rand_id(length=8), 'cidr': '10.0.0.0/16',
                 'state': 'available', 'is_default': False, 'name': 'production'},
            ],
            'count': 1
        }
    if 'lambda' in tool_name or 'function' in tool_name:
        return {
            'success': True, 'simulated': True,
            'functions': [
                {'name': 'process-orders', 'runtime': 'python3.12', 'memory': 256,
                 'timeout': 30, 'last_modified': _recent_time(1440)},
                {'name': 'send-notifications', 'runtime': 'nodejs20.x', 'memory': 128,
                 'timeout': 15, 'last_modified': _recent_time(4320)},
            ],
            'count': 2
        }
    # Generic AWS list
    return {
        'success': True, 'simulated': True,
        'resources': [
            {'id': _rand_id('res-', 12), 'name': 'resource-1', 'status': 'active'},
            {'id': _rand_id('res-', 12), 'name': 'resource-2', 'status': 'active'},
        ],
        'count': 2
    }


def _mock_aws_describe(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'ec2' in tool_name or 'instance' in tool_name:
        iid = tool_input.get('instance_id', 'i-' + _rand_id(length=17))
        return {
            'success': True, 'simulated': True,
            'instance': {
                'instance_id': iid, 'name': 'web-server-1', 'state': 'running',
                'type': 't3.medium', 'private_ip': _rand_ip(), 'public_ip': _rand_public_ip(),
                'vpc_id': 'vpc-' + _rand_id(length=8), 'subnet_id': 'subnet-' + _rand_id(length=8),
                'availability_zone': 'us-east-1a', 'launch_time': _recent_time(1440),
                'security_groups': [{'id': 'sg-' + _rand_id(length=8), 'name': 'web-sg'}],
                'tags': {'Name': 'web-server-1', 'Environment': 'production'},
                'monitoring': 'enabled', 'cpu_utilization': round(random.uniform(5, 65), 1),
            }
        }
    return {
        'success': True, 'simulated': True,
        'resource': {'id': tool_input.get('resource_id', _rand_id('res-', 12)),
                     'status': 'active', 'created': _recent_time(10080)}
    }


def _mock_aws_create(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'ec2' in tool_name or 'instance' in tool_name:
        iid = 'i-' + _rand_id(length=17)
        return {
            'success': True, 'simulated': True,
            'message': f'EC2 instance {iid} launched successfully',
            'instance_id': iid, 'state': 'pending',
            'private_ip': _rand_ip()
        }
    if 's3' in tool_name or 'bucket' in tool_name:
        name = tool_input.get('bucket_name', 'my-new-bucket')
        return {
            'success': True, 'simulated': True,
            'message': f'S3 bucket "{name}" created successfully',
            'bucket_name': name, 'region': tool_input.get('region', 'us-east-1')
        }
    if 'security_group' in tool_name or 'sg' in tool_name:
        sgid = 'sg-' + _rand_id(length=8)
        return {
            'success': True, 'simulated': True,
            'message': f'Security group {sgid} created',
            'group_id': sgid
        }
    return {
        'success': True, 'simulated': True,
        'message': f'Resource created successfully',
        'resource_id': _rand_id('res-', 12)
    }


# ---------------------------------------------------------------------------
# Kubernetes mock generators
# ---------------------------------------------------------------------------

def _mock_k8s(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    ns = tool_input.get('namespace', 'default')
    if 'list' in tool_name and 'pod' in tool_name:
        return {
            'success': True, 'simulated': True,
            'pods': [
                {'name': 'web-app-7d8f9b6c4d-abc12', 'namespace': ns, 'status': 'Running',
                 'ready': '1/1', 'restarts': 0, 'age': '3d', 'node': 'node-1'},
                {'name': 'web-app-7d8f9b6c4d-def34', 'namespace': ns, 'status': 'Running',
                 'ready': '1/1', 'restarts': 0, 'age': '3d', 'node': 'node-2'},
                {'name': 'redis-0', 'namespace': ns, 'status': 'Running',
                 'ready': '1/1', 'restarts': 1, 'age': '7d', 'node': 'node-1'},
            ],
            'count': 3
        }
    if 'list' in tool_name and 'deploy' in tool_name:
        return {
            'success': True, 'simulated': True,
            'deployments': [
                {'name': 'web-app', 'namespace': ns, 'ready': '2/2',
                 'up_to_date': 2, 'available': 2, 'age': '14d'},
            ],
            'count': 1
        }
    if 'list' in tool_name and 'service' in tool_name:
        return {
            'success': True, 'simulated': True,
            'services': [
                {'name': 'web-app', 'namespace': ns, 'type': 'ClusterIP',
                 'cluster_ip': '10.96.0.10', 'ports': '80/TCP', 'age': '14d'},
                {'name': 'redis', 'namespace': ns, 'type': 'ClusterIP',
                 'cluster_ip': '10.96.0.20', 'ports': '6379/TCP', 'age': '14d'},
            ],
            'count': 2
        }
    if 'list' in tool_name and 'namespace' in tool_name:
        return {
            'success': True, 'simulated': True,
            'namespaces': [
                {'name': 'default', 'status': 'Active', 'age': '30d'},
                {'name': 'kube-system', 'status': 'Active', 'age': '30d'},
                {'name': 'monitoring', 'status': 'Active', 'age': '14d'},
            ],
            'count': 3
        }
    if 'log' in tool_name:
        return {
            'success': True, 'simulated': True,
            'logs': '[SIM] 2024-01-15T10:30:00Z INFO  Server started on port 8080\n'
                    '[SIM] 2024-01-15T10:30:01Z INFO  Connected to database\n'
                    '[SIM] 2024-01-15T10:30:05Z INFO  Ready to accept connections\n'
        }
    if 'create' in tool_name:
        return {
            'success': True, 'simulated': True,
            'message': f'Resource created in namespace "{ns}"'
        }
    if 'delete' in tool_name:
        return {
            'success': True, 'simulated': True,
            'message': f'Resource deleted from namespace "{ns}"'
        }
    return {'success': True, 'simulated': True, 'message': 'Kubernetes operation completed'}


# ---------------------------------------------------------------------------
# Azure mock generators
# ---------------------------------------------------------------------------

def _mock_azure(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'list' in tool_name and 'vm' in tool_name:
        return {
            'success': True, 'simulated': True,
            'vms': [
                {'name': 'web-vm-1', 'resource_group': 'prod-rg', 'location': 'eastus',
                 'size': 'Standard_B2s', 'status': 'running', 'private_ip': _rand_ip()},
            ],
            'count': 1
        }
    if 'list' in tool_name and 'storage' in tool_name:
        return {
            'success': True, 'simulated': True,
            'accounts': [
                {'name': 'prodstorageacct', 'location': 'eastus', 'kind': 'StorageV2',
                 'sku': 'Standard_LRS', 'status': 'available'},
            ],
            'count': 1
        }
    if 'create' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Azure resource created successfully'}
    if 'delete' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Azure resource deleted successfully'}
    return {'success': True, 'simulated': True, 'message': 'Azure operation completed'}


# ---------------------------------------------------------------------------
# GCP mock generators
# ---------------------------------------------------------------------------

def _mock_gcp(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    project = tool_input.get('project_id', 'my-project-123')
    if 'list' in tool_name and ('instance' in tool_name or 'compute' in tool_name):
        return {
            'success': True, 'simulated': True,
            'instances': [
                {'name': 'web-server-1', 'zone': 'us-central1-a', 'machine_type': 'e2-medium',
                 'status': 'RUNNING', 'internal_ip': _rand_ip(), 'external_ip': _rand_public_ip()},
            ],
            'count': 1, 'project': project
        }
    if 'list' in tool_name and ('bucket' in tool_name or 'gcs' in tool_name):
        return {
            'success': True, 'simulated': True,
            'buckets': [
                {'name': f'{project}-assets', 'location': 'US', 'storage_class': 'STANDARD'},
            ],
            'count': 1
        }
    if 'create' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'GCP resource created successfully'}
    if 'delete' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'GCP resource deleted successfully'}
    return {'success': True, 'simulated': True, 'message': 'GCP operation completed'}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_mock_result(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a realistic simulated response for a tool call.

    Args:
        tool_name: The tool being called (e.g. 'list_ec2_instances')
        tool_input: The input parameters for the tool

    Returns:
        A dict mimicking the real tool's response with 'simulated': True
    """
    tn = tool_name.lower()

    # Categorize by cloud provider
    is_k8s = any(k in tn for k in ('k8s', 'kube', 'pod', 'deploy', 'namespace', 'node', 'ingress', 'job'))
    is_azure = 'azure' in tn or tn.startswith(('list_azure', 'create_azure', 'delete_azure',
                                                 'start_azure', 'stop_azure', 'restart_azure'))
    is_gcp = any(k in tn for k in ('gcp', 'gcloud', 'gke', 'gcs', 'cloud_run', 'cloud_sql',
                                     'bigquery', 'pubsub', 'cloud_function', 'cloud_log'))

    # Route to provider-specific mock
    if is_k8s:
        return _mock_k8s(tn, tool_input)
    if is_azure:
        return _mock_azure(tn, tool_input)
    if is_gcp:
        return _mock_gcp(tn, tool_input)

    # AWS / generic — categorize by operation type
    if tn.startswith('list_') or tn.startswith('get_') and 'list' in tn:
        return _mock_aws_list(tn, tool_input)
    if tn.startswith('describe_') or tn.startswith('get_'):
        return _mock_aws_describe(tn, tool_input)
    if tn.startswith('create_') or tn.startswith('launch_') or tn.startswith('run_'):
        return _mock_aws_create(tn, tool_input)
    if tn.startswith('delete_') or tn.startswith('terminate_') or tn.startswith('remove_'):
        resource = tool_input.get('instance_id') or tool_input.get('resource_id') or 'the resource'
        return {
            'success': True, 'simulated': True,
            'message': f'Successfully deleted/terminated {resource}'
        }
    if tn.startswith('stop_'):
        return {'success': True, 'simulated': True, 'message': 'Resource stopped successfully'}
    if tn.startswith('start_') or tn.startswith('restart_'):
        return {'success': True, 'simulated': True, 'message': 'Resource started successfully'}
    if tn.startswith('update_') or tn.startswith('modify_'):
        return {'success': True, 'simulated': True, 'message': 'Resource updated successfully'}

    # Fallback
    return {
        'success': True, 'simulated': True,
        'message': f'[Sandbox] Tool "{tool_name}" executed with simulated results'
    }
