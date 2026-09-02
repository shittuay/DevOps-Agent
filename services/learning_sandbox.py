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
        if 'list_s3_objects' in tool_name or 'object_version' in tool_name:
            bucket = tool_input.get('bucket_name', 'my-bucket')
            prefix = tool_input.get('prefix', '')
            return {
                'success': True, 'simulated': True, 'bucket_name': bucket,
                'objects': [
                    {'key': f'{prefix}app.log', 'size_bytes': 45231, 'last_modified': _recent_time(60), 'storage_class': 'STANDARD'},
                    {'key': f'{prefix}config.json', 'size_bytes': 1024, 'last_modified': _recent_time(1440), 'storage_class': 'STANDARD'},
                    {'key': f'{prefix}backup.tar.gz', 'size_bytes': 1073741824, 'last_modified': _recent_time(10080), 'storage_class': 'STANDARD_IA'},
                ],
                'count': 3, 'is_truncated': False
            }
        if 'get_s3_object_metadata' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': tool_input.get('bucket_name', 'my-bucket'),
                'key': tool_input.get('key', 'file.txt'),
                'content_type': 'application/json', 'content_length': 4096,
                'last_modified': _recent_time(1440), 'storage_class': 'STANDARD',
                'server_side_encryption': 'AES256', 'etag': 'abc123def456'
            }
        if 'download_s3_object' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': tool_input.get('bucket_name', 'my-bucket'),
                'key': tool_input.get('key', 'file.txt'),
                'content': '{"simulated": true, "message": "This is sandbox content"}',
                'content_type': 'application/json', 'content_length': 58,
                'last_modified': _recent_time(1440), 'truncated': False
            }
        if 'presigned' in tool_name:
            bucket = tool_input.get('bucket_name', 'my-bucket')
            key = tool_input.get('key', 'file.txt')
            expires = tool_input.get('expires_in', 3600)
            return {
                'success': True, 'simulated': True,
                'url': f'https://{bucket}.s3.amazonaws.com/{key}?X-Amz-Expires={expires}&X-Amz-Signature=simulated123',
                'expires_in_seconds': expires,
                'message': f'[Sandbox] Pre-signed URL generated for s3://{bucket}/{key}'
            }
        if 'get_s3_bucket_policy' in tool_name:
            bucket = tool_input.get('bucket_name', 'my-bucket')
            return {
                'success': True, 'simulated': True, 'bucket_name': bucket,
                'policy': {'Version': '2012-10-17', 'Statement': [{
                    'Effect': 'Deny', 'Principal': '*', 'Action': 's3:*',
                    'Resource': [f'arn:aws:s3:::{bucket}', f'arn:aws:s3:::{bucket}/*'],
                    'Condition': {'Bool': {'aws:SecureTransport': 'false'}}
                }]}
            }
        if 'get_s3_bucket_tags' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': tool_input.get('bucket_name', 'my-bucket'),
                'tags': {'Environment': 'production', 'Team': 'platform', 'CostCenter': 'engineering'},
                'count': 3
            }
        if 'get_s3_lifecycle' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': tool_input.get('bucket_name', 'my-bucket'),
                'rules': [{'ID': 'archive-old-logs', 'Status': 'Enabled', 'Filter': {'Prefix': 'logs/'},
                           'Transitions': [{'Days': 30, 'StorageClass': 'STANDARD_IA'}],
                           'Expiration': {'Days': 365}}],
                'rules_count': 1
            }
        if 'get_s3_replication' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': tool_input.get('bucket_name', 'my-bucket'),
                'role': 'arn:aws:iam::123456789012:role/s3-replication-role',
                'rules': [{'ID': 'replication-rule', 'Status': 'Enabled',
                           'Destination': {'Bucket': 'arn:aws:s3:::my-bucket-backup'}}],
                'rules_count': 1
            }
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
        if 'lifecycle' in tool_name:
            rules = tool_input.get('rules', [])
            return {
                'success': True, 'simulated': True,
                'bucket_name': name,
                'rules_applied': len(rules),
                'message': f'[Sandbox] Lifecycle policy applied to {name} with {len(rules)} rule(s)'
            }
        if 'replication' in tool_name:
            dest = tool_input.get('destination_bucket', 'my-backup-bucket')
            dest_region = tool_input.get('destination_region', 'eu-west-1')
            return {
                'success': True, 'simulated': True,
                'source_bucket': name,
                'destination_bucket': dest,
                'destination_region': dest_region,
                'message': f'[Sandbox] Cross-region replication configured: {name} → {dest} ({dest_region})'
            }
        if 'policy' in tool_name:
            return {
                'success': True, 'simulated': True,
                'bucket_name': name,
                'message': f'[Sandbox] Bucket policy applied to {name}'
            }
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
    if 'ami' in tool_name or 'image' in tool_name:
        image_id = 'ami-' + _rand_id(length=17)
        iid = tool_input.get('instance_id', 'i-xxxx')
        name = tool_input.get('name', 'my-ami')
        return {
            'success': True, 'simulated': True,
            'image_id': image_id,
            'instance_id': iid,
            'name': name,
            'message': f'AMI creation initiated: {image_id} from {iid} (state: pending)'
        }
    if 'snapshot' in tool_name:
        snap_id = 'snap-' + _rand_id(length=17)
        return {
            'success': True, 'simulated': True,
            'snapshot_id': snap_id,
            'source_snapshot_id': tool_input.get('snapshot_id', 'snap-src'),
            'destination_region': tool_input.get('destination_region', 'eu-west-1'),
            'message': f'Snapshot copy initiated as {snap_id}'
        }
    if 'cloudwatch_alarm' in tool_name or 'alarm' in tool_name:
        name = tool_input.get('alarm_name', 'my-alarm')
        metric = tool_input.get('metric_name', 'CPUUtilization')
        threshold = tool_input.get('threshold', 80)
        return {
            'success': True, 'simulated': True,
            'alarm_name': name,
            'metric': metric,
            'threshold': threshold,
            'message': f'[Sandbox] CloudWatch alarm "{name}" created on {metric} > {threshold}'
        }
    if 'scaling_policy' in tool_name:
        asg = tool_input.get('asg_name', 'my-asg')
        policy = tool_input.get('policy_name', 'scale-out-policy')
        return {
            'success': True, 'simulated': True,
            'policy_arn': f'arn:aws:autoscaling:us-east-1:123456789012:scalingPolicy:abc123:autoScalingGroupName/{asg}:policyName/{policy}',
            'asg_name': asg,
            'policy_name': policy,
            'message': f'[Sandbox] Scaling policy "{policy}" created for {asg}'
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
    name = tool_input.get('name') or tool_input.get('deployment_name') or tool_input.get('node_name', 'sim-resource')
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
    # --- Deployment extended ---
    if tool_name in ('describe_deployment', 'rollout_status'):
        return {
            'success': True, 'simulated': True,
            'name': name, 'namespace': ns,
            'replicas': 2, 'ready_replicas': 2, 'available_replicas': 2, 'updated_replicas': 2,
            'rollout_complete': True,
            'strategy': 'RollingUpdate',
            'containers': [{'name': 'app', 'image': 'myapp:v1.2.3'}],
            'conditions': [{'type': 'Available', 'status': 'True', 'reason': 'MinimumReplicasAvailable'}],
            'message': f'deployment "{name}" successfully rolled out'
        }
    if tool_name == 'rollout_history':
        return {
            'success': True, 'simulated': True,
            'deployment_name': name, 'namespace': ns,
            'revisions': [
                {'revision': 1, 'change_cause': '<none>', 'images': ['myapp:v1.1.0'], 'replicaset': f'{name}-abc123'},
                {'revision': 2, 'change_cause': '<none>', 'images': ['myapp:v1.2.3'], 'replicaset': f'{name}-def456'},
            ],
            'revision_count': 2
        }
    if tool_name == 'rollback_deployment':
        return {
            'success': True, 'simulated': True,
            'deployment_name': name, 'namespace': ns,
            'rolled_back_to_replicaset': f'{name}-abc123',
            'images': ['myapp:v1.1.0'],
            'message': f'Deployment {name} rolled back'
        }
    if tool_name in ('pause_rollout', 'resume_rollout'):
        paused = 'pause' in tool_name
        return {'success': True, 'simulated': True, 'deployment_name': name,
                'namespace': ns, 'paused': paused,
                'message': f'Deployment {name} rollout {"paused" if paused else "resumed"}'}
    # --- StatefulSets ---
    if 'statefulset' in tool_name and 'list' in tool_name:
        return {
            'success': True, 'simulated': True,
            'statefulsets': [
                {'name': 'postgres', 'namespace': ns, 'replicas': 3,
                 'ready_replicas': 3, 'service_name': 'postgres-headless', 'labels': {'app': 'postgres'}},
            ],
            'count': 1
        }
    if 'statefulset' in tool_name and 'scale' in tool_name:
        return {'success': True, 'simulated': True, 'name': name, 'namespace': ns,
                'replicas': tool_input.get('replicas', 1),
                'message': f'StatefulSet {name} scaled to {tool_input.get("replicas", 1)} replicas'}
    # --- ReplicaSets ---
    if 'replicaset' in tool_name:
        return {
            'success': True, 'simulated': True,
            'replicasets': [
                {'name': 'web-app-def456', 'namespace': ns, 'desired': 2, 'ready': 2,
                 'owner': 'web-app', 'revision': '2'},
                {'name': 'web-app-abc123', 'namespace': ns, 'desired': 0, 'ready': 0,
                 'owner': 'web-app', 'revision': '1'},
            ],
            'count': 2
        }
    # --- Service describe ---
    if tool_name == 'describe_service':
        return {
            'success': True, 'simulated': True,
            'name': tool_input.get('service_name', 'web-app'), 'namespace': ns,
            'type': 'ClusterIP', 'cluster_ip': '10.96.0.10',
            'ports': [{'port': 80, 'target_port': 8080, 'protocol': 'TCP'}],
            'selector': {'app': 'web-app'},
            'endpoints': ['10.244.0.5:8080', '10.244.0.6:8080']
        }
    # --- ConfigMaps ---
    if 'configmap' in tool_name and 'list' in tool_name:
        return {
            'success': True, 'simulated': True,
            'configmaps': [
                {'name': 'app-config', 'namespace': ns, 'data_keys': ['DB_HOST', 'LOG_LEVEL'], 'age': '7d'},
                {'name': 'kube-root-ca.crt', 'namespace': ns, 'data_keys': ['ca.crt'], 'age': '30d'},
            ],
            'count': 2
        }
    if tool_name == 'get_configmap':
        return {
            'success': True, 'simulated': True,
            'name': tool_input.get('name', 'app-config'), 'namespace': ns,
            'data': {'DB_HOST': 'postgres.default.svc.cluster.local', 'LOG_LEVEL': 'info', 'PORT': '8080'}
        }
    # --- Secrets ---
    if 'secret' in tool_name and 'list' in tool_name:
        return {
            'success': True, 'simulated': True,
            'secrets': [
                {'name': 'db-credentials', 'namespace': ns, 'type': 'Opaque', 'keys': ['username', 'password']},
                {'name': 'tls-cert', 'namespace': ns, 'type': 'kubernetes.io/tls', 'keys': ['tls.crt', 'tls.key']},
            ],
            'count': 2
        }
    # --- Nodes ---
    if tool_name == 'describe_node':
        return {
            'success': True, 'simulated': True,
            'name': tool_input.get('node_name', 'node-1'),
            'capacity': {'cpu': '4', 'memory': '8Gi', 'pods': '110'},
            'allocatable': {'cpu': '3800m', 'memory': '7.5Gi', 'pods': '110'},
            'conditions': [{'type': 'Ready', 'status': 'True'}],
            'labels': {'kubernetes.io/os': 'linux', 'node.kubernetes.io/instance-type': 't3.medium'},
            'taints': []
        }
    if tool_name in ('taint_node', 'remove_node_taint', 'label_node'):
        return {'success': True, 'simulated': True,
                'node_name': tool_input.get('node_name', 'node-1'),
                'message': f'[Sandbox] {tool_name} completed'}
    if tool_name == 'top_nodes':
        return {
            'success': True, 'simulated': True,
            'nodes': [
                {'name': 'node-1', 'cpu': '450m', 'cpu_percent': '11%', 'memory': '1.8Gi', 'memory_percent': '22%'},
                {'name': 'node-2', 'cpu': '380m', 'cpu_percent': '9%', 'memory': '2.1Gi', 'memory_percent': '26%'},
            ]
        }
    if tool_name == 'top_pods':
        return {
            'success': True, 'simulated': True,
            'pods': [
                {'name': 'web-app-7d8f9b6c4d-abc12', 'namespace': ns, 'cpu': '12m', 'memory': '128Mi'},
                {'name': 'web-app-7d8f9b6c4d-def34', 'namespace': ns, 'cpu': '9m', 'memory': '115Mi'},
                {'name': 'redis-0', 'namespace': ns, 'cpu': '5m', 'memory': '64Mi'},
            ]
        }
    # --- Jobs ---
    if 'list' in tool_name and 'job' in tool_name and 'cron' not in tool_name:
        return {
            'success': True, 'simulated': True,
            'jobs': [
                {'name': 'db-migrate-20240115', 'namespace': ns, 'active': 0, 'succeeded': 1, 'failed': 0, 'age': '2d'},
            ],
            'count': 1
        }
    # --- CronJobs ---
    if 'list' in tool_name and 'cronjob' in tool_name:
        return {
            'success': True, 'simulated': True,
            'cronjobs': [
                {'name': 'cleanup-job', 'namespace': ns, 'schedule': '0 2 * * *',
                 'suspended': False, 'active': 0, 'last_schedule': '2024-01-15T02:00:00Z'},
            ],
            'count': 1
        }
    if tool_name == 'suspend_cronjob':
        return {'success': True, 'simulated': True, 'name': tool_input.get('name', 'cronjob'),
                'namespace': ns, 'suspended': tool_input.get('suspend', True),
                'message': f'[Sandbox] CronJob {"suspended" if tool_input.get("suspend", True) else "resumed"}'}
    # --- HPA ---
    if 'list' in tool_name and '_hpa' in tool_name:
        return {
            'success': True, 'simulated': True,
            'hpas': [
                {'name': 'web-app-hpa', 'namespace': ns, 'target': 'web-app',
                 'min_replicas': 2, 'max_replicas': 10, 'current_replicas': 2,
                 'desired_replicas': 2, 'cpu_percent': '35%'},
            ],
            'count': 1
        }
    # --- PVs/PVCs ---
    if tool_name == 'list_pvs':
        return {
            'success': True, 'simulated': True,
            'pvs': [
                {'name': 'pv-postgres-0', 'capacity': '20Gi', 'access_modes': ['ReadWriteOnce'],
                 'reclaim_policy': 'Retain', 'status': 'Bound', 'claim': 'default/postgres-data-0'},
            ],
            'count': 1
        }
    if tool_name == 'list_pvcs':
        return {
            'success': True, 'simulated': True,
            'pvcs': [
                {'name': 'postgres-data-0', 'namespace': ns, 'status': 'Bound',
                 'volume': 'pv-postgres-0', 'capacity': '20Gi', 'storage_class': 'gp2'},
            ],
            'count': 1
        }
    # --- RBAC ---
    if tool_name == 'list_roles':
        return {
            'success': True, 'simulated': True,
            'roles': [
                {'name': 'pod-reader', 'namespace': ns, 'age': '5d'},
                {'name': 'deployment-manager', 'namespace': ns, 'age': '5d'},
            ],
            'count': 2
        }
    if 'service_account' in tool_name and 'list' in tool_name:
        return {
            'success': True, 'simulated': True,
            'service_accounts': [
                {'name': 'default', 'namespace': ns, 'age': '30d'},
                {'name': 'app-sa', 'namespace': ns, 'age': '5d', 'annotations': {}},
            ],
            'count': 2
        }
    # --- Cluster events ---
    if 'cluster_event' in tool_name:
        return {
            'success': True, 'simulated': True,
            'events': [
                {'type': 'Normal', 'reason': 'Scheduled', 'object': 'pod/web-app-abc12',
                 'message': 'Successfully assigned pod to node-1', 'age': '3d'},
                {'type': 'Warning', 'reason': 'BackOff', 'object': 'pod/redis-0',
                 'message': 'Back-off restarting failed container', 'age': '1h'},
            ],
            'count': 2
        }
    # --- Context ---
    if tool_name == 'list_contexts':
        return {
            'success': True, 'simulated': True,
            'contexts': [
                {'name': 'prod-cluster', 'cluster': 'prod-cluster', 'user': 'admin', 'current': False},
                {'name': 'staging-cluster', 'cluster': 'staging-cluster', 'user': 'admin', 'current': True},
            ],
            'count': 2
        }
    if tool_name == 'get_current_context':
        return {'success': True, 'simulated': True, 'current_context': 'staging-cluster'}
    if tool_name == 'apply_manifest':
        return {'success': True, 'simulated': True,
                'message': '[Sandbox] Manifest applied successfully',
                'kind': tool_input.get('manifest', {}).get('kind', 'Unknown')}
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
# ---------------------------------------------------------------------------
# Git mock generators
# ---------------------------------------------------------------------------

def _mock_git(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for git tools."""
    tn = tool_name.lower()
    repo_path = tool_input.get('repo_path', '/mock/repo')

    if 'clone' in tn:
        return {
            'success': True, 'simulated': True,
            'repo_path': tool_input.get('dest_path', '/mock/cloned-repo'),
            'message': f'[Sandbox] Cloned {tool_input.get("url", "https://github.com/example/repo.git")}'
        }
    if 'stash_list' in tn:
        return {
            'success': True, 'simulated': True,
            'stashes': [
                {'index': 0, 'description': 'stash@{0}: WIP on main: abc1234 Fix login'},
                {'index': 1, 'description': 'stash@{1}: On feature: def5678 Add tests'},
            ],
            'count': 2
        }
    if 'list_tags' in tn:
        return {
            'success': True, 'simulated': True,
            'tags': [
                {'name': 'v1.2.0', 'commit': 'abc1234', 'date': _recent_time(1440)},
                {'name': 'v1.1.0', 'commit': 'def5678', 'date': _recent_time(10080)},
                {'name': 'v1.0.0', 'commit': 'ghi9012', 'date': _recent_time(20160)},
            ],
            'count': 3
        }
    if 'list_remotes' in tn:
        return {
            'success': True, 'simulated': True,
            'remotes': [{'name': 'origin', 'urls': ['https://github.com/example/repo.git']}],
            'count': 1
        }
    if 'blame' in tn:
        return {
            'success': True, 'simulated': True,
            'file_path': tool_input.get('file_path', 'main.py'),
            'blame': 'abc1234 (Dev User 2026-04-01 10:00:00 +0000 1) import os\ndef5678 (Dev User 2026-04-02 11:00:00 +0000 2) import sys',
            'lines': 2
        }
    if 'reflog' in tn:
        return {
            'success': True, 'simulated': True,
            'entries': [
                'abc1234 HEAD@{0}: commit: Fix login bug',
                'def5678 HEAD@{1}: checkout: moving from feature to main',
                'ghi9012 HEAD@{2}: commit: Add user model',
            ],
            'count': 3
        }
    if 'shortlog' in tn:
        return {
            'success': True, 'simulated': True,
            'authors': [
                {'commits': 42, 'name': 'Dev User', 'email': 'dev@example.com'},
                {'commits': 15, 'name': 'Other Dev', 'email': 'other@example.com'},
            ],
            'count': 2
        }
    if 'log_file' in tn or 'search_commits' in tn:
        return {
            'success': True, 'simulated': True,
            'commits': [
                {'sha': 'abc1234', 'author': 'Dev User', 'date': _recent_time(60), 'message': 'Fix login bug'},
                {'sha': 'def5678', 'author': 'Dev User', 'date': _recent_time(1440), 'message': 'Add user model'},
            ],
            'count': 2
        }
    if 'grep' in tn:
        return {
            'success': True, 'simulated': True,
            'pattern': tool_input.get('pattern', ''),
            'results': 'app.py:10:# matching line\nutils.py:25:# another match',
            'lines': 2
        }
    if 'count_objects' in tn:
        return {
            'success': True, 'simulated': True,
            'stats': {'count': 1250, 'size': '4.80 MiB', 'in-pack': 1200, 'packs': 3, 'size-pack': '3.20 MiB'}
        }
    if 'show_file' in tn:
        return {
            'success': True, 'simulated': True,
            'content': '# Simulated file content at commit\nimport os\n',
            'lines': 2
        }
    if 'show_commit' in tn:
        sha = tool_input.get('commit_sha', 'abc1234')
        return {
            'success': True, 'simulated': True,
            'commit': {
                'sha': sha, 'author': 'Dev User', 'date': _recent_time(60),
                'message': 'Fix critical bug', 'files_changed': ['app.py', 'utils.py'],
                'stats': {'insertions': 15, 'deletions': 3, 'files': 2}
            }
        }
    if 'diff_stat' in tn or 'diff' in tn:
        return {
            'success': True, 'simulated': True,
            'stat': ' app.py | 10 +++++-----\n utils.py | 3 ++-\n 2 files changed, 8 insertions(+), 5 deletions(-)',
            'lines': 3
        }
    # Write operations: commit, push, pull, merge, rebase, cherry_pick, etc.
    for keyword in ('commit', 'push', 'pull', 'merge', 'rebase', 'cherry_pick', 'revert',
                     'amend', 'fetch', 'reset', 'clean', 'switch', 'create', 'delete',
                     'rename', 'add_files', 'add_remote', 'init', 'stash', 'tag'):
        if keyword in tn:
            return {
                'success': True, 'simulated': True,
                'message': f'[Sandbox] {tool_name} completed successfully'
            }

    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} completed'}


# Public entry point
# ---------------------------------------------------------------------------

def _mock_jenkins(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for Jenkins tools."""
    if 'list_jobs' in tool_name or 'list_jenkins_jobs' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 4,
            'jobs': [
                {'name': 'backend-build', 'url': 'http://jenkins.sandbox/job/backend-build/', 'color': 'blue'},
                {'name': 'frontend-build', 'url': 'http://jenkins.sandbox/job/frontend-build/', 'color': 'blue'},
                {'name': 'deploy-staging', 'url': 'http://jenkins.sandbox/job/deploy-staging/', 'color': 'yellow'},
                {'name': 'integration-tests', 'url': 'http://jenkins.sandbox/job/integration-tests/', 'color': 'red'},
            ]
        }
    if 'queue' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 1,
            'queue': [{'id': 42, 'task_name': 'backend-build', 'why': 'Waiting for next available executor', 'stuck': False, 'blocked': False, 'buildable': True, 'in_queue_since': 1700000000000}]
        }
    if 'status' in tool_name or 'get_jenkins_job' in tool_name:
        return {
            'success': True, 'simulated': True,
            'job_name': tool_input.get('job_name', 'backend-build'),
            'build_number': tool_input.get('build_number', 47),
            'status': 'SUCCESS', 'building': False,
            'duration_ms': 124500, 'timestamp': 1700000000000,
            'url': 'http://jenkins.sandbox/job/backend-build/47/'
        }
    if 'logs' in tool_name:
        return {
            'success': True, 'simulated': True,
            'job_name': tool_input.get('job_name', 'backend-build'),
            'build_number': tool_input.get('build_number', 47),
            'logs': '[Pipeline] Start of Pipeline\n[Pipeline] node\n[Pipeline] { (Build)\n+ mvn clean package\n[INFO] BUILD SUCCESS\n[INFO] Total time: 1:45 min\n[Pipeline] } (Build)\n[Pipeline] End of Pipeline\nFinished: SUCCESS',
            'log_length': 250
        }
    if 'nodes' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 2,
            'nodes': [
                {'name': 'Built-In Node', 'offline': False, 'temporarily_offline': False, 'idle': False, 'num_executors': 2, 'offline_cause': None},
                {'name': 'agent-linux-01', 'offline': False, 'temporarily_offline': False, 'idle': True, 'num_executors': 4, 'offline_cause': None},
            ]
        }
    if 'config' in tool_name:
        return {
            'success': True, 'simulated': True,
            'job_name': tool_input.get('job_name', 'backend-build'),
            'config_xml': '<?xml version="1.0"?>\n<flow-definition>\n  <definition class="org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition">\n    <script>pipeline { agent any; stages { stage(\'Build\') { steps { sh \'mvn clean package\' } } } }</script>\n  </definition>\n</flow-definition>',
            'length': 280
        }
    # abort, enable, disable, delete build — simple success
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] Jenkins operation "{tool_name}" completed successfully'}


def _mock_github_actions(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for GitHub Actions tools."""
    repo = f"{tool_input.get('repo_owner', 'myorg')}/{tool_input.get('repo_name', 'myrepo')}"
    if 'list_github_workflows' in tool_name:
        return {
            'success': True, 'simulated': True, 'repo': repo, 'count': 3,
            'workflows': [
                {'id': 1001, 'name': 'CI', 'path': '.github/workflows/ci.yml', 'state': 'active', 'url': f'https://github.com/{repo}/blob/main/.github/workflows/ci.yml', 'badge_url': f'https://github.com/{repo}/workflows/CI/badge.svg'},
                {'id': 1002, 'name': 'Deploy to Staging', 'path': '.github/workflows/deploy-staging.yml', 'state': 'active', 'url': f'https://github.com/{repo}/blob/main/.github/workflows/deploy-staging.yml', 'badge_url': f'https://github.com/{repo}/workflows/Deploy%20to%20Staging/badge.svg'},
                {'id': 1003, 'name': 'Nightly Security Scan', 'path': '.github/workflows/security.yml', 'state': 'active', 'url': f'https://github.com/{repo}/blob/main/.github/workflows/security.yml', 'badge_url': f'https://github.com/{repo}/workflows/Nightly%20Security%20Scan/badge.svg'},
            ]
        }
    if 'workflow_runs' in tool_name or 'get_github_workflow_runs' in tool_name:
        return {
            'success': True, 'simulated': True, 'repo': repo, 'count': 3,
            'runs': [
                {'id': 5001, 'name': 'CI', 'status': 'completed', 'conclusion': 'success', 'event': 'push', 'branch': 'main', 'commit': 'a3b4c5d6', 'created_at': '2024-01-15T10:00:00Z', 'updated_at': '2024-01-15T10:05:00Z', 'url': f'https://github.com/{repo}/actions/runs/5001'},
                {'id': 5002, 'name': 'CI', 'status': 'completed', 'conclusion': 'failure', 'event': 'push', 'branch': 'feature/auth', 'commit': 'e5f6g7h8', 'created_at': '2024-01-15T09:00:00Z', 'updated_at': '2024-01-15T09:08:00Z', 'url': f'https://github.com/{repo}/actions/runs/5002'},
                {'id': 5003, 'name': 'Deploy to Staging', 'status': 'in_progress', 'conclusion': None, 'event': 'workflow_dispatch', 'branch': 'main', 'commit': 'a3b4c5d6', 'created_at': '2024-01-15T10:10:00Z', 'updated_at': '2024-01-15T10:12:00Z', 'url': f'https://github.com/{repo}/actions/runs/5003'},
            ]
        }
    if 'get_github_workflow_run' in tool_name:
        run_id = tool_input.get('run_id', 5001)
        return {
            'success': True, 'simulated': True,
            'run': {'id': run_id, 'name': 'CI', 'status': 'completed', 'conclusion': 'success', 'event': 'push', 'branch': 'main', 'commit': 'a3b4c5d6', 'created_at': '2024-01-15T10:00:00Z', 'updated_at': '2024-01-15T10:05:00Z', 'run_number': 47, 'url': f'https://github.com/{repo}/actions/runs/{run_id}', 'jobs_url': f'https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs', 'logs_url': f'https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs'}
        }
    if 'runners' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 2,
            'runners': [
                {'id': 1, 'name': 'self-hosted-linux-1', 'os': 'Linux', 'status': 'online', 'busy': False, 'labels': ['self-hosted', 'Linux', 'x64']},
                {'id': 2, 'name': 'self-hosted-linux-2', 'os': 'Linux', 'status': 'online', 'busy': True, 'labels': ['self-hosted', 'Linux', 'x64', 'gpu']},
            ]
        }
    if 'secrets' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 4,
            'note': 'Secret values are never exposed by the GitHub API — only names and timestamps are returned.',
            'secrets': [
                {'name': 'AWS_ACCESS_KEY_ID', 'created_at': '2024-01-01T00:00:00Z', 'updated_at': '2024-01-10T00:00:00Z'},
                {'name': 'AWS_SECRET_ACCESS_KEY', 'created_at': '2024-01-01T00:00:00Z', 'updated_at': '2024-01-10T00:00:00Z'},
                {'name': 'DOCKER_PASSWORD', 'created_at': '2024-01-01T00:00:00Z', 'updated_at': '2024-01-01T00:00:00Z'},
                {'name': 'SLACK_WEBHOOK_URL', 'created_at': '2024-01-05T00:00:00Z', 'updated_at': '2024-01-05T00:00:00Z'},
            ]
        }
    if 'environments' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 2,
            'environments': [
                {'id': 101, 'name': 'staging', 'url': f'https://github.com/{repo}/deployments/activity_log?environment=staging', 'protection_rules': [], 'created_at': '2024-01-01T00:00:00Z', 'updated_at': '2024-01-01T00:00:00Z'},
                {'id': 102, 'name': 'production', 'url': f'https://github.com/{repo}/deployments/activity_log?environment=production', 'protection_rules': ['required_reviewers'], 'created_at': '2024-01-01T00:00:00Z', 'updated_at': '2024-01-15T00:00:00Z'},
            ]
        }
    if 'usage' in tool_name or 'timing' in tool_name:
        return {
            'success': True, 'simulated': True,
            'workflow_id': tool_input.get('workflow_id', 'ci.yml'),
            'billable': {'UBUNTU': {'total_ms': 480000, 'jobs': 8}, 'MACOS': {'total_ms': 0, 'jobs': 0}, 'WINDOWS': {'total_ms': 0, 'jobs': 0}}
        }
    # cancel, rerun — simple success
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] GitHub Actions operation "{tool_name}" completed successfully'}


def _mock_docker(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for Docker tools (all 22 tools)."""
    _containers = [
        {'id': 'abc1234567890', 'name': 'web-app', 'image': 'myapp:1.2.3', 'status': 'running', 'ports': '0.0.0.0:8080->8080/tcp', 'created': '2 days ago', 'state': 'running'},
        {'id': 'def4567890123', 'name': 'postgres-db', 'image': 'postgres:16', 'status': 'running', 'ports': '5432/tcp', 'created': '2 days ago', 'state': 'running'},
        {'id': 'ghi7890123456', 'name': 'redis-cache', 'image': 'redis:7-alpine', 'status': 'running', 'ports': '6379/tcp', 'created': '2 days ago', 'state': 'running'},
    ]
    _images = [
        {'id': 'sha256:aaa111', 'repository': 'myapp', 'tag': '1.2.3', 'size': '245MB', 'created': '3 days ago'},
        {'id': 'sha256:bbb222', 'repository': 'postgres', 'tag': '16', 'size': '379MB', 'created': '2 weeks ago'},
        {'id': 'sha256:ccc333', 'repository': 'redis', 'tag': '7-alpine', 'size': '30MB', 'created': '2 weeks ago'},
    ]

    if 'list_containers' in tool_name:
        return {'success': True, 'simulated': True, 'count': len(_containers), 'containers': _containers}

    if 'get_container_details' in tool_name:
        cid = tool_input.get('container_id', 'abc1234567890')
        return {
            'success': True, 'simulated': True,
            'container': {'id': cid, 'name': 'web-app', 'image': 'myapp:1.2.3', 'state': 'running',
                          'ip_address': '172.17.0.2', 'ports': {'8080/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8080'}]},
                          'mounts': [{'Type': 'volume', 'Source': 'app-data', 'Destination': '/app/data'}],
                          'env': ['NODE_ENV=production', 'PORT=8080'],
                          'cpu_shares': 1024, 'memory_limit': 536870912, 'restart_policy': 'unless-stopped'}
        }

    if 'manage_container' in tool_name:
        action = tool_input.get('action', 'stop')
        cid = tool_input.get('container_id', 'abc1234567890')
        messages = {'start': 'started', 'stop': 'stopped', 'restart': 'restarted', 'remove': 'removed', 'pause': 'paused', 'unpause': 'unpaused'}
        return {'success': True, 'simulated': True, 'message': f'Container {cid} {messages.get(action, action)} successfully', 'container_id': cid, 'action': action}

    if 'get_container_logs' in tool_name:
        cid = tool_input.get('container_id', 'abc1234567890')
        return {
            'success': True, 'simulated': True, 'container_id': cid,
            'logs': '2024-01-15T10:00:01Z INFO  Server started on port 8080\n2024-01-15T10:00:02Z INFO  Connected to PostgreSQL\n2024-01-15T10:00:02Z INFO  Connected to Redis\n2024-01-15T10:01:00Z INFO  GET /health 200 2ms\n2024-01-15T10:02:30Z INFO  POST /api/users 201 45ms\n2024-01-15T10:03:15Z WARN  Slow query detected: 850ms\n2024-01-15T10:04:00Z INFO  GET /api/users 200 12ms'
        }

    if 'list_images' in tool_name:
        return {'success': True, 'simulated': True, 'count': len(_images), 'images': _images}

    if 'pull_image' in tool_name:
        image = tool_input.get('image', 'nginx:latest')
        return {'success': True, 'simulated': True, 'message': f'Successfully pulled {image}', 'image': image, 'id': 'sha256:ddd444aabbcc'}

    if 'remove_image' in tool_name:
        image = tool_input.get('image_id', 'sha256:aaa111')
        return {'success': True, 'simulated': True, 'message': f'Image {image} removed', 'image': image}

    if 'list_volumes' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 2,
            'volumes': [
                {'name': 'app-data', 'driver': 'local', 'mountpoint': '/var/lib/docker/volumes/app-data/_data', 'created': '2 days ago'},
                {'name': 'postgres-data', 'driver': 'local', 'mountpoint': '/var/lib/docker/volumes/postgres-data/_data', 'created': '2 days ago'},
            ]
        }

    if 'list_networks' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 3,
            'networks': [
                {'id': 'net001', 'name': 'bridge', 'driver': 'bridge', 'scope': 'local', 'subnet': '172.17.0.0/16'},
                {'id': 'net002', 'name': 'host', 'driver': 'host', 'scope': 'local', 'subnet': None},
                {'id': 'net003', 'name': 'app-network', 'driver': 'bridge', 'scope': 'local', 'subnet': '172.20.0.0/16'},
            ]
        }

    if 'get_stats' in tool_name:
        cid = tool_input.get('container_id', 'abc1234567890')
        return {
            'success': True, 'simulated': True, 'container_id': cid,
            'stats': {'cpu_percent': 2.4, 'memory_usage_mb': 128.5, 'memory_limit_mb': 512.0, 'memory_percent': 25.1,
                      'network_rx_mb': 45.2, 'network_tx_mb': 12.8, 'block_read_mb': 0.5, 'block_write_mb': 2.1}
        }

    if 'compose_up' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Docker Compose services started', 'services_started': ['web', 'db', 'redis'], 'output': 'Creating network "app_default"\nCreating app_db_1 ... done\nCreating app_redis_1 ... done\nCreating app_web_1 ... done'}

    if 'compose_down' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Docker Compose services stopped and removed', 'output': 'Stopping app_web_1 ... done\nStopping app_redis_1 ... done\nStopping app_db_1 ... done\nRemoving app_web_1 ... done\nRemoving network app_default'}

    if 'build_image' in tool_name:
        tag = tool_input.get('tag', 'myapp:latest')
        return {'success': True, 'simulated': True, 'message': f'Image {tag} built successfully', 'tag': tag, 'image_id': 'sha256:eee555aabbcc', 'output': f'Step 1/8 : FROM node:20-alpine\nStep 2/8 : WORKDIR /app\nStep 3/8 : COPY package*.json .\nStep 4/8 : RUN npm ci --only=production\nStep 5/8 : COPY . .\nStep 6/8 : EXPOSE 8080\nStep 7/8 : CMD ["node", "server.js"]\nSuccessfully built eee555aabbcc\nSuccessfully tagged {tag}'}

    if 'create_container' in tool_name:
        name = tool_input.get('name', 'my-container')
        image = tool_input.get('image', 'nginx:latest')
        return {'success': True, 'simulated': True, 'message': f'Container "{name}" created', 'container_id': 'jkl0123456789', 'name': name, 'image': image}

    if 'create_network' in tool_name:
        name = tool_input.get('name', 'my-network')
        return {'success': True, 'simulated': True, 'message': f'Network "{name}" created', 'network_id': 'net999', 'name': name, 'driver': tool_input.get('driver', 'bridge')}

    if 'remove_network' in tool_name:
        return {'success': True, 'simulated': True, 'message': f'Network {tool_input.get("network_id", "net999")} removed'}

    if 'create_volume' in tool_name:
        name = tool_input.get('name', 'my-volume')
        return {'success': True, 'simulated': True, 'message': f'Volume "{name}" created', 'name': name, 'driver': 'local'}

    if 'remove_volume' in tool_name:
        return {'success': True, 'simulated': True, 'message': f'Volume {tool_input.get("volume_name", "my-volume")} removed'}

    if 'exec' in tool_name:
        return {'success': True, 'simulated': True, 'output': '# command executed in container\n[Sandbox] output here', 'exit_code': 0}

    if 'tag_image' in tool_name:
        return {'success': True, 'simulated': True, 'message': f'Image tagged as {tool_input.get("new_tag", "myapp:new")}'}

    if 'push_image' in tool_name:
        image = tool_input.get('image', 'myapp:latest')
        return {'success': True, 'simulated': True, 'message': f'{image} pushed to registry', 'output': f'The push refers to repository [docker.io/myorg/{image}]\nlatest: digest: sha256:abc123 size: 1234'}

    if 'system_prune' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Docker system pruned', 'space_reclaimed': '1.2GB', 'containers_removed': 3, 'images_removed': 5, 'volumes_removed': 1}

    return {'success': True, 'simulated': True, 'message': f'[Sandbox] Docker operation "{tool_name}" completed'}


def _mock_terraform(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for Terraform tools."""
    wdir = tool_input.get('working_dir', './terraform')
    if 'init' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Terraform initialized successfully', 'output': 'Initializing provider plugins...\n- Finding hashicorp/aws versions matching "~> 5.0"...\n- Installing hashicorp/aws v5.31.0...\nTerraform has been successfully initialized!', 'errors': ''}
    if 'plan' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Plan generated successfully', 'output': 'Terraform will perform the following actions:\n\n  # aws_instance.web will be created\n  + resource "aws_instance" "web" {\n      + ami           = "ami-0c02fb55956c7d316"\n      + instance_type = "t3.micro"\n    }\n\nPlan: 1 to add, 0 to change, 0 to destroy.', 'errors': '', 'plan_file': tool_input.get('out')}
    if 'apply' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Apply completed successfully', 'output': 'aws_instance.web: Creating...\naws_instance.web: Creation complete after 30s [id=i-sandbox1234567890]\n\nApply complete! Resources: 1 added, 0 changed, 0 destroyed.', 'errors': ''}
    if 'destroy' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Destroy completed successfully', 'output': 'aws_instance.web: Destroying... [id=i-sandbox1234567890]\naws_instance.web: Destruction complete after 10s\n\nDestroy complete! Resources: 1 destroyed.', 'errors': ''}
    if 'state_list' in tool_name:
        return {'success': True, 'simulated': True, 'count': 3, 'resources': ['aws_instance.web', 'aws_security_group.web_sg', 'aws_vpc.main']}
    if 'output' in tool_name:
        return {'success': True, 'simulated': True, 'outputs': {'instance_public_ip': {'value': '54.10.20.30', 'type': 'string'}, 'vpc_id': {'value': 'vpc-sandbox123', 'type': 'string'}}}
    if 'workspace_list' in tool_name:
        return {'success': True, 'simulated': True, 'workspaces': ['default', 'staging', 'production'], 'current': 'default'}
    if 'validate' in tool_name:
        return {'success': True, 'simulated': True, 'validation': {'valid': True, 'error_count': 0, 'warning_count': 0}}
    if 'fmt' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Format completed', 'modified_files': [], 'errors': ''}
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] Terraform "{tool_name}" completed successfully'}


def _mock_sonarqube(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for SonarQube tools."""
    if 'list_sonar_projects' in tool_name or 'list_projects' in tool_name or 'get_sonar_projects' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 2,
            'projects': [
                {'key': 'my-backend', 'name': 'My Backend', 'qualifier': 'TRK', 'visibility': 'private', 'last_analysis': '2024-01-15T10:00:00+0000'},
                {'key': 'my-frontend', 'name': 'My Frontend', 'qualifier': 'TRK', 'visibility': 'private', 'last_analysis': '2024-01-14T08:00:00+0000'},
            ]
        }
    if 'quality_gate' in tool_name and 'list' in tool_name:
        return {
            'success': True, 'simulated': True,
            'quality_gates': [
                {'id': 1, 'name': 'Sonar way', 'is_default': True, 'is_built_in': True},
                {'id': 2, 'name': 'Strict Gate', 'is_default': False, 'is_built_in': False},
            ]
        }
    if 'issues' in tool_name:
        return {
            'success': True, 'simulated': True, 'total': 3,
            'issues': [
                {'key': 'iss-001', 'rule': 'java:S2068', 'severity': 'CRITICAL', 'component': 'my-backend:src/main/java/Auth.java', 'line': 42, 'message': 'Hard-coded credentials are security-sensitive', 'status': 'OPEN', 'type': 'VULNERABILITY'},
                {'key': 'iss-002', 'rule': 'java:S1481', 'severity': 'MINOR', 'component': 'my-backend:src/main/java/UserService.java', 'line': 87, 'message': 'Remove this unused "temp" local variable', 'status': 'OPEN', 'type': 'CODE_SMELL'},
                {'key': 'iss-003', 'rule': 'java:S1612', 'severity': 'MAJOR', 'component': 'my-backend:src/main/java/DataProcessor.java', 'line': 23, 'message': 'Replace this lambda with a method reference', 'status': 'OPEN', 'type': 'CODE_SMELL'},
            ]
        }
    if 'analysis_history' in tool_name:
        return {
            'success': True, 'simulated': True,
            'analyses': [
                {'key': 'AX9abc', 'date': '2024-01-15T10:00:00+0000', 'events': [{'category': 'VERSION', 'name': '1.2.3'}]},
                {'key': 'AX8def', 'date': '2024-01-08T10:00:00+0000', 'events': []},
                {'key': 'AX7ghi', 'date': '2024-01-01T10:00:00+0000', 'events': [{'category': 'VERSION', 'name': '1.2.0'}]},
            ]
        }
    if 'project_quality' in tool_name or 'project_status' in tool_name:
        project_key = tool_input.get('project_key', 'my-backend')
        return {
            'success': True, 'simulated': True,
            'project_key': project_key,
            'quality_gate': {'status': 'OK', 'name': 'Sonar way'},
            'metrics': {
                'coverage': '82.3', 'duplicated_lines_density': '4.1',
                'bugs': '2', 'vulnerabilities': '1', 'code_smells': '14',
                'reliability_rating': 'B', 'security_rating': 'A', 'sqale_rating': 'A',
            }
        }
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] SonarQube "{tool_name}" completed successfully'}


def _mock_nexus(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Sandbox mocks for Nexus Repository tools."""
    if 'status' in tool_name:
        return {'success': True, 'simulated': True, 'edition': 'OSS', 'version': '3.61.0-02', 'status': 'GREEN', 'available_cpus': 4, 'available_memory_bytes': 4294967296, 'writable': True}
    if 'list_repositories' in tool_name:
        return {
            'success': True, 'simulated': True, 'count': 4,
            'repositories': [
                {'name': 'maven-releases', 'format': 'maven2', 'type': 'hosted', 'url': 'http://nexus.sandbox/repository/maven-releases/'},
                {'name': 'maven-snapshots', 'format': 'maven2', 'type': 'hosted', 'url': 'http://nexus.sandbox/repository/maven-snapshots/'},
                {'name': 'maven-central', 'format': 'maven2', 'type': 'proxy', 'url': 'http://nexus.sandbox/repository/maven-central/'},
                {'name': 'npm-proxy', 'format': 'npm', 'type': 'proxy', 'url': 'http://nexus.sandbox/repository/npm-proxy/'},
            ]
        }
    if 'get_repository' in tool_name:
        return {'success': True, 'simulated': True, 'repository': {'name': tool_input.get('repository_name', 'maven-releases'), 'format': 'maven2', 'type': 'hosted', 'storage': {'blobStoreName': 'default', 'strictContentTypeValidation': True}}}
    if 'search_components' in tool_name or 'list_assets' in tool_name:
        return {
            'success': True, 'simulated': True, 'continuation_token': None,
            'items': [
                {'id': 'comp-001', 'repository': tool_input.get('repository', 'maven-releases'), 'format': 'maven2', 'group': 'com.example', 'name': 'my-app', 'version': '1.2.3'},
                {'id': 'comp-002', 'repository': tool_input.get('repository', 'maven-releases'), 'format': 'maven2', 'group': 'com.example', 'name': 'my-lib', 'version': '2.0.0'},
            ]
        }
    if 'list_users' in tool_name:
        return {
            'success': True, 'simulated': True,
            'users': [
                {'userId': 'admin', 'firstName': 'Nexus', 'lastName': 'Administrator', 'emailAddress': 'admin@example.com', 'status': 'active', 'roles': ['nx-admin']},
                {'userId': 'ci-user', 'firstName': 'CI', 'lastName': 'Pipeline', 'emailAddress': 'ci@example.com', 'status': 'active', 'roles': ['nx-developer']},
            ]
        }
    if 'cleanup' in tool_name:
        return {'success': True, 'simulated': True, 'message': 'Cleanup task "Purge old snapshots" triggered — runs asynchronously in background'}
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] Nexus "{tool_name}" completed successfully'}


def _mock_rds_extended(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Mock RDS extended operations."""
    tn = tool_name
    db_id = tool_input.get('db_instance_identifier', 'sandbox-db')
    cluster_id = tool_input.get('db_cluster_identifier', 'sandbox-cluster')

    _base_instance = {
        'db_instance_identifier': db_id,
        'engine': 'mysql', 'engine_version': '8.0.35',
        'db_instance_class': 'db.t3.medium',
        'status': 'available',
        'endpoint': f'{db_id}.cxyz1234.us-east-1.rds.amazonaws.com',
        'port': 3306, 'allocated_storage': 100, 'multi_az': False,
        'publicly_accessible': False, 'backup_retention_period': 7,
        'deletion_protection': False,
    }

    if tn == 'describe_rds_instance':
        return {'success': True, 'simulated': True, **_base_instance}
    if tn == 'start_rds_instance':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'starting', 'message': f'[Sandbox] RDS instance {db_id} starting'}
    if tn == 'stop_rds_instance':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'stopping', 'message': f'[Sandbox] RDS instance {db_id} stopping'}
    if tn == 'reboot_rds_instance':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'rebooting', 'force_failover': tool_input.get('force_failover', False),
                'message': f'[Sandbox] RDS instance {db_id} rebooting'}
    if tn == 'modify_rds_instance':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'modifying',
                'pending_modified_values': {'DBInstanceClass': tool_input.get('db_instance_class')},
                'message': f'[Sandbox] RDS instance {db_id} modification initiated'}
    if tn == 'tag_rds_instance':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'tags': tool_input.get('tags', {}), 'message': f'[Sandbox] Tags applied to {db_id}'}
    if tn == 'create_rds_snapshot':
        snap_id = tool_input.get('db_snapshot_identifier', 'sandbox-snap')
        return {'success': True, 'simulated': True,
                'snapshot_identifier': snap_id, 'db_instance_identifier': db_id,
                'status': 'creating', 'message': f'[Sandbox] Snapshot {snap_id} creation initiated'}
    if tn == 'list_rds_snapshots':
        return {
            'success': True, 'simulated': True,
            'snapshots': [
                {'snapshot_identifier': f'{db_id}-snap-20260115', 'db_instance_identifier': db_id,
                 'engine': 'mysql', 'engine_version': '8.0.35', 'status': 'available',
                 'allocated_storage': 100, 'created_time': '2026-01-15T02:00:00', 'encrypted': True},
            ], 'count': 1
        }
    if tn == 'delete_rds_snapshot':
        snap_id = tool_input.get('db_snapshot_identifier', 'sandbox-snap')
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Snapshot {snap_id} deleted'}
    if tn == 'restore_rds_from_snapshot':
        new_id = tool_input.get('db_instance_identifier', 'restored-db')
        return {'success': True, 'simulated': True, 'db_instance_identifier': new_id,
                'status': 'creating', 'engine': 'mysql',
                'message': f'[Sandbox] Restoring {new_id} from snapshot'}
    if tn == 'copy_rds_snapshot':
        target = tool_input.get('target_snapshot_identifier', 'snapshot-copy')
        return {'success': True, 'simulated': True, 'target_snapshot_identifier': target,
                'status': 'copying', 'message': f'[Sandbox] Snapshot copy {target} initiated'}
    if tn == 'restore_rds_to_point_in_time':
        target = tool_input.get('target_db_instance_identifier', 'restored-pitr')
        return {'success': True, 'simulated': True, 'db_instance_identifier': target,
                'status': 'creating', 'message': f'[Sandbox] Point-in-time restore to {target} initiated'}
    if tn == 'create_db_parameter_group':
        group = tool_input.get('group_name', 'sandbox-params')
        return {'success': True, 'simulated': True, 'parameter_group_name': group,
                'family': tool_input.get('family', 'mysql8.0'),
                'message': f'[Sandbox] Parameter group {group} created'}
    if tn == 'list_db_parameter_groups':
        return {
            'success': True, 'simulated': True,
            'parameter_groups': [
                {'name': 'default.mysql8.0', 'family': 'mysql8.0', 'description': 'Default parameter group for mysql8.0'},
                {'name': 'sandbox-custom-params', 'family': 'mysql8.0', 'description': 'Custom parameters'},
            ], 'count': 2
        }
    if tn == 'modify_db_parameter_group':
        group = tool_input.get('group_name', 'sandbox-params')
        params = tool_input.get('parameters', [])
        return {'success': True, 'simulated': True, 'parameter_group_name': group,
                'parameters_modified': len(params),
                'message': f'[Sandbox] {len(params)} parameter(s) updated in {group}'}
    if tn == 'delete_db_parameter_group':
        group = tool_input.get('group_name', 'sandbox-params')
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] Parameter group {group} deleted'}
    if tn == 'create_db_subnet_group':
        group = tool_input.get('group_name', 'sandbox-subnet-group')
        return {'success': True, 'simulated': True, 'subnet_group_name': group,
                'vpc_id': 'vpc-sandbox', 'subnet_count': len(tool_input.get('subnet_ids', [])),
                'message': f'[Sandbox] DB subnet group {group} created'}
    if tn == 'list_db_subnet_groups':
        return {
            'success': True, 'simulated': True,
            'subnet_groups': [
                {'name': 'sandbox-subnet-group', 'vpc_id': 'vpc-sandbox',
                 'status': 'Complete', 'availability_zones': ['us-east-1a', 'us-east-1b']},
            ], 'count': 1
        }
    if tn == 'delete_db_subnet_group':
        group = tool_input.get('group_name', 'sandbox-subnet-group')
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] DB subnet group {group} deleted'}
    if tn == 'rotate_rds_master_password':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'modifying', 'message': f'[Sandbox] Master password rotation initiated for {db_id}'}
    if tn == 'enable_rds_iam_auth':
        enable = tool_input.get('enable', True)
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'iam_auth_enabled': enable,
                'message': f'[Sandbox] IAM authentication {"enabled" if enable else "disabled"} for {db_id}'}
    if tn == 'list_rds_log_files':
        return {
            'success': True, 'simulated': True, 'db_instance_identifier': db_id,
            'log_files': [
                {'log_file_name': 'error/mysql-error.log', 'last_written': 1705312800000, 'size': 4096},
                {'log_file_name': 'slowquery/mysql-slowquery.log', 'last_written': 1705309200000, 'size': 1024},
            ], 'count': 2
        }
    if tn == 'download_rds_log_file':
        log_name = tool_input.get('log_file_name', 'error/mysql-error.log')
        return {'success': True, 'simulated': True,
                'log_file_name': log_name, 'additional_data_pending': False,
                'log_content': '[Sandbox] 2026-01-15T10:00:00 [Note] InnoDB: buffer pool(s) load completed\n[Sandbox] 2026-01-15T10:01:00 [Note] /rds/sbin/mysqld: ready for connections\n'}
    if tn == 'list_rds_events':
        return {
            'success': True, 'simulated': True,
            'events': [
                {'source_identifier': db_id, 'source_type': 'db-instance',
                 'message': 'Backing up DB instance', 'event_categories': ['backup'],
                 'date': '2026-01-15T02:00:00'},
                {'source_identifier': db_id, 'source_type': 'db-instance',
                 'message': 'Finished DB Instance backup', 'event_categories': ['backup'],
                 'date': '2026-01-15T02:30:00'},
            ], 'count': 2
        }
    if tn == 'create_rds_read_replica':
        replica_id = tool_input.get('replica_identifier', 'sandbox-replica')
        return {'success': True, 'simulated': True, 'replica_identifier': replica_id,
                'source_identifier': tool_input.get('source_db_instance_identifier', db_id),
                'status': 'creating', 'message': f'[Sandbox] Read replica {replica_id} creation initiated'}
    if tn == 'promote_rds_read_replica':
        return {'success': True, 'simulated': True, 'db_instance_identifier': db_id,
                'status': 'modifying',
                'message': f'[Sandbox] Read replica {db_id} promotion initiated — replication will stop'}
    if tn == 'create_aurora_cluster':
        return {
            'success': True, 'simulated': True,
            'cluster_identifier': cluster_id, 'status': 'creating',
            'engine': tool_input.get('engine', 'aurora-mysql'),
            'endpoint': f'{cluster_id}.cluster-cxyz1234.us-east-1.rds.amazonaws.com',
            'reader_endpoint': f'{cluster_id}.cluster-ro-cxyz1234.us-east-1.rds.amazonaws.com',
            'message': f'[Sandbox] Aurora cluster {cluster_id} creation initiated'
        }
    if tn == 'list_aurora_clusters':
        return {
            'success': True, 'simulated': True,
            'clusters': [
                {'cluster_identifier': 'sandbox-aurora', 'engine': 'aurora-mysql',
                 'engine_version': '8.0.mysql_aurora.3.04.0', 'status': 'available',
                 'endpoint': 'sandbox-aurora.cluster-cxyz.us-east-1.rds.amazonaws.com',
                 'reader_endpoint': 'sandbox-aurora.cluster-ro-cxyz.us-east-1.rds.amazonaws.com',
                 'member_count': 2, 'backup_retention': 7, 'encrypted': True},
            ], 'count': 1
        }
    if tn == 'delete_aurora_cluster':
        return {'success': True, 'simulated': True, 'cluster_identifier': cluster_id,
                'status': 'deleting', 'message': f'[Sandbox] Aurora cluster {cluster_id} deletion initiated'}
    if tn == 'failover_aurora_cluster':
        return {'success': True, 'simulated': True, 'cluster_identifier': cluster_id,
                'status': 'failing-over', 'message': f'[Sandbox] Aurora cluster {cluster_id} failover initiated'}
    if tn == 'describe_pending_rds_maintenance':
        return {
            'success': True, 'simulated': True,
            'pending_actions': [
                {'resource_identifier': f'arn:aws:rds:us-east-1:123456789012:db:{db_id}',
                 'action': 'system-update', 'description': 'New Operating System update is available',
                 'auto_applied_after_date': '2026-02-01T00:00:00', 'current_apply_date': None},
            ], 'count': 1
        }
    if tn == 'describe_rds_engine_versions':
        engine = tool_input.get('engine', 'mysql')
        return {
            'success': True, 'simulated': True,
            'engine_versions': [
                {'engine': engine, 'engine_version': '8.0.36', 'status': 'available',
                 'supports_multi_az': True, 'supports_read_replica': True,
                 'default_parameter_group_family': f'{engine}8.0'},
                {'engine': engine, 'engine_version': '8.0.35', 'status': 'available',
                 'supports_multi_az': True, 'supports_read_replica': True,
                 'default_parameter_group_family': f'{engine}8.0'},
            ], 'count': 2
        }

    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} executed'}


def _mock_vpc_extended(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Mock VPC extended operations."""
    tn = tool_name
    vpc_id = tool_input.get('vpc_id', 'vpc-0abc123456789def0')
    subnet_id = tool_input.get('subnet_id', 'subnet-0abc123456789def0')
    group_id = tool_input.get('group_id', 'sg-0abc123456789def0')

    if tn in ('tag_vpc', 'tag_subnet', 'tag_security_group'):
        resource = vpc_id if 'vpc' in tn else (subnet_id if 'subnet' in tn else group_id)
        return {'success': True, 'simulated': True,
                'resource_id': resource, 'tags': tool_input.get('tags', {}),
                'message': f'[Sandbox] Tags applied to {resource}'}
    if tn == 'enable_vpc_flow_logs':
        return {
            'success': True, 'simulated': True,
            'vpc_id': vpc_id, 'flow_log_ids': ['fl-' + _rand_id(length=17)],
            'destination_type': tool_input.get('destination_type', 'cloud-watch-logs'),
            'traffic_type': tool_input.get('traffic_type', 'ALL'),
            'message': f'[Sandbox] Flow logs enabled for VPC {vpc_id}'
        }
    if tn == 'disable_vpc_flow_logs':
        flow_log_id = tool_input.get('flow_log_id', 'fl-sandbox')
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Flow log {flow_log_id} deleted'}
    if tn == 'list_vpc_flow_logs':
        return {
            'success': True, 'simulated': True,
            'flow_logs': [
                {'flow_log_id': 'fl-' + _rand_id(length=17), 'resource_id': vpc_id,
                 'traffic_type': 'ALL', 'log_destination_type': 'cloud-watch-logs',
                 'log_destination': f'/aws/vpc/flowlogs/{vpc_id}', 'flow_log_status': 'ACTIVE'},
            ], 'count': 1
        }
    if tn in ('attach_internet_gateway',):
        igw_id = tool_input.get('igw_id', 'igw-sandbox')
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] IGW {igw_id} attached to VPC {vpc_id}'}
    if tn in ('detach_internet_gateway',):
        igw_id = tool_input.get('igw_id', 'igw-sandbox')
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] IGW {igw_id} detached from VPC {vpc_id}'}
    if tn == 'add_route':
        rtb_id = tool_input.get('route_table_id', 'rtb-sandbox')
        dest = tool_input.get('destination_cidr', '0.0.0.0/0')
        return {'success': True, 'simulated': True,
                'route_table_id': rtb_id, 'destination_cidr': dest,
                'message': f'[Sandbox] Route {dest} added to {rtb_id}'}
    if tn == 'replace_route':
        rtb_id = tool_input.get('route_table_id', 'rtb-sandbox')
        dest = tool_input.get('destination_cidr', '0.0.0.0/0')
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Route {dest} in {rtb_id} updated'}
    if tn == 'set_main_route_table':
        rtb_id = tool_input.get('route_table_id', 'rtb-sandbox')
        return {'success': True, 'simulated': True,
                'route_table_id': rtb_id, 'vpc_id': vpc_id,
                'new_association_id': 'rtbassoc-' + _rand_id(length=17),
                'message': f'[Sandbox] Route table {rtb_id} set as main for VPC {vpc_id}'}
    if tn == 'authorize_security_group_egress':
        return {
            'success': True, 'simulated': True, 'group_id': group_id,
            'protocol': tool_input.get('protocol', 'tcp'),
            'ports': f"{tool_input.get('from_port', 0)}-{tool_input.get('to_port', 65535)}",
            'message': f'[Sandbox] Outbound rule added to {group_id}'
        }
    if tn == 'revoke_security_group_egress':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Outbound rule removed from {group_id}'}
    if tn == 'audit_security_group_rules':
        return {
            'success': True, 'simulated': True,
            'findings': [
                {'group_id': 'sg-0abc123456789def0', 'group_name': 'web-sg', 'vpc_id': vpc_id,
                 'protocol': 'tcp', 'ports': '22', 'cidr': '0.0.0.0/0',
                 'direction': 'inbound', 'risk': 'CRITICAL'},
                {'group_id': 'sg-0abc123456789def1', 'group_name': 'app-sg', 'vpc_id': vpc_id,
                 'protocol': 'tcp', 'ports': '8080', 'cidr': '0.0.0.0/0',
                 'direction': 'inbound', 'risk': 'HIGH'},
            ],
            'total_findings': 2, 'critical': 1, 'high': 1,
            'message': '[Sandbox] Found 2 overly permissive inbound rules — SSH on port 22 open to 0.0.0.0/0 is CRITICAL'
        }
    if tn == 'accept_vpc_peering':
        pcx_id = tool_input.get('peering_connection_id', 'pcx-sandbox')
        return {
            'success': True, 'simulated': True,
            'peering_connection_id': pcx_id, 'status': 'active',
            'message': f'[Sandbox] Peering {pcx_id} accepted — update route tables to route peered VPC traffic'
        }
    if tn == 'attach_eni':
        eni_id = tool_input.get('network_interface_id', 'eni-sandbox')
        inst_id = tool_input.get('instance_id', 'i-sandbox')
        return {
            'success': True, 'simulated': True,
            'network_interface_id': eni_id, 'instance_id': inst_id,
            'attachment_id': 'eni-attach-' + _rand_id(length=17),
            'message': f'[Sandbox] ENI {eni_id} attached to {inst_id}'
        }
    if tn == 'detach_eni':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] ENI attachment {tool_input.get("attachment_id", "eni-attach-sandbox")} detached'}

    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} executed'}


def _mock_iam(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    """Mock IAM extended operations."""
    tn = tool_name

    username = tool_input.get('username', 'sandbox-user')
    group_name = tool_input.get('group_name', 'sandbox-group')
    role_name = tool_input.get('role_name', 'sandbox-role')
    policy_arn = tool_input.get('policy_arn', 'arn:aws:iam::123456789012:policy/SandboxPolicy')

    if tn == 'create_iam_user':
        return {
            'success': True, 'simulated': True,
            'user': {'username': username, 'arn': f'arn:aws:iam::123456789012:user/{username}',
                     'user_id': 'AIDAIOSFODNN7EXAMPLE', 'path': tool_input.get('path', '/'),
                     'created': '2026-01-15T10:00:00Z'},
            'message': f'[Sandbox] IAM user {username} created'
        }
    if tn == 'get_iam_user':
        return {
            'success': True, 'simulated': True,
            'user': {'username': username, 'arn': f'arn:aws:iam::123456789012:user/{username}',
                     'user_id': 'AIDAIOSFODNN7EXAMPLE', 'created': '2026-01-15T10:00:00Z',
                     'groups': ['Developers', 'ReadOnlyAccess'],
                     'attached_policies': ['arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess']},
            'message': f'[Sandbox] IAM user {username} retrieved'
        }
    if tn in ('delete_iam_user',):
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] IAM user {username} deleted'}
    if tn == 'create_iam_login_profile':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Console access enabled for {username}',
                'password_reset_required': tool_input.get('password_reset_required', True)}
    if tn == 'delete_iam_login_profile':
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] Console access removed for {username}'}
    if tn in ('tag_iam_user', 'tag_iam_role'):
        entity = username if 'user' in tn else role_name
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Tags applied to {entity}',
                'tags': tool_input.get('tags', {})}
    if tn == 'create_iam_access_key':
        return {
            'success': True, 'simulated': True,
            'access_key': {
                'access_key_id': 'AKIAIOSFODNN7EXAMPLE',
                'secret_access_key': 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',
                'status': 'Active', 'username': username,
                'created': '2026-01-15T10:00:00Z'
            },
            'message': f'[Sandbox] Access key created for {username} — store the secret key now, it is not retrievable later'
        }
    if tn == 'list_iam_access_keys':
        return {
            'success': True, 'simulated': True,
            'username': username,
            'access_keys': [
                {'access_key_id': 'AKIAIOSFODNN7EXAMPLE', 'status': 'Active', 'created': '2026-01-15T10:00:00Z'},
            ]
        }
    if tn == 'delete_iam_access_key':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Access key {tool_input.get("access_key_id", "AKIA...")} deleted for {username}'}
    if tn == 'update_iam_access_key':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Access key set to {tool_input.get("status", "Active")} for {username}'}
    if tn == 'get_access_key_last_used':
        return {
            'success': True, 'simulated': True,
            'access_key_id': tool_input.get('access_key_id', 'AKIAIOSFODNN7EXAMPLE'),
            'last_used': {'service': 'ec2', 'region': 'us-east-1', 'last_used_date': '2026-01-14T08:30:00Z'},
            'username': username
        }
    if tn == 'create_iam_group':
        return {'success': True, 'simulated': True,
                'group': {'group_name': group_name, 'arn': f'arn:aws:iam::123456789012:group/{group_name}',
                          'group_id': 'AGPAIOSFODNN7EXAMPLE', 'path': tool_input.get('path', '/')},
                'message': f'[Sandbox] IAM group {group_name} created'}
    if tn == 'list_iam_groups':
        return {
            'success': True, 'simulated': True,
            'groups': [
                {'group_name': 'Developers', 'arn': 'arn:aws:iam::123456789012:group/Developers', 'path': '/'},
                {'group_name': 'ReadOnlyAccess', 'arn': 'arn:aws:iam::123456789012:group/ReadOnlyAccess', 'path': '/'},
                {'group_name': 'Admins', 'arn': 'arn:aws:iam::123456789012:group/Admins', 'path': '/'},
            ]
        }
    if tn == 'delete_iam_group':
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] IAM group {group_name} deleted'}
    if tn in ('add_iam_user_to_group', 'remove_iam_user_from_group'):
        action = 'added to' if 'add' in tn else 'removed from'
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] {username} {action} {group_name}'}
    if tn == 'list_iam_groups_for_user':
        return {
            'success': True, 'simulated': True,
            'username': username,
            'groups': ['Developers', 'ReadOnlyAccess']
        }
    if tn == 'get_iam_role':
        return {
            'success': True, 'simulated': True,
            'role': {'role_name': role_name, 'arn': f'arn:aws:iam::123456789012:role/{role_name}',
                     'role_id': 'AROAIOSFODNN7EXAMPLE', 'path': '/',
                     'trust_policy': {'Version': '2012-10-17', 'Statement': [
                         {'Effect': 'Allow', 'Principal': {'Service': 'ec2.amazonaws.com'}, 'Action': 'sts:AssumeRole'}
                     ]},
                     'attached_policies': ['arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess']},
            'message': f'[Sandbox] IAM role {role_name} retrieved'
        }
    if tn == 'update_iam_role_trust_policy':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Trust policy updated for role {role_name}'}
    if tn == 'assume_iam_role':
        return {
            'success': True, 'simulated': True,
            'credentials': {
                'access_key_id': 'ASIAIOSFODNN7EXAMPLE',
                'secret_access_key': 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYSIMULATED',
                'session_token': 'AQoDYXdzEJr//////////wEa...SIMULATED',
                'expiration': '2026-01-15T14:00:00Z'
            },
            'assumed_role': {'arn': tool_input.get('role_arn', 'arn:aws:iam::123456789012:role/SandboxRole'),
                             'session_name': tool_input.get('session_name', 'sandbox-session')},
            'message': '[Sandbox] Role assumed — temporary credentials valid for 1 hour'
        }
    if tn == 'list_iam_policies':
        return {
            'success': True, 'simulated': True,
            'policies': [
                {'policy_name': 'SandboxReadOnly', 'arn': 'arn:aws:iam::123456789012:policy/SandboxReadOnly',
                 'description': 'Read-only access to sandbox resources', 'attached_entities': 2},
                {'policy_name': 'S3FullAccess', 'arn': 'arn:aws:iam::123456789012:policy/S3FullAccess',
                 'description': 'Full S3 bucket access', 'attached_entities': 5},
            ],
            'scope': tool_input.get('scope', 'Local')
        }
    if tn == 'get_iam_policy':
        return {
            'success': True, 'simulated': True,
            'policy': {'arn': policy_arn, 'policy_name': 'SandboxPolicy', 'attached_entities': 3,
                       'document': {'Version': '2012-10-17', 'Statement': [
                           {'Effect': 'Allow', 'Action': 'ec2:Describe*', 'Resource': '*'}
                       ]}},
            'message': f'[Sandbox] Policy retrieved'
        }
    if tn in ('delete_iam_policy',):
        return {'success': True, 'simulated': True, 'message': f'[Sandbox] Policy {policy_arn} deleted'}
    if tn in ('attach_iam_user_policy', 'attach_iam_group_policy'):
        entity = username if 'user' in tn else group_name
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Policy attached to {entity}'}
    if tn == 'detach_iam_policy':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Policy detached from {tool_input.get("entity_name", "entity")}'}
    if tn in ('put_iam_inline_policy',):
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Inline policy {tool_input.get("policy_name", "policy")} applied'}
    if tn == 'delete_iam_inline_policy':
        return {'success': True, 'simulated': True,
                'message': f'[Sandbox] Inline policy {tool_input.get("policy_name", "policy")} deleted'}
    if tn == 'list_attached_role_policies':
        return {
            'success': True, 'simulated': True,
            'role_name': role_name,
            'attached_policies': [
                {'policy_name': 'AmazonEC2ReadOnlyAccess', 'arn': 'arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess'},
                {'policy_name': 'AmazonS3ReadOnlyAccess', 'arn': 'arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess'},
            ]
        }
    if tn == 'generate_iam_credential_report':
        return {'success': True, 'simulated': True,
                'message': '[Sandbox] Credential report generation initiated', 'state': 'COMPLETE'}
    if tn == 'get_iam_credential_report':
        return {
            'success': True, 'simulated': True,
            'report': [
                {'user': 'sandbox-user', 'arn': 'arn:aws:iam::123456789012:user/sandbox-user',
                 'password_enabled': True, 'password_last_used': '2026-01-14',
                 'mfa_active': False, 'access_key_1_active': True, 'access_key_1_last_used': '2026-01-14'},
                {'user': 'admin', 'arn': 'arn:aws:iam::123456789012:user/admin',
                 'password_enabled': True, 'password_last_used': '2026-01-15',
                 'mfa_active': True, 'access_key_1_active': False, 'access_key_1_last_used': 'N/A'},
            ]
        }
    if tn == 'get_iam_account_summary':
        return {
            'success': True, 'simulated': True,
            'summary': {
                'users': 12, 'users_quota': 5000,
                'groups': 5, 'groups_quota': 300,
                'roles': 28, 'roles_quota': 1000,
                'policies': 8, 'policies_quota': 1500,
                'mfa_devices': 3, 'mfa_devices_in_use': 2,
                'account_access_keys_present': 0,
                'account_mfa_enabled': True,
            }
        }
    if tn == 'list_iam_services_last_accessed':
        return {
            'success': True, 'simulated': True,
            'arn': tool_input.get('arn', 'arn:aws:iam::123456789012:user/sandbox-user'),
            'services_accessed': [
                {'service_name': 'Amazon EC2', 'last_accessed': '2026-01-14T08:30:00Z', 'region': 'us-east-1'},
                {'service_name': 'Amazon S3', 'last_accessed': '2026-01-13T14:00:00Z', 'region': 'us-east-1'},
                {'service_name': 'AWS IAM', 'last_accessed': '2026-01-10T09:00:00Z', 'region': 'us-east-1'},
            ],
            'services_not_accessed': ['Amazon RDS', 'AWS Lambda', 'Amazon ECS'],
            'message': '[Sandbox] Services last accessed report — use this to apply least-privilege'
        }

    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} executed'}


def _mock_gitlab(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    project_id = tool_input.get('project_id', 'mygroup/myrepo')
    if 'list_gitlab_pipelines' in tool_name:
        return {
            'success': True, 'simulated': True,
            'project_id': project_id,
            'pipelines': [
                {'id': 1042, 'status': 'success', 'ref': 'main', 'sha': 'a1b2c3d4', 'created_at': _recent_time(60)},
                {'id': 1041, 'status': 'failed', 'ref': 'feature/auth', 'sha': 'e5f6g7h8', 'created_at': _recent_time(120)},
                {'id': 1040, 'status': 'success', 'ref': 'main', 'sha': 'i9j0k1l2', 'created_at': _recent_time(240)},
            ],
            'count': 3
        }
    if 'get_gitlab_pipeline' in tool_name:
        return {
            'success': True, 'simulated': True,
            'id': tool_input.get('pipeline_id', 1042),
            'status': 'success', 'ref': 'main', 'sha': 'a1b2c3d4e5f6',
            'source': 'push', 'duration': 187,
            'created_at': _recent_time(60), 'finished_at': _recent_time(57),
            'web_url': f'https://gitlab.com/{project_id}/-/pipelines/1042'
        }
    if 'trigger_gitlab_pipeline' in tool_name:
        return {
            'success': True, 'simulated': True,
            'pipeline_id': 1043, 'status': 'created',
            'ref': tool_input.get('ref', 'main'),
            'web_url': f'https://gitlab.com/{project_id}/-/pipelines/1043',
            'message': f'[Sandbox] Pipeline triggered on {tool_input.get("ref", "main")} (id: 1043)'
        }
    if 'list_gitlab_jobs' in tool_name:
        return {
            'success': True, 'simulated': True,
            'pipeline_id': tool_input.get('pipeline_id', 1042),
            'jobs': [
                {'id': 5001, 'name': 'test', 'stage': 'test', 'status': 'success', 'duration': 45, 'web_url': '#'},
                {'id': 5002, 'name': 'build', 'stage': 'build', 'status': 'success', 'duration': 120, 'web_url': '#'},
                {'id': 5003, 'name': 'deploy', 'stage': 'deploy', 'status': 'success', 'duration': 22, 'web_url': '#'},
            ],
            'count': 3
        }
    if 'get_gitlab_job_log' in tool_name:
        return {
            'success': True, 'simulated': True,
            'job_id': tool_input.get('job_id', 5001),
            'log': '[Sandbox] Running with gitlab-runner...\n$ npm test\nAll tests passed (42/42)\nJob succeeded',
            'truncated': False
        }
    if 'approve_gitlab_deployment' in tool_name:
        return {
            'success': True, 'simulated': True,
            'deployment_id': tool_input.get('deployment_id', 99),
            'status': tool_input.get('status', 'approved'),
            'message': f'[Sandbox] Deployment {tool_input.get("deployment_id", 99)} approved'
        }
    if 'create_gitlab_pipeline_trigger' in tool_name:
        return {
            'success': True, 'simulated': True,
            'trigger_id': 42,
            'token': 'glptt-simulated-trigger-token-abc123',
            'description': tool_input.get('description', 'External CI trigger'),
            'message': f'[Sandbox] Trigger token created'
        }
    # retry / cancel / default
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} completed'}


def _mock_deployment_strategy(tool_name: str, tool_input: Dict) -> Dict[str, Any]:
    if 'rollout_status' in tool_name:
        name = tool_input.get('deployment_name', 'my-deployment')
        return {
            'success': True, 'simulated': True,
            'deployment_name': name,
            'namespace': tool_input.get('namespace', 'default'),
            'desired': 3, 'ready': 3, 'updated': 3, 'available': 3,
            'complete': True,
            'message': '[Sandbox] Rollout complete'
        }
    if 'blue_green' in tool_name:
        color = tool_input.get('target_color', 'green')
        return {
            'success': True, 'simulated': True,
            'service_name': tool_input.get('service_name', 'my-service'),
            'namespace': tool_input.get('namespace', 'default'),
            'active_color': color,
            'message': f'[Sandbox] Service switched to {color} deployment'
        }
    if 'canary_update' in tool_name:
        weight = tool_input.get('canary_weight_percent', 20)
        return {
            'success': True, 'simulated': True,
            'stable_deployment': tool_input.get('stable_deployment', 'app-stable'),
            'canary_deployment': tool_input.get('canary_deployment', 'app-canary'),
            'stable_replicas': max(5 - round(5 * weight / 100), 0),
            'canary_replicas': max(round(5 * weight / 100), 0),
            'canary_weight_percent': weight,
            'message': f'[Sandbox] Canary weight set to {weight}%'
        }
    if 'smoke_test' in tool_name:
        return {
            'success': True, 'simulated': True,
            'url': tool_input.get('url', 'https://api.example.com/health'),
            'status_code': 200,
            'expected_status': tool_input.get('expected_status', 200),
            'response_time_ms': 42,
            'healthy': True,
            'message': '[Sandbox] Smoke test passed: 200 (expected 200)'
        }
    if 'auto_rollback' in tool_name:
        return {
            'success': True, 'simulated': True,
            'deployment_name': tool_input.get('deployment_name', 'my-deployment'),
            'healthy': True,
            'action': 'none',
            'message': '[Sandbox] Health check passed — deployment is healthy (no rollback needed)'
        }
    return {'success': True, 'simulated': True, 'message': f'[Sandbox] {tool_name} completed'}


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

    # Route CI/CD tools
    is_jenkins = any(k in tn for k in ('jenkins',))
    is_github_actions = any(k in tn for k in ('github_workflow', 'github_runner', 'github_secret', 'github_environment'))
    is_gitlab = any(k in tn for k in ('gitlab',))
    is_deployment_strategy = any(k in tn for k in ('blue_green', 'canary_update', 'smoke_test', 'auto_rollback', 'rollout_status'))
    is_docker = any(k in tn for k in ('docker',))
    is_terraform = any(k in tn for k in ('terraform',))
    is_sonarqube = any(k in tn for k in ('sonar',))
    is_nexus = any(k in tn for k in ('nexus',))
    is_git = tn.startswith('git_') and not any(k in tn for k in ('docker', 'ansible', 'terraform', 'github'))
    is_resize_ec2 = 'resize_ec2' in tn

    # find_ami must return a usable ami_id: it is the lookup step create_ec2_instance
    # depends on, so a generic "[Sandbox] executed" fallback would break the chain
    # mid-flow for a learner walking through launching an instance.
    if tn == 'find_ami':
        distro = (tool_input.get('distro') or 'ubuntu').lower()
        version = tool_input.get('version') or {'ubuntu': '24.04', 'debian': '12', 'rhel': '9'}.get(distro, 'latest')
        return {
            'success': True, 'simulated': True,
            'ami_id': 'ami-' + _rand_id(length=17),
            'name': f'{distro}-{version}-amd64-server-20260901',
            'architecture': tool_input.get('architecture', 'x86_64'),
            'publisher': {'ubuntu': 'Canonical', 'amazon-linux': 'Amazon'}.get(distro, distro.title()),
            'region': tool_input.get('region', 'us-east-1'),
            'alternates': [],
            'message': f'[Sandbox] Newest {distro} {version} AMI. Pass this as ami_id to create_ec2_instance.',
        }

    if is_git:
        return _mock_git(tn, tool_input)
    if is_jenkins:
        return _mock_jenkins(tn, tool_input)
    if is_github_actions:
        return _mock_github_actions(tn, tool_input)
    if is_gitlab:
        return _mock_gitlab(tn, tool_input)
    if is_deployment_strategy:
        return _mock_deployment_strategy(tn, tool_input)
    if is_docker:
        return _mock_docker(tn, tool_input)
    if is_terraform:
        return _mock_terraform(tn, tool_input)
    if is_resize_ec2:
        instance_id = tool_input.get('instance_id', 'i-simulated123456')
        new_type = tool_input.get('new_instance_type', 't3.small')
        return {
            'success': True,
            'simulated': True,
            'instance_id': instance_id,
            'new_instance_type': new_type,
            'message': f'[Sandbox] Successfully resized instance {instance_id} to {new_type}'
        }
    if 'describe_security_group' in tn:
        group_id = tool_input.get('group_id', 'sg-simulated12345')
        return {
            'success': True,
            'simulated': True,
            'group_id': group_id,
            'group_name': 'simulated-sg',
            'description': 'Simulated security group for learning',
            'vpc_id': 'vpc-simulated123',
            'ingress_rules': [
                {'protocol': 'tcp', 'from_port': 22, 'to_port': 22, 'cidr': '0.0.0.0/0', 'description': 'SSH from anywhere'},
                {'protocol': 'tcp', 'from_port': 80, 'to_port': 80, 'cidr': '0.0.0.0/0', 'description': 'HTTP from anywhere'}
            ],
            'ingress_rules_count': 2,
            'egress_rules': [
                {'protocol': '-1', 'from_port': None, 'to_port': None, 'cidr': '0.0.0.0/0', 'description': 'All outbound'}
            ],
            'egress_rules_count': 1
        }
    if is_sonarqube:
        return _mock_sonarqube(tn, tool_input)
    if is_nexus:
        return _mock_nexus(tn, tool_input)

    # Categorize by cloud provider
    is_k8s = any(k in tn for k in (
        'k8s', 'kube', 'pod', 'deploy', 'namespace', 'node', 'ingress', 'job',
        'rollout', 'statefulset', 'replicaset', 'configmap', '_hpa', '_pvc', '_pvs',
        'service_account', 'cluster_event', 'manifest', 'list_roles', 'create_role',
        'describe_service', 'list_secrets', 'list_contexts', 'get_current_context',
        'eks_cluster', 'eks_node', 'eks_fargate', 'eks_addon', 'eks_access', 'eks_oidc', 'eks_kubeconfig',
    ))
    is_azure = 'azure' in tn or tn.startswith(('list_azure', 'create_azure', 'delete_azure',
                                                 'start_azure', 'stop_azure', 'restart_azure'))
    is_gcp = any(k in tn for k in ('gcp', 'gcloud', 'gke', 'gcs', 'cloud_run', 'cloud_sql',
                                     'bigquery', 'pubsub', 'cloud_function', 'cloud_log'))

    # RDS extended operations (must come before generic AWS handlers)
    is_rds_extended = any(k in tn for k in (
        'describe_rds', 'start_rds', 'stop_rds', 'reboot_rds', 'modify_rds',
        'tag_rds', 'create_rds_snapshot', 'list_rds_snapshot', 'delete_rds_snapshot',
        'restore_rds', 'copy_rds_snapshot', 'create_db_parameter', 'list_db_parameter',
        'modify_db_parameter', 'delete_db_parameter', 'create_db_subnet', 'list_db_subnet',
        'delete_db_subnet', 'rotate_rds', 'enable_rds_iam', 'list_rds_log', 'download_rds_log',
        'list_rds_events', 'create_rds_read_replica', 'promote_rds_read_replica',
        'create_aurora', 'list_aurora', 'delete_aurora', 'failover_aurora',
        'describe_pending_rds', 'describe_rds_engine',
    ))
    if is_rds_extended:
        return _mock_rds_extended(tn, tool_input)

    # IAM extended operations (must come before generic AWS handlers)
    is_iam_extended = any(k in tn for k in (
        'iam_user', 'iam_group', 'iam_policy', 'iam_access_key', 'iam_login_profile',
        'iam_role', 'iam_inline', 'iam_services_last_accessed', 'iam_account_summary',
        'iam_credential_report', 'access_key_last_used', 'attached_role_policies',
        'iam_groups_for_user', 'iam_user_to_group',
    ))

    # Route to provider-specific mock
    if is_k8s:
        return _mock_k8s(tn, tool_input)
    if is_azure:
        return _mock_azure(tn, tool_input)
    if is_gcp:
        return _mock_gcp(tn, tool_input)
    if is_iam_extended:
        return _mock_iam(tn, tool_input)

    # VPC extended operations (must come before generic AWS handlers)
    is_vpc_extended = any(k in tn for k in (
        'enable_vpc_flow', 'disable_vpc_flow', 'list_vpc_flow',
        'attach_internet_gateway', 'detach_internet_gateway',
        'add_route', 'replace_route', 'set_main_route',
        'authorize_security_group_egress', 'revoke_security_group_egress',
        'audit_security_group',
        'accept_vpc_peering',
        'attach_eni', 'detach_eni',
        'tag_vpc', 'tag_subnet', 'tag_security_group',
    ))
    if is_vpc_extended:
        return _mock_vpc_extended(tn, tool_input)

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
    if tn.startswith('update_') or tn.startswith('modify_') or tn.startswith('resize_'):
        return {'success': True, 'simulated': True, 'message': 'Resource updated successfully'}
    if tn.startswith('associate_'):
        return {
            'success': True, 'simulated': True,
            'association_id': 'eipassoc-' + _rand_id(length=8),
            'message': f'[Sandbox] Resource associated successfully'
        }
    if tn.startswith('disassociate_'):
        return {'success': True, 'simulated': True, 'message': '[Sandbox] Resource disassociated successfully'}
    if tn in ('add_tags', 'remove_tags'):
        ids = tool_input.get('resource_ids', [])
        return {
            'success': True, 'simulated': True,
            'resource_ids': ids,
            'message': f'[Sandbox] Tags updated on {len(ids)} resource(s)'
        }
    if tn == 'list_resources_by_tag':
        tag_key = tool_input.get('tag_key', 'Environment')
        tag_value = tool_input.get('tag_value', 'production')
        return {
            'success': True, 'simulated': True,
            'tag_filter': {tag_key: tag_value},
            'total_resources': 3,
            'resources': {
                'instances': [
                    {'id': 'i-' + _rand_id(length=17), 'state': 'running', 'type': 't3.medium',
                     'tags': {tag_key: tag_value, 'Name': 'web-server-1'}},
                    {'id': 'i-' + _rand_id(length=17), 'state': 'running', 'type': 't3.small',
                     'tags': {tag_key: tag_value, 'Name': 'api-server-1'}},
                ],
                'volumes': [
                    {'id': 'vol-' + _rand_id(length=17), 'size_gb': 100, 'state': 'in-use',
                     'tags': {tag_key: tag_value}}
                ]
            },
            'message': f'Found 3 resource(s) with tag {tag_key}={tag_value}'
        }

    # Fallback
    return {
        'success': True, 'simulated': True,
        'message': f'[Sandbox] Tool "{tool_name}" executed with simulated results'
    }
