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
# Failure / debugging scenarios for practice
# ---------------------------------------------------------------------------

_FAILURE_SCENARIOS = {
    'pod_crashloop': {
        'title': 'Pod in CrashLoopBackOff',
        'description': 'A pod keeps crashing and restarting. The container starts, fails, and Kubernetes restarts it repeatedly. This is one of the most common Kubernetes problems you will debug.',
        'hint': 'Start by running: describe the failing pod, then check the pod logs. Look at the exit code and the last few log lines.',
        'tool': 'list_pods',
    },
    'security_group_blocked': {
        'title': 'Web Traffic Blocked by Security Group',
        'description': 'Users cannot reach your web application. The EC2 instance is running but HTTP/HTTPS traffic is not getting through. This is a classic networking issue.',
        'hint': 'List the security groups on the instance. Check the inbound rules — are ports 80 and 443 open to 0.0.0.0/0?',
        'tool': 'list_security_groups',
    },
    'high_cpu': {
        'title': 'EC2 Instance at 98% CPU',
        'description': 'Users are reporting the app is slow or timing out. The EC2 instance is running but performance is degraded. You need to investigate and decide whether to scale.',
        'hint': 'Describe the instance to see CPU utilization. Then check running processes. Consider scaling vertically (larger instance) or horizontally (more instances behind a load balancer).',
        'tool': 'describe_ec2_instance',
    },
    'disk_pressure': {
        'title': 'Kubernetes Node Disk Pressure',
        'description': 'Pods are being evicted from a node. The node is showing DiskPressure condition because disk usage is at 95%. This is a common production emergency.',
        'hint': 'List your nodes and look at their conditions. When DiskPressure is True, Kubernetes starts evicting pods. You need to free disk space or add capacity.',
        'tool': 'list_nodes',
    },
    'oom_killed': {
        'title': 'Pod OOMKilled — Out of Memory',
        'description': 'A pod keeps dying with exit code 137 and reason OOMKilled. The container is using more memory than its limit allows. The Linux kernel is killing it.',
        'hint': 'Describe the pod and look at the container memory limit vs usage. You either need to increase the memory limit or find and fix a memory leak in the application.',
        'tool': 'describe_pod',
    },
    'db_connection_refused': {
        'title': 'Database Connection Refused',
        'description': 'Your application logs show "connection refused" when trying to reach the RDS database. The database is running but the app cannot connect to it.',
        'hint': 'Check the database security group inbound rules. The app server security group ID must be explicitly allowed as a source on port 5432 (or 3306 for MySQL).',
        'tool': 'describe_rds_instance',
    },
    'image_pull_backoff': {
        'title': 'ImagePullBackOff — Container Image Not Found',
        'description': 'A new deployment is failing because Kubernetes cannot pull the container image. Pods are stuck in ImagePullBackOff or ErrImagePull status.',
        'hint': 'Check the pod events with describe. Look at the image name and tag — is it correct? Does the ECR repo exist? Does the node have permission to pull from that registry?',
        'tool': 'list_pods',
    },
}


def _failure_mock_pod_crashloop(ns: str = 'default') -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'pods': [
            {'name': 'web-app-7d8f9b6c4d-abc12', 'namespace': ns, 'status': 'CrashLoopBackOff',
             'ready': '0/1', 'restarts': 47, 'age': '2h', 'node': 'node-1',
             'last_state': 'terminated', 'exit_code': 1,
             'message': 'Back-off restarting failed container web-app in pod web-app-7d8f9b6c4d-abc12'},
            {'name': 'redis-0', 'namespace': ns, 'status': 'Running',
             'ready': '1/1', 'restarts': 0, 'age': '7d', 'node': 'node-1'},
        ],
        'count': 2,
        'sandbox_tip': 'Notice web-app has 47 restarts and status CrashLoopBackOff. Next step: check its logs with "get logs for web-app-7d8f9b6c4d-abc12"'
    }


def _failure_mock_security_group() -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'security_groups': [
            {
                'group_id': 'sg-0abc123', 'name': 'web-server-sg',
                'description': 'Security group for web tier',
                'inbound_rules': [
                    {'port': 22, 'protocol': 'tcp', 'source': '203.0.113.0/32', 'description': 'SSH from office IP'},
                ],
                'outbound_rules': [
                    {'port': -1, 'protocol': '-1', 'destination': '0.0.0.0/0', 'description': 'All outbound allowed'},
                ],
                'issue': 'PROBLEM FOUND: Port 80 (HTTP) and 443 (HTTPS) are missing from inbound rules. All web traffic is blocked!'
            }
        ],
        'count': 1,
        'sandbox_tip': 'The inbound rules only allow SSH (port 22). To fix this, you need to add rules for port 80 from 0.0.0.0/0 and port 443 from 0.0.0.0/0'
    }


def _failure_mock_high_cpu() -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'instance': {
            'instance_id': 'i-0abc123def456789', 'name': 'web-server-1', 'state': 'running',
            'type': 't3.medium', 'private_ip': '10.0.1.50', 'public_ip': '54.210.100.200',
            'cpu_utilization': 98.3,
            'cpu_credit_balance': 0,
            'status_check': 'Instance reachability check: PASSED | System reachability: PASSED',
            'network_in_mbps': 0.2, 'network_out_mbps': 0.1,
            'warning': 'CPU utilization is critically high at 98.3%. The instance has exhausted its CPU credits (t3 burstable instance). Users will experience slow response times.',
            'sandbox_tip': 'Options: (1) Stop the runaway process if you can identify it, (2) Scale vertically to a larger instance type like t3.large, (3) Scale horizontally by adding more instances behind a load balancer'
        }
    }


def _failure_mock_disk_pressure() -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'nodes': [
            {
                'name': 'node-1', 'status': 'Ready', 'roles': 'control-plane,worker',
                'conditions': [
                    {'type': 'DiskPressure', 'status': 'True', 'reason': 'KubeletHasDiskPressure',
                     'message': 'Disk usage on root filesystem is 95% (38GB of 40GB used)'},
                    {'type': 'MemoryPressure', 'status': 'False'},
                    {'type': 'PIDPressure', 'status': 'False'},
                    {'type': 'Ready', 'status': 'True'},
                ],
                'disk_usage_percent': 95,
                'warning': 'CRITICAL: Node is actively evicting pods due to disk pressure! Newly scheduled pods may fail.',
            },
            {
                'name': 'node-2', 'status': 'Ready', 'roles': 'worker',
                'conditions': [
                    {'type': 'DiskPressure', 'status': 'False'},
                    {'type': 'Ready', 'status': 'True'},
                ],
                'disk_usage_percent': 42,
            },
        ],
        'count': 2,
        'sandbox_tip': 'Node-1 is at 95% disk. Common causes: container logs filling up, old Docker images not cleaned, application writing too much data. Fix: docker system prune, journalctl --vacuum-size=1G, or expand the disk.'
    }


def _failure_mock_oom_killed() -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'pod': {
            'name': 'api-server-7d8f9b-xyz99', 'namespace': 'production',
            'phase': 'Running', 'restart_count': 23,
            'containers': [{
                'name': 'api-server',
                'state': 'waiting',
                'reason': 'CrashLoopBackOff',
                'last_state': 'terminated',
                'last_exit_code': 137,
                'last_reason': 'OOMKilled',
                'last_message': 'Container exceeded memory limit',
                'memory_limit': '256Mi',
                'memory_request': '128Mi',
                'last_memory_usage_before_kill': '255Mi',
            }],
            'events': [
                {'reason': 'OOMKilling', 'message': 'Memory limit reached. Container api-server (limit: 256Mi) killed by kernel OOM killer', 'count': 23},
            ],
            'sandbox_tip': 'Exit code 137 = killed by signal 9 (SIGKILL) from the OOM killer. The container hit its 256Mi limit. Either increase the limit in the Deployment manifest or find the memory leak (common cause: unbounded caches, connection pool leaks, loading too much data into memory at once).'
        }
    }


def _failure_mock_db_connection() -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'instance': {
            'db_instance_id': 'prod-postgres-db',
            'engine': 'postgres', 'engine_version': '15.4',
            'status': 'available',
            'endpoint': 'prod-postgres-db.abc123xyz.us-east-1.rds.amazonaws.com',
            'port': 5432,
            'vpc_security_groups': [
                {'group_id': 'sg-0db456789', 'name': 'rds-sg', 'status': 'active'}
            ],
            'rds_security_group_inbound_rules': [
                {'port': 5432, 'source_sg': 'sg-0oldwebsg99', 'description': 'Old web server sg — STALE'},
            ],
            'issue': 'PROBLEM FOUND: The database security group (sg-0db456789) only allows connections from sg-0oldwebsg99 (the old web server security group). Your current app servers use sg-0newwebsg12, which is NOT in the inbound rules. That is why connection is refused!',
            'sandbox_tip': 'Fix: Add an inbound rule to sg-0db456789 allowing port 5432 from source sg-0newwebsg12. Never open the database to 0.0.0.0/0 — always use security group references.'
        }
    }


def _failure_mock_image_pull(ns: str = 'default') -> Dict[str, Any]:
    return {
        'success': True, 'simulated': True, 'failure_scenario': True,
        'pods': [
            {'name': 'api-deploy-6c7b8d9f-abc12', 'namespace': ns, 'status': 'ImagePullBackOff',
             'ready': '0/1', 'restarts': 0, 'age': '5m', 'node': 'node-2',
             'container_image': '123456789012.dkr.ecr.us-east-1.amazonaws.com/my-api:v2.1.0',
             'image_pull_error': 'Failed to pull image: no basic auth credentials / repository does not exist or may require authorization',
             'events': [
                 {'reason': 'Failed', 'message': 'Error: ErrImagePull — repository 123456789012.dkr.ecr.us-east-1.amazonaws.com/my-api:v2.1.0 not found or unauthorized'},
                 {'reason': 'BackOff', 'message': 'Back-off pulling image'},
             ]},
            {'name': 'api-deploy-5b6a7c8e-xyz34', 'namespace': ns, 'status': 'Running',
             'ready': '1/1', 'restarts': 0, 'age': '3d', 'node': 'node-1',
             'container_image': '123456789012.dkr.ecr.us-east-1.amazonaws.com/my-api:v2.0.0'},
        ],
        'count': 2,
        'sandbox_tip': 'The old pod (v2.0.0) is still running while the new one (v2.1.0) fails. This means the image tag v2.1.0 does not exist in ECR, OR the node does not have permission to pull from ECR (missing the ecr:GetAuthorizationToken IAM permission on the node role).'
    }


_FAILURE_MOCK_FNS = {
    'pod_crashloop': _failure_mock_pod_crashloop,
    'security_group_blocked': _failure_mock_security_group,
    'high_cpu': _failure_mock_high_cpu,
    'disk_pressure': _failure_mock_disk_pressure,
    'oom_killed': _failure_mock_oom_killed,
    'db_connection_refused': _failure_mock_db_connection,
    'image_pull_backoff': _failure_mock_image_pull,
}


def get_failure_scenarios() -> list:
    """Return list of available debugging scenarios (metadata only, no mock data)."""
    return [
        {
            'id': scenario_id,
            'title': data['title'],
            'description': data['description'],
            'hint': data['hint'],
            'tool': data['tool'],
        }
        for scenario_id, data in _FAILURE_SCENARIOS.items()
    ]


def generate_failure_scenario(scenario_type: str = None) -> Dict[str, Any]:
    """
    Generate a realistic failure/debugging scenario for sandbox practice.

    Args:
        scenario_type: One of the scenario IDs, or None for a random scenario

    Returns:
        Dict with scenario metadata and the mock result
    """
    if scenario_type and scenario_type in _FAILURE_SCENARIOS:
        chosen_id = scenario_type
    else:
        chosen_id = random.choice(list(_FAILURE_SCENARIOS.keys()))

    scenario_meta = _FAILURE_SCENARIOS[chosen_id]
    mock_fn = _FAILURE_MOCK_FNS[chosen_id]
    result = mock_fn()

    return {
        'scenario_type': chosen_id,
        'title': scenario_meta['title'],
        'description': scenario_meta['description'],
        'hint': scenario_meta['hint'],
        'suggested_tool': scenario_meta['tool'],
        'result': result,
        'available_scenarios': list(_FAILURE_SCENARIOS.keys()),
    }


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
