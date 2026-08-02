"""AWS tools for DevOps Agent."""
import boto3
import json
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import threading
import time
from ..utils import get_logger


logger = get_logger(__name__)

# Thread-local storage for user context
_user_context = threading.local()


def set_user_context(user_id: Optional[int] = None):
    """
    Set user context for AWS operations in this thread.

    Args:
        user_id: User ID to use for credential lookup
    """
    _user_context.user_id = user_id


def clear_user_context():
    """Clear user context from this thread."""
    _user_context.user_id = None


def get_current_user_id() -> Optional[int]:
    """Get the current user ID from thread-local storage."""
    return getattr(_user_context, 'user_id', None)


def _get_effective_region(region: Optional[str] = None) -> str:
    """Return the actual AWS region that will be used for an operation.

    When no explicit region is passed, reads the user's configured default
    region from credentials so callers can report it accurately.
    """
    if region:
        return region
    user_id = get_current_user_id()
    if user_id:
        try:
            from services.credential_service import get_user_aws_credentials
            creds = get_user_aws_credentials(user_id)
            if creds:
                return creds.get('region', 'us-east-1')
        except Exception:
            pass
    return 'us-east-1'


def _get_boto_client(service: str, region: Optional[str] = None):
    """
    Get boto3 client for AWS service using per-user credentials ONLY.

    SECURITY: Never falls back to environment/IAM role credentials.
    Each user MUST configure their own AWS credentials.

    Args:
        service: AWS service name
        region: AWS region

    Returns:
        Boto3 client instance

    Raises:
        Exception: If user context is not set or credentials are not configured
    """
    user_id = get_current_user_id()

    # SECURITY: User context is REQUIRED - no anonymous AWS access
    if user_id is None:
        logger.error("AWS operation attempted without user context")
        raise Exception(
            "Authentication required. Please log in to access AWS resources."
        )

    # Use per-user credentials ONLY - no fallback to shared credentials
    try:
        # Import here to avoid circular dependency
        import sys
        import os

        # Add parent directory to path to import from services
        parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        from services.credential_service import get_user_boto_client

        return get_user_boto_client(user_id, service, region)
    except Exception as e:
        logger.error(f"Failed to get AWS credentials for user {user_id}: {str(e)}")
        # SECURITY: Do NOT fall back to environment/IAM role credentials
        # Re-raise the original error so the agent sees what actually went wrong
        raise


def get_ec2_instances(
    filters: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get list of EC2 instances with optional filtering.

    Args:
        filters: Dictionary of filters (e.g., {'Name': 'tag:Environment', 'Values': ['production']})
        region: AWS region (optional)

    Returns:
        Dictionary with instance information
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        # Build filters
        boto_filters = []
        if filters:
            for key, value in filters.items():
                boto_filters.append({'Name': key, 'Values': [value] if isinstance(value, str) else value})

        response = ec2.describe_instances(Filters=boto_filters if boto_filters else [])

        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                # Extract comprehensive information
                tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}

                # Build comprehensive instance details
                inst_details = {
                    # Basic Details
                    'instance_id': instance['InstanceId'],
                    'instance_type': instance['InstanceType'],
                    'ami_id': instance['ImageId'],
                    'launch_time': instance['LaunchTime'].isoformat(),
                    'availability_zone': instance['Placement']['AvailabilityZone'],
                    'platform': instance.get('Platform', 'Linux/UNIX'),
                    'architecture': instance.get('Architecture', 'x86_64'),
                    'virtualization_type': instance.get('VirtualizationType', 'hvm'),

                    # Status
                    'state': instance['State']['Name'],
                    'state_code': instance['State']['Code'],
                    'monitoring_state': instance['Monitoring']['State'],

                    # Networking
                    'vpc_id': instance.get('VpcId', 'EC2-Classic'),
                    'subnet_id': instance.get('SubnetId', 'N/A'),
                    'private_ip': instance.get('PrivateIpAddress', 'N/A'),
                    'private_dns': instance.get('PrivateDnsName', 'N/A'),
                    'public_ip': instance.get('PublicIpAddress', 'N/A'),
                    'public_dns': instance.get('PublicDnsName', 'N/A'),

                    # Security
                    'security_groups': [
                        {'id': sg['GroupId'], 'name': sg['GroupName']}
                        for sg in instance.get('SecurityGroups', [])
                    ],
                    'key_pair': instance.get('KeyName', 'No key pair'),
                    'iam_role': instance.get('IamInstanceProfile', {}).get('Arn', 'No IAM role'),

                    # Storage
                    'root_device_type': instance.get('RootDeviceType', 'ebs'),
                    'root_device_name': instance.get('RootDeviceName', '/dev/xvda'),
                    'block_devices': [
                        {
                            'device_name': bd['DeviceName'],
                            'volume_id': bd['Ebs']['VolumeId'],
                            'status': bd['Ebs']['Status'],
                            'delete_on_termination': bd['Ebs']['DeleteOnTermination'],
                        } for bd in instance.get('BlockDeviceMappings', [])
                    ],
                    'ebs_optimized': instance.get('EbsOptimized', False),

                    # Tags
                    'tags': tags,
                    'name': tags.get('Name', 'N/A'),
                }

                instances.append(inst_details)

        return {
            'success': True,
            'count': len(instances),
            'instances': instances,
            'region': _get_effective_region(region),
            'message': f'Found {len(instances)} EC2 instance(s)'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error getting EC2 instances: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def manage_ec2_instance(
    instance_id: str,
    action: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manage EC2 instance (start, stop, reboot, terminate).

    Args:
        instance_id: EC2 instance ID
        action: Action to perform (start, stop, reboot, terminate)
        region: AWS region

    Returns:
        Dictionary with action result
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        action = action.lower()
        if action == 'start':
            response = ec2.start_instances(InstanceIds=[instance_id])
        elif action == 'stop':
            response = ec2.stop_instances(InstanceIds=[instance_id])
        elif action == 'reboot':
            response = ec2.reboot_instances(InstanceIds=[instance_id])
            response = {'StartingInstances': [{'InstanceId': instance_id}]}
        elif action == 'terminate':
            response = ec2.terminate_instances(InstanceIds=[instance_id])
        else:
            return {
                'success': False,
                'error': f"Invalid action: {action}. Must be one of: start, stop, reboot, terminate"
            }

        return {
            'success': True,
            'action': action,
            'instance_id': instance_id,
            'message': f"Successfully {action}ed instance {instance_id}",
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error managing EC2 instance: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def resize_ec2_instance(
    instance_id: str,
    new_instance_type: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resize an EC2 instance by changing its type.

    Workflow: stop instance → wait for stopped state → modify instance type → start instance.

    Args:
        instance_id: EC2 instance ID
        new_instance_type: Target instance type (e.g., 't3.small', 't3.medium')
        region: AWS region

    Returns:
        Dictionary with resize result
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        # Step 1: Stop the instance
        logger.info(f"Stopping instance {instance_id} for resize to {new_instance_type}")
        ec2.stop_instances(InstanceIds=[instance_id])

        # Step 2: Wait for instance to be stopped
        waiter = ec2.get_waiter('instance_stopped')
        waiter.wait(InstanceIds=[instance_id])
        logger.info(f"Instance {instance_id} stopped successfully")

        # Step 3: Modify instance type
        logger.info(f"Modifying instance {instance_id} type to {new_instance_type}")
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            InstanceType={'Value': new_instance_type}
        )

        # Step 4: Start the instance
        logger.info(f"Starting instance {instance_id}")
        ec2.start_instances(InstanceIds=[instance_id])

        return {
            'success': True,
            'instance_id': instance_id,
            'new_instance_type': new_instance_type,
            'message': f"Successfully resized instance {instance_id} to {new_instance_type}",
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error during resize: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code'],
            'instance_id': instance_id
        }
    except Exception as e:
        logger.error(f"Error resizing EC2 instance: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'instance_id': instance_id
        }


def describe_security_group(
    group_id: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Describe a security group with full rule details.

    Args:
        group_id: Security group ID
        region: AWS region

    Returns:
        Dictionary with security group details including ingress and egress rules
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        response = ec2.describe_security_groups(GroupIds=[group_id])
        if not response['SecurityGroups']:
            return {'success': False, 'error': f"Security group {group_id} not found"}

        sg = response['SecurityGroups'][0]

        # Format ingress rules
        ingress_rules = []
        for rule in sg.get('IpPermissions', []):
            protocol = rule.get('IpProtocol', '-1')
            from_port = rule.get('FromPort')
            to_port = rule.get('ToPort')

            # Handle CIDR blocks
            for cidr_info in rule.get('IpRanges', []):
                ingress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'cidr': cidr_info.get('CidrIp'),
                    'description': cidr_info.get('Description', '')
                })

            # Handle IPv6 CIDR blocks
            for cidr_info in rule.get('Ipv6Ranges', []):
                ingress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'cidr': cidr_info.get('CidrIpv6'),
                    'description': cidr_info.get('Description', '')
                })

            # Handle source security groups
            for sg_info in rule.get('UserIdGroupPairs', []):
                ingress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'source_sg_id': sg_info.get('GroupId'),
                    'source_sg_owner_id': sg_info.get('UserId'),
                    'description': sg_info.get('Description', '')
                })

        # Format egress rules
        egress_rules = []
        for rule in sg.get('IpPermissionsEgress', []):
            protocol = rule.get('IpProtocol', '-1')
            from_port = rule.get('FromPort')
            to_port = rule.get('ToPort')

            for cidr_info in rule.get('IpRanges', []):
                egress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'cidr': cidr_info.get('CidrIp'),
                    'description': cidr_info.get('Description', '')
                })

            for cidr_info in rule.get('Ipv6Ranges', []):
                egress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'cidr': cidr_info.get('CidrIpv6'),
                    'description': cidr_info.get('Description', '')
                })

            for sg_info in rule.get('UserIdGroupPairs', []):
                egress_rules.append({
                    'protocol': protocol,
                    'from_port': from_port,
                    'to_port': to_port,
                    'source_sg_id': sg_info.get('GroupId'),
                    'source_sg_owner_id': sg_info.get('UserId'),
                    'description': sg_info.get('Description', '')
                })

        return {
            'success': True,
            'group_id': sg.get('GroupId'),
            'group_name': sg.get('GroupName'),
            'description': sg.get('GroupDescription', ''),
            'vpc_id': sg.get('VpcId'),
            'ingress_rules': ingress_rules,
            'ingress_rules_count': len(ingress_rules),
            'egress_rules': egress_rules,
            'egress_rules_count': len(egress_rules),
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error describing security group: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error describing security group: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_s3_buckets(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List all S3 buckets.

    Args:
        region: AWS region (optional, S3 is global but region can be specified)

    Returns:
        Dictionary with bucket information
    """
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.list_buckets()

        buckets = []
        for bucket in response['Buckets']:
            buckets.append({
                'name': bucket['Name'],
                'creation_date': bucket['CreationDate'].isoformat()
            })

        return {
            'success': True,
            'count': len(buckets),
            'buckets': buckets
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error listing S3 buckets: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_s3_bucket_info(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """
    Get detailed information about an S3 bucket.

    Args:
        bucket_name: Name of the S3 bucket
        region: AWS region

    Returns:
        Dictionary with bucket information
    """
    try:
        s3 = _get_boto_client('s3', region)

        # Get bucket location
        try:
            location_response = s3.get_bucket_location(Bucket=bucket_name)
            location = location_response['LocationConstraint'] or 'us-east-1'
        except Exception:
            location = 'unknown'

        # Get bucket size (list objects and calculate)
        try:
            paginator = s3.get_paginator('list_objects_v2')
            total_size = 0
            object_count = 0

            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        total_size += obj['Size']
                        object_count += 1

            size_mb = total_size / (1024 * 1024)
        except Exception:
            size_mb = 0
            object_count = 0

        return {
            'success': True,
            'bucket_name': bucket_name,
            'location': location,
            'object_count': object_count,
            'total_size_mb': round(size_mb, 2)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error getting S3 bucket info: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def get_eks_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    Get list of EKS clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with cluster information
    """
    try:
        eks = _get_boto_client('eks', region)
        response = eks.list_clusters()

        clusters = []
        for cluster_name in response['clusters']:
            # Get detailed cluster info
            cluster_info = eks.describe_cluster(name=cluster_name)['cluster']

            clusters.append({
                'name': cluster_info['name'],
                'status': cluster_info['status'],
                'version': cluster_info['version'],
                'endpoint': cluster_info['endpoint'],
                'created_at': cluster_info['createdAt'].isoformat(),
                'arn': cluster_info['arn']
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error getting EKS clusters: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_eks_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List all EKS clusters with their node group details.

    Args:
        region: AWS region

    Returns:
        Dictionary with cluster and node group information
    """
    try:
        eks = _get_boto_client('eks', region)
        paginator = eks.get_paginator('list_clusters')

        cluster_names = []
        for page in paginator.paginate():
            cluster_names.extend(page.get('clusters', []))

        clusters_detail = []
        for name in cluster_names:
            desc = eks.describe_cluster(name=name)['cluster']

            ng_names = eks.list_nodegroups(clusterName=name).get('nodegroups', [])
            node_groups = []
            for ng_name in ng_names:
                ng = eks.describe_nodegroup(clusterName=name, nodegroupName=ng_name)['nodegroup']
                node_groups.append({
                    'name': ng_name,
                    'status': ng.get('status', ''),
                    'instance_types': ng.get('instanceTypes', []),
                    'desired': ng.get('scalingConfig', {}).get('desiredSize', 0),
                    'min': ng.get('scalingConfig', {}).get('minSize', 0),
                    'max': ng.get('scalingConfig', {}).get('maxSize', 0),
                    'ami_type': ng.get('amiType', ''),
                })

            clusters_detail.append({
                'name': name,
                'status': desc.get('status', ''),
                'k8s_version': desc.get('version', ''),
                'endpoint': desc.get('endpoint', 'N/A'),
                'role_arn': desc.get('roleArn', ''),
                'vpc_id': desc.get('resourcesVpcConfig', {}).get('vpcId', ''),
                'logging': desc.get('logging', {}).get('clusterLogging', []),
                'node_groups': node_groups,
                'tags': desc.get('tags', {}),
            })

        return {
            'success': True,
            'count': len(clusters_detail),
            'clusters': clusters_detail,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EKS clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_eks_cluster(
    cluster_name: str,
    role_arn: str,
    subnet_ids: List[str],
    security_group_ids: Optional[List[str]] = None,
    kubernetes_version: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EKS (Kubernetes) cluster."""
    try:
        eks = _get_boto_client('eks', region)
        vpc_config = {'subnetIds': subnet_ids}
        if security_group_ids:
            vpc_config['securityGroupIds'] = security_group_ids

        params = {
            'name': cluster_name,
            'roleArn': role_arn,
            'resourcesVpcConfig': vpc_config,
        }
        if kubernetes_version:
            params['version'] = kubernetes_version
        if tags:
            params['tags'] = tags

        response = eks.create_cluster(**params)
        cluster = response['cluster']
        return {
            'success': True, 'cluster_name': cluster['name'],
            'arn': cluster['arn'], 'status': cluster['status'],
            'kubernetes_version': cluster.get('version'),
            'endpoint': cluster.get('endpoint', 'Provisioning...'),
            'message': f'Successfully initiated EKS cluster creation: {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EKS cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_eks_cluster(cluster_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an EKS cluster. Node groups must be deleted first."""
    try:
        eks = _get_boto_client('eks', region)
        eks.delete_cluster(name=cluster_name)
        return {
            'success': True, 'cluster_name': cluster_name,
            'message': f'Successfully initiated deletion of EKS cluster {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting EKS cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_eks_node_group(
    cluster_name: str,
    node_group_name: str,
    node_role_arn: str,
    subnet_ids: List[str],
    instance_types: Optional[List[str]] = None,
    scaling_config_min: int = 1,
    scaling_config_max: int = 3,
    scaling_config_desired: int = 2,
    disk_size: int = 20,
    ami_type: str = 'AL2_x86_64',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EKS managed node group."""
    try:
        eks = _get_boto_client('eks', region)
        params = {
            'clusterName': cluster_name,
            'nodegroupName': node_group_name,
            'nodeRole': node_role_arn,
            'subnets': subnet_ids,
            'scalingConfig': {
                'minSize': scaling_config_min,
                'maxSize': scaling_config_max,
                'desiredSize': scaling_config_desired,
            },
            'diskSize': disk_size,
            'amiType': ami_type,
        }
        if instance_types:
            params['instanceTypes'] = instance_types

        response = eks.create_nodegroup(**params)
        ng = response['nodegroup']
        return {
            'success': True, 'node_group_name': ng['nodegroupName'],
            'cluster_name': ng['clusterName'], 'status': ng['status'],
            'scaling': ng.get('scalingConfig'),
            'message': f'Successfully initiated node group creation: {node_group_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EKS node group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---- EKS Extended ----

def describe_eks_cluster(cluster_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed info about an EKS cluster: endpoint, version, OIDC, logging, status."""
    try:
        eks = _get_boto_client('eks', region)
        cluster = eks.describe_cluster(name=cluster_name)['cluster']
        return {
            'success': True,
            'name': cluster['name'],
            'arn': cluster['arn'],
            'status': cluster['status'],
            'version': cluster['version'],
            'endpoint': cluster.get('endpoint'),
            'role_arn': cluster.get('roleArn'),
            'kubernetes_network_config': cluster.get('kubernetesNetworkConfig'),
            'resources_vpc_config': cluster.get('resourcesVpcConfig'),
            'logging': cluster.get('logging'),
            'identity': cluster.get('identity'),
            'tags': cluster.get('tags', {}),
            'created_at': cluster['createdAt'].isoformat() if cluster.get('createdAt') else None,
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_eks_cluster_version(
    cluster_name: str,
    kubernetes_version: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Upgrade the Kubernetes control plane version of an EKS cluster."""
    try:
        eks = _get_boto_client('eks', region)
        response = eks.update_cluster_version(name=cluster_name, version=kubernetes_version)
        update = response['update']
        return {
            'success': True,
            'cluster_name': cluster_name,
            'update_id': update['id'],
            'status': update['status'],
            'kubernetes_version': kubernetes_version,
            'message': f'Cluster version update initiated to {kubernetes_version}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_eks_cluster_config(
    cluster_name: str,
    endpoint_public_access: Optional[bool] = None,
    endpoint_private_access: Optional[bool] = None,
    public_access_cidrs: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Modify EKS API server endpoint access (public/private)."""
    try:
        eks = _get_boto_client('eks', region)
        vpc_config = {}
        if endpoint_public_access is not None:
            vpc_config['endpointPublicAccess'] = endpoint_public_access
        if endpoint_private_access is not None:
            vpc_config['endpointPrivateAccess'] = endpoint_private_access
        if public_access_cidrs:
            vpc_config['publicAccessCidrs'] = public_access_cidrs
        response = eks.update_cluster_config(name=cluster_name, resourcesVpcConfig=vpc_config)
        update = response['update']
        return {
            'success': True,
            'cluster_name': cluster_name,
            'update_id': update['id'],
            'status': update['status'],
            'message': f'Cluster config update initiated for {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def enable_eks_control_plane_logging(
    cluster_name: str,
    log_types: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable EKS control plane logging to CloudWatch (api, audit, authenticator, controllerManager, scheduler)."""
    try:
        eks = _get_boto_client('eks', region)
        types = log_types or ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler']
        response = eks.update_cluster_config(
            name=cluster_name,
            logging={'clusterLogging': [{'types': types, 'enabled': True}]}
        )
        update = response['update']
        return {
            'success': True,
            'cluster_name': cluster_name,
            'update_id': update['id'],
            'log_types_enabled': types,
            'message': f'Control plane logging enabled for {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def associate_eks_oidc_provider(
    cluster_name: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Associate an OIDC identity provider with an EKS cluster to enable IRSA."""
    try:
        import urllib.request
        import hashlib
        eks = _get_boto_client('eks', region)
        iam = _get_boto_client('iam', region)

        cluster = eks.describe_cluster(name=cluster_name)['cluster']
        oidc_issuer = cluster.get('identity', {}).get('oidc', {}).get('issuer')
        if not oidc_issuer:
            return {'success': False, 'error': 'Cluster has no OIDC issuer. Ensure the cluster is active.'}

        # Derive thumbprint from OIDC issuer
        from ..utils.network_safety import assert_safe_url
        assert_safe_url(oidc_issuer)
        oidc_host = oidc_issuer.replace('https://', '')
        try:
            import ssl
            conn = ssl.create_default_context()
            cert = ssl.get_server_certificate((oidc_host.split('/')[0], 443))
            thumbprint = hashlib.sha1(ssl.PEM_cert_to_DER_cert(cert)).hexdigest()
        except Exception as ssl_err:
            return {'success': False, 'error': f'Could not derive OIDC thumbprint from {oidc_host}: {ssl_err}'}

        iam.create_open_id_connect_provider(
            Url=oidc_issuer,
            ClientIDList=['sts.amazonaws.com'],
            ThumbprintList=[thumbprint]
        )
        return {
            'success': True,
            'cluster_name': cluster_name,
            'oidc_issuer': oidc_issuer,
            'message': f'OIDC provider associated for {cluster_name}. IRSA is now enabled.',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'EntityAlreadyExists':
            return {'success': True, 'message': 'OIDC provider already exists', 'cluster_name': cluster_name}
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_eks_node_group(
    cluster_name: str,
    node_group_name: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a managed node group from an EKS cluster."""
    try:
        eks = _get_boto_client('eks', region)
        eks.delete_nodegroup(clusterName=cluster_name, nodegroupName=node_group_name)
        return {
            'success': True,
            'cluster_name': cluster_name,
            'node_group_name': node_group_name,
            'message': f'Node group {node_group_name} deletion initiated',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_eks_node_groups(cluster_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """List all node groups in an EKS cluster."""
    try:
        eks = _get_boto_client('eks', region)
        response = eks.list_nodegroups(clusterName=cluster_name)
        node_groups = []
        for ng_name in response.get('nodegroups', []):
            ng = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=ng_name)['nodegroup']
            node_groups.append({
                'name': ng['nodegroupName'],
                'status': ng['status'],
                'instance_types': ng.get('instanceTypes', []),
                'ami_type': ng.get('amiType'),
                'scaling_config': ng.get('scalingConfig', {}),
                'disk_size': ng.get('diskSize'),
                'release_version': ng.get('releaseVersion'),
                'created_at': ng['createdAt'].isoformat() if ng.get('createdAt') else None,
            })
        return {'success': True, 'cluster_name': cluster_name, 'node_groups': node_groups, 'count': len(node_groups)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def describe_eks_node_group(
    cluster_name: str,
    node_group_name: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Get full details of an EKS node group: AMI, instance type, scaling, and status."""
    try:
        eks = _get_boto_client('eks', region)
        ng = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=node_group_name)['nodegroup']
        return {
            'success': True,
            'name': ng['nodegroupName'],
            'cluster_name': cluster_name,
            'status': ng['status'],
            'instance_types': ng.get('instanceTypes', []),
            'ami_type': ng.get('amiType'),
            'release_version': ng.get('releaseVersion'),
            'scaling_config': ng.get('scalingConfig', {}),
            'disk_size': ng.get('diskSize'),
            'node_role': ng.get('nodeRole'),
            'subnets': ng.get('subnets', []),
            'labels': ng.get('labels', {}),
            'taints': ng.get('taints', []),
            'tags': ng.get('tags', {}),
            'created_at': ng['createdAt'].isoformat() if ng.get('createdAt') else None,
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_eks_node_group_version(
    cluster_name: str,
    node_group_name: str,
    kubernetes_version: Optional[str] = None,
    release_version: Optional[str] = None,
    force: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Upgrade node group AMI or Kubernetes version."""
    try:
        eks = _get_boto_client('eks', region)
        params = {'clusterName': cluster_name, 'nodegroupName': node_group_name, 'force': force}
        if kubernetes_version:
            params['version'] = kubernetes_version
        if release_version:
            params['releaseVersion'] = release_version
        response = eks.update_nodegroup_version(**params)
        update = response['update']
        return {
            'success': True,
            'cluster_name': cluster_name,
            'node_group_name': node_group_name,
            'update_id': update['id'],
            'status': update['status'],
            'message': f'Node group version update initiated for {node_group_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_eks_node_group_config(
    cluster_name: str,
    node_group_name: str,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    desired_size: Optional[int] = None,
    labels_add: Optional[Dict[str, str]] = None,
    labels_remove: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Modify min/max/desired scaling values for a node group."""
    try:
        eks = _get_boto_client('eks', region)
        params = {'clusterName': cluster_name, 'nodegroupName': node_group_name}
        scaling = {}
        if min_size is not None:
            scaling['minSize'] = min_size
        if max_size is not None:
            scaling['maxSize'] = max_size
        if desired_size is not None:
            scaling['desiredSize'] = desired_size
        if scaling:
            params['scalingConfig'] = scaling
        labels = {}
        if labels_add:
            labels['addOrUpdateLabels'] = labels_add
        if labels_remove:
            labels['removeLabels'] = labels_remove
        if labels:
            params['labels'] = labels
        response = eks.update_nodegroup_config(**params)
        update = response['update']
        return {
            'success': True,
            'cluster_name': cluster_name,
            'node_group_name': node_group_name,
            'update_id': update['id'],
            'message': f'Node group config update initiated for {node_group_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_eks_fargate_profile(
    cluster_name: str,
    profile_name: str,
    pod_execution_role_arn: str,
    selectors: List[Dict],
    subnets: Optional[List[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Fargate profile to run pods serverlessly without managing nodes."""
    try:
        eks = _get_boto_client('eks', region)
        params = {
            'clusterName': cluster_name,
            'fargateProfileName': profile_name,
            'podExecutionRoleArn': pod_execution_role_arn,
            'selectors': selectors,
        }
        if subnets:
            params['subnets'] = subnets
        if tags:
            params['tags'] = tags
        response = eks.create_fargate_profile(**params)
        profile = response['fargateProfile']
        return {
            'success': True,
            'profile_name': profile['fargateProfileName'],
            'cluster_name': cluster_name,
            'status': profile['status'],
            'selectors': profile.get('selectors', []),
            'message': f'Fargate profile {profile_name} creation initiated',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_eks_fargate_profile(
    cluster_name: str,
    profile_name: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete an EKS Fargate profile."""
    try:
        eks = _get_boto_client('eks', region)
        eks.delete_fargate_profile(clusterName=cluster_name, fargateProfileName=profile_name)
        return {
            'success': True,
            'profile_name': profile_name,
            'cluster_name': cluster_name,
            'message': f'Fargate profile {profile_name} deletion initiated',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_eks_fargate_profiles(cluster_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """List all Fargate profiles for an EKS cluster."""
    try:
        eks = _get_boto_client('eks', region)
        response = eks.list_fargate_profiles(clusterName=cluster_name)
        profiles = []
        for name in response.get('fargateProfileNames', []):
            p = eks.describe_fargate_profile(clusterName=cluster_name, fargateProfileName=name)['fargateProfile']
            profiles.append({
                'name': p['fargateProfileName'],
                'status': p['status'],
                'selectors': p.get('selectors', []),
                'subnets': p.get('subnets', []),
            })
        return {'success': True, 'cluster_name': cluster_name, 'fargate_profiles': profiles, 'count': len(profiles)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_eks_access_entry(
    cluster_name: str,
    principal_arn: str,
    username: Optional[str] = None,
    groups: Optional[List[str]] = None,
    entry_type: str = 'STANDARD',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Add an IAM principal to cluster access using the EKS Access API."""
    try:
        eks = _get_boto_client('eks', region)
        params = {'clusterName': cluster_name, 'principalArn': principal_arn, 'type': entry_type}
        if username:
            params['username'] = username
        if groups:
            params['kubernetesGroups'] = groups
        response = eks.create_access_entry(**params)
        entry = response['accessEntry']
        return {
            'success': True,
            'principal_arn': principal_arn,
            'cluster_name': cluster_name,
            'username': entry.get('username'),
            'groups': entry.get('kubernetesGroups', []),
            'message': f'Access entry created for {principal_arn}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_eks_access_entry(
    cluster_name: str,
    principal_arn: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Remove an IAM principal's cluster access entry."""
    try:
        eks = _get_boto_client('eks', region)
        eks.delete_access_entry(clusterName=cluster_name, principalArn=principal_arn)
        return {
            'success': True,
            'principal_arn': principal_arn,
            'cluster_name': cluster_name,
            'message': f'Access entry deleted for {principal_arn}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def associate_eks_access_policy(
    cluster_name: str,
    principal_arn: str,
    policy_arn: str,
    access_scope_type: str = 'cluster',
    namespaces: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Bind an EKS access policy (e.g., AmazonEKSClusterAdminPolicy) to a principal."""
    try:
        eks = _get_boto_client('eks', region)
        access_scope = {'type': access_scope_type}
        if access_scope_type == 'namespace' and namespaces:
            access_scope['namespaces'] = namespaces
        eks.associate_access_policy(
            clusterName=cluster_name,
            principalArn=principal_arn,
            policyArn=policy_arn,
            accessScope=access_scope
        )
        return {
            'success': True,
            'principal_arn': principal_arn,
            'policy_arn': policy_arn,
            'cluster_name': cluster_name,
            'access_scope': access_scope,
            'message': f'Policy {policy_arn} associated with {principal_arn}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def generate_eks_kubeconfig(
    cluster_name: str,
    region: Optional[str] = None,
    role_arn: Optional[str] = None
) -> Dict[str, Any]:
    """Generate kubeconfig content for kubectl access to an EKS cluster."""
    try:
        import subprocess
        cmd = ['aws', 'eks', 'update-kubeconfig', '--name', cluster_name]
        if region:
            cmd.extend(['--region', region])
        if role_arn:
            cmd.extend(['--role-arn', role_arn])
        cmd.extend(['--dry-run'])
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return {
                'success': True,
                'cluster_name': cluster_name,
                'kubeconfig': result.stdout,
                'message': f'Kubeconfig generated for {cluster_name}',
                'region': _get_effective_region(region)
            }
        # Fallback: build config manually using boto3
        eks = _get_boto_client('eks', region)
        cluster = eks.describe_cluster(name=cluster_name)['cluster']
        endpoint = cluster.get('endpoint', '')
        ca_data = cluster.get('certificateAuthority', {}).get('data', '')
        kubeconfig = {
            'apiVersion': 'v1',
            'clusters': [{'cluster': {'certificate-authority-data': ca_data, 'server': endpoint}, 'name': cluster_name}],
            'contexts': [{'context': {'cluster': cluster_name, 'user': cluster_name}, 'name': cluster_name}],
            'current-context': cluster_name,
            'kind': 'Config',
            'users': [{'name': cluster_name, 'user': {'exec': {
                'apiVersion': 'client.authentication.k8s.io/v1beta1',
                'command': 'aws',
                'args': ['eks', 'get-token', '--cluster-name', cluster_name] + (['--region', region] if region else []),
            }}}]
        }
        return {
            'success': True,
            'cluster_name': cluster_name,
            'kubeconfig': json.dumps(kubeconfig, indent=2),
            'message': f'Kubeconfig generated for {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_eks_addon(
    cluster_name: str,
    addon_name: str,
    addon_version: Optional[str] = None,
    service_account_role_arn: Optional[str] = None,
    resolve_conflicts: str = 'OVERWRITE',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Install a managed EKS add-on (CoreDNS, kube-proxy, vpc-cni, aws-ebs-csi-driver)."""
    try:
        eks = _get_boto_client('eks', region)
        params = {
            'clusterName': cluster_name,
            'addonName': addon_name,
            'resolveConflicts': resolve_conflicts,
        }
        if addon_version:
            params['addonVersion'] = addon_version
        if service_account_role_arn:
            params['serviceAccountRoleArn'] = service_account_role_arn
        response = eks.create_addon(**params)
        addon = response['addon']
        return {
            'success': True,
            'addon_name': addon['addonName'],
            'cluster_name': cluster_name,
            'status': addon['status'],
            'version': addon.get('addonVersion'),
            'message': f'Add-on {addon_name} installation initiated on {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_eks_addon(
    cluster_name: str,
    addon_name: str,
    preserve: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Remove an installed EKS add-on."""
    try:
        eks = _get_boto_client('eks', region)
        eks.delete_addon(clusterName=cluster_name, addonName=addon_name, preserve=preserve)
        return {
            'success': True,
            'addon_name': addon_name,
            'cluster_name': cluster_name,
            'message': f'Add-on {addon_name} deletion initiated',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_eks_addons(cluster_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """List all installed add-ons and their versions for an EKS cluster."""
    try:
        eks = _get_boto_client('eks', region)
        response = eks.list_addons(clusterName=cluster_name)
        addons = []
        for name in response.get('addons', []):
            addon = eks.describe_addon(clusterName=cluster_name, addonName=name)['addon']
            addons.append({
                'name': addon['addonName'],
                'version': addon.get('addonVersion'),
                'status': addon['status'],
                'service_account_role_arn': addon.get('serviceAccountRoleArn'),
                'created_at': addon['createdAt'].isoformat() if addon.get('createdAt') else None,
            })
        return {'success': True, 'cluster_name': cluster_name, 'addons': addons, 'count': len(addons)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def update_eks_addon(
    cluster_name: str,
    addon_name: str,
    addon_version: str,
    resolve_conflicts: str = 'OVERWRITE',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Upgrade an EKS add-on to a newer version."""
    try:
        eks = _get_boto_client('eks', region)
        response = eks.update_addon(
            clusterName=cluster_name,
            addonName=addon_name,
            addonVersion=addon_version,
            resolveConflicts=resolve_conflicts
        )
        update = response['update']
        return {
            'success': True,
            'addon_name': addon_name,
            'cluster_name': cluster_name,
            'update_id': update['id'],
            'status': update['status'],
            'addon_version': addon_version,
            'message': f'Add-on {addon_name} update initiated to version {addon_version}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def describe_eks_addon_versions(
    addon_name: str,
    kubernetes_version: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List available versions for a given EKS add-on."""
    try:
        eks = _get_boto_client('eks', region)
        params = {'addonName': addon_name}
        if kubernetes_version:
            params['kubernetesVersion'] = kubernetes_version
        response = eks.describe_addon_versions(**params)
        addons = []
        for addon in response.get('addons', []):
            for version in addon.get('addonVersions', []):
                addons.append({
                    'addon_name': addon['addonName'],
                    'version': version['addonVersion'],
                    'default_version': version.get('compatibilities', [{}])[0].get('defaultVersion', False),
                    'compatible_k8s': [c.get('clusterVersion') for c in version.get('compatibilities', [])],
                })
        return {'success': True, 'addon_name': addon_name, 'versions': addons, 'count': len(addons)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_cloudwatch_logs(
    log_group: str,
    log_stream: Optional[str] = None,
    hours: int = 1,
    filter_pattern: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get CloudWatch logs from a log group.

    Args:
        log_group: CloudWatch log group name
        log_stream: Specific log stream name (optional)
        hours: Number of hours to look back (default: 1)
        filter_pattern: Filter pattern for log events
        region: AWS region

    Returns:
        Dictionary with log events
    """
    try:
        logs = _get_boto_client('logs', region)

        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        # Query logs
        if log_stream:
            # Get logs from specific stream
            response = logs.get_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                startTime=start_ms,
                endTime=end_ms,
                limit=100
            )
            events = response['events']
        else:
            # Filter across all streams
            kwargs = {
                'logGroupName': log_group,
                'startTime': start_ms,
                'endTime': end_ms,
                'limit': 100
            }
            if filter_pattern:
                kwargs['filterPattern'] = filter_pattern

            response = logs.filter_log_events(**kwargs)
            events = response['events']

        # Format events
        formatted_events = []
        for event in events:
            formatted_events.append({
                'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat(),
                'message': event['message'],
                'log_stream': event.get('logStreamName', 'N/A')
            })

        return {
            'success': True,
            'log_group': log_group,
            'count': len(formatted_events),
            'events': formatted_events,
            'time_range_hours': hours,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error getting CloudWatch logs: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_iam_users() -> Dict[str, Any]:
    """
    List IAM users.

    Returns:
        Dictionary with user information
    """
    try:
        iam = _get_boto_client('iam')
        response = iam.list_users()

        users = []
        for user in response['Users']:
            users.append({
                'username': user['UserName'],
                'user_id': user['UserId'],
                'arn': user['Arn'],
                'created_date': user['CreateDate'].isoformat()
            })

        return {
            'success': True,
            'count': len(users),
            'users': users
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error listing IAM users: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def list_iam_roles() -> Dict[str, Any]:
    """
    List IAM roles.

    Returns:
        Dictionary with role information
    """
    try:
        iam = _get_boto_client('iam')
        response = iam.list_roles()

        roles = []
        for role in response['Roles']:
            roles.append({
                'role_name': role['RoleName'],
                'role_id': role['RoleId'],
                'arn': role['Arn'],
                'created_date': role['CreateDate'].isoformat(),
                'description': role.get('Description', 'N/A')
            })

        return {
            'success': True,
            'count': len(roles),
            'roles': roles
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error listing IAM roles: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def create_iam_role(
    role_name: str,
    assume_role_policy: str,
    description: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create an IAM role with a trust policy."""
    try:
        iam = _get_boto_client('iam')
        params = {'RoleName': role_name, 'AssumeRolePolicyDocument': assume_role_policy}
        if description:
            params['Description'] = description
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = iam.create_role(**params)
        role = response['Role']
        return {
            'success': True, 'role_name': role['RoleName'], 'arn': role['Arn'],
            'role_id': role['RoleId'], 'create_date': role['CreateDate'].isoformat(),
            'message': f'Successfully created IAM role {role_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating IAM role: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_iam_policy(
    policy_name: str,
    policy_document: str,
    description: Optional[str] = None,
    path: Optional[str] = None
) -> Dict[str, Any]:
    """Create an IAM policy."""
    try:
        iam = _get_boto_client('iam')
        params = {'PolicyName': policy_name, 'PolicyDocument': policy_document}
        if description:
            params['Description'] = description
        if path:
            params['Path'] = path

        response = iam.create_policy(**params)
        policy = response['Policy']
        return {
            'success': True, 'policy_name': policy['PolicyName'], 'arn': policy['Arn'],
            'policy_id': policy['PolicyId'], 'create_date': policy['CreateDate'].isoformat(),
            'message': f'Successfully created IAM policy {policy_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating IAM policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def attach_iam_role_policy(role_name: str, policy_arn: str) -> Dict[str, Any]:
    """Attach a managed policy to an IAM role."""
    try:
        iam = _get_boto_client('iam')
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
        return {
            'success': True, 'role_name': role_name, 'policy_arn': policy_arn,
            'message': f'Successfully attached policy {policy_arn} to role {role_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error attaching policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_role(role_name: str) -> Dict[str, Any]:
    """Delete an IAM role. Detaches all managed policies and deletes inline policies first."""
    try:
        iam = _get_boto_client('iam')

        # Detach all managed policies
        attached = iam.list_attached_role_policies(RoleName=role_name)
        for policy in attached.get('AttachedPolicies', []):
            iam.detach_role_policy(RoleName=role_name, PolicyArn=policy['PolicyArn'])

        # Delete all inline policies
        inline = iam.list_role_policies(RoleName=role_name)
        for policy_name in inline.get('PolicyNames', []):
            iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)

        # Remove role from instance profiles
        profiles = iam.list_instance_profiles_for_role(RoleName=role_name)
        for profile in profiles.get('InstanceProfiles', []):
            iam.remove_role_from_instance_profile(
                InstanceProfileName=profile['InstanceProfileName'], RoleName=role_name
            )

        iam.delete_role(RoleName=role_name)
        return {
            'success': True, 'role_name': role_name,
            'message': f'Successfully deleted IAM role: {role_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting IAM role: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# IAM EXTENDED OPERATIONS
# ============================================================================

# --- Users ---

def create_iam_user(
    username: str,
    path: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Create a new IAM user."""
    try:
        iam = _get_boto_client('iam')
        params: Dict = {'UserName': username}
        if path:
            params['Path'] = path
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]
        response = iam.create_user(**params)
        user = response['User']
        return {
            'success': True, 'username': username,
            'user_id': user['UserId'], 'arn': user['Arn'],
            'message': f'IAM user "{username}" created'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating IAM user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_iam_user(username: str) -> Dict[str, Any]:
    """Get details of a specific IAM user including groups and attached policies."""
    try:
        iam = _get_boto_client('iam')
        response = iam.get_user(UserName=username)
        user = response['User']

        groups = [g['GroupName'] for g in iam.list_groups_for_user(UserName=username).get('Groups', [])]
        attached = [p['PolicyName'] for p in iam.list_attached_user_policies(UserName=username).get('AttachedPolicies', [])]
        inline = iam.list_user_policies(UserName=username).get('PolicyNames', [])

        login_profile = None
        try:
            iam.get_login_profile(UserName=username)
            login_profile = 'enabled'
        except ClientError:
            login_profile = 'disabled'

        return {
            'success': True, 'username': username,
            'user_id': user['UserId'], 'arn': user['Arn'],
            'created': str(user['CreateDate']),
            'console_access': login_profile,
            'groups': groups, 'attached_policies': attached, 'inline_policies': inline,
            'tags': {t['Key']: t['Value'] for t in user.get('Tags', [])}
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting IAM user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_user(username: str) -> Dict[str, Any]:
    """
    Delete an IAM user and all associated resources (access keys, login profile,
    group memberships, policy attachments, MFA devices).
    """
    try:
        iam = _get_boto_client('iam')

        # Delete access keys
        for key in iam.list_access_keys(UserName=username).get('AccessKeyMetadata', []):
            iam.delete_access_key(UserName=username, AccessKeyId=key['AccessKeyId'])

        # Delete login profile
        try:
            iam.delete_login_profile(UserName=username)
        except ClientError:
            pass

        # Deactivate and delete MFA devices
        for device in iam.list_mfa_devices(UserName=username).get('MFADevices', []):
            iam.deactivate_mfa_device(UserName=username, SerialNumber=device['SerialNumber'])
            if device['SerialNumber'].startswith('arn'):
                try:
                    iam.delete_virtual_mfa_device(SerialNumber=device['SerialNumber'])
                except ClientError:
                    pass

        # Remove from groups
        for group in iam.list_groups_for_user(UserName=username).get('Groups', []):
            iam.remove_user_from_group(GroupName=group['GroupName'], UserName=username)

        # Detach managed policies
        for policy in iam.list_attached_user_policies(UserName=username).get('AttachedPolicies', []):
            iam.detach_user_policy(UserName=username, PolicyArn=policy['PolicyArn'])

        # Delete inline policies
        for policy_name in iam.list_user_policies(UserName=username).get('PolicyNames', []):
            iam.delete_user_policy(UserName=username, PolicyName=policy_name)

        iam.delete_user(UserName=username)
        return {
            'success': True, 'username': username,
            'message': f'IAM user "{username}" and all associated resources deleted'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting IAM user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_iam_login_profile(
    username: str,
    password: str,
    password_reset_required: bool = True
) -> Dict[str, Any]:
    """Enable AWS console access for an IAM user by creating a login profile."""
    try:
        iam = _get_boto_client('iam')
        iam.create_login_profile(
            UserName=username, Password=password,
            PasswordResetRequired=password_reset_required
        )
        return {
            'success': True, 'username': username,
            'password_reset_required': password_reset_required,
            'message': f'Console access enabled for "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating login profile: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_login_profile(username: str) -> Dict[str, Any]:
    """Disable AWS console access for an IAM user."""
    try:
        iam = _get_boto_client('iam')
        iam.delete_login_profile(UserName=username)
        return {
            'success': True, 'username': username,
            'message': f'Console access disabled for "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting login profile: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def tag_iam_user(username: str, tags: Dict[str, str]) -> Dict[str, Any]:
    """Apply tags to an IAM user."""
    try:
        iam = _get_boto_client('iam')
        iam.tag_user(UserName=username, Tags=[{'Key': k, 'Value': v} for k, v in tags.items()])
        return {
            'success': True, 'username': username, 'tags': tags,
            'message': f'Tags applied to IAM user "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error tagging IAM user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# --- Access Keys ---

def create_iam_access_key(username: str) -> Dict[str, Any]:
    """Create a new programmatic access key for an IAM user. Returns secret key once — save it."""
    try:
        iam = _get_boto_client('iam')
        response = iam.create_access_key(UserName=username)
        key = response['AccessKey']
        # Include account ID so user can verify they're looking at the right AWS account
        account_id = key.get('UserName', username)
        try:
            sts = _get_boto_client('sts')
            identity = sts.get_caller_identity()
            account_id = identity['Account']
        except Exception:
            account_id = 'unknown'
        return {
            'success': True, 'username': username,
            'access_key_id': key['AccessKeyId'],
            'secret_access_key': key['SecretAccessKey'],
            'status': key['Status'],
            'aws_account_id': account_id,
            'warning': 'Save the SecretAccessKey now — it cannot be retrieved again.',
            'message': f'Access key {key["AccessKeyId"]} created for "{username}" in AWS account {account_id}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating access key: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_iam_access_keys(username: str) -> Dict[str, Any]:
    """List all access keys for an IAM user with their status and creation date."""
    try:
        iam = _get_boto_client('iam')
        response = iam.list_access_keys(UserName=username)
        keys = [
            {
                'access_key_id': k['AccessKeyId'],
                'status': k['Status'],
                'created': str(k['CreateDate'])
            }
            for k in response.get('AccessKeyMetadata', [])
        ]
        account_id = 'unknown'
        try:
            sts = _get_boto_client('sts')
            account_id = sts.get_caller_identity()['Account']
        except Exception:
            pass
        return {
            'success': True, 'username': username,
            'access_keys': keys, 'count': len(keys),
            'aws_account_id': account_id
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing access keys: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_access_key(username: str, access_key_id: str) -> Dict[str, Any]:
    """Delete an IAM access key."""
    try:
        iam = _get_boto_client('iam')
        iam.delete_access_key(UserName=username, AccessKeyId=access_key_id)
        return {
            'success': True, 'username': username, 'access_key_id': access_key_id,
            'message': f'Access key {access_key_id} deleted for "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting access key: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_iam_access_key(username: str, access_key_id: str, status: str) -> Dict[str, Any]:
    """Activate or deactivate an IAM access key without deleting it."""
    try:
        iam = _get_boto_client('iam')
        iam.update_access_key(UserName=username, AccessKeyId=access_key_id, Status=status)
        return {
            'success': True, 'username': username,
            'access_key_id': access_key_id, 'new_status': status,
            'message': f'Access key {access_key_id} set to {status} for "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating access key: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_access_key_last_used(access_key_id: str) -> Dict[str, Any]:
    """Check when an access key was last used and which service/region it accessed."""
    try:
        iam = _get_boto_client('iam')
        response = iam.get_access_key_last_used(AccessKeyId=access_key_id)
        last_used = response.get('AccessKeyLastUsed', {})
        return {
            'success': True, 'access_key_id': access_key_id,
            'username': response.get('UserName', ''),
            'last_used_date': str(last_used.get('LastUsedDate', 'Never')),
            'service_name': last_used.get('ServiceName', 'N/A'),
            'region': last_used.get('Region', 'N/A')
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting key last used: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# --- Groups ---

def create_iam_group(group_name: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Create a new IAM group."""
    try:
        iam = _get_boto_client('iam')
        params: Dict = {'GroupName': group_name}
        if path:
            params['Path'] = path
        response = iam.create_group(**params)
        group = response['Group']
        return {
            'success': True, 'group_name': group_name,
            'group_id': group['GroupId'], 'arn': group['Arn'],
            'message': f'IAM group "{group_name}" created'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating IAM group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_iam_groups() -> Dict[str, Any]:
    """List all IAM groups in the account."""
    try:
        iam = _get_boto_client('iam')
        paginator = iam.get_paginator('list_groups')
        groups = []
        for page in paginator.paginate():
            for g in page['Groups']:
                groups.append({
                    'group_name': g['GroupName'],
                    'group_id': g['GroupId'],
                    'arn': g['Arn'],
                    'created': str(g['CreateDate'])
                })
        return {'success': True, 'groups': groups, 'count': len(groups)}
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing IAM groups: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_group(group_name: str) -> Dict[str, Any]:
    """Delete an IAM group. Removes all members and policy attachments first."""
    try:
        iam = _get_boto_client('iam')

        # Remove all users from the group
        for user in iam.get_group(GroupName=group_name).get('Users', []):
            iam.remove_user_from_group(GroupName=group_name, UserName=user['UserName'])

        # Detach managed policies
        for policy in iam.list_attached_group_policies(GroupName=group_name).get('AttachedPolicies', []):
            iam.detach_group_policy(GroupName=group_name, PolicyArn=policy['PolicyArn'])

        # Delete inline policies
        for policy_name in iam.list_group_policies(GroupName=group_name).get('PolicyNames', []):
            iam.delete_group_policy(GroupName=group_name, PolicyName=policy_name)

        iam.delete_group(GroupName=group_name)
        return {
            'success': True, 'group_name': group_name,
            'message': f'IAM group "{group_name}" deleted'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting IAM group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def add_iam_user_to_group(username: str, group_name: str) -> Dict[str, Any]:
    """Add an IAM user to a group."""
    try:
        iam = _get_boto_client('iam')
        iam.add_user_to_group(GroupName=group_name, UserName=username)
        return {
            'success': True, 'username': username, 'group_name': group_name,
            'message': f'User "{username}" added to group "{group_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error adding user to group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def remove_iam_user_from_group(username: str, group_name: str) -> Dict[str, Any]:
    """Remove an IAM user from a group."""
    try:
        iam = _get_boto_client('iam')
        iam.remove_user_from_group(GroupName=group_name, UserName=username)
        return {
            'success': True, 'username': username, 'group_name': group_name,
            'message': f'User "{username}" removed from group "{group_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error removing user from group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_iam_groups_for_user(username: str) -> Dict[str, Any]:
    """List all IAM groups a user belongs to."""
    try:
        iam = _get_boto_client('iam')
        response = iam.list_groups_for_user(UserName=username)
        groups = [
            {'group_name': g['GroupName'], 'group_id': g['GroupId'], 'arn': g['Arn']}
            for g in response.get('Groups', [])
        ]
        return {
            'success': True, 'username': username,
            'groups': groups, 'count': len(groups)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing groups for user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# --- Roles ---

def get_iam_role(role_name: str) -> Dict[str, Any]:
    """Get details of an IAM role including trust policy and attached policies."""
    try:
        iam = _get_boto_client('iam')
        response = iam.get_role(RoleName=role_name)
        role = response['Role']

        attached = [
            {'policy_name': p['PolicyName'], 'policy_arn': p['PolicyArn']}
            for p in iam.list_attached_role_policies(RoleName=role_name).get('AttachedPolicies', [])
        ]
        inline = iam.list_role_policies(RoleName=role_name).get('PolicyNames', [])

        trust_policy = role.get('AssumeRolePolicyDocument', {})
        if isinstance(trust_policy, str):
            from urllib.parse import unquote
            trust_policy = json.loads(unquote(trust_policy))

        return {
            'success': True, 'role_name': role_name,
            'role_id': role['RoleId'], 'arn': role['Arn'],
            'created': str(role['CreateDate']),
            'trust_policy': trust_policy,
            'attached_policies': attached,
            'inline_policies': inline,
            'tags': {t['Key']: t['Value'] for t in role.get('Tags', [])}
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting IAM role: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_iam_role_trust_policy(role_name: str, trust_policy: Dict) -> Dict[str, Any]:
    """Update the trust policy (assume role policy) of an IAM role."""
    try:
        iam = _get_boto_client('iam')
        iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json.dumps(trust_policy)
        )
        return {
            'success': True, 'role_name': role_name,
            'message': f'Trust policy updated for role "{role_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating trust policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def assume_iam_role(
    role_arn: str,
    session_name: str,
    duration_seconds: int = 3600,
    external_id: Optional[str] = None
) -> Dict[str, Any]:
    """Assume an IAM role and return temporary credentials via STS."""
    try:
        sts = _get_boto_client('sts')
        params: Dict = {
            'RoleArn': role_arn,
            'RoleSessionName': session_name,
            'DurationSeconds': duration_seconds
        }
        if external_id:
            params['ExternalId'] = external_id
        response = sts.assume_role(**params)
        creds = response['Credentials']
        return {
            'success': True, 'role_arn': role_arn, 'session_name': session_name,
            'access_key_id': creds['AccessKeyId'],
            'secret_access_key': creds['SecretAccessKey'],
            'session_token': creds['SessionToken'],
            'expiration': str(creds['Expiration']),
            'message': f'Assumed role {role_arn} — credentials expire at {creds["Expiration"]}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error assuming role: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def tag_iam_role(role_name: str, tags: Dict[str, str]) -> Dict[str, Any]:
    """Apply tags to an IAM role."""
    try:
        iam = _get_boto_client('iam')
        iam.tag_role(RoleName=role_name, Tags=[{'Key': k, 'Value': v} for k, v in tags.items()])
        return {
            'success': True, 'role_name': role_name, 'tags': tags,
            'message': f'Tags applied to IAM role "{role_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error tagging IAM role: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# --- Policies ---

def list_iam_policies(scope: str = 'Local', max_items: int = 100) -> Dict[str, Any]:
    """
    List IAM managed policies.
    scope: 'Local' (customer-managed only), 'AWS' (AWS-managed only), or 'All'
    """
    try:
        iam = _get_boto_client('iam')
        paginator = iam.get_paginator('list_policies')
        policies = []
        for page in paginator.paginate(Scope=scope, MaxItems=max_items):
            for p in page['Policies']:
                policies.append({
                    'policy_name': p['PolicyName'],
                    'policy_id': p['PolicyId'],
                    'arn': p['Arn'],
                    'attachment_count': p['AttachmentCount'],
                    'created': str(p['CreateDate']),
                    'updated': str(p['UpdateDate'])
                })
            if len(policies) >= max_items:
                break
        return {'success': True, 'policies': policies[:max_items], 'count': len(policies[:max_items])}
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing IAM policies: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_iam_policy(policy_arn: str) -> Dict[str, Any]:
    """Get details and the current policy document for an IAM managed policy."""
    try:
        iam = _get_boto_client('iam')
        policy = iam.get_policy(PolicyArn=policy_arn)['Policy']
        version = iam.get_policy_version(
            PolicyArn=policy_arn, VersionId=policy['DefaultVersionId']
        )['PolicyVersion']
        return {
            'success': True, 'policy_name': policy['PolicyName'],
            'arn': policy_arn,
            'attachment_count': policy['AttachmentCount'],
            'default_version': policy['DefaultVersionId'],
            'document': version['Document'],
            'created': str(policy['CreateDate'])
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting IAM policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_policy(policy_arn: str) -> Dict[str, Any]:
    """Delete a customer-managed IAM policy. Detaches from all entities first."""
    try:
        iam = _get_boto_client('iam')

        # Detach from all entities
        entities = iam.list_entities_for_policy(PolicyArn=policy_arn)
        for user in entities.get('PolicyUsers', []):
            iam.detach_user_policy(UserName=user['UserName'], PolicyArn=policy_arn)
        for group in entities.get('PolicyGroups', []):
            iam.detach_group_policy(GroupName=group['GroupName'], PolicyArn=policy_arn)
        for role in entities.get('PolicyRoles', []):
            iam.detach_role_policy(RoleName=role['RoleName'], PolicyArn=policy_arn)

        # Delete non-default versions first
        for version in iam.list_policy_versions(PolicyArn=policy_arn).get('Versions', []):
            if not version['IsDefaultVersion']:
                iam.delete_policy_version(PolicyArn=policy_arn, VersionId=version['VersionId'])

        iam.delete_policy(PolicyArn=policy_arn)
        return {
            'success': True, 'policy_arn': policy_arn,
            'message': f'Policy {policy_arn} deleted'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting IAM policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def attach_iam_user_policy(username: str, policy_arn: str) -> Dict[str, Any]:
    """Attach a managed policy directly to an IAM user."""
    try:
        iam = _get_boto_client('iam')
        iam.attach_user_policy(UserName=username, PolicyArn=policy_arn)
        return {
            'success': True, 'username': username, 'policy_arn': policy_arn,
            'message': f'Policy {policy_arn} attached to user "{username}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error attaching policy to user: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def attach_iam_group_policy(group_name: str, policy_arn: str) -> Dict[str, Any]:
    """Attach a managed policy to an IAM group."""
    try:
        iam = _get_boto_client('iam')
        iam.attach_group_policy(GroupName=group_name, PolicyArn=policy_arn)
        return {
            'success': True, 'group_name': group_name, 'policy_arn': policy_arn,
            'message': f'Policy {policy_arn} attached to group "{group_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error attaching policy to group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def detach_iam_policy(entity_type: str, entity_name: str, policy_arn: str) -> Dict[str, Any]:
    """
    Detach a managed policy from a user, group, or role.
    entity_type: 'user', 'group', or 'role'
    """
    try:
        iam = _get_boto_client('iam')
        if entity_type == 'user':
            iam.detach_user_policy(UserName=entity_name, PolicyArn=policy_arn)
        elif entity_type == 'group':
            iam.detach_group_policy(GroupName=entity_name, PolicyArn=policy_arn)
        elif entity_type == 'role':
            iam.detach_role_policy(RoleName=entity_name, PolicyArn=policy_arn)
        else:
            return {'success': False, 'error': 'entity_type must be user, group, or role'}
        return {
            'success': True, 'entity_type': entity_type,
            'entity_name': entity_name, 'policy_arn': policy_arn,
            'message': f'Policy {policy_arn} detached from {entity_type} "{entity_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error detaching policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def put_iam_inline_policy(
    entity_type: str,
    entity_name: str,
    policy_name: str,
    policy_document: Dict
) -> Dict[str, Any]:
    """
    Embed an inline policy directly into a user, group, or role.
    entity_type: 'user', 'group', or 'role'
    """
    try:
        iam = _get_boto_client('iam')
        doc = json.dumps(policy_document)
        if entity_type == 'user':
            iam.put_user_policy(UserName=entity_name, PolicyName=policy_name, PolicyDocument=doc)
        elif entity_type == 'group':
            iam.put_group_policy(GroupName=entity_name, PolicyName=policy_name, PolicyDocument=doc)
        elif entity_type == 'role':
            iam.put_role_policy(RoleName=entity_name, PolicyName=policy_name, PolicyDocument=doc)
        else:
            return {'success': False, 'error': 'entity_type must be user, group, or role'}
        return {
            'success': True, 'entity_type': entity_type,
            'entity_name': entity_name, 'policy_name': policy_name,
            'message': f'Inline policy "{policy_name}" applied to {entity_type} "{entity_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error putting inline policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_iam_inline_policy(
    entity_type: str,
    entity_name: str,
    policy_name: str
) -> Dict[str, Any]:
    """Remove an inline policy from a user, group, or role."""
    try:
        iam = _get_boto_client('iam')
        if entity_type == 'user':
            iam.delete_user_policy(UserName=entity_name, PolicyName=policy_name)
        elif entity_type == 'group':
            iam.delete_group_policy(GroupName=entity_name, PolicyName=policy_name)
        elif entity_type == 'role':
            iam.delete_role_policy(RoleName=entity_name, PolicyName=policy_name)
        else:
            return {'success': False, 'error': 'entity_type must be user, group, or role'}
        return {
            'success': True, 'entity_type': entity_type,
            'entity_name': entity_name, 'policy_name': policy_name,
            'message': f'Inline policy "{policy_name}" deleted from {entity_type} "{entity_name}"'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting inline policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_attached_role_policies(role_name: str) -> Dict[str, Any]:
    """List all managed policies attached to an IAM role."""
    try:
        iam = _get_boto_client('iam')
        managed = [
            {'policy_name': p['PolicyName'], 'policy_arn': p['PolicyArn']}
            for p in iam.list_attached_role_policies(RoleName=role_name).get('AttachedPolicies', [])
        ]
        inline = iam.list_role_policies(RoleName=role_name).get('PolicyNames', [])
        return {
            'success': True, 'role_name': role_name,
            'managed_policies': managed, 'managed_count': len(managed),
            'inline_policies': inline, 'inline_count': len(inline)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing role policies: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# --- Audit ---

def generate_iam_credential_report() -> Dict[str, Any]:
    """Trigger generation of the IAM credential report (CSV of all users and credential status)."""
    try:
        iam = _get_boto_client('iam')
        response = iam.generate_credential_report()
        return {
            'success': True,
            'state': response['State'],
            'description': response.get('Description', ''),
            'message': f'Credential report generation: {response["State"]}. Call get_iam_credential_report to retrieve it.'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error generating credential report: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_iam_credential_report() -> Dict[str, Any]:
    """Download and parse the IAM credential report as structured data."""
    try:
        import csv, io
        iam = _get_boto_client('iam')
        response = iam.get_credential_report()
        content = response['Content'].decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        users = list(reader)
        return {
            'success': True,
            'generated_time': str(response['GeneratedTime']),
            'users': users,
            'count': len(users)
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'ReportNotPresent':
            return {'success': False, 'error': 'No credential report available. Call generate_iam_credential_report first.'}
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting credential report: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_iam_account_summary() -> Dict[str, Any]:
    """Get IAM usage statistics and limits for the account."""
    try:
        iam = _get_boto_client('iam')
        response = iam.get_account_summary()
        summary = response.get('SummaryMap', {})
        return {
            'success': True,
            'users': summary.get('Users', 0),
            'users_quota': summary.get('UsersQuota', 5000),
            'groups': summary.get('Groups', 0),
            'groups_quota': summary.get('GroupsQuota', 300),
            'roles': summary.get('Roles', 0),
            'roles_quota': summary.get('RolesQuota', 1000),
            'policies': summary.get('Policies', 0),
            'policies_quota': summary.get('PoliciesQuota', 1500),
            'mfa_devices': summary.get('MFADevices', 0),
            'account_mfa_enabled': summary.get('AccountMFAEnabled', 0) == 1,
            'access_keys_per_user_quota': summary.get('AccessKeysPerUserQuota', 2)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting account summary: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_iam_services_last_accessed(arn: str) -> Dict[str, Any]:
    """
    List AWS services a user, group, role, or policy last accessed.
    Useful for identifying unused permissions for least-privilege enforcement.
    """
    try:
        iam = _get_boto_client('iam')
        response = iam.generate_service_last_accessed_details(Arn=arn)
        job_id = response['JobId']

        # Poll for completion (max 10 attempts)
        import time as _time
        for _ in range(10):
            details = iam.get_service_last_accessed_details(JobId=job_id)
            if details['JobStatus'] in ('COMPLETED', 'FAILED'):
                break
            _time.sleep(1)

        services = [
            {
                'service_name': s['ServiceName'],
                'service_namespace': s['ServiceNamespace'],
                'last_authenticated': str(s.get('LastAuthenticated', 'Never')),
                'last_authenticated_entity': s.get('LastAuthenticatedEntity', 'N/A'),
                'total_authenticated_entities': s.get('TotalAuthenticatedEntities', 0)
            }
            for s in details.get('ServicesLastAccessed', [])
        ]
        used = [s for s in services if s['last_authenticated'] != 'Never']
        unused = [s for s in services if s['last_authenticated'] == 'Never']

        return {
            'success': True, 'arn': arn,
            'services_used': used, 'services_unused': unused,
            'used_count': len(used), 'unused_count': len(unused),
            'message': f'{len(used)} services used, {len(unused)} services never accessed — consider revoking unused'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting services last accessed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# CREATE OPERATIONS
# ============================================================================

def create_ec2_keypair(
    key_name: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an EC2 key pair for SSH access.

    Args:
        key_name: Name for the key pair (must be unique)
        region: AWS region

    Returns:
        Dictionary with keypair information and private key material
    """
    try:
        logger.info(f"Creating EC2 key pair: {key_name}")

        ec2 = _get_boto_client('ec2', region)

        # Create the key pair
        response = ec2.create_key_pair(KeyName=key_name)

        logger.info(f"Successfully created EC2 key pair: {key_name}")

        return {
            'success': True,
            'message': f'Successfully created EC2 key pair: {key_name}',
            'key_name': response['KeyName'],
            'key_fingerprint': response['KeyFingerprint'],
            'key_pair_id': response.get('KeyPairId', 'N/A'),
            'region': region or ec2.meta.region_name,
            'private_key': response['KeyMaterial'],
            # Special field to trigger download
            'download_file': {
                'filename': f'{key_name}.pem',
                'content': response['KeyMaterial'],
                'content_type': 'application/x-pem-file'
            },
            'warning': 'IMPORTANT: Save the private key now! This is the only time you can download it.',
            'instructions': [
                f'The private key has been generated and is ready for download as {key_name}.pem',
                'Save this file in a secure location',
                'Set appropriate permissions: chmod 400 {}.pem (on Linux/Mac)'.format(key_name),
                f'Use it to connect: ssh -i {key_name}.pem ec2-user@<instance-ip>'
            ]
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_msg = e.response['Error']['Message']

        logger.error(f"Failed to create key pair {key_name}: {error_msg}")

        if error_code == 'InvalidKeyPair.Duplicate':
            return {
                'success': False,
                'error': 'Duplicate key pair',
                'message': f'Key pair "{key_name}" already exists. Please choose a different name or delete the existing key pair first.'
            }

        return {
            'success': False,
            'error': error_code,
            'message': error_msg
        }

    except Exception as e:
        logger.error(f"Unexpected error creating key pair: {str(e)}")
        return {
            'success': False,
            'error': 'Unexpected error',
            'message': str(e)
        }


def delete_ec2_keypair(key_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an EC2 key pair."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_key_pair(KeyName=key_name)
        return {
            'success': True,
            'key_name': key_name,
            'message': f'Key pair "{key_name}" deleted successfully'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting key pair: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ec2_instance(
    ami_id: str,
    instance_type: str,
    key_name: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    subnet_id: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    user_data: Optional[str] = None,
    region: Optional[str] = None,
    count: int = 1
) -> Dict[str, Any]:
    """
    Create EC2 instance(s).

    Args:
        ami_id: AMI ID to use (e.g., ami-0c55b159cbfafe1f0)
        instance_type: Instance type (e.g., t2.micro, t3.small)
        key_name: SSH key pair name
        security_group_ids: List of security group IDs
        subnet_id: Subnet ID for VPC placement
        tags: Dictionary of tags to apply
        user_data: User data script
        region: AWS region
        count: Number of instances to create (default: 1, max: 10)

    Returns:
        Dictionary with created instance information
    """
    try:
        # Validate count
        if count < 1 or count > 10:
            return {
                'success': False,
                'error': 'Invalid count',
                'message': 'Count must be between 1 and 10'
            }

        logger.info(f"Creating {count} EC2 instance(s) of type {instance_type}")

        ec2 = _get_boto_client('ec2', region)

        # Build launch parameters
        launch_params = {
            'ImageId': ami_id,
            'InstanceType': instance_type,
            'MinCount': count,
            'MaxCount': count
        }

        if key_name:
            launch_params['KeyName'] = key_name

        if security_group_ids:
            launch_params['SecurityGroupIds'] = security_group_ids

        if subnet_id:
            launch_params['SubnetId'] = subnet_id

        if user_data:
            launch_params['UserData'] = user_data

        # Launch instance(s)
        response = ec2.run_instances(**launch_params)
        instances = response['Instances']

        instance_ids = [inst['InstanceId'] for inst in instances]

        logger.info(f"Successfully created {len(instance_ids)} EC2 instance(s): {', '.join(instance_ids)}")

        # Apply tags if provided
        if tags and instance_ids:
            tag_specifications = [{'Key': k, 'Value': v} for k, v in tags.items()]
            ec2.create_tags(
                Resources=instance_ids,
                Tags=tag_specifications
            )

        # Wait a moment for instance to initialize and fetch full details
        import time
        time.sleep(2)  # Brief wait for AWS to populate all fields

        # Fetch complete instance details
        detailed_instances = ec2.describe_instances(InstanceIds=instance_ids)

        # Return information about created instances
        if count == 1:
            # Single instance - return comprehensive details
            instance = detailed_instances['Reservations'][0]['Instances'][0]

            # Extract all comprehensive details
            details = {
                'success': True,
                'message': f'Successfully created EC2 instance {instance["InstanceId"]}',
                'region': region or ec2.meta.region_name,

                # DETAILS Section
                'details': {
                    'instance_id': instance['InstanceId'],
                    'instance_type': instance['InstanceType'],
                    'ami_id': instance['ImageId'],
                    'launch_time': instance['LaunchTime'].isoformat(),
                    'availability_zone': instance['Placement']['AvailabilityZone'],
                    'platform': instance.get('Platform', 'Linux/UNIX'),
                    'architecture': instance.get('Architecture', 'x86_64'),
                    'virtualization_type': instance.get('VirtualizationType', 'hvm'),
                    'hypervisor': instance.get('Hypervisor', 'xen'),
                    'root_device_type': instance.get('RootDeviceType', 'ebs'),
                    'root_device_name': instance.get('RootDeviceName', '/dev/xvda'),
                },

                # STATUS AND ALARMS Section
                'status': {
                    'instance_state': instance['State']['Name'],
                    'instance_state_code': instance['State']['Code'],
                    'monitoring_state': instance['Monitoring']['State'],
                    'status_checks': 'Initializing',  # Will be available after a few minutes
                    'scheduled_events': 'No scheduled events',
                },

                # MONITORING Section
                'monitoring': {
                    'monitoring_enabled': instance['Monitoring']['State'] == 'enabled',
                    'detailed_monitoring': instance['Monitoring']['State'],
                    'cloudwatch_available': True,
                    'metrics_available': ['CPUUtilization', 'NetworkIn', 'NetworkOut', 'DiskReadBytes', 'DiskWriteBytes'],
                },

                # SECURITY Section
                'security': {
                    'security_groups': [
                        {
                            'id': sg['GroupId'],
                            'name': sg['GroupName']
                        } for sg in instance.get('SecurityGroups', [])
                    ],
                    'iam_role': instance.get('IamInstanceProfile', {}).get('Arn', 'No IAM role'),
                    'key_pair': instance.get('KeyName', 'No key pair'),
                    'source_dest_check': instance.get('SourceDestCheck', True),
                },

                # NETWORKING Section
                'networking': {
                    'vpc_id': instance.get('VpcId', 'EC2-Classic'),
                    'subnet_id': instance.get('SubnetId', 'N/A'),
                    'private_ip': instance.get('PrivateIpAddress', 'Pending'),
                    'private_dns': instance.get('PrivateDnsName', 'Pending'),
                    'public_ip': instance.get('PublicIpAddress', 'None'),
                    'public_dns': instance.get('PublicDnsName', 'None'),
                    'elastic_ip': 'None',  # Would need separate check
                    'network_interfaces': [
                        {
                            'id': ni['NetworkInterfaceId'],
                            'status': ni['Status'],
                            'mac_address': ni.get('MacAddress', 'N/A'),
                            'private_ip': ni.get('PrivateIpAddress', 'N/A'),
                            'public_ip': ni.get('Association', {}).get('PublicIp', 'None'),
                            'ipv6_addresses': [addr['Ipv6Address'] for addr in ni.get('Ipv6Addresses', [])],
                        } for ni in instance.get('NetworkInterfaces', [])
                    ],
                },

                # STORAGE Section
                'storage': {
                    'root_device': instance.get('RootDeviceName', '/dev/xvda'),
                    'root_device_type': instance.get('RootDeviceType', 'ebs'),
                    'block_devices': [
                        {
                            'device_name': bd['DeviceName'],
                            'volume_id': bd['Ebs']['VolumeId'],
                            'status': bd['Ebs']['Status'],
                            'attach_time': bd['Ebs']['AttachTime'].isoformat(),
                            'delete_on_termination': bd['Ebs']['DeleteOnTermination'],
                        } for bd in instance.get('BlockDeviceMappings', [])
                    ],
                    'ebs_optimized': instance.get('EbsOptimized', False),
                },

                # TAGS Section
                'tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])},
            }

            return details

        else:
            # Multiple instances - return list with comprehensive details for each
            all_instances_details = []

            for reservation in detailed_instances['Reservations']:
                for instance in reservation['Instances']:
                    inst_details = {
                        'instance_id': instance['InstanceId'],
                        'instance_type': instance['InstanceType'],
                        'state': instance['State']['Name'],
                        'availability_zone': instance['Placement']['AvailabilityZone'],
                        'private_ip': instance.get('PrivateIpAddress', 'Pending'),
                        'public_ip': instance.get('PublicIpAddress', 'None'),
                        'launch_time': instance['LaunchTime'].isoformat(),
                        'security_groups': [sg['GroupName'] for sg in instance.get('SecurityGroups', [])],
                        'vpc_id': instance.get('VpcId', 'N/A'),
                        'subnet_id': instance.get('SubnetId', 'N/A'),
                        'tags': {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])},
                    }
                    all_instances_details.append(inst_details)

            return {
                'success': True,
                'count': len(instances),
                'instance_ids': instance_ids,
                'instances': all_instances_details,
                'message': f'Successfully created {len(instances)} EC2 instances: {", ".join(instance_ids)}',
                'region': region or ec2.meta.region_name
            }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error creating EC2 instance: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def create_spot_instance(
    ami_id: str,
    instance_type: str,
    spot_price: Optional[str] = None,
    spot_type: str = 'one-time',
    key_name: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    subnet_id: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    user_data: Optional[str] = None,
    region: Optional[str] = None,
    count: int = 1
) -> Dict[str, Any]:
    """
    Create EC2 spot instance(s) for cost-effective compute.

    Args:
        ami_id: AMI ID to use
        instance_type: Instance type (e.g., t3.medium, m5.large)
        spot_price: Maximum hourly price in USD (e.g., '0.05'). If not set, uses on-demand price as max.
        spot_type: Spot request type - 'one-time' or 'persistent'
        key_name: SSH key pair name
        security_group_ids: List of security group IDs
        subnet_id: Subnet ID for VPC placement
        tags: Dictionary of tags to apply
        user_data: User data script to run on launch
        region: AWS region
        count: Number of instances (1-10)

    Returns:
        Dictionary with created spot instance information
    """
    try:
        if count < 1 or count > 10:
            return {'success': False, 'error': 'Count must be between 1 and 10'}

        logger.info(f"Creating {count} spot instance(s) of type {instance_type}")
        ec2 = _get_boto_client('ec2', region)

        launch_params = {
            'ImageId': ami_id,
            'InstanceType': instance_type,
            'MinCount': count,
            'MaxCount': count,
            'InstanceMarketOptions': {
                'MarketType': 'spot',
                'SpotOptions': {
                    'SpotInstanceType': spot_type,
                    'InstanceInterruptionBehavior': 'terminate'
                }
            }
        }

        if spot_price:
            launch_params['InstanceMarketOptions']['SpotOptions']['MaxPrice'] = spot_price

        if key_name:
            launch_params['KeyName'] = key_name
        if security_group_ids:
            launch_params['SecurityGroupIds'] = security_group_ids
        if subnet_id:
            launch_params['SubnetId'] = subnet_id
        if user_data:
            launch_params['UserData'] = user_data

        response = ec2.run_instances(**launch_params)
        instances = response['Instances']
        instance_ids = [inst['InstanceId'] for inst in instances]

        if tags and instance_ids:
            tag_specs = [{'Key': k, 'Value': v} for k, v in tags.items()]
            ec2.create_tags(Resources=instance_ids, Tags=tag_specs)

        import time
        time.sleep(2)

        detailed = ec2.describe_instances(InstanceIds=instance_ids)
        details = []
        for res in detailed['Reservations']:
            for inst in res['Instances']:
                details.append({
                    'instance_id': inst['InstanceId'],
                    'instance_type': inst['InstanceType'],
                    'state': inst['State']['Name'],
                    'spot_instance_request_id': inst.get('SpotInstanceRequestId', 'N/A'),
                    'availability_zone': inst['Placement']['AvailabilityZone'],
                    'private_ip': inst.get('PrivateIpAddress', 'Pending'),
                    'public_ip': inst.get('PublicIpAddress', 'None'),
                    'launch_time': inst['LaunchTime'].isoformat(),
                    'instance_lifecycle': inst.get('InstanceLifecycle', 'spot'),
                })

        return {
            'success': True,
            'count': len(instances),
            'instance_ids': instance_ids,
            'instances': details,
            'message': f'Successfully created {len(instances)} spot instance(s): {", ".join(instance_ids)}',
            'region': region or ec2.meta.region_name
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating spot instance: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_s3_bucket(
    bucket_name: str,
    region: Optional[str] = None,
    versioning_enabled: bool = False,
    encryption_enabled: bool = True,
    public_access_block: bool = True
) -> Dict[str, Any]:
    """
    Create a new S3 bucket.

    Args:
        bucket_name: Name of the bucket (must be globally unique)
        region: AWS region
        versioning_enabled: Enable versioning
        encryption_enabled: Enable server-side encryption
        public_access_block: Block all public access

    Returns:
        Dictionary with created bucket information
    """
    try:
        s3 = _get_boto_client('s3', region)

        # Create bucket
        if region and region != 'us-east-1':
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        else:
            s3.create_bucket(Bucket=bucket_name)

        # Enable versioning if requested
        if versioning_enabled:
            s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={'Status': 'Enabled'}
            )

        # Enable encryption if requested
        if encryption_enabled:
            s3.put_bucket_encryption(
                Bucket=bucket_name,
                ServerSideEncryptionConfiguration={
                    'Rules': [{
                        'ApplyServerSideEncryptionByDefault': {
                            'SSEAlgorithm': 'AES256'
                        }
                    }]
                }
            )

        # Block public access if requested
        if public_access_block:
            s3.put_public_access_block(
                Bucket=bucket_name,
                PublicAccessBlockConfiguration={
                    'BlockPublicAcls': True,
                    'IgnorePublicAcls': True,
                    'BlockPublicPolicy': True,
                    'RestrictPublicBuckets': True
                }
            )

        return {
            'success': True,
            'bucket_name': bucket_name,
            'region': region or 'us-east-1',
            'versioning_enabled': versioning_enabled,
            'encryption_enabled': encryption_enabled,
            'public_access_blocked': public_access_block,
            'message': f'Successfully created S3 bucket {bucket_name}'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error creating S3 bucket: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def create_rds_instance(
    db_instance_identifier: str,
    db_instance_class: str,
    engine: str,
    master_username: str,
    master_password: str,
    allocated_storage: int = 20,
    db_name: Optional[str] = None,
    engine_version: Optional[str] = None,
    multi_az: bool = False,
    publicly_accessible: bool = False,
    backup_retention_period: int = 7,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new RDS database instance.

    Args:
        db_instance_identifier: Unique identifier for the DB instance
        db_instance_class: Instance class (e.g., db.t3.micro)
        engine: Database engine (mysql, postgres, mariadb, oracle-ee, sqlserver-ex)
        master_username: Master username
        master_password: Master password
        allocated_storage: Storage in GB (default: 20)
        db_name: Initial database name
        engine_version: Specific engine version
        multi_az: Enable Multi-AZ deployment
        publicly_accessible: Make instance publicly accessible
        backup_retention_period: Backup retention in days (0-35)
        region: AWS region

    Returns:
        Dictionary with created RDS instance information
    """
    try:
        rds = _get_boto_client('rds', region)

        # Build create parameters
        create_params = {
            'DBInstanceIdentifier': db_instance_identifier,
            'DBInstanceClass': db_instance_class,
            'Engine': engine,
            'MasterUsername': master_username,
            'MasterUserPassword': master_password,
            'AllocatedStorage': allocated_storage,
            'MultiAZ': multi_az,
            'PubliclyAccessible': publicly_accessible,
            'BackupRetentionPeriod': backup_retention_period,
            'StorageEncrypted': True  # Always encrypt for security
        }

        if db_name:
            create_params['DBName'] = db_name

        if engine_version:
            create_params['EngineVersion'] = engine_version

        # Create RDS instance
        response = rds.create_db_instance(**create_params)
        db_instance = response['DBInstance']

        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'db_instance_class': db_instance_class,
            'engine': engine,
            'engine_version': db_instance.get('EngineVersion'),
            'endpoint': 'Pending - will be available when instance is ready',
            'port': db_instance.get('DbInstancePort'),
            'status': db_instance['DBInstanceStatus'],
            'multi_az': multi_az,
            'allocated_storage_gb': allocated_storage,
            'message': f'Successfully initiated creation of RDS instance {db_instance_identifier}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error creating RDS instance: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def delete_rds_instance(
    db_instance_identifier: str,
    skip_final_snapshot: bool = False,
    final_snapshot_identifier: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete an RDS database instance."""
    try:
        rds = _get_boto_client('rds', region)
        params = {
            'DBInstanceIdentifier': db_instance_identifier,
            'SkipFinalSnapshot': skip_final_snapshot,
        }
        if not skip_final_snapshot:
            params['FinalDBSnapshotIdentifier'] = final_snapshot_identifier or f'{db_instance_identifier}-final-snapshot'

        response = rds.delete_db_instance(**params)
        db = response['DBInstance']
        return {
            'success': True, 'db_instance_identifier': db['DBInstanceIdentifier'],
            'status': db['DBInstanceStatus'],
            'message': f'Successfully initiated deletion of RDS instance {db_instance_identifier}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting RDS instance: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_security_group(
    group_name: str,
    description: str,
    vpc_id: Optional[str] = None,
    ingress_rules: Optional[List[Dict[str, Any]]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new security group.

    Args:
        group_name: Name of the security group
        description: Description of the security group
        vpc_id: VPC ID (required for VPC security groups)
        ingress_rules: List of ingress rules [{'protocol': 'tcp', 'port': 80, 'cidr': '0.0.0.0/0'}]
        region: AWS region

    Returns:
        Dictionary with created security group information
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        # Create security group
        create_params = {
            'GroupName': group_name,
            'Description': description
        }

        if vpc_id:
            create_params['VpcId'] = vpc_id

        response = ec2.create_security_group(**create_params)
        group_id = response['GroupId']

        # Add ingress rules if provided
        if ingress_rules:
            for rule in ingress_rules:
                ec2.authorize_security_group_ingress(
                    GroupId=group_id,
                    IpProtocol=rule.get('protocol', 'tcp'),
                    FromPort=rule.get('port', 80),
                    ToPort=rule.get('port', 80),
                    CidrIp=rule.get('cidr', '0.0.0.0/0')
                )

        return {
            'success': True,
            'group_id': group_id,
            'group_name': group_name,
            'description': description,
            'vpc_id': vpc_id,
            'ingress_rules_added': len(ingress_rules) if ingress_rules else 0,
            'message': f'Successfully created security group {group_id}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error creating security group: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def authorize_security_group_ingress(
    group_id: str,
    protocol: str = 'tcp',
    from_port: int = 80,
    to_port: Optional[int] = None,
    cidr: Optional[str] = None,
    source_security_group_id: Optional[str] = None,
    description: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add an ingress rule to an existing security group.
    Supports CIDR-based rules OR source-security-group-based rules.

    Args:
        group_id: Security group ID to add the rule to
        protocol: Protocol (tcp, udp, icmp, -1 for all)
        from_port: Start of port range
        to_port: End of port range (defaults to from_port for single port)
        cidr: CIDR block (e.g., '10.0.0.0/16'). Mutually exclusive with source_security_group_id.
        source_security_group_id: Source security group ID to allow traffic from. Use this instead of CIDR for SG-to-SG rules.
        description: Rule description
        region: AWS region

    Returns:
        Dictionary with rule details
    """
    try:
        if not cidr and not source_security_group_id:
            return {
                'success': False,
                'error': 'Must specify either cidr or source_security_group_id'
            }

        ec2 = _get_boto_client('ec2', region)
        if to_port is None:
            to_port = from_port

        ip_permission = {
            'IpProtocol': protocol,
            'FromPort': from_port,
            'ToPort': to_port,
        }

        if source_security_group_id:
            sg_ref = {'GroupId': source_security_group_id}
            if description:
                sg_ref['Description'] = description
            ip_permission['UserIdGroupPairs'] = [sg_ref]
        else:
            ip_range = {'CidrIp': cidr}
            if description:
                ip_range['Description'] = description
            ip_permission['IpRanges'] = [ip_range]

        ec2.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[ip_permission]
        )

        source = source_security_group_id if source_security_group_id else cidr
        return {
            'success': True,
            'group_id': group_id,
            'protocol': protocol,
            'from_port': from_port,
            'to_port': to_port,
            'source': source,
            'source_type': 'security_group' if source_security_group_id else 'cidr',
            'message': f'Successfully added ingress rule to {group_id}: {protocol} {from_port}-{to_port} from {source}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error authorizing security group ingress: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def revoke_security_group_ingress(
    group_id: str,
    protocol: str = 'tcp',
    from_port: int = 80,
    to_port: Optional[int] = None,
    cidr: Optional[str] = None,
    source_security_group_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Remove an ingress rule from a security group."""
    try:
        if not cidr and not source_security_group_id:
            return {'success': False, 'error': 'Must specify either cidr or source_security_group_id'}

        ec2 = _get_boto_client('ec2', region)
        if to_port is None:
            to_port = from_port

        ip_permission = {'IpProtocol': protocol, 'FromPort': from_port, 'ToPort': to_port}
        if source_security_group_id:
            ip_permission['UserIdGroupPairs'] = [{'GroupId': source_security_group_id}]
        else:
            ip_permission['IpRanges'] = [{'CidrIp': cidr}]

        ec2.revoke_security_group_ingress(GroupId=group_id, IpPermissions=[ip_permission])
        source = source_security_group_id or cidr
        return {
            'success': True, 'group_id': group_id,
            'message': f'Successfully revoked ingress rule from {group_id}: {protocol} {from_port}-{to_port} from {source}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error revoking SG ingress: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_security_group(group_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a security group."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_security_group(GroupId=group_id)
        return {
            'success': True, 'group_id': group_id,
            'message': f'Successfully deleted security group {group_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting security group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_lambda_function(
    function_name: str,
    runtime: str,
    role_arn: str,
    handler: str,
    zip_file_path: str,
    description: Optional[str] = None,
    timeout: int = 3,
    memory_size: int = 128,
    environment_variables: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Lambda function.

    Args:
        function_name: Name of the Lambda function
        runtime: Runtime (e.g., python3.9, nodejs18.x, java11)
        role_arn: IAM role ARN for Lambda execution
        handler: Handler function (e.g., index.handler)
        zip_file_path: Path to ZIP file containing function code
        description: Function description
        timeout: Timeout in seconds (1-900)
        memory_size: Memory in MB (128-10240)
        environment_variables: Environment variables dict
        region: AWS region

    Returns:
        Dictionary with created Lambda function information
    """
    try:
        lambda_client = _get_boto_client('lambda', region)

        # Read ZIP file
        with open(zip_file_path, 'rb') as f:
            zip_content = f.read()

        # Build create parameters
        create_params = {
            'FunctionName': function_name,
            'Runtime': runtime,
            'Role': role_arn,
            'Handler': handler,
            'Code': {'ZipFile': zip_content},
            'Timeout': timeout,
            'MemorySize': memory_size
        }

        if description:
            create_params['Description'] = description

        if environment_variables:
            create_params['Environment'] = {'Variables': environment_variables}

        # Create function
        response = lambda_client.create_function(**create_params)

        return {
            'success': True,
            'function_name': function_name,
            'function_arn': response['FunctionArn'],
            'runtime': runtime,
            'handler': handler,
            'memory_size': memory_size,
            'timeout': timeout,
            'state': response['State'],
            'message': f'Successfully created Lambda function {function_name}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error creating Lambda function: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def delete_lambda_function(function_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Lambda function."""
    try:
        lam = _get_boto_client('lambda', region)
        lam.delete_function(FunctionName=function_name)
        return {
            'success': True, 'function_name': function_name,
            'message': f'Successfully deleted Lambda function {function_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting Lambda function: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_lambda_function_config(
    function_name: str,
    timeout: Optional[int] = None,
    memory_size: Optional[int] = None,
    environment_variables: Optional[Dict[str, str]] = None,
    description: Optional[str] = None,
    runtime: Optional[str] = None,
    handler: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update a Lambda function's configuration (timeout, memory, env vars, etc.)."""
    try:
        lam = _get_boto_client('lambda', region)
        params = {'FunctionName': function_name}
        if timeout is not None:
            params['Timeout'] = timeout
        if memory_size is not None:
            params['MemorySize'] = memory_size
        if environment_variables is not None:
            params['Environment'] = {'Variables': environment_variables}
        if description is not None:
            params['Description'] = description
        if runtime is not None:
            params['Runtime'] = runtime
        if handler is not None:
            params['Handler'] = handler

        response = lam.update_function_configuration(**params)
        return {
            'success': True, 'function_name': response['FunctionName'],
            'runtime': response.get('Runtime'), 'timeout': response.get('Timeout'),
            'memory_size': response.get('MemorySize'), 'state': response.get('State'),
            'message': f'Successfully updated Lambda function config for {function_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating Lambda config: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ec2_instance(
    instance_id: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete (terminate) an EC2 instance.

    Args:
        instance_id: EC2 instance ID
        region: AWS region

    Returns:
        Dictionary with deletion result
    """
    return manage_ec2_instance(instance_id, 'terminate', region)


def delete_s3_bucket(
    bucket_name: str,
    force: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete an S3 bucket.

    Args:
        bucket_name: Name of the bucket to delete
        force: If True, delete all objects first
        region: AWS region

    Returns:
        Dictionary with deletion result
    """
    try:
        s3 = _get_boto_client('s3', region)

        # If force, delete all objects first
        if force:
            # Delete all objects
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    objects = [{'Key': obj['Key']} for obj in page['Contents']]
                    s3.delete_objects(Bucket=bucket_name, Delete={'Objects': objects})

            # Delete all versions if versioning is enabled
            try:
                version_paginator = s3.get_paginator('list_object_versions')
                for page in version_paginator.paginate(Bucket=bucket_name):
                    versions = []
                    if 'Versions' in page:
                        versions.extend([{'Key': v['Key'], 'VersionId': v['VersionId']} for v in page['Versions']])
                    if 'DeleteMarkers' in page:
                        versions.extend([{'Key': d['Key'], 'VersionId': d['VersionId']} for d in page['DeleteMarkers']])

                    if versions:
                        s3.delete_objects(Bucket=bucket_name, Delete={'Objects': versions})
            except Exception:
                pass  # Versioning might not be enabled

        # Delete bucket
        s3.delete_bucket(Bucket=bucket_name)

        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Successfully deleted S3 bucket {bucket_name}',
            'force_delete': force
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'error_code': e.response['Error']['Code']
        }
    except Exception as e:
        logger.error(f"Error deleting S3 bucket: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def put_s3_lifecycle_policy(
    bucket_name: str,
    rules: List[Dict],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set lifecycle policies on an S3 bucket.

    Args:
        bucket_name: Name of the S3 bucket
        rules: List of lifecycle rule dicts. Each rule must have 'id' and 'status'
               ('Enabled'/'Disabled'). Common fields:
               - 'prefix': object key prefix filter (empty string = all objects)
               - 'transitions': list of {days, storage_class} e.g.
                 [{'days': 30, 'storage_class': 'STANDARD_IA'},
                  {'days': 90, 'storage_class': 'GLACIER'}]
               - 'expiration_days': delete objects after N days
               - 'noncurrent_version_expiration_days': for versioned buckets
        region: AWS region

    Returns:
        Dictionary with result
    """
    try:
        s3 = _get_boto_client('s3', region)

        lifecycle_rules = []
        for r in rules:
            rule = {
                'ID': r['id'],
                'Status': r.get('status', 'Enabled'),
                'Filter': {'Prefix': r.get('prefix', '')}
            }
            if r.get('transitions'):
                rule['Transitions'] = [
                    {'Days': t['days'], 'StorageClass': t['storage_class']}
                    for t in r['transitions']
                ]
            if r.get('expiration_days'):
                rule['Expiration'] = {'Days': r['expiration_days']}
            if r.get('noncurrent_version_expiration_days'):
                rule['NoncurrentVersionExpiration'] = {
                    'NoncurrentDays': r['noncurrent_version_expiration_days']
                }
            lifecycle_rules.append(rule)

        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration={'Rules': lifecycle_rules}
        )

        return {
            'success': True,
            'bucket_name': bucket_name,
            'rules_applied': len(lifecycle_rules),
            'message': f'Lifecycle policy applied to {bucket_name} with {len(lifecycle_rules)} rule(s)'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 lifecycle policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def put_s3_replication(
    bucket_name: str,
    destination_bucket: str,
    destination_region: str,
    iam_role_arn: str,
    prefix: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure cross-region replication on an S3 bucket.

    Args:
        bucket_name: Source bucket name
        destination_bucket: Destination bucket name (must exist, versioning enabled)
        destination_region: AWS region of the destination bucket
        iam_role_arn: IAM role ARN that S3 will assume to replicate objects
        prefix: Optional key prefix filter (omit to replicate all objects)
        region: AWS region of the source bucket

    Returns:
        Dictionary with result
    """
    try:
        s3 = _get_boto_client('s3', region)

        # Versioning must be enabled on the source bucket for replication
        s3.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={'Status': 'Enabled'}
        )

        dest_bucket_arn = f'arn:aws:s3:::{destination_bucket}'
        rule: Dict = {
            'ID': 'replication-rule',
            'Status': 'Enabled',
            'Destination': {
                'Bucket': dest_bucket_arn,
                'StorageClass': 'STANDARD'
            }
        }
        if prefix is not None:
            rule['Filter'] = {'Prefix': prefix}
        else:
            rule['Filter'] = {'Prefix': ''}

        s3.put_bucket_replication(
            Bucket=bucket_name,
            ReplicationConfiguration={
                'Role': iam_role_arn,
                'Rules': [rule]
            }
        )

        return {
            'success': True,
            'source_bucket': bucket_name,
            'destination_bucket': destination_bucket,
            'destination_region': destination_region,
            'message': f'Cross-region replication configured: {bucket_name} → {destination_bucket} ({destination_region})'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 replication: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def put_s3_bucket_policy(
    bucket_name: str,
    policy: Dict,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Apply a bucket policy to an S3 bucket.

    Args:
        bucket_name: Name of the S3 bucket
        policy: IAM policy document as a dict. Example:
                {
                  'Version': '2012-10-17',
                  'Statement': [{
                    'Effect': 'Allow',
                    'Principal': {'AWS': 'arn:aws:iam::123456789012:role/MyRole'},
                    'Action': ['s3:GetObject'],
                    'Resource': 'arn:aws:s3:::my-bucket/*'
                  }]
                }
        region: AWS region

    Returns:
        Dictionary with result
    """
    try:
        s3 = _get_boto_client('s3', region)

        policy_str = json.dumps(policy) if isinstance(policy, dict) else policy
        s3.put_bucket_policy(Bucket=bucket_name, Policy=policy_str)

        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Bucket policy applied to {bucket_name}'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 bucket policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# S3 EXTENDED OPERATIONS
# ============================================================================

def list_s3_objects(
    bucket_name: str,
    prefix: Optional[str] = None,
    delimiter: Optional[str] = None,
    max_keys: int = 100,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List objects in an S3 bucket, optionally filtered by prefix."""
    try:
        s3 = _get_boto_client('s3', region)
        params: Dict = {'Bucket': bucket_name, 'MaxKeys': max_keys}
        if prefix:
            params['Prefix'] = prefix
        if delimiter:
            params['Delimiter'] = delimiter

        response = s3.list_objects_v2(**params)
        objects = [
            {
                'key': obj['Key'],
                'size_bytes': obj['Size'],
                'last_modified': str(obj['LastModified']),
                'storage_class': obj.get('StorageClass', 'STANDARD'),
                'etag': obj.get('ETag', '').strip('"')
            }
            for obj in response.get('Contents', [])
        ]
        common_prefixes = [p['Prefix'] for p in response.get('CommonPrefixes', [])]
        return {
            'success': True,
            'bucket_name': bucket_name,
            'objects': objects,
            'count': len(objects),
            'common_prefixes': common_prefixes,
            'is_truncated': response.get('IsTruncated', False),
            'key_count': response.get('KeyCount', len(objects))
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing S3 objects: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def upload_s3_object(
    bucket_name: str,
    key: str,
    content: str,
    content_type: str = 'text/plain',
    storage_class: str = 'STANDARD',
    metadata: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Upload text/JSON content as an object to S3."""
    try:
        s3 = _get_boto_client('s3', region)
        params: Dict = {
            'Bucket': bucket_name,
            'Key': key,
            'Body': content.encode('utf-8'),
            'ContentType': content_type,
            'StorageClass': storage_class
        }
        if metadata:
            params['Metadata'] = metadata

        s3.put_object(**params)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'key': key,
            'size_bytes': len(content.encode('utf-8')),
            'storage_class': storage_class,
            'message': f'Object uploaded: s3://{bucket_name}/{key}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error uploading S3 object: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def download_s3_object(
    bucket_name: str,
    key: str,
    max_bytes: int = 102400,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Download an object from S3 and return its text content (up to max_bytes)."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.get_object(Bucket=bucket_name, Key=key)
        body = response['Body'].read(max_bytes)
        truncated = response['ContentLength'] > max_bytes

        try:
            content = body.decode('utf-8')
        except UnicodeDecodeError:
            content = f'[Binary content — {response["ContentLength"]} bytes. Use generate_s3_presigned_url to download.]'

        return {
            'success': True,
            'bucket_name': bucket_name,
            'key': key,
            'content': content,
            'content_type': response.get('ContentType', ''),
            'content_length': response['ContentLength'],
            'last_modified': str(response['LastModified']),
            'truncated': truncated,
            'etag': response.get('ETag', '').strip('"')
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error downloading S3 object: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_object(bucket_name: str, key: str, version_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a single object from S3 (optionally a specific version)."""
    try:
        s3 = _get_boto_client('s3', region)
        params: Dict = {'Bucket': bucket_name, 'Key': key}
        if version_id:
            params['VersionId'] = version_id

        s3.delete_object(**params)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'key': key,
            'message': f'Deleted s3://{bucket_name}/{key}' + (f' (version {version_id})' if version_id else '')
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting S3 object: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_objects_batch(
    bucket_name: str,
    keys: List[str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete up to 1000 objects from S3 in a single request."""
    try:
        s3 = _get_boto_client('s3', region)
        delete_objects = [{'Key': k} for k in keys[:1000]]
        response = s3.delete_objects(
            Bucket=bucket_name,
            Delete={'Objects': delete_objects, 'Quiet': False}
        )
        deleted = [d['Key'] for d in response.get('Deleted', [])]
        errors = response.get('Errors', [])
        return {
            'success': True,
            'bucket_name': bucket_name,
            'deleted_count': len(deleted),
            'error_count': len(errors),
            'errors': errors,
            'message': f'Deleted {len(deleted)} object(s) from {bucket_name}' + (
                f', {len(errors)} failed' if errors else ''
            )
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error batch deleting S3 objects: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def copy_s3_object(
    source_bucket: str,
    source_key: str,
    dest_bucket: str,
    dest_key: str,
    storage_class: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Copy an object within or across S3 buckets."""
    try:
        s3 = _get_boto_client('s3', region)
        params: Dict = {
            'CopySource': {'Bucket': source_bucket, 'Key': source_key},
            'Bucket': dest_bucket,
            'Key': dest_key
        }
        if storage_class:
            params['StorageClass'] = storage_class
            params['MetadataDirective'] = 'COPY'

        s3.copy_object(**params)
        return {
            'success': True,
            'source': f's3://{source_bucket}/{source_key}',
            'destination': f's3://{dest_bucket}/{dest_key}',
            'message': f'Copied s3://{source_bucket}/{source_key} → s3://{dest_bucket}/{dest_key}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error copying S3 object: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_s3_object_metadata(bucket_name: str, key: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get metadata for an S3 object (ContentType, ETag, size, etc.) without downloading it."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.head_object(Bucket=bucket_name, Key=key)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'key': key,
            'content_type': response.get('ContentType', ''),
            'content_length': response.get('ContentLength', 0),
            'last_modified': str(response.get('LastModified', '')),
            'etag': response.get('ETag', '').strip('"'),
            'storage_class': response.get('StorageClass', 'STANDARD'),
            'server_side_encryption': response.get('ServerSideEncryption', 'None'),
            'version_id': response.get('VersionId', ''),
            'metadata': response.get('Metadata', {}),
            'expiration': response.get('Expiration', '')
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting S3 object metadata: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def generate_s3_presigned_url(
    bucket_name: str,
    key: str,
    operation: str = 'get_object',
    expires_in: int = 3600,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Generate a pre-signed URL for secure time-limited access to an S3 object."""
    try:
        s3 = _get_boto_client('s3', region)
        url = s3.generate_presigned_url(
            ClientMethod=operation,
            Params={'Bucket': bucket_name, 'Key': key},
            ExpiresIn=expires_in
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'key': key,
            'url': url,
            'expires_in_seconds': expires_in,
            'operation': operation,
            'message': f'Pre-signed URL generated for s3://{bucket_name}/{key} (expires in {expires_in}s)'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error generating S3 pre-signed URL: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_s3_bucket_policy(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Read the current bucket policy JSON for an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.get_bucket_policy(Bucket=bucket_name)
        policy = json.loads(response['Policy'])
        return {
            'success': True,
            'bucket_name': bucket_name,
            'policy': policy
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchBucketPolicy':
            return {'success': True, 'bucket_name': bucket_name, 'policy': None,
                    'message': 'No bucket policy is set on this bucket'}
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting S3 bucket policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_bucket_policy(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove the bucket policy from an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.delete_bucket_policy(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Bucket policy removed from {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting S3 bucket policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_public_access_block(
    bucket_name: str,
    block_public_acls: bool = True,
    ignore_public_acls: bool = True,
    block_public_policy: bool = True,
    restrict_public_buckets: bool = True,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable or configure public access block settings on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': block_public_acls,
                'IgnorePublicAcls': ignore_public_acls,
                'BlockPublicPolicy': block_public_policy,
                'RestrictPublicBuckets': restrict_public_buckets
            }
        )
        all_blocked = all([block_public_acls, ignore_public_acls, block_public_policy, restrict_public_buckets])
        return {
            'success': True,
            'bucket_name': bucket_name,
            'block_public_acls': block_public_acls,
            'ignore_public_acls': ignore_public_acls,
            'block_public_policy': block_public_policy,
            'restrict_public_buckets': restrict_public_buckets,
            'message': f'Public access {"fully blocked" if all_blocked else "configured"} on {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 public access block: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_versioning(
    bucket_name: str,
    status: str = 'Enabled',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable or suspend versioning on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.put_bucket_versioning(
            Bucket=bucket_name,
            VersioningConfiguration={'Status': status}
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'versioning_status': status,
            'message': f'Versioning {status.lower()} on {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 versioning: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_s3_object_versions(
    bucket_name: str,
    prefix: Optional[str] = None,
    max_keys: int = 100,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List all versions (and delete markers) of objects in a versioned S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        params: Dict = {'Bucket': bucket_name, 'MaxKeys': max_keys}
        if prefix:
            params['Prefix'] = prefix

        response = s3.list_object_versions(**params)
        versions = [
            {
                'key': v['Key'],
                'version_id': v['VersionId'],
                'is_latest': v['IsLatest'],
                'last_modified': str(v['LastModified']),
                'size_bytes': v['Size'],
                'etag': v.get('ETag', '').strip('"')
            }
            for v in response.get('Versions', [])
        ]
        delete_markers = [
            {
                'key': d['Key'],
                'version_id': d['VersionId'],
                'is_latest': d['IsLatest'],
                'last_modified': str(d['LastModified'])
            }
            for d in response.get('DeleteMarkers', [])
        ]
        return {
            'success': True,
            'bucket_name': bucket_name,
            'versions': versions,
            'delete_markers': delete_markers,
            'versions_count': len(versions),
            'delete_markers_count': len(delete_markers)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing S3 object versions: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_default_encryption(
    bucket_name: str,
    sse_algorithm: str = 'AES256',
    kms_key_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enable default server-side encryption on an S3 bucket.
    Use sse_algorithm='AES256' for SSE-S3 or 'aws:kms' with kms_key_id for SSE-KMS.
    """
    try:
        s3 = _get_boto_client('s3', region)
        rule: Dict = {'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': sse_algorithm}}
        if kms_key_id:
            rule['ApplyServerSideEncryptionByDefault']['KMSMasterKeyID'] = kms_key_id

        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={'Rules': [rule]}
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'sse_algorithm': sse_algorithm,
            'kms_key_id': kms_key_id or 'AWS managed',
            'message': f'Default encryption ({sse_algorithm}) enabled on {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 encryption: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_website(
    bucket_name: str,
    index_document: str = 'index.html',
    error_document: str = 'error.html',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable static website hosting on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.put_bucket_website(
            Bucket=bucket_name,
            WebsiteConfiguration={
                'IndexDocument': {'Suffix': index_document},
                'ErrorDocument': {'Key': error_document}
            }
        )
        region_name = region or 'us-east-1'
        website_url = (
            f'http://{bucket_name}.s3-website-{region_name}.amazonaws.com'
            if region_name == 'us-east-1'
            else f'http://{bucket_name}.s3-website.{region_name}.amazonaws.com'
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'index_document': index_document,
            'error_document': error_document,
            'website_url': website_url,
            'message': f'Static website hosting enabled: {website_url}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error enabling S3 website: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_website(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Disable static website hosting on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.delete_bucket_website(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Static website hosting disabled on {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error disabling S3 website: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_cors(
    bucket_name: str,
    allowed_origins: List[str],
    allowed_methods: Optional[List[str]] = None,
    allowed_headers: Optional[List[str]] = None,
    max_age_seconds: int = 3600,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Configure CORS rules on an S3 bucket for cross-origin web access."""
    try:
        s3 = _get_boto_client('s3', region)
        rule: Dict = {
            'AllowedOrigins': allowed_origins,
            'AllowedMethods': allowed_methods or ['GET', 'HEAD'],
            'MaxAgeSeconds': max_age_seconds
        }
        if allowed_headers:
            rule['AllowedHeaders'] = allowed_headers

        s3.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={'CORSRules': [rule]}
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'allowed_origins': allowed_origins,
            'allowed_methods': rule['AllowedMethods'],
            'message': f'CORS configured on {bucket_name} for origins: {allowed_origins}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 CORS: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_logging(
    bucket_name: str,
    target_bucket: str,
    target_prefix: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable server access logging on an S3 bucket, writing logs to a target bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        logging_config: Dict = {
            'LoggingEnabled': {
                'TargetBucket': target_bucket,
                'TargetPrefix': target_prefix or f'{bucket_name}/'
            }
        }
        s3.put_bucket_logging(Bucket=bucket_name, BucketLoggingStatus=logging_config)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'target_bucket': target_bucket,
            'target_prefix': target_prefix or f'{bucket_name}/',
            'message': f'Access logging enabled on {bucket_name} → s3://{target_bucket}/{target_prefix or bucket_name + "/"}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error enabling S3 logging: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def tag_s3_bucket(
    bucket_name: str,
    tags: Dict[str, str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Apply tags to an S3 bucket (replaces all existing tags)."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={'TagSet': [{'Key': k, 'Value': v} for k, v in tags.items()]}
        )
        return {
            'success': True,
            'bucket_name': bucket_name,
            'tags': tags,
            'message': f'Tags applied to bucket {bucket_name}: {tags}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error tagging S3 bucket: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_s3_bucket_tags(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get all tags on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.get_bucket_tagging(Bucket=bucket_name)
        tags = {t['Key']: t['Value'] for t in response.get('TagSet', [])}
        return {
            'success': True,
            'bucket_name': bucket_name,
            'tags': tags,
            'count': len(tags)
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchTagSet':
            return {'success': True, 'bucket_name': bucket_name, 'tags': {}, 'count': 0,
                    'message': 'No tags on this bucket'}
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting S3 bucket tags: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_bucket_tags(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove all tags from an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.delete_bucket_tagging(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'All tags removed from bucket {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting S3 bucket tags: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def set_s3_notification(
    bucket_name: str,
    lambda_arn: Optional[str] = None,
    sqs_arn: Optional[str] = None,
    sns_arn: Optional[str] = None,
    events: Optional[List[str]] = None,
    prefix_filter: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Configure event notifications on an S3 bucket to trigger Lambda, SQS, or SNS."""
    try:
        s3 = _get_boto_client('s3', region)
        event_list = events or ['s3:ObjectCreated:*']
        filters: Dict = {}
        if prefix_filter:
            filters = {'Key': {'FilterRules': [{'Name': 'prefix', 'Value': prefix_filter}]}}

        config: Dict = {}
        if lambda_arn:
            config['LambdaFunctionConfigurations'] = [{
                'LambdaFunctionArn': lambda_arn,
                'Events': event_list,
                **(({'Filter': filters}) if filters else {})
            }]
        if sqs_arn:
            config['QueueConfigurations'] = [{
                'QueueArn': sqs_arn,
                'Events': event_list,
                **(({'Filter': filters}) if filters else {})
            }]
        if sns_arn:
            config['TopicConfigurations'] = [{
                'TopicArn': sns_arn,
                'Events': event_list,
                **(({'Filter': filters}) if filters else {})
            }]

        if not config:
            return {'success': False, 'error': 'Provide at least one of: lambda_arn, sqs_arn, sns_arn'}

        s3.put_bucket_notification_configuration(
            Bucket=bucket_name,
            NotificationConfiguration=config
        )
        targets = [t for t in [lambda_arn, sqs_arn, sns_arn] if t]
        return {
            'success': True,
            'bucket_name': bucket_name,
            'events': event_list,
            'targets': targets,
            'message': f'Event notifications configured on {bucket_name} for events: {event_list}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error setting S3 notifications: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_s3_lifecycle_policy(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Read the current lifecycle configuration on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'rules': response.get('Rules', []),
            'rules_count': len(response.get('Rules', []))
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchLifecycleConfiguration':
            return {'success': True, 'bucket_name': bucket_name, 'rules': [], 'rules_count': 0,
                    'message': 'No lifecycle configuration on this bucket'}
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting S3 lifecycle policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_lifecycle_policy(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove all lifecycle rules from an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.delete_bucket_lifecycle(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Lifecycle configuration removed from {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting S3 lifecycle policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_s3_replication(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Read the current replication configuration on an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        response = s3.get_bucket_replication(Bucket=bucket_name)
        config = response.get('ReplicationConfiguration', {})
        return {
            'success': True,
            'bucket_name': bucket_name,
            'role': config.get('Role', ''),
            'rules': config.get('Rules', []),
            'rules_count': len(config.get('Rules', []))
        }
    except ClientError as e:
        if e.response['Error']['Code'] == 'ReplicationConfigurationNotFoundError':
            return {'success': True, 'bucket_name': bucket_name, 'rules': [], 'rules_count': 0,
                    'message': 'No replication configuration on this bucket'}
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error getting S3 replication: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_s3_replication(bucket_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove the replication configuration from an S3 bucket."""
    try:
        s3 = _get_boto_client('s3', region)
        s3.delete_bucket_replication(Bucket=bucket_name)
        return {
            'success': True,
            'bucket_name': bucket_name,
            'message': f'Replication configuration removed from {bucket_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting S3 replication: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# VPC OPERATIONS
# ============================================================================

def list_vpcs(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List all VPCs in the account.

    Args:
        region: AWS region

    Returns:
        Dictionary with VPC information
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_vpcs()

        vpcs = []
        for vpc in response['Vpcs']:
            tags = {tag['Key']: tag['Value'] for tag in vpc.get('Tags', [])}
            vpcs.append({
                'vpc_id': vpc['VpcId'],
                'cidr_block': vpc['CidrBlock'],
                'state': vpc['State'],
                'is_default': vpc.get('IsDefault', False),
                'name': tags.get('Name', 'N/A'),
                'tags': tags
            })

        return {
            'success': True,
            'count': len(vpcs),
            'vpcs': vpcs,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing VPCs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_subnets(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """
    List subnets, optionally filtered by VPC.

    Args:
        vpc_id: VPC ID to filter by (optional)
        region: AWS region

    Returns:
        Dictionary with subnet information
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        filters = []
        if vpc_id:
            filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})

        response = ec2.describe_subnets(Filters=filters)

        subnets = []
        for subnet in response['Subnets']:
            tags = {tag['Key']: tag['Value'] for tag in subnet.get('Tags', [])}
            subnets.append({
                'subnet_id': subnet['SubnetId'],
                'vpc_id': subnet['VpcId'],
                'cidr_block': subnet['CidrBlock'],
                'availability_zone': subnet['AvailabilityZone'],
                'available_ips': subnet['AvailableIpAddressCount'],
                'state': subnet['State'],
                'name': tags.get('Name', 'N/A'),
                'tags': tags
            })

        return {
            'success': True,
            'count': len(subnets),
            'subnets': subnets,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing subnets: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_vpc(
    cidr_block: str,
    name: Optional[str] = None,
    enable_dns_support: bool = True,
    enable_dns_hostnames: bool = True,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a VPC with DNS support enabled."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.create_vpc(CidrBlock=cidr_block)
        vpc_id = response['Vpc']['VpcId']

        if enable_dns_support:
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})
        if enable_dns_hostnames:
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
        if name:
            ec2.create_tags(Resources=[vpc_id], Tags=[{'Key': 'Name', 'Value': name}])

        return {
            'success': True, 'vpc_id': vpc_id, 'cidr_block': cidr_block,
            'name': name or 'N/A', 'dns_support': enable_dns_support,
            'dns_hostnames': enable_dns_hostnames,
            'message': f'Successfully created VPC {vpc_id} ({cidr_block})',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating VPC: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_vpc(vpc_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a VPC. All dependent resources must be deleted first."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_vpc(VpcId=vpc_id)
        return {
            'success': True, 'vpc_id': vpc_id,
            'message': f'Successfully deleted VPC {vpc_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting VPC: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_subnet(
    vpc_id: str,
    cidr_block: str,
    availability_zone: Optional[str] = None,
    name: Optional[str] = None,
    map_public_ip: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a subnet in a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params = {'VpcId': vpc_id, 'CidrBlock': cidr_block}
        if availability_zone:
            params['AvailabilityZone'] = availability_zone

        response = ec2.create_subnet(**params)
        subnet_id = response['Subnet']['SubnetId']

        if map_public_ip:
            ec2.modify_subnet_attribute(SubnetId=subnet_id, MapPublicIpOnLaunch={'Value': True})
        if name:
            ec2.create_tags(Resources=[subnet_id], Tags=[{'Key': 'Name', 'Value': name}])

        return {
            'success': True, 'subnet_id': subnet_id, 'vpc_id': vpc_id,
            'cidr_block': cidr_block,
            'availability_zone': response['Subnet'].get('AvailabilityZone'),
            'map_public_ip': map_public_ip,
            'message': f'Successfully created subnet {subnet_id} in {vpc_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating subnet: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_subnet(subnet_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a subnet."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_subnet(SubnetId=subnet_id)
        return {
            'success': True, 'subnet_id': subnet_id,
            'message': f'Successfully deleted subnet: {subnet_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting subnet: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_internet_gateway(
    vpc_id: str,
    name: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an internet gateway and attach it to a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.create_internet_gateway()
        igw_id = response['InternetGateway']['InternetGatewayId']

        ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)

        if name:
            ec2.create_tags(Resources=[igw_id], Tags=[{'Key': 'Name', 'Value': name}])

        return {
            'success': True, 'internet_gateway_id': igw_id, 'vpc_id': vpc_id,
            'message': f'Successfully created and attached internet gateway {igw_id} to {vpc_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating internet gateway: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_route_table(
    vpc_id: str,
    name: Optional[str] = None,
    routes: Optional[List[Dict[str, str]]] = None,
    subnet_ids: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a route table, add routes, and associate with subnets."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.create_route_table(VpcId=vpc_id)
        rtb_id = response['RouteTable']['RouteTableId']

        if name:
            ec2.create_tags(Resources=[rtb_id], Tags=[{'Key': 'Name', 'Value': name}])

        routes_added = 0
        if routes:
            for route in routes:
                route_params = {'RouteTableId': rtb_id, 'DestinationCidrBlock': route['cidr']}
                if 'gateway_id' in route:
                    route_params['GatewayId'] = route['gateway_id']
                elif 'nat_gateway_id' in route:
                    route_params['NatGatewayId'] = route['nat_gateway_id']
                elif 'instance_id' in route:
                    route_params['InstanceId'] = route['instance_id']
                ec2.create_route(**route_params)
                routes_added += 1

        associations = []
        if subnet_ids:
            for subnet_id in subnet_ids:
                assoc = ec2.associate_route_table(RouteTableId=rtb_id, SubnetId=subnet_id)
                associations.append(assoc['AssociationId'])

        return {
            'success': True, 'route_table_id': rtb_id, 'vpc_id': vpc_id,
            'routes_added': routes_added, 'subnet_associations': associations,
            'message': f'Successfully created route table {rtb_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating route table: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ---- VPC EXTENDED OPERATIONS ----

def describe_vpc(vpc_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed information about a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpc = response['Vpcs'][0]
        tags = {t['Key']: t['Value'] for t in vpc.get('Tags', [])}
        cidr_blocks = [a['CidrBlock'] for a in vpc.get('CidrBlockAssociationSet', [])]
        return {
            'success': True, 'vpc_id': vpc_id,
            'cidr_block': vpc.get('CidrBlock'),
            'additional_cidrs': cidr_blocks,
            'state': vpc.get('State'),
            'is_default': vpc.get('IsDefault'),
            'tenancy': vpc.get('InstanceTenancy'),
            'dhcp_options_id': vpc.get('DhcpOptionsId'),
            'tags': tags, 'name': tags.get('Name', ''),
            'owner_id': vpc.get('OwnerId'),
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def modify_vpc_attribute(
    vpc_id: str,
    enable_dns_support: Optional[bool] = None,
    enable_dns_hostnames: Optional[bool] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable or disable DNS resolution and DNS hostnames for a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        if enable_dns_support is not None:
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': enable_dns_support})
        if enable_dns_hostnames is not None:
            ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': enable_dns_hostnames})
        return {
            'success': True, 'vpc_id': vpc_id,
            'dns_support': enable_dns_support, 'dns_hostnames': enable_dns_hostnames,
            'message': f'VPC {vpc_id} attributes updated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def associate_vpc_cidr(vpc_id: str, cidr_block: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Add a secondary CIDR block to an existing VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.associate_vpc_cidr_block(VpcId=vpc_id, CidrBlock=cidr_block)
        assoc = response.get('CidrBlockAssociation', {})
        return {
            'success': True, 'vpc_id': vpc_id, 'cidr_block': cidr_block,
            'association_id': assoc.get('AssociationId'),
            'state': assoc.get('CidrBlockState', {}).get('State'),
            'message': f'CIDR {cidr_block} associated with VPC {vpc_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def disassociate_vpc_cidr(association_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove a secondary CIDR block from a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.disassociate_vpc_cidr_block(AssociationId=association_id)
        assoc = response.get('CidrBlockAssociation', {})
        return {
            'success': True, 'association_id': association_id,
            'cidr_block': assoc.get('CidrBlock'),
            'state': assoc.get('CidrBlockState', {}).get('State'),
            'message': f'CIDR association {association_id} disassociated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def tag_vpc(vpc_id: str, tags: Dict[str, str], region: Optional[str] = None) -> Dict[str, Any]:
    """Add or update tags on a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.create_tags(Resources=[vpc_id], Tags=[{'Key': k, 'Value': v} for k, v in tags.items()])
        return {'success': True, 'vpc_id': vpc_id, 'tags': tags, 'message': f'Tags applied to VPC {vpc_id}'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def enable_vpc_flow_logs(
    vpc_id: str,
    destination_type: str = 'cloud-watch-logs',
    log_group_name: Optional[str] = None,
    s3_bucket_arn: Optional[str] = None,
    iam_role_arn: Optional[str] = None,
    traffic_type: str = 'ALL',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable VPC Flow Logs to CloudWatch Logs or S3."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {
            'ResourceIds': [vpc_id],
            'ResourceType': 'VPC',
            'TrafficType': traffic_type,
            'LogDestinationType': destination_type,
        }
        if destination_type == 'cloud-watch-logs':
            kwargs['LogGroupName'] = log_group_name or f'/aws/vpc/flowlogs/{vpc_id}'
            if iam_role_arn:
                kwargs['DeliverLogsPermissionArn'] = iam_role_arn
        else:
            kwargs['LogDestination'] = s3_bucket_arn
        response = ec2.create_flow_logs(**kwargs)
        flow_log_ids = response.get('FlowLogIds', [])
        return {
            'success': True, 'vpc_id': vpc_id,
            'flow_log_ids': flow_log_ids,
            'destination_type': destination_type,
            'traffic_type': traffic_type,
            'message': f'Flow logs enabled for VPC {vpc_id}: {flow_log_ids}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_vpc_flow_logs(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List VPC Flow Log configurations."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'resource-id', 'Values': [vpc_id]}]
        response = ec2.describe_flow_logs(**kwargs)
        logs = []
        for fl in response.get('FlowLogs', []):
            logs.append({
                'flow_log_id': fl.get('FlowLogId'),
                'resource_id': fl.get('ResourceId'),
                'traffic_type': fl.get('TrafficType'),
                'log_destination_type': fl.get('LogDestinationType'),
                'log_destination': fl.get('LogDestination') or fl.get('LogGroupName'),
                'flow_log_status': fl.get('FlowLogStatus'),
            })
        return {'success': True, 'flow_logs': logs, 'count': len(logs)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def disable_vpc_flow_logs(flow_log_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a VPC Flow Log configuration."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_flow_logs(FlowLogIds=[flow_log_id])
        return {'success': True, 'flow_log_id': flow_log_id, 'message': f'Flow log {flow_log_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- SUBNET EXTENDED ----

def modify_subnet_attribute(
    subnet_id: str,
    map_public_ip_on_launch: Optional[bool] = None,
    assign_ipv6_address_on_creation: Optional[bool] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable/disable auto-assign public IP or IPv6 for a subnet."""
    try:
        ec2 = _get_boto_client('ec2', region)
        if map_public_ip_on_launch is not None:
            ec2.modify_subnet_attribute(SubnetId=subnet_id,
                                        MapPublicIpOnLaunch={'Value': map_public_ip_on_launch})
        if assign_ipv6_address_on_creation is not None:
            ec2.modify_subnet_attribute(SubnetId=subnet_id,
                                        AssignIpv6AddressOnCreation={'Value': assign_ipv6_address_on_creation})
        return {
            'success': True, 'subnet_id': subnet_id,
            'map_public_ip': map_public_ip_on_launch,
            'message': f'Subnet {subnet_id} attributes updated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def tag_subnet(subnet_id: str, tags: Dict[str, str], region: Optional[str] = None) -> Dict[str, Any]:
    """Add or update tags on a subnet."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.create_tags(Resources=[subnet_id], Tags=[{'Key': k, 'Value': v} for k, v in tags.items()])
        return {'success': True, 'subnet_id': subnet_id, 'tags': tags, 'message': f'Tags applied to subnet {subnet_id}'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- INTERNET GATEWAY EXTENDED ----

def list_internet_gateways(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List all Internet Gateways and their attachment status."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]
        response = ec2.describe_internet_gateways(**kwargs)
        igws = []
        for igw in response.get('InternetGateways', []):
            tags = {t['Key']: t['Value'] for t in igw.get('Tags', [])}
            attachments = igw.get('Attachments', [])
            igws.append({
                'internet_gateway_id': igw['InternetGatewayId'],
                'name': tags.get('Name', ''),
                'state': attachments[0]['State'] if attachments else 'detached',
                'attached_vpc': attachments[0]['VpcId'] if attachments else None,
                'tags': tags,
            })
        return {'success': True, 'internet_gateways': igws, 'count': len(igws)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def attach_internet_gateway(igw_id: str, vpc_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Attach an existing Internet Gateway to a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
        return {'success': True, 'internet_gateway_id': igw_id, 'vpc_id': vpc_id,
                'message': f'IGW {igw_id} attached to VPC {vpc_id}'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def detach_internet_gateway(igw_id: str, vpc_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Detach an Internet Gateway from a VPC without deleting it."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
        return {'success': True, 'internet_gateway_id': igw_id, 'vpc_id': vpc_id,
                'message': f'IGW {igw_id} detached from VPC {vpc_id}'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_internet_gateway(igw_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an Internet Gateway (must be detached first)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_internet_gateway(InternetGatewayId=igw_id)
        return {'success': True, 'internet_gateway_id': igw_id,
                'message': f'IGW {igw_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- ROUTE TABLE EXTENDED ----

def list_route_tables(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List all route tables in a VPC or region."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'vpc-id', 'Values': [vpc_id]}]
        response = ec2.describe_route_tables(**kwargs)
        tables = []
        for rt in response.get('RouteTables', []):
            tags = {t['Key']: t['Value'] for t in rt.get('Tags', [])}
            routes = [{'destination': r.get('DestinationCidrBlock'),
                       'target': r.get('GatewayId') or r.get('NatGatewayId') or r.get('InstanceId', 'local'),
                       'state': r.get('State')} for r in rt.get('Routes', [])]
            associations = [a.get('SubnetId') for a in rt.get('Associations', []) if a.get('SubnetId')]
            tables.append({
                'route_table_id': rt['RouteTableId'],
                'vpc_id': rt.get('VpcId'),
                'name': tags.get('Name', ''),
                'is_main': any(a.get('Main') for a in rt.get('Associations', [])),
                'routes': routes,
                'associated_subnets': associations,
                'tags': tags,
            })
        return {'success': True, 'route_tables': tables, 'count': len(tables)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_route_table(route_table_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a route table (must have no subnet associations)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_route_table(RouteTableId=route_table_id)
        return {'success': True, 'route_table_id': route_table_id,
                'message': f'Route table {route_table_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def add_route(
    route_table_id: str,
    destination_cidr: str,
    gateway_id: Optional[str] = None,
    nat_gateway_id: Optional[str] = None,
    instance_id: Optional[str] = None,
    vpc_peering_connection_id: Optional[str] = None,
    transit_gateway_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Add a route to a route table."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {'RouteTableId': route_table_id, 'DestinationCidrBlock': destination_cidr}
        if gateway_id:
            kwargs['GatewayId'] = gateway_id
        elif nat_gateway_id:
            kwargs['NatGatewayId'] = nat_gateway_id
        elif instance_id:
            kwargs['InstanceId'] = instance_id
        elif vpc_peering_connection_id:
            kwargs['VpcPeeringConnectionId'] = vpc_peering_connection_id
        elif transit_gateway_id:
            kwargs['TransitGatewayId'] = transit_gateway_id
        ec2.create_route(**kwargs)
        return {
            'success': True, 'route_table_id': route_table_id,
            'destination_cidr': destination_cidr,
            'message': f'Route {destination_cidr} added to {route_table_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_route(route_table_id: str, destination_cidr: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Remove a route from a route table."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_route(RouteTableId=route_table_id, DestinationCidrBlock=destination_cidr)
        return {
            'success': True, 'route_table_id': route_table_id,
            'destination_cidr': destination_cidr,
            'message': f'Route {destination_cidr} deleted from {route_table_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def replace_route(
    route_table_id: str,
    destination_cidr: str,
    gateway_id: Optional[str] = None,
    nat_gateway_id: Optional[str] = None,
    instance_id: Optional[str] = None,
    transit_gateway_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Replace the target of an existing route in a route table."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {'RouteTableId': route_table_id, 'DestinationCidrBlock': destination_cidr}
        if gateway_id:
            kwargs['GatewayId'] = gateway_id
        elif nat_gateway_id:
            kwargs['NatGatewayId'] = nat_gateway_id
        elif instance_id:
            kwargs['InstanceId'] = instance_id
        elif transit_gateway_id:
            kwargs['TransitGatewayId'] = transit_gateway_id
        ec2.replace_route(**kwargs)
        return {
            'success': True, 'route_table_id': route_table_id,
            'destination_cidr': destination_cidr,
            'message': f'Route {destination_cidr} in {route_table_id} updated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def associate_route_table(
    route_table_id: str,
    subnet_id: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Associate a subnet with a route table."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.associate_route_table(RouteTableId=route_table_id, SubnetId=subnet_id)
        return {
            'success': True, 'route_table_id': route_table_id, 'subnet_id': subnet_id,
            'association_id': response['AssociationId'],
            'message': f'Subnet {subnet_id} associated with route table {route_table_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def disassociate_route_table(association_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Disassociate a subnet from a route table."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.disassociate_route_table(AssociationId=association_id)
        return {'success': True, 'association_id': association_id,
                'message': f'Route table association {association_id} removed'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def set_main_route_table(route_table_id: str, vpc_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Change the main (default) route table for a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        # Find the current main route table association
        response = ec2.describe_route_tables(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}, {'Name': 'association.main', 'Values': ['true']}]
        )
        if not response.get('RouteTables'):
            return {'success': False, 'error': 'Could not find current main route table'}
        main_assoc_id = None
        for assoc in response['RouteTables'][0].get('Associations', []):
            if assoc.get('Main'):
                main_assoc_id = assoc['RouteTableAssociationId']
                break
        if not main_assoc_id:
            return {'success': False, 'error': 'Could not find main route table association ID'}
        result = ec2.replace_route_table_association(AssociationId=main_assoc_id, RouteTableId=route_table_id)
        return {
            'success': True, 'route_table_id': route_table_id, 'vpc_id': vpc_id,
            'new_association_id': result['NewAssociationId'],
            'message': f'Route table {route_table_id} set as main for VPC {vpc_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- SECURITY GROUP EXTENDED ----

def authorize_security_group_egress(
    group_id: str,
    protocol: str,
    from_port: int,
    to_port: int,
    cidr_ip: str = '0.0.0.0/0',
    description: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Add an outbound (egress) rule to a security group."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ip_permission = {
            'IpProtocol': protocol,
            'FromPort': from_port,
            'ToPort': to_port,
            'IpRanges': [{'CidrIp': cidr_ip, 'Description': description or ''}],
        }
        ec2.authorize_security_group_egress(GroupId=group_id, IpPermissions=[ip_permission])
        return {
            'success': True, 'group_id': group_id,
            'protocol': protocol, 'ports': f'{from_port}-{to_port}', 'cidr': cidr_ip,
            'message': f'Outbound rule added to {group_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def revoke_security_group_egress(
    group_id: str,
    protocol: str,
    from_port: int,
    to_port: int,
    cidr_ip: str = '0.0.0.0/0',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Remove an outbound (egress) rule from a security group."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ip_permission = {
            'IpProtocol': protocol,
            'FromPort': from_port,
            'ToPort': to_port,
            'IpRanges': [{'CidrIp': cidr_ip}],
        }
        ec2.revoke_security_group_egress(GroupId=group_id, IpPermissions=[ip_permission])
        return {
            'success': True, 'group_id': group_id,
            'message': f'Outbound rule {protocol}/{from_port}-{to_port} from {cidr_ip} removed from {group_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def audit_security_group_rules(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """Identify overly permissive security group rules (0.0.0.0/0 on sensitive ports)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'vpc-id', 'Values': [vpc_id]}]
        response = ec2.describe_security_groups(**kwargs)
        sensitive_ports = {22, 3389, 3306, 5432, 6379, 27017, 9200, 8080, 443, 80}
        findings = []
        for sg in response.get('SecurityGroups', []):
            tags = {t['Key']: t['Value'] for t in sg.get('Tags', [])}
            for perm in sg.get('IpPermissions', []):
                for ip_range in perm.get('IpRanges', []):
                    if ip_range.get('CidrIp') in ('0.0.0.0/0', '::/0'):
                        from_port = perm.get('FromPort', 0)
                        to_port = perm.get('ToPort', 65535)
                        risk = 'CRITICAL' if any(p in range(from_port, to_port + 1) for p in sensitive_ports) else 'HIGH'
                        findings.append({
                            'group_id': sg['GroupId'],
                            'group_name': sg.get('GroupName'),
                            'name': tags.get('Name', ''),
                            'vpc_id': sg.get('VpcId'),
                            'protocol': perm.get('IpProtocol'),
                            'ports': f"{from_port}-{to_port}" if from_port != to_port else str(from_port),
                            'cidr': ip_range.get('CidrIp'),
                            'direction': 'inbound',
                            'risk': risk,
                        })
        return {
            'success': True, 'findings': findings, 'total_findings': len(findings),
            'critical': len([f for f in findings if f['risk'] == 'CRITICAL']),
            'high': len([f for f in findings if f['risk'] == 'HIGH']),
            'message': f'Found {len(findings)} overly permissive inbound rules'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def tag_security_group(group_id: str, tags: Dict[str, str], region: Optional[str] = None) -> Dict[str, Any]:
    """Add or update tags on a security group."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.create_tags(Resources=[group_id], Tags=[{'Key': k, 'Value': v} for k, v in tags.items()])
        return {'success': True, 'group_id': group_id, 'tags': tags,
                'message': f'Tags applied to security group {group_id}'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- NETWORK ACLs ----

def create_network_acl(
    vpc_id: str,
    name: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Network ACL in a VPC."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.create_network_acl(VpcId=vpc_id)
        nacl_id = response['NetworkAcl']['NetworkAclId']
        if name:
            ec2.create_tags(Resources=[nacl_id], Tags=[{'Key': 'Name', 'Value': name}])
        return {
            'success': True, 'network_acl_id': nacl_id, 'vpc_id': vpc_id,
            'message': f'Network ACL {nacl_id} created in VPC {vpc_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_network_acls(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List Network ACLs in a VPC or region."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'vpc-id', 'Values': [vpc_id]}]
        response = ec2.describe_network_acls(**kwargs)
        nacls = []
        for nacl in response.get('NetworkAcls', []):
            tags = {t['Key']: t['Value'] for t in nacl.get('Tags', [])}
            nacls.append({
                'network_acl_id': nacl['NetworkAclId'],
                'vpc_id': nacl.get('VpcId'),
                'name': tags.get('Name', ''),
                'is_default': nacl.get('IsDefault'),
                'entries_count': len(nacl.get('Entries', [])),
                'associated_subnets': [a['SubnetId'] for a in nacl.get('Associations', [])],
                'tags': tags,
            })
        return {'success': True, 'network_acls': nacls, 'count': len(nacls)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_network_acl(network_acl_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Network ACL (must have no subnet associations)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_network_acl(NetworkAclId=network_acl_id)
        return {'success': True, 'network_acl_id': network_acl_id,
                'message': f'Network ACL {network_acl_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def create_nacl_entry(
    network_acl_id: str,
    rule_number: int,
    protocol: str,
    rule_action: str,
    egress: bool,
    cidr_block: str,
    from_port: Optional[int] = None,
    to_port: Optional[int] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Add an entry (rule) to a Network ACL."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {
            'NetworkAclId': network_acl_id,
            'RuleNumber': rule_number,
            'Protocol': protocol,
            'RuleAction': rule_action,
            'Egress': egress,
            'CidrBlock': cidr_block,
        }
        if from_port is not None and to_port is not None:
            kwargs['PortRange'] = {'From': from_port, 'To': to_port}
        ec2.create_network_acl_entry(**kwargs)
        return {
            'success': True, 'network_acl_id': network_acl_id, 'rule_number': rule_number,
            'direction': 'egress' if egress else 'ingress', 'action': rule_action,
            'message': f'NACL rule {rule_number} added to {network_acl_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_nacl_entry(
    network_acl_id: str,
    rule_number: int,
    egress: bool,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a specific rule from a Network ACL by rule number."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_network_acl_entry(NetworkAclId=network_acl_id, RuleNumber=rule_number, Egress=egress)
        return {
            'success': True, 'network_acl_id': network_acl_id, 'rule_number': rule_number,
            'message': f'NACL rule {rule_number} deleted from {network_acl_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def associate_nacl_with_subnet(
    network_acl_id: str,
    subnet_id: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Associate a Network ACL with a subnet (replaces any existing association)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        # Find the current association for this subnet
        response = ec2.describe_network_acls(
            Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}]
        )
        if not response.get('NetworkAcls'):
            return {'success': False, 'error': f'No existing NACL association found for subnet {subnet_id}'}
        current_assoc_id = None
        for nacl in response['NetworkAcls']:
            for assoc in nacl.get('Associations', []):
                if assoc.get('SubnetId') == subnet_id:
                    current_assoc_id = assoc['NetworkAclAssociationId']
                    break
        if not current_assoc_id:
            return {'success': False, 'error': 'Could not find association ID for subnet'}
        result = ec2.replace_network_acl_association(
            AssociationId=current_assoc_id, NetworkAclId=network_acl_id
        )
        return {
            'success': True, 'network_acl_id': network_acl_id, 'subnet_id': subnet_id,
            'new_association_id': result['NewAssociationId'],
            'message': f'Subnet {subnet_id} now uses NACL {network_acl_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- VPC PEERING ----

def create_vpc_peering(
    vpc_id: str,
    peer_vpc_id: str,
    peer_owner_id: Optional[str] = None,
    peer_region: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Initiate a VPC peering connection request."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {'VpcId': vpc_id, 'PeerVpcId': peer_vpc_id}
        if peer_owner_id:
            kwargs['PeerOwnerId'] = peer_owner_id
        if peer_region:
            kwargs['PeerRegion'] = peer_region
        response = ec2.create_vpc_peering_connection(**kwargs)
        pcx = response['VpcPeeringConnection']
        return {
            'success': True,
            'peering_connection_id': pcx['VpcPeeringConnectionId'],
            'status': pcx['Status']['Code'],
            'requester_vpc': pcx['RequesterVpcInfo'].get('VpcId'),
            'accepter_vpc': pcx['AccepterVpcInfo'].get('VpcId'),
            'message': f'VPC peering request created: {pcx["VpcPeeringConnectionId"]} — accepter must approve'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_vpc_peerings(region: Optional[str] = None) -> Dict[str, Any]:
    """List all VPC peering connections and their status."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_vpc_peering_connections()
        peerings = []
        for pcx in response.get('VpcPeeringConnections', []):
            tags = {t['Key']: t['Value'] for t in pcx.get('Tags', [])}
            peerings.append({
                'peering_connection_id': pcx['VpcPeeringConnectionId'],
                'status': pcx['Status']['Code'],
                'status_message': pcx['Status'].get('Message', ''),
                'requester_vpc': pcx['RequesterVpcInfo'].get('VpcId'),
                'requester_cidr': pcx['RequesterVpcInfo'].get('CidrBlock'),
                'accepter_vpc': pcx['AccepterVpcInfo'].get('VpcId'),
                'accepter_cidr': pcx['AccepterVpcInfo'].get('CidrBlock'),
                'name': tags.get('Name', ''),
            })
        return {'success': True, 'peering_connections': peerings, 'count': len(peerings)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def accept_vpc_peering(peering_connection_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Accept an incoming VPC peering connection request."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.accept_vpc_peering_connection(VpcPeeringConnectionId=peering_connection_id)
        pcx = response['VpcPeeringConnection']
        return {
            'success': True, 'peering_connection_id': peering_connection_id,
            'status': pcx['Status']['Code'],
            'message': f'Peering connection {peering_connection_id} accepted — update route tables to route traffic'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_vpc_peering(peering_connection_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a VPC peering connection."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_vpc_peering_connection(VpcPeeringConnectionId=peering_connection_id)
        return {
            'success': True, 'peering_connection_id': peering_connection_id,
            'message': f'VPC peering connection {peering_connection_id} deleted'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- VPC ENDPOINTS ----

def create_vpc_endpoint(
    vpc_id: str,
    service_name: str,
    endpoint_type: str = 'Gateway',
    route_table_ids: Optional[List[str]] = None,
    subnet_ids: Optional[List[str]] = None,
    security_group_ids: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a VPC endpoint (Gateway for S3/DynamoDB, Interface for other services)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {'VpcId': vpc_id, 'ServiceName': service_name, 'VpcEndpointType': endpoint_type}
        if route_table_ids and endpoint_type == 'Gateway':
            kwargs['RouteTableIds'] = route_table_ids
        if subnet_ids and endpoint_type == 'Interface':
            kwargs['SubnetIds'] = subnet_ids
        if security_group_ids and endpoint_type == 'Interface':
            kwargs['SecurityGroupIds'] = security_group_ids
        response = ec2.create_vpc_endpoint(**kwargs)
        ep = response.get('VpcEndpoint', {})
        return {
            'success': True,
            'endpoint_id': ep.get('VpcEndpointId'),
            'state': ep.get('State'),
            'service_name': service_name,
            'endpoint_type': endpoint_type,
            'message': f'{endpoint_type} endpoint created for {service_name}: {ep.get("VpcEndpointId")}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_vpc_endpoints(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """List VPC endpoints and their service associations."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {}
        if vpc_id:
            kwargs['Filters'] = [{'Name': 'vpc-id', 'Values': [vpc_id]}]
        response = ec2.describe_vpc_endpoints(**kwargs)
        endpoints = []
        for ep in response.get('VpcEndpoints', []):
            endpoints.append({
                'endpoint_id': ep.get('VpcEndpointId'),
                'vpc_id': ep.get('VpcId'),
                'service_name': ep.get('ServiceName'),
                'state': ep.get('State'),
                'endpoint_type': ep.get('VpcEndpointType'),
                'private_dns_enabled': ep.get('PrivateDnsEnabled'),
                'subnets': ep.get('SubnetIds', []),
            })
        return {'success': True, 'endpoints': endpoints, 'count': len(endpoints)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_vpc_endpoint(endpoint_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a VPC endpoint."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
        return {'success': True, 'endpoint_id': endpoint_id,
                'message': f'VPC endpoint {endpoint_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- ELASTIC NETWORK INTERFACES (ENIs) ----

def create_eni(
    subnet_id: str,
    description: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    private_ip: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an Elastic Network Interface in a subnet."""
    try:
        ec2 = _get_boto_client('ec2', region)
        kwargs = {'SubnetId': subnet_id}
        if description:
            kwargs['Description'] = description
        if security_group_ids:
            kwargs['Groups'] = security_group_ids
        if private_ip:
            kwargs['PrivateIpAddress'] = private_ip
        response = ec2.create_network_interface(**kwargs)
        eni = response['NetworkInterface']
        return {
            'success': True,
            'network_interface_id': eni['NetworkInterfaceId'],
            'subnet_id': subnet_id,
            'private_ip': eni.get('PrivateIpAddress'),
            'status': eni.get('Status'),
            'message': f'ENI {eni["NetworkInterfaceId"]} created in subnet {subnet_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_enis(
    subnet_id: Optional[str] = None,
    vpc_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List Elastic Network Interfaces."""
    try:
        ec2 = _get_boto_client('ec2', region)
        filters = []
        if subnet_id:
            filters.append({'Name': 'subnet-id', 'Values': [subnet_id]})
        if vpc_id:
            filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})
        kwargs = {'Filters': filters} if filters else {}
        response = ec2.describe_network_interfaces(**kwargs)
        enis = []
        for eni in response.get('NetworkInterfaces', []):
            attachment = eni.get('Attachment', {})
            enis.append({
                'network_interface_id': eni['NetworkInterfaceId'],
                'subnet_id': eni.get('SubnetId'),
                'vpc_id': eni.get('VpcId'),
                'status': eni.get('Status'),
                'private_ip': eni.get('PrivateIpAddress'),
                'description': eni.get('Description'),
                'attached_instance': attachment.get('InstanceId'),
                'attachment_status': attachment.get('Status'),
            })
        return {'success': True, 'network_interfaces': enis, 'count': len(enis)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def attach_eni(
    network_interface_id: str,
    instance_id: str,
    device_index: int = 1,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Attach a network interface to an EC2 instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.attach_network_interface(
            NetworkInterfaceId=network_interface_id,
            InstanceId=instance_id,
            DeviceIndex=device_index
        )
        return {
            'success': True,
            'network_interface_id': network_interface_id,
            'instance_id': instance_id,
            'attachment_id': response['AttachmentId'],
            'message': f'ENI {network_interface_id} attached to {instance_id}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def detach_eni(attachment_id: str, force: bool = False, region: Optional[str] = None) -> Dict[str, Any]:
    """Detach a network interface from an EC2 instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.detach_network_interface(AttachmentId=attachment_id, Force=force)
        return {'success': True, 'attachment_id': attachment_id,
                'message': f'ENI attachment {attachment_id} detached'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_eni(network_interface_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an Elastic Network Interface (must be detached first)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_network_interface(NetworkInterfaceId=network_interface_id)
        return {'success': True, 'network_interface_id': network_interface_id,
                'message': f'ENI {network_interface_id} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def allocate_elastic_ip(
    instance_id: Optional[str] = None,
    name: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Allocate an Elastic IP and optionally associate with an instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.allocate_address(Domain='vpc')
        allocation_id = response['AllocationId']
        public_ip = response['PublicIp']

        if name:
            ec2.create_tags(Resources=[allocation_id], Tags=[{'Key': 'Name', 'Value': name}])

        association_id = None
        if instance_id:
            assoc = ec2.associate_address(AllocationId=allocation_id, InstanceId=instance_id)
            association_id = assoc['AssociationId']

        return {
            'success': True, 'allocation_id': allocation_id, 'public_ip': public_ip,
            'association_id': association_id, 'instance_id': instance_id,
            'message': f'Successfully allocated Elastic IP {public_ip}' +
                       (f' and associated with {instance_id}' if instance_id else ''),
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error allocating Elastic IP: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def release_elastic_ip(allocation_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Release an Elastic IP address."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.release_address(AllocationId=allocation_id)
        return {
            'success': True, 'allocation_id': allocation_id,
            'message': f'Successfully released Elastic IP {allocation_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error releasing Elastic IP: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def associate_elastic_ip(
    allocation_id: str,
    instance_id: Optional[str] = None,
    network_interface_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Associate an existing Elastic IP with an instance or network interface."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params: Dict = {'AllocationId': allocation_id}
        if instance_id:
            params['InstanceId'] = instance_id
        elif network_interface_id:
            params['NetworkInterfaceId'] = network_interface_id
        else:
            return {'success': False, 'error': 'instance_id or network_interface_id required'}

        response = ec2.associate_address(**params)
        target = instance_id or network_interface_id
        return {
            'success': True,
            'allocation_id': allocation_id,
            'association_id': response['AssociationId'],
            'target': target,
            'message': f'Elastic IP {allocation_id} associated with {target}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error associating Elastic IP: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def disassociate_elastic_ip(association_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Disassociate an Elastic IP from an instance or network interface."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.disassociate_address(AssociationId=association_id)
        return {
            'success': True,
            'association_id': association_id,
            'message': f'Elastic IP disassociated (association {association_id} removed)'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error disassociating Elastic IP: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_security_groups(vpc_id: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """
    List security groups, optionally filtered by VPC.

    Args:
        vpc_id: VPC ID to filter by (optional)
        region: AWS region

    Returns:
        Dictionary with security group information
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        filters = []
        if vpc_id:
            filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})

        response = ec2.describe_security_groups(Filters=filters)

        security_groups = []
        for sg in response['SecurityGroups']:
            tags = {tag['Key']: tag['Value'] for tag in sg.get('Tags', [])}
            security_groups.append({
                'group_id': sg['GroupId'],
                'group_name': sg['GroupName'],
                'description': sg['Description'],
                'vpc_id': sg.get('VpcId', 'EC2-Classic'),
                'ingress_rules_count': len(sg.get('IpPermissions', [])),
                'egress_rules_count': len(sg.get('IpPermissionsEgress', [])),
                'tags': tags
            })

        return {
            'success': True,
            'count': len(security_groups),
            'security_groups': security_groups,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing security groups: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# DYNAMODB OPERATIONS
# ============================================================================

def list_dynamodb_tables(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List all DynamoDB tables.

    Args:
        region: AWS region

    Returns:
        Dictionary with table information
    """
    try:
        dynamodb = _get_boto_client('dynamodb', region)
        response = dynamodb.list_tables()

        table_names = response.get('TableNames', [])

        # Get detailed info for each table
        tables = []
        for table_name in table_names:
            try:
                table_info = dynamodb.describe_table(TableName=table_name)['Table']
                tables.append({
                    'table_name': table_name,
                    'status': table_info.get('TableStatus'),
                    'item_count': table_info.get('ItemCount', 0),
                    'size_bytes': table_info.get('TableSizeBytes', 0),
                    'creation_date': table_info.get('CreationDateTime').isoformat() if table_info.get('CreationDateTime') else 'N/A',
                    'key_schema': table_info.get('KeySchema', []),
                    'billing_mode': table_info.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
                })
            except Exception:
                # If describe fails, just add basic info
                tables.append({'table_name': table_name, 'status': 'Unknown'})

        return {
            'success': True,
            'count': len(tables),
            'tables': tables,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing DynamoDB tables: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_dynamodb_table(
    table_name: str,
    partition_key: str,
    partition_key_type: str = 'S',
    sort_key: Optional[str] = None,
    sort_key_type: str = 'S',
    billing_mode: str = 'PAY_PER_REQUEST',
    read_capacity: int = 5,
    write_capacity: int = 5,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a DynamoDB table."""
    try:
        dynamodb = _get_boto_client('dynamodb', region)

        key_schema = [{'AttributeName': partition_key, 'KeyType': 'HASH'}]
        attr_defs = [{'AttributeName': partition_key, 'AttributeType': partition_key_type}]
        if sort_key:
            key_schema.append({'AttributeName': sort_key, 'KeyType': 'RANGE'})
            attr_defs.append({'AttributeName': sort_key, 'AttributeType': sort_key_type})

        params = {
            'TableName': table_name,
            'KeySchema': key_schema,
            'AttributeDefinitions': attr_defs,
            'BillingMode': billing_mode,
        }
        if billing_mode == 'PROVISIONED':
            params['ProvisionedThroughput'] = {
                'ReadCapacityUnits': read_capacity,
                'WriteCapacityUnits': write_capacity
            }
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = dynamodb.create_table(**params)
        table = response['TableDescription']
        return {
            'success': True, 'table_name': table['TableName'],
            'table_arn': table['TableArn'], 'status': table['TableStatus'],
            'billing_mode': billing_mode,
            'message': f'Successfully created DynamoDB table {table_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating DynamoDB table: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_dynamodb_table(table_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a DynamoDB table."""
    try:
        dynamodb = _get_boto_client('dynamodb', region)
        dynamodb.delete_table(TableName=table_name)
        return {
            'success': True, 'table_name': table_name,
            'message': f'Successfully initiated deletion of DynamoDB table {table_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting DynamoDB table: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ELASTICACHE OPERATIONS
# ============================================================================

def list_elasticache_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List ElastiCache clusters (Redis and Memcached).

    Args:
        region: AWS region

    Returns:
        Dictionary with cluster information
    """
    try:
        elasticache = _get_boto_client('elasticache', region)
        response = elasticache.describe_cache_clusters()

        clusters = []
        for cluster in response.get('CacheClusters', []):
            clusters.append({
                'cluster_id': cluster['CacheClusterId'],
                'engine': cluster.get('Engine'),
                'engine_version': cluster.get('EngineVersion'),
                'node_type': cluster.get('CacheNodeType'),
                'num_nodes': cluster.get('NumCacheNodes'),
                'status': cluster.get('CacheClusterStatus'),
                'created_date': cluster.get('CacheClusterCreateTime').isoformat() if cluster.get('CacheClusterCreateTime') else 'N/A'
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ElastiCache clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_elasticache_cluster(
    cluster_id: str,
    engine: str = 'redis',
    node_type: str = 'cache.t3.micro',
    num_nodes: int = 1,
    engine_version: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    subnet_group_name: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an ElastiCache cluster (Redis or Memcached)."""
    try:
        ec = _get_boto_client('elasticache', region)
        params = {
            'CacheClusterId': cluster_id,
            'Engine': engine,
            'CacheNodeType': node_type,
            'NumCacheNodes': num_nodes,
        }
        if engine_version:
            params['EngineVersion'] = engine_version
        if security_group_ids:
            params['SecurityGroupIds'] = security_group_ids
        if subnet_group_name:
            params['CacheSubnetGroupName'] = subnet_group_name
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = ec.create_cache_cluster(**params)
        cluster = response['CacheCluster']
        return {
            'success': True, 'cluster_id': cluster['CacheClusterId'],
            'engine': cluster['Engine'], 'node_type': cluster['CacheNodeType'],
            'status': cluster['CacheClusterStatus'], 'num_nodes': cluster['NumCacheNodes'],
            'message': f'Successfully created ElastiCache {engine} cluster {cluster_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating ElastiCache cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_elasticache_cluster(cluster_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an ElastiCache cluster."""
    try:
        ec = _get_boto_client('elasticache', region)
        ec.delete_cache_cluster(CacheClusterId=cluster_id)
        return {
            'success': True, 'cluster_id': cluster_id,
            'message': f'Successfully initiated deletion of ElastiCache cluster {cluster_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting ElastiCache cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ECS OPERATIONS
# ============================================================================

def list_ecs_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List ECS clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with ECS cluster information
    """
    try:
        ecs = _get_boto_client('ecs', region)
        response = ecs.list_clusters()

        cluster_arns = response.get('clusterArns', [])

        # Get detailed info
        clusters = []
        if cluster_arns:
            describe_response = ecs.describe_clusters(clusters=cluster_arns)
            for cluster in describe_response.get('clusters', []):
                clusters.append({
                    'cluster_name': cluster['clusterName'],
                    'cluster_arn': cluster['clusterArn'],
                    'status': cluster.get('status'),
                    'running_tasks': cluster.get('runningTasksCount', 0),
                    'pending_tasks': cluster.get('pendingTasksCount', 0),
                    'active_services': cluster.get('activeServicesCount', 0),
                    'registered_instances': cluster.get('registeredContainerInstancesCount', 0)
                })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ECS clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_ecs_services(cluster: str, region: Optional[str] = None) -> Dict[str, Any]:
    """
    List ECS services in a cluster.

    Args:
        cluster: ECS cluster name or ARN
        region: AWS region

    Returns:
        Dictionary with ECS service information
    """
    try:
        ecs = _get_boto_client('ecs', region)
        response = ecs.list_services(cluster=cluster)

        service_arns = response.get('serviceArns', [])

        # Get detailed info
        services = []
        if service_arns:
            describe_response = ecs.describe_services(cluster=cluster, services=service_arns)
            for service in describe_response.get('services', []):
                services.append({
                    'service_name': service['serviceName'],
                    'service_arn': service['serviceArn'],
                    'status': service.get('status'),
                    'desired_count': service.get('desiredCount', 0),
                    'running_count': service.get('runningCount', 0),
                    'pending_count': service.get('pendingCount', 0),
                    'launch_type': service.get('launchType', 'N/A'),
                    'task_definition': service.get('taskDefinition', 'N/A')
                })

        return {
            'success': True,
            'cluster': cluster,
            'count': len(services),
            'services': services,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ECS services: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ecs_cluster(
    cluster_name: str,
    capacity_providers: Optional[List[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an ECS cluster."""
    try:
        ecs = _get_boto_client('ecs', region)
        params = {'clusterName': cluster_name}
        if capacity_providers:
            params['capacityProviders'] = capacity_providers
        if tags:
            params['tags'] = [{'key': k, 'value': v} for k, v in tags.items()]

        response = ecs.create_cluster(**params)
        cluster = response['cluster']
        return {
            'success': True, 'cluster_name': cluster['clusterName'],
            'cluster_arn': cluster['clusterArn'], 'status': cluster['status'],
            'registered_container_instances': cluster.get('registeredContainerInstancesCount', 0),
            'message': f'Successfully created ECS cluster {cluster_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating ECS cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def run_ecs_task(
    cluster: str,
    task_definition: str,
    count: int = 1,
    launch_type: str = 'FARGATE',
    subnets: Optional[List[str]] = None,
    security_groups: Optional[List[str]] = None,
    assign_public_ip: bool = True,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Run a task on an ECS cluster."""
    try:
        ecs = _get_boto_client('ecs', region)
        params = {
            'cluster': cluster,
            'taskDefinition': task_definition,
            'count': count,
            'launchType': launch_type,
        }
        if launch_type == 'FARGATE' and subnets:
            network_config = {
                'awsvpcConfiguration': {
                    'subnets': subnets,
                    'assignPublicIp': 'ENABLED' if assign_public_ip else 'DISABLED'
                }
            }
            if security_groups:
                network_config['awsvpcConfiguration']['securityGroups'] = security_groups
            params['networkConfiguration'] = network_config

        response = ecs.run_task(**params)
        tasks = response.get('tasks', [])
        failures = response.get('failures', [])

        task_arns = [t['taskArn'] for t in tasks]
        return {
            'success': True, 'tasks_started': len(tasks), 'task_arns': task_arns,
            'failures': [{'arn': f.get('arn', 'N/A'), 'reason': f.get('reason', 'unknown')} for f in failures],
            'message': f'Successfully started {len(tasks)} task(s) on cluster {cluster}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error running ECS task: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_ecs_service(
    cluster: str,
    service: str,
    desired_count: Optional[int] = None,
    task_definition: Optional[str] = None,
    force_new_deployment: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update an ECS service (desired count, task definition, or force deploy)."""
    try:
        ecs = _get_boto_client('ecs', region)
        params = {'cluster': cluster, 'service': service}
        if desired_count is not None:
            params['desiredCount'] = desired_count
        if task_definition:
            params['taskDefinition'] = task_definition
        if force_new_deployment:
            params['forceNewDeployment'] = True

        response = ecs.update_service(**params)
        svc = response['service']
        return {
            'success': True, 'service_name': svc['serviceName'],
            'status': svc['status'], 'desired_count': svc['desiredCount'],
            'running_count': svc['runningCount'], 'pending_count': svc['pendingCount'],
            'task_definition': svc['taskDefinition'],
            'message': f'Successfully updated ECS service {service}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating ECS service: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ecs_cluster(cluster: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an ECS cluster. All services and tasks must be stopped first."""
    try:
        ecs = _get_boto_client('ecs', region)
        response = ecs.delete_cluster(cluster=cluster)
        cl = response['cluster']
        return {
            'success': True, 'cluster_name': cl['clusterName'],
            'cluster_arn': cl['clusterArn'], 'status': cl['status'],
            'message': f'Successfully deleted ECS cluster {cluster}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting ECS cluster: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ELASTIC BEANSTALK OPERATIONS
# ============================================================================

def list_beanstalk_applications(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Elastic Beanstalk applications.

    Args:
        region: AWS region

    Returns:
        Dictionary with application information
    """
    try:
        beanstalk = _get_boto_client('elasticbeanstalk', region)
        response = beanstalk.describe_applications()

        applications = []
        for app in response.get('Applications', []):
            applications.append({
                'application_name': app['ApplicationName'],
                'description': app.get('Description', 'N/A'),
                'created_date': app.get('DateCreated').isoformat() if app.get('DateCreated') else 'N/A',
                'updated_date': app.get('DateUpdated').isoformat() if app.get('DateUpdated') else 'N/A',
                'versions_count': len(app.get('Versions', []))
            })

        return {
            'success': True,
            'count': len(applications),
            'applications': applications,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Beanstalk applications: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_beanstalk_environments(application_name: Optional[str] = None, region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Elastic Beanstalk environments.

    Args:
        application_name: Filter by application name (optional)
        region: AWS region

    Returns:
        Dictionary with environment information
    """
    try:
        beanstalk = _get_boto_client('elasticbeanstalk', region)

        kwargs = {}
        if application_name:
            kwargs['ApplicationName'] = application_name

        response = beanstalk.describe_environments(**kwargs)

        environments = []
        for env in response.get('Environments', []):
            environments.append({
                'environment_name': env['EnvironmentName'],
                'environment_id': env['EnvironmentId'],
                'application_name': env['ApplicationName'],
                'status': env.get('Status'),
                'health': env.get('Health'),
                'health_status': env.get('HealthStatus'),
                'platform': env.get('PlatformArn', 'N/A'),
                'url': env.get('CNAME', 'N/A'),
                'created_date': env.get('DateCreated').isoformat() if env.get('DateCreated') else 'N/A'
            })

        return {
            'success': True,
            'count': len(environments),
            'environments': environments,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Beanstalk environments: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# CLOUDFRONT OPERATIONS
# ============================================================================

def list_cloudfront_distributions(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List CloudFront distributions.

    Args:
        region: AWS region (CloudFront is global, but region can be specified)

    Returns:
        Dictionary with distribution information
    """
    try:
        cloudfront = _get_boto_client('cloudfront', region)
        response = cloudfront.list_distributions()

        distributions = []
        for dist in response.get('DistributionList', {}).get('Items', []):
            distributions.append({
                'distribution_id': dist['Id'],
                'domain_name': dist['DomainName'],
                'status': dist.get('Status'),
                'enabled': dist.get('Enabled', False),
                'aliases': dist.get('Aliases', {}).get('Items', []),
                'origins_count': dist.get('Origins', {}).get('Quantity', 0),
                'comment': dist.get('Comment', 'N/A'),
                'price_class': dist.get('PriceClass', 'N/A')
            })

        return {
            'success': True,
            'count': len(distributions),
            'distributions': distributions
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CloudFront distributions: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_cloudfront_invalidation(
    distribution_id: str,
    paths: List[str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a CloudFront cache invalidation for specified paths."""
    try:
        cf = _get_boto_client('cloudfront', region)
        import time
        caller_ref = f'inv-{int(time.time())}'
        response = cf.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                'Paths': {'Quantity': len(paths), 'Items': paths},
                'CallerReference': caller_ref
            }
        )
        inv = response['Invalidation']
        return {
            'success': True, 'invalidation_id': inv['Id'],
            'status': inv['Status'], 'paths': paths,
            'message': f'Successfully created invalidation for {len(paths)} path(s)',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating CloudFront invalidation: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ROUTE 53 OPERATIONS
# ============================================================================

def list_route53_zones(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Route 53 hosted zones.

    Args:
        region: AWS region (Route 53 is global, but region can be specified)

    Returns:
        Dictionary with hosted zone information
    """
    try:
        route53 = _get_boto_client('route53', region)
        response = route53.list_hosted_zones()

        zones = []
        for zone in response.get('HostedZones', []):
            zones.append({
                'zone_id': zone['Id'].split('/')[-1],
                'name': zone['Name'],
                'private_zone': zone.get('Config', {}).get('PrivateZone', False),
                'resource_record_set_count': zone.get('ResourceRecordSetCount', 0),
                'comment': zone.get('Config', {}).get('Comment', 'N/A')
            })

        return {
            'success': True,
            'count': len(zones),
            'hosted_zones': zones
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Route 53 hosted zones: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_route53_record(
    hosted_zone_id: str,
    record_name: str,
    record_type: str,
    record_value: str,
    ttl: int = 300,
    action: str = 'UPSERT',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create or update a DNS record in Route 53."""
    try:
        r53 = _get_boto_client('route53', region)
        response = r53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': action,
                    'ResourceRecordSet': {
                        'Name': record_name,
                        'Type': record_type,
                        'TTL': ttl,
                        'ResourceRecords': [{'Value': record_value}]
                    }
                }]
            }
        )
        change_id = response['ChangeInfo']['Id']
        status = response['ChangeInfo']['Status']
        return {
            'success': True, 'change_id': change_id, 'status': status,
            'record_name': record_name, 'record_type': record_type, 'record_value': record_value,
            'message': f'Successfully {action.lower()}d DNS record {record_name} ({record_type})'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating Route53 record: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_route53_record(
    hosted_zone_id: str,
    record_name: str,
    record_type: str,
    record_value: str,
    ttl: int = 300,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a DNS record from Route 53."""
    try:
        r53 = _get_boto_client('route53', region)
        response = r53.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'Name': record_name,
                        'Type': record_type,
                        'TTL': ttl,
                        'ResourceRecords': [{'Value': record_value}]
                    }
                }]
            }
        )
        return {
            'success': True, 'change_id': response['ChangeInfo']['Id'],
            'status': response['ChangeInfo']['Status'],
            'message': f'Successfully deleted DNS record {record_name} ({record_type})'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting Route53 record: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# API GATEWAY OPERATIONS
# ============================================================================

def list_api_gateways(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List API Gateway REST APIs.

    Args:
        region: AWS region

    Returns:
        Dictionary with API information
    """
    try:
        apigateway = _get_boto_client('apigateway', region)
        response = apigateway.get_rest_apis()

        apis = []
        for api in response.get('items', []):
            apis.append({
                'api_id': api['id'],
                'name': api['name'],
                'description': api.get('description', 'N/A'),
                'created_date': api.get('createdDate').isoformat() if api.get('createdDate') else 'N/A',
                'api_key_source': api.get('apiKeySource', 'HEADER'),
                'endpoint_configuration': api.get('endpointConfiguration', {}).get('types', [])
            })

        return {
            'success': True,
            'count': len(apis),
            'apis': apis,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing API Gateways: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_api_gateway_v2(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List API Gateway V2 APIs (HTTP and WebSocket).

    Args:
        region: AWS region

    Returns:
        Dictionary with API information
    """
    try:
        apigatewayv2 = _get_boto_client('apigatewayv2', region)
        response = apigatewayv2.get_apis()

        apis = []
        for api in response.get('Items', []):
            apis.append({
                'api_id': api['ApiId'],
                'name': api['Name'],
                'protocol_type': api.get('ProtocolType', 'N/A'),
                'api_endpoint': api.get('ApiEndpoint', 'N/A'),
                'created_date': api.get('CreatedDate').isoformat() if api.get('CreatedDate') else 'N/A',
                'description': api.get('Description', 'N/A')
            })

        return {
            'success': True,
            'count': len(apis),
            'apis': apis,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing API Gateway V2: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# LAMBDA OPERATIONS
# ============================================================================

def list_lambda_functions(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Lambda functions.

    Args:
        region: AWS region

    Returns:
        Dictionary with Lambda function information
    """
    try:
        lambda_client = _get_boto_client('lambda', region)
        paginator = lambda_client.get_paginator('list_functions')

        functions = []
        for page in paginator.paginate():
            for func in page.get('Functions', []):
                functions.append({
                    'function_name': func['FunctionName'],
                    'function_arn': func['FunctionArn'],
                    'runtime': func.get('Runtime', 'N/A'),
                    'handler': func.get('Handler', 'N/A'),
                    'code_size': func.get('CodeSize', 0),
                    'memory_size': func.get('MemorySize', 128),
                    'timeout': func.get('Timeout', 3),
                    'last_modified': func.get('LastModified', 'N/A'),
                    'state': func.get('State', 'Active'),
                    'package_type': func.get('PackageType', 'Zip'),
                    'description': func.get('Description', 'N/A')
                })

        return {
            'success': True,
            'count': len(functions),
            'functions': functions,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Lambda functions: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# RDS OPERATIONS
# ============================================================================

def list_rds_instances(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List RDS database instances.

    Args:
        region: AWS region

    Returns:
        Dictionary with RDS instance information
    """
    try:
        rds = _get_boto_client('rds', region)
        paginator = rds.get_paginator('describe_db_instances')

        instances = []
        for page in paginator.paginate():
            for db in page.get('DBInstances', []):
                instances.append({
                    'db_instance_identifier': db['DBInstanceIdentifier'],
                    'engine': db.get('Engine'),
                    'engine_version': db.get('EngineVersion'),
                    'db_instance_class': db.get('DBInstanceClass'),
                    'status': db.get('DBInstanceStatus'),
                    'endpoint': db.get('Endpoint', {}).get('Address', 'N/A'),
                    'port': db.get('Endpoint', {}).get('Port', 'N/A'),
                    'allocated_storage': db.get('AllocatedStorage', 0),
                    'storage_type': db.get('StorageType', ''),
                    'multi_az': db.get('MultiAZ', False),
                    'publicly_accessible': db.get('PubliclyAccessible', False),
                    'deletion_protection': db.get('DeletionProtection', False),
                    'vpc_id': db.get('DBSubnetGroup', {}).get('VpcId', 'N/A'),
                    'created_date': db.get('InstanceCreateTime').isoformat() if db.get('InstanceCreateTime') else 'N/A'
                })

        return {
            'success': True,
            'count': len(instances),
            'instances': instances,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing RDS instances: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# RDS EXTENDED OPERATIONS
# ============================================================================

def describe_rds_instance(db_instance_identifier: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Get full details of a specific RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)
        db = response['DBInstances'][0]
        return {
            'success': True,
            'db_instance_identifier': db['DBInstanceIdentifier'],
            'engine': db.get('Engine'),
            'engine_version': db.get('EngineVersion'),
            'db_instance_class': db.get('DBInstanceClass'),
            'status': db.get('DBInstanceStatus'),
            'endpoint': db.get('Endpoint', {}).get('Address'),
            'port': db.get('Endpoint', {}).get('Port'),
            'allocated_storage': db.get('AllocatedStorage'),
            'max_allocated_storage': db.get('MaxAllocatedStorage'),
            'multi_az': db.get('MultiAZ'),
            'availability_zone': db.get('AvailabilityZone'),
            'secondary_az': db.get('SecondaryAvailabilityZone'),
            'publicly_accessible': db.get('PubliclyAccessible'),
            'db_name': db.get('DBName'),
            'master_username': db.get('MasterUsername'),
            'parameter_group': db.get('DBParameterGroups', [{}])[0].get('DBParameterGroupName'),
            'subnet_group': db.get('DBSubnetGroup', {}).get('DBSubnetGroupName'),
            'vpc_id': db.get('DBSubnetGroup', {}).get('VpcId'),
            'security_groups': [sg['VpcSecurityGroupId'] for sg in db.get('VpcSecurityGroups', [])],
            'backup_retention_period': db.get('BackupRetentionPeriod'),
            'preferred_backup_window': db.get('PreferredBackupWindow'),
            'preferred_maintenance_window': db.get('PreferredMaintenanceWindow'),
            'auto_minor_version_upgrade': db.get('AutoMinorVersionUpgrade'),
            'iam_database_authentication_enabled': db.get('IAMDatabaseAuthenticationEnabled'),
            'performance_insights_enabled': db.get('PerformanceInsightsEnabled'),
            'deletion_protection': db.get('DeletionProtection'),
            'created_time': db.get('InstanceCreateTime').isoformat() if db.get('InstanceCreateTime') else None,
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def start_rds_instance(db_instance_identifier: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Start a stopped RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.start_db_instance(DBInstanceIdentifier=db_instance_identifier)
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'RDS instance {db_instance_identifier} starting'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def stop_rds_instance(
    db_instance_identifier: str,
    db_snapshot_identifier: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Stop a running RDS instance to save costs (with optional snapshot)."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {'DBInstanceIdentifier': db_instance_identifier}
        if db_snapshot_identifier:
            kwargs['DBSnapshotIdentifier'] = db_snapshot_identifier
        response = rds.stop_db_instance(**kwargs)
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'RDS instance {db_instance_identifier} stopping'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def reboot_rds_instance(
    db_instance_identifier: str,
    force_failover: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Reboot a DB instance, optionally forcing Multi-AZ failover."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.reboot_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            ForceFailover=force_failover
        )
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'force_failover': force_failover,
            'message': f'RDS instance {db_instance_identifier} rebooting'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def modify_rds_instance(
    db_instance_identifier: str,
    db_instance_class: Optional[str] = None,
    allocated_storage: Optional[int] = None,
    backup_retention_period: Optional[int] = None,
    preferred_backup_window: Optional[str] = None,
    preferred_maintenance_window: Optional[str] = None,
    multi_az: Optional[bool] = None,
    auto_minor_version_upgrade: Optional[bool] = None,
    deletion_protection: Optional[bool] = None,
    engine_version: Optional[str] = None,
    apply_immediately: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Modify RDS instance settings (class, storage, Multi-AZ, engine version, etc.)."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'DBInstanceIdentifier': db_instance_identifier,
            'ApplyImmediately': apply_immediately,
        }
        if db_instance_class:
            kwargs['DBInstanceClass'] = db_instance_class
        if allocated_storage is not None:
            kwargs['AllocatedStorage'] = allocated_storage
        if backup_retention_period is not None:
            kwargs['BackupRetentionPeriod'] = backup_retention_period
        if preferred_backup_window:
            kwargs['PreferredBackupWindow'] = preferred_backup_window
        if preferred_maintenance_window:
            kwargs['PreferredMaintenanceWindow'] = preferred_maintenance_window
        if multi_az is not None:
            kwargs['MultiAZ'] = multi_az
        if auto_minor_version_upgrade is not None:
            kwargs['AutoMinorVersionUpgrade'] = auto_minor_version_upgrade
        if deletion_protection is not None:
            kwargs['DeletionProtection'] = deletion_protection
        if engine_version:
            kwargs['EngineVersion'] = engine_version
        response = rds.modify_db_instance(**kwargs)
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'pending_modified_values': db.get('PendingModifiedValues', {}),
            'apply_immediately': apply_immediately,
            'message': f'RDS instance {db_instance_identifier} modification initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def tag_rds_instance(db_instance_identifier: str, tags: Dict[str, str], region: Optional[str] = None) -> Dict[str, Any]:
    """Add or update tags on an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        # Build the ARN from the instance identifier
        response = rds.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)
        arn = response['DBInstances'][0]['DBInstanceArn']
        rds.add_tags_to_resource(
            ResourceName=arn,
            Tags=[{'Key': k, 'Value': v} for k, v in tags.items()]
        )
        return {
            'success': True, 'db_instance_identifier': db_instance_identifier,
            'tags': tags, 'message': f'Tags applied to RDS instance {db_instance_identifier}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Snapshots ----

def create_rds_snapshot(
    db_instance_identifier: str,
    db_snapshot_identifier: str,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Take a manual point-in-time snapshot of a DB instance."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'DBInstanceIdentifier': db_instance_identifier,
            'DBSnapshotIdentifier': db_snapshot_identifier,
        }
        if tags:
            kwargs['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]
        response = rds.create_db_snapshot(**kwargs)
        snap = response['DBSnapshot']
        return {
            'success': True,
            'snapshot_identifier': snap['DBSnapshotIdentifier'],
            'db_instance_identifier': db_instance_identifier,
            'status': snap.get('Status'),
            'message': f'Snapshot {db_snapshot_identifier} creation initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_rds_snapshots(
    db_instance_identifier: Optional[str] = None,
    snapshot_type: str = 'manual',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List DB snapshots (manual or automated)."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {'SnapshotType': snapshot_type}
        if db_instance_identifier:
            kwargs['DBInstanceIdentifier'] = db_instance_identifier
        response = rds.describe_db_snapshots(**kwargs)
        snapshots = []
        for snap in response.get('DBSnapshots', []):
            snapshots.append({
                'snapshot_identifier': snap['DBSnapshotIdentifier'],
                'db_instance_identifier': snap.get('DBInstanceIdentifier'),
                'engine': snap.get('Engine'),
                'engine_version': snap.get('EngineVersion'),
                'status': snap.get('Status'),
                'allocated_storage': snap.get('AllocatedStorage'),
                'created_time': snap.get('SnapshotCreateTime').isoformat() if snap.get('SnapshotCreateTime') else None,
                'availability_zone': snap.get('AvailabilityZone'),
                'encrypted': snap.get('Encrypted'),
            })
        return {'success': True, 'snapshots': snapshots, 'count': len(snapshots)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_rds_snapshot(db_snapshot_identifier: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a manual RDS snapshot."""
    try:
        rds = _get_boto_client('rds', region)
        rds.delete_db_snapshot(DBSnapshotIdentifier=db_snapshot_identifier)
        return {
            'success': True, 'snapshot_identifier': db_snapshot_identifier,
            'message': f'Snapshot {db_snapshot_identifier} deleted'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def restore_rds_from_snapshot(
    db_snapshot_identifier: str,
    db_instance_identifier: str,
    db_instance_class: Optional[str] = None,
    db_subnet_group_name: Optional[str] = None,
    vpc_security_group_ids: Optional[List[str]] = None,
    publicly_accessible: bool = False,
    multi_az: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Launch a new RDS instance from a snapshot."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'DBSnapshotIdentifier': db_snapshot_identifier,
            'DBInstanceIdentifier': db_instance_identifier,
            'PubliclyAccessible': publicly_accessible,
            'MultiAZ': multi_az,
        }
        if db_instance_class:
            kwargs['DBInstanceClass'] = db_instance_class
        if db_subnet_group_name:
            kwargs['DBSubnetGroupName'] = db_subnet_group_name
        if vpc_security_group_ids:
            kwargs['VpcSecurityGroupIds'] = vpc_security_group_ids
        response = rds.restore_db_instance_from_db_snapshot(**kwargs)
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'engine': db.get('Engine'),
            'message': f'Restoring {db_instance_identifier} from snapshot {db_snapshot_identifier}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def copy_rds_snapshot(
    source_snapshot_identifier: str,
    target_snapshot_identifier: str,
    source_region: Optional[str] = None,
    kms_key_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Copy a DB snapshot within or across regions."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'SourceDBSnapshotIdentifier': source_snapshot_identifier,
            'TargetDBSnapshotIdentifier': target_snapshot_identifier,
        }
        if source_region:
            kwargs['SourceRegion'] = source_region
        if kms_key_id:
            kwargs['KmsKeyId'] = kms_key_id
        response = rds.copy_db_snapshot(**kwargs)
        snap = response['DBSnapshot']
        return {
            'success': True,
            'target_snapshot_identifier': target_snapshot_identifier,
            'status': snap.get('Status'),
            'message': f'Snapshot copy {target_snapshot_identifier} initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def restore_rds_to_point_in_time(
    source_db_instance_identifier: str,
    target_db_instance_identifier: str,
    restore_time: Optional[str] = None,
    use_latest_restorable_time: bool = False,
    db_instance_class: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Restore a DB instance to a specific point in time."""
    try:
        import datetime
        rds = _get_boto_client('rds', region)
        kwargs = {
            'SourceDBInstanceIdentifier': source_db_instance_identifier,
            'TargetDBInstanceIdentifier': target_db_instance_identifier,
            'UseLatestRestorableTime': use_latest_restorable_time,
        }
        if restore_time and not use_latest_restorable_time:
            kwargs['RestoreTime'] = datetime.datetime.fromisoformat(restore_time)
        if db_instance_class:
            kwargs['DBInstanceClass'] = db_instance_class
        response = rds.restore_db_instance_to_point_in_time(**kwargs)
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': target_db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'Point-in-time restore to {target_db_instance_identifier} initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Parameter Groups ----

def create_db_parameter_group(
    group_name: str,
    family: str,
    description: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a DB parameter group for custom engine configuration."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.create_db_parameter_group(
            DBParameterGroupName=group_name,
            DBParameterGroupFamily=family,
            Description=description
        )
        pg = response['DBParameterGroup']
        return {
            'success': True,
            'parameter_group_name': pg['DBParameterGroupName'],
            'family': pg.get('DBParameterGroupFamily'),
            'description': pg.get('Description'),
            'message': f'Parameter group {group_name} created'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_db_parameter_groups(region: Optional[str] = None) -> Dict[str, Any]:
    """List all DB parameter groups in the account."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.describe_db_parameter_groups()
        groups = []
        for pg in response.get('DBParameterGroups', []):
            groups.append({
                'name': pg['DBParameterGroupName'],
                'family': pg.get('DBParameterGroupFamily'),
                'description': pg.get('Description'),
                'arn': pg.get('DBParameterGroupArn'),
            })
        return {'success': True, 'parameter_groups': groups, 'count': len(groups)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def modify_db_parameter_group(
    group_name: str,
    parameters: List[Dict],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update parameter values in a DB parameter group.

    Parameters format: [{"name": "max_connections", "value": "200", "apply_method": "immediate"}]
    """
    try:
        rds = _get_boto_client('rds', region)
        params = [
            {
                'ParameterName': p['name'],
                'ParameterValue': p['value'],
                'ApplyMethod': p.get('apply_method', 'pending-reboot'),
            }
            for p in parameters
        ]
        rds.modify_db_parameter_group(
            DBParameterGroupName=group_name,
            Parameters=params
        )
        return {
            'success': True, 'parameter_group_name': group_name,
            'parameters_modified': len(parameters),
            'message': f'Parameter group {group_name} updated with {len(parameters)} parameter(s)'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_db_parameter_group(group_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a custom DB parameter group."""
    try:
        rds = _get_boto_client('rds', region)
        rds.delete_db_parameter_group(DBParameterGroupName=group_name)
        return {'success': True, 'parameter_group_name': group_name,
                'message': f'Parameter group {group_name} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Subnet Groups ----

def create_db_subnet_group(
    group_name: str,
    description: str,
    subnet_ids: List[str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a DB subnet group for VPC placement."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.create_db_subnet_group(
            DBSubnetGroupName=group_name,
            DBSubnetGroupDescription=description,
            SubnetIds=subnet_ids
        )
        sg = response['DBSubnetGroup']
        return {
            'success': True,
            'subnet_group_name': sg['DBSubnetGroupName'],
            'vpc_id': sg.get('VpcId'),
            'subnet_count': len(sg.get('Subnets', [])),
            'message': f'DB subnet group {group_name} created'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_db_subnet_groups(region: Optional[str] = None) -> Dict[str, Any]:
    """List all DB subnet groups."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.describe_db_subnet_groups()
        groups = []
        for sg in response.get('DBSubnetGroups', []):
            groups.append({
                'name': sg['DBSubnetGroupName'],
                'description': sg.get('DBSubnetGroupDescription'),
                'vpc_id': sg.get('VpcId'),
                'status': sg.get('SubnetGroupStatus'),
                'subnets': [s['SubnetIdentifier'] for s in sg.get('Subnets', [])],
                'availability_zones': list({s['SubnetAvailabilityZone']['Name'] for s in sg.get('Subnets', [])}),
            })
        return {'success': True, 'subnet_groups': groups, 'count': len(groups)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_db_subnet_group(group_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a DB subnet group."""
    try:
        rds = _get_boto_client('rds', region)
        rds.delete_db_subnet_group(DBSubnetGroupName=group_name)
        return {'success': True, 'subnet_group_name': group_name,
                'message': f'DB subnet group {group_name} deleted'}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Security & Auth ----

def rotate_rds_master_password(
    db_instance_identifier: str,
    new_password: str,
    apply_immediately: bool = True,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update the master user password on an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.modify_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            MasterUserPassword=new_password,
            ApplyImmediately=apply_immediately
        )
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'Master password rotation initiated for {db_instance_identifier}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def enable_rds_iam_auth(
    db_instance_identifier: str,
    enable: bool = True,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Enable or disable IAM database authentication on an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.modify_db_instance(
            DBInstanceIdentifier=db_instance_identifier,
            EnableIAMDatabaseAuthentication=enable,
            ApplyImmediately=True
        )
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'iam_auth_enabled': enable,
            'status': db.get('DBInstanceStatus'),
            'message': f'IAM authentication {"enabled" if enable else "disabled"} for {db_instance_identifier}'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Monitoring ----

def list_rds_log_files(db_instance_identifier: str, region: Optional[str] = None) -> Dict[str, Any]:
    """List available log files on an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.describe_db_log_files(DBInstanceIdentifier=db_instance_identifier)
        logs = []
        for log in response.get('DescribeDBLogFiles', []):
            logs.append({
                'log_file_name': log['LogFileName'],
                'last_written': log.get('LastWritten'),
                'size': log.get('Size'),
            })
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'log_files': logs,
            'count': len(logs)
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def download_rds_log_file(
    db_instance_identifier: str,
    log_file_name: str,
    max_lines: int = 500,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Download a specific log file from an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.download_db_log_file_portion(
            DBInstanceIdentifier=db_instance_identifier,
            LogFileName=log_file_name,
            NumberOfLines=max_lines
        )
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'log_file_name': log_file_name,
            'log_content': response.get('LogFileData', ''),
            'additional_data_pending': response.get('AdditionalDataPending', False),
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_rds_events(
    db_instance_identifier: Optional[str] = None,
    duration_minutes: int = 60,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List recent RDS events (failover, backup, maintenance, errors)."""
    try:
        import datetime
        rds = _get_boto_client('rds', region)
        kwargs = {'Duration': duration_minutes}
        if db_instance_identifier:
            kwargs['SourceIdentifier'] = db_instance_identifier
            kwargs['SourceType'] = 'db-instance'
        response = rds.describe_events(**kwargs)
        events = []
        for event in response.get('Events', []):
            events.append({
                'source_identifier': event.get('SourceIdentifier'),
                'source_type': event.get('SourceType'),
                'message': event.get('Message'),
                'event_categories': event.get('EventCategories', []),
                'date': event.get('Date').isoformat() if event.get('Date') else None,
            })
        return {'success': True, 'events': events, 'count': len(events)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Read Replicas ----

def create_rds_read_replica(
    source_db_instance_identifier: str,
    replica_identifier: str,
    db_instance_class: Optional[str] = None,
    availability_zone: Optional[str] = None,
    publicly_accessible: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a read-only replica of an RDS instance."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'SourceDBInstanceIdentifier': source_db_instance_identifier,
            'DBInstanceIdentifier': replica_identifier,
            'PubliclyAccessible': publicly_accessible,
        }
        if db_instance_class:
            kwargs['DBInstanceClass'] = db_instance_class
        if availability_zone:
            kwargs['AvailabilityZone'] = availability_zone
        response = rds.create_db_instance_read_replica(**kwargs)
        db = response['DBInstance']
        return {
            'success': True,
            'replica_identifier': replica_identifier,
            'source_identifier': source_db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'Read replica {replica_identifier} creation initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def promote_rds_read_replica(
    db_instance_identifier: str,
    backup_retention_period: int = 1,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Promote a read replica to a standalone DB instance."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.promote_read_replica(
            DBInstanceIdentifier=db_instance_identifier,
            BackupRetentionPeriod=backup_retention_period
        )
        db = response['DBInstance']
        return {
            'success': True,
            'db_instance_identifier': db_instance_identifier,
            'status': db.get('DBInstanceStatus'),
            'message': f'Read replica {db_instance_identifier} promotion initiated — it will become a standalone instance'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- Aurora Clusters ----

def create_aurora_cluster(
    db_cluster_identifier: str,
    engine: str,
    master_username: str,
    master_password: str,
    db_subnet_group_name: Optional[str] = None,
    vpc_security_group_ids: Optional[List[str]] = None,
    availability_zones: Optional[List[str]] = None,
    backup_retention_period: int = 7,
    database_name: Optional[str] = None,
    engine_version: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Provision an Aurora MySQL or PostgreSQL cluster."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'DBClusterIdentifier': db_cluster_identifier,
            'Engine': engine,
            'MasterUsername': master_username,
            'MasterUserPassword': master_password,
            'BackupRetentionPeriod': backup_retention_period,
            'StorageEncrypted': True,
        }
        if db_subnet_group_name:
            kwargs['DBSubnetGroupName'] = db_subnet_group_name
        if vpc_security_group_ids:
            kwargs['VpcSecurityGroupIds'] = vpc_security_group_ids
        if availability_zones:
            kwargs['AvailabilityZones'] = availability_zones
        if database_name:
            kwargs['DatabaseName'] = database_name
        if engine_version:
            kwargs['EngineVersion'] = engine_version
        response = rds.create_db_cluster(**kwargs)
        cluster = response['DBCluster']
        return {
            'success': True,
            'cluster_identifier': cluster['DBClusterIdentifier'],
            'status': cluster.get('Status'),
            'engine': cluster.get('Engine'),
            'engine_version': cluster.get('EngineVersion'),
            'endpoint': cluster.get('Endpoint'),
            'reader_endpoint': cluster.get('ReaderEndpoint'),
            'message': f'Aurora cluster {db_cluster_identifier} creation initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_aurora_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """List all Aurora DB clusters."""
    try:
        rds = _get_boto_client('rds', region)
        response = rds.describe_db_clusters()
        clusters = []
        for cluster in response.get('DBClusters', []):
            clusters.append({
                'cluster_identifier': cluster['DBClusterIdentifier'],
                'engine': cluster.get('Engine'),
                'engine_version': cluster.get('EngineVersion'),
                'status': cluster.get('Status'),
                'endpoint': cluster.get('Endpoint'),
                'reader_endpoint': cluster.get('ReaderEndpoint'),
                'multi_az': cluster.get('MultiAZ'),
                'database_name': cluster.get('DatabaseName'),
                'member_count': len(cluster.get('DBClusterMembers', [])),
                'backup_retention': cluster.get('BackupRetentionPeriod'),
                'encrypted': cluster.get('StorageEncrypted'),
            })
        return {'success': True, 'clusters': clusters, 'count': len(clusters)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def delete_aurora_cluster(
    db_cluster_identifier: str,
    skip_final_snapshot: bool = False,
    final_snapshot_identifier: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete an Aurora cluster (all instances must be deleted first)."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {
            'DBClusterIdentifier': db_cluster_identifier,
            'SkipFinalSnapshot': skip_final_snapshot,
        }
        if not skip_final_snapshot and final_snapshot_identifier:
            kwargs['FinalDBSnapshotIdentifier'] = final_snapshot_identifier
        response = rds.delete_db_cluster(**kwargs)
        cluster = response['DBCluster']
        return {
            'success': True,
            'cluster_identifier': db_cluster_identifier,
            'status': cluster.get('Status'),
            'message': f'Aurora cluster {db_cluster_identifier} deletion initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def failover_aurora_cluster(
    db_cluster_identifier: str,
    target_db_instance_identifier: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Trigger a failover for an Aurora cluster (promotes a reader to writer)."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {'DBClusterIdentifier': db_cluster_identifier}
        if target_db_instance_identifier:
            kwargs['TargetDBInstanceIdentifier'] = target_db_instance_identifier
        response = rds.failover_db_cluster(**kwargs)
        cluster = response['DBCluster']
        return {
            'success': True,
            'cluster_identifier': db_cluster_identifier,
            'status': cluster.get('Status'),
            'message': f'Aurora cluster {db_cluster_identifier} failover initiated'
        }
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ---- RDS Maintenance ----

def describe_pending_rds_maintenance(
    db_instance_identifier: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """View queued maintenance actions for RDS instances."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {}
        if db_instance_identifier:
            kwargs['Filters'] = [{'Name': 'db-instance-id', 'Values': [db_instance_identifier]}]
        response = rds.describe_pending_maintenance_actions(**kwargs)
        actions = []
        for item in response.get('PendingMaintenanceActions', []):
            for action in item.get('PendingMaintenanceActionDetails', []):
                actions.append({
                    'resource_identifier': item.get('ResourceIdentifier'),
                    'action': action.get('Action'),
                    'auto_applied_after_date': action.get('AutoAppliedAfterDate').isoformat() if action.get('AutoAppliedAfterDate') else None,
                    'current_apply_date': action.get('CurrentApplyDate').isoformat() if action.get('CurrentApplyDate') else None,
                    'description': action.get('Description'),
                })
        return {'success': True, 'pending_actions': actions, 'count': len(actions)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def describe_rds_engine_versions(
    engine: Optional[str] = None,
    engine_version: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List supported RDS engine versions and their features."""
    try:
        rds = _get_boto_client('rds', region)
        kwargs = {}
        if engine:
            kwargs['Engine'] = engine
        if engine_version:
            kwargs['EngineVersion'] = engine_version
        response = rds.describe_db_engine_versions(**kwargs)
        versions = []
        for v in response.get('DBEngineVersions', []):
            versions.append({
                'engine': v.get('Engine'),
                'engine_version': v.get('EngineVersion'),
                'db_engine_description': v.get('DBEngineDescription'),
                'db_engine_version_description': v.get('DBEngineVersionDescription'),
                'default_parameter_group_family': v.get('DBParameterGroupFamily'),
                'status': v.get('Status'),
                'supports_multi_az': v.get('MultiAZCapable', False),
                'supports_read_replica': v.get('ReadReplicaCapable', False),
            })
        return {'success': True, 'engine_versions': versions, 'count': len(versions)}
    except ClientError as e:
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============================================================================
# CLOUDFORMATION OPERATIONS
# ============================================================================

def list_cloudformation_stacks(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List CloudFormation stacks.

    Args:
        region: AWS region

    Returns:
        Dictionary with stack information
    """
    try:
        cfn = _get_boto_client('cloudformation', region)
        response = cfn.list_stacks(
            StackStatusFilter=[
                'CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE',
                'CREATE_IN_PROGRESS', 'UPDATE_IN_PROGRESS', 'DELETE_IN_PROGRESS',
                'ROLLBACK_COMPLETE', 'ROLLBACK_IN_PROGRESS'
            ]
        )

        stacks = []
        for stack in response.get('StackSummaries', []):
            stacks.append({
                'stack_name': stack['StackName'],
                'stack_id': stack['StackId'],
                'status': stack.get('StackStatus'),
                'creation_time': stack.get('CreationTime').isoformat() if stack.get('CreationTime') else 'N/A',
                'last_updated': stack.get('LastUpdatedTime').isoformat() if stack.get('LastUpdatedTime') else 'N/A',
                'template_description': stack.get('TemplateDescription', 'N/A'),
                'drift_status': stack.get('DriftInformation', {}).get('StackDriftStatus', 'NOT_CHECKED')
            })

        return {
            'success': True,
            'count': len(stacks),
            'stacks': stacks,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CloudFormation stacks: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_cloudformation_stack(
    stack_name: str,
    template_body: Optional[str] = None,
    template_url: Optional[str] = None,
    parameters: Optional[List[Dict[str, str]]] = None,
    capabilities: Optional[List[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a CloudFormation stack from a template."""
    try:
        cf = _get_boto_client('cloudformation', region)
        params = {'StackName': stack_name}

        if template_body:
            params['TemplateBody'] = template_body
        elif template_url:
            params['TemplateURL'] = template_url
        else:
            return {'success': False, 'error': 'Must specify either template_body or template_url'}

        if parameters:
            params['Parameters'] = [
                {'ParameterKey': p['key'], 'ParameterValue': p['value']} for p in parameters
            ]
        if capabilities:
            params['Capabilities'] = capabilities
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = cf.create_stack(**params)
        return {
            'success': True, 'stack_id': response['StackId'], 'stack_name': stack_name,
            'message': f'Successfully initiated creation of CloudFormation stack {stack_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating CloudFormation stack: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_cloudformation_stack(
    stack_name: str,
    template_body: Optional[str] = None,
    template_url: Optional[str] = None,
    parameters: Optional[List[Dict[str, str]]] = None,
    capabilities: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update an existing CloudFormation stack."""
    try:
        cf = _get_boto_client('cloudformation', region)
        params = {'StackName': stack_name}

        if template_body:
            params['TemplateBody'] = template_body
        elif template_url:
            params['TemplateURL'] = template_url

        if parameters:
            params['Parameters'] = [
                {'ParameterKey': p['key'], 'ParameterValue': p['value']} for p in parameters
            ]
        if capabilities:
            params['Capabilities'] = capabilities

        response = cf.update_stack(**params)
        return {
            'success': True, 'stack_id': response['StackId'], 'stack_name': stack_name,
            'message': f'Successfully initiated update of CloudFormation stack {stack_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating CloudFormation stack: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_cloudformation_stack(stack_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a CloudFormation stack and all its resources."""
    try:
        cf = _get_boto_client('cloudformation', region)
        cf.delete_stack(StackName=stack_name)
        return {
            'success': True, 'stack_name': stack_name,
            'message': f'Successfully initiated deletion of CloudFormation stack {stack_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting CloudFormation stack: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SYSTEMS MANAGER OPERATIONS
# ============================================================================

def list_ssm_parameters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Systems Manager parameters.

    Args:
        region: AWS region

    Returns:
        Dictionary with parameter information
    """
    try:
        ssm = _get_boto_client('ssm', region)
        response = ssm.describe_parameters(MaxResults=50)

        parameters = []
        for param in response.get('Parameters', []):
            parameters.append({
                'name': param['Name'],
                'type': param.get('Type'),
                'tier': param.get('Tier', 'Standard'),
                'last_modified': param.get('LastModifiedDate').isoformat() if param.get('LastModifiedDate') else 'N/A',
                'version': param.get('Version', 1),
                'description': param.get('Description', 'N/A')
            })

        return {
            'success': True,
            'count': len(parameters),
            'parameters': parameters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SSM parameters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_ssm_managed_instances(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Systems Manager managed instances.

    Args:
        region: AWS region

    Returns:
        Dictionary with managed instance information
    """
    try:
        ssm = _get_boto_client('ssm', region)
        response = ssm.describe_instance_information()

        instances = []
        for instance in response.get('InstanceInformationList', []):
            instances.append({
                'instance_id': instance['InstanceId'],
                'ping_status': instance.get('PingStatus'),
                'platform_type': instance.get('PlatformType'),
                'platform_name': instance.get('PlatformName', 'N/A'),
                'platform_version': instance.get('PlatformVersion', 'N/A'),
                'agent_version': instance.get('AgentVersion', 'N/A'),
                'is_latest_version': instance.get('IsLatestVersion', False),
                'last_ping': instance.get('LastPingDateTime').isoformat() if instance.get('LastPingDateTime') else 'N/A'
            })

        return {
            'success': True,
            'count': len(instances),
            'instances': instances,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SSM managed instances: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def ssm_run_command(
    instance_ids: List[str],
    commands: List[str],
    document_name: str = 'AWS-RunShellScript',
    comment: Optional[str] = None,
    timeout_seconds: int = 600,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Run a command on EC2 instances via SSM."""
    try:
        ssm = _get_boto_client('ssm', region)
        params = {
            'InstanceIds': instance_ids,
            'DocumentName': document_name,
            'Parameters': {'commands': commands},
            'TimeoutSeconds': timeout_seconds,
        }
        if comment:
            params['Comment'] = comment

        response = ssm.send_command(**params)
        cmd = response['Command']
        return {
            'success': True, 'command_id': cmd['CommandId'],
            'status': cmd['Status'], 'instance_ids': instance_ids,
            'document_name': document_name,
            'message': f'Successfully sent command to {len(instance_ids)} instance(s)',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error running SSM command: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def ssm_put_parameter(
    name: str,
    value: str,
    param_type: str = 'String',
    description: Optional[str] = None,
    overwrite: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create or update an SSM parameter."""
    try:
        ssm = _get_boto_client('ssm', region)
        params = {'Name': name, 'Value': value, 'Type': param_type, 'Overwrite': overwrite}
        if description:
            params['Description'] = description

        response = ssm.put_parameter(**params)
        return {
            'success': True, 'name': name, 'type': param_type,
            'version': response.get('Version'),
            'message': f'Successfully {"updated" if overwrite else "created"} SSM parameter {name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error putting SSM parameter: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# CLOUDTRAIL OPERATIONS
# ============================================================================

def list_cloudtrail_trails(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List CloudTrail trails.

    Args:
        region: AWS region

    Returns:
        Dictionary with trail information
    """
    try:
        cloudtrail = _get_boto_client('cloudtrail', region)
        response = cloudtrail.describe_trails()

        trails = []
        for trail in response.get('trailList', []):
            # Get trail status
            try:
                status = cloudtrail.get_trail_status(Name=trail['TrailARN'])
                is_logging = status.get('IsLogging', False)
                latest_delivery = status.get('LatestDeliveryTime')
            except Exception:
                is_logging = False
                latest_delivery = None

            trails.append({
                'name': trail['Name'],
                'trail_arn': trail['TrailARN'],
                's3_bucket': trail.get('S3BucketName', 'N/A'),
                'is_multi_region': trail.get('IsMultiRegionTrail', False),
                'is_organization_trail': trail.get('IsOrganizationTrail', False),
                'is_logging': is_logging,
                'latest_delivery': latest_delivery.isoformat() if latest_delivery else 'N/A',
                'log_file_validation': trail.get('LogFileValidationEnabled', False)
            })

        return {
            'success': True,
            'count': len(trails),
            'trails': trails,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CloudTrail trails: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# AWS CONFIG OPERATIONS
# ============================================================================

def list_config_rules(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List AWS Config rules.

    Args:
        region: AWS region

    Returns:
        Dictionary with config rule information
    """
    try:
        config = _get_boto_client('config', region)
        response = config.describe_config_rules()

        rules = []
        for rule in response.get('ConfigRules', []):
            # Get compliance status
            try:
                compliance = config.describe_compliance_by_config_rule(
                    ConfigRuleNames=[rule['ConfigRuleName']]
                )
                compliance_type = compliance['ComplianceByConfigRules'][0]['Compliance']['ComplianceType']
            except Exception:
                compliance_type = 'UNKNOWN'

            rules.append({
                'rule_name': rule['ConfigRuleName'],
                'rule_arn': rule['ConfigRuleArn'],
                'description': rule.get('Description', 'N/A'),
                'compliance_status': compliance_type,
                'source': rule.get('Source', {}).get('Owner', 'N/A'),
                'rule_state': rule.get('ConfigRuleState', 'N/A')
            })

        return {
            'success': True,
            'count': len(rules),
            'rules': rules,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Config rules: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# AUTO SCALING OPERATIONS
# ============================================================================

def list_autoscaling_groups(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Auto Scaling groups.

    Args:
        region: AWS region

    Returns:
        Dictionary with Auto Scaling group information
    """
    try:
        autoscaling = _get_boto_client('autoscaling', region)
        response = autoscaling.describe_auto_scaling_groups()

        groups = []
        for asg in response.get('AutoScalingGroups', []):
            groups.append({
                'name': asg['AutoScalingGroupName'],
                'arn': asg['AutoScalingGroupARN'],
                'desired_capacity': asg.get('DesiredCapacity', 0),
                'min_size': asg.get('MinSize', 0),
                'max_size': asg.get('MaxSize', 0),
                'current_instances': len(asg.get('Instances', [])),
                'health_check_type': asg.get('HealthCheckType', 'N/A'),
                'health_check_grace_period': asg.get('HealthCheckGracePeriod', 0),
                'availability_zones': asg.get('AvailabilityZones', []),
                'launch_config': asg.get('LaunchConfigurationName', asg.get('LaunchTemplate', {}).get('LaunchTemplateName', 'N/A')),
                'created_time': asg.get('CreatedTime').isoformat() if asg.get('CreatedTime') else 'N/A'
            })

        return {
            'success': True,
            'count': len(groups),
            'groups': groups,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Auto Scaling groups: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_launch_template(
    template_name: str,
    ami_id: str,
    instance_type: str,
    key_name: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    user_data: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EC2 launch template for Auto Scaling."""
    try:
        ec2 = _get_boto_client('ec2', region)
        launch_data = {'ImageId': ami_id, 'InstanceType': instance_type}
        if key_name:
            launch_data['KeyName'] = key_name
        if security_group_ids:
            launch_data['SecurityGroupIds'] = security_group_ids
        if user_data:
            import base64
            launch_data['UserData'] = base64.b64encode(user_data.encode()).decode()

        params = {'LaunchTemplateName': template_name, 'LaunchTemplateData': launch_data}
        if tags:
            params['TagSpecifications'] = [{
                'ResourceType': 'launch-template',
                'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
            }]

        response = ec2.create_launch_template(**params)
        lt = response['LaunchTemplate']
        return {
            'success': True, 'template_name': lt['LaunchTemplateName'],
            'template_id': lt['LaunchTemplateId'], 'version': lt['LatestVersionNumber'],
            'message': f'Successfully created launch template {template_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating launch template: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_auto_scaling_group(
    group_name: str,
    launch_template_id: Optional[str] = None,
    launch_template_name: Optional[str] = None,
    min_size: int = 1,
    max_size: int = 1,
    desired_capacity: int = 1,
    subnet_ids: Optional[List[str]] = None,
    target_group_arns: Optional[List[str]] = None,
    health_check_type: str = 'EC2',
    health_check_grace_period: int = 300,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an Auto Scaling group."""
    try:
        asg = _get_boto_client('autoscaling', region)
        params = {
            'AutoScalingGroupName': group_name,
            'MinSize': min_size,
            'MaxSize': max_size,
            'DesiredCapacity': desired_capacity,
            'HealthCheckType': health_check_type,
            'HealthCheckGracePeriod': health_check_grace_period,
        }

        lt_spec = {}
        if launch_template_id:
            lt_spec['LaunchTemplateId'] = launch_template_id
        elif launch_template_name:
            lt_spec['LaunchTemplateName'] = launch_template_name
        else:
            return {'success': False, 'error': 'Must specify launch_template_id or launch_template_name'}
        lt_spec['Version'] = '$Latest'
        params['LaunchTemplate'] = lt_spec

        if subnet_ids:
            params['VPCZoneIdentifier'] = ','.join(subnet_ids)
        if target_group_arns:
            params['TargetGroupARNs'] = target_group_arns
        if tags:
            params['Tags'] = [
                {'Key': k, 'Value': v, 'ResourceId': group_name,
                 'ResourceType': 'auto-scaling-group', 'PropagateAtLaunch': True}
                for k, v in tags.items()
            ]

        asg.create_auto_scaling_group(**params)
        return {
            'success': True, 'group_name': group_name,
            'min_size': min_size, 'max_size': max_size, 'desired_capacity': desired_capacity,
            'message': f'Successfully created Auto Scaling group {group_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating Auto Scaling group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_auto_scaling_group(
    group_name: str,
    min_size: Optional[int] = None,
    max_size: Optional[int] = None,
    desired_capacity: Optional[int] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update an Auto Scaling group (min/max/desired capacity)."""
    try:
        asg = _get_boto_client('autoscaling', region)
        params = {'AutoScalingGroupName': group_name}
        if min_size is not None:
            params['MinSize'] = min_size
        if max_size is not None:
            params['MaxSize'] = max_size
        if desired_capacity is not None:
            params['DesiredCapacity'] = desired_capacity

        asg.update_auto_scaling_group(**params)
        return {
            'success': True, 'group_name': group_name,
            'min_size': min_size, 'max_size': max_size, 'desired_capacity': desired_capacity,
            'message': f'Successfully updated Auto Scaling group {group_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating Auto Scaling group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_scaling_policy(
    asg_name: str,
    policy_name: str,
    policy_type: str = 'TargetTrackingScaling',
    target_value: float = 50.0,
    predefined_metric: str = 'ASGAverageCPUUtilization',
    adjustment_type: Optional[str] = None,
    scaling_adjustment: Optional[int] = None,
    cooldown: int = 300,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a scaling policy for an Auto Scaling Group.

    Args:
        asg_name: Auto Scaling Group name
        policy_name: Name for the policy
        policy_type: 'TargetTrackingScaling' (recommended), 'SimpleScaling', or 'StepScaling'
        target_value: For TargetTracking — target metric value (e.g. 50.0 for 50% CPU)
        predefined_metric: For TargetTracking — 'ASGAverageCPUUtilization',
                          'ASGAverageNetworkIn', 'ASGAverageNetworkOut',
                          or 'ALBRequestCountPerTarget'
        adjustment_type: For SimpleScaling — 'ChangeInCapacity', 'ExactCapacity', 'PercentChangeInCapacity'
        scaling_adjustment: For SimpleScaling — number of instances to add/remove
        cooldown: Cooldown seconds between scaling actions (SimpleScaling only)
        region: AWS region
    """
    try:
        autoscaling = _get_boto_client('autoscaling', region)
        params: Dict = {
            'AutoScalingGroupName': asg_name,
            'PolicyName': policy_name,
            'PolicyType': policy_type
        }

        if policy_type == 'TargetTrackingScaling':
            params['TargetTrackingConfiguration'] = {
                'PredefinedMetricSpecification': {
                    'PredefinedMetricType': predefined_metric
                },
                'TargetValue': target_value,
                'DisableScaleIn': False
            }
        elif policy_type == 'SimpleScaling':
            params['AdjustmentType'] = adjustment_type or 'ChangeInCapacity'
            params['ScalingAdjustment'] = scaling_adjustment or 1
            params['Cooldown'] = cooldown

        response = autoscaling.put_scaling_policy(**params)
        return {
            'success': True,
            'policy_arn': response.get('PolicyARN', ''),
            'asg_name': asg_name,
            'policy_name': policy_name,
            'policy_type': policy_type,
            'message': f'Scaling policy "{policy_name}" created for {asg_name}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating scaling policy: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_cloudwatch_alarm(
    alarm_name: str,
    metric_name: str,
    namespace: str,
    threshold: float,
    comparison_operator: str,
    evaluation_periods: int = 2,
    period: int = 300,
    statistic: str = 'Average',
    dimensions: Optional[List[Dict[str, str]]] = None,
    alarm_actions: Optional[List[str]] = None,
    ok_actions: Optional[List[str]] = None,
    description: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a CloudWatch alarm on any metric.

    Args:
        alarm_name: Unique alarm name
        metric_name: e.g. 'CPUUtilization', 'NetworkIn', 'StatusCheckFailed'
        namespace: e.g. 'AWS/EC2', 'AWS/RDS', 'AWS/ECS', 'AWS/Lambda'
        threshold: Numeric threshold to trigger alarm
        comparison_operator: 'GreaterThanThreshold', 'LessThanThreshold',
                            'GreaterThanOrEqualToThreshold', 'LessThanOrEqualToThreshold'
        evaluation_periods: Number of periods to evaluate before alarming
        period: Evaluation period in seconds (60, 300, 3600, etc.)
        statistic: 'Average', 'Sum', 'Maximum', 'Minimum', 'SampleCount'
        dimensions: e.g. [{'Name': 'InstanceId', 'Value': 'i-0abc123'}]
        alarm_actions: List of SNS topic ARNs to notify when alarm fires
        ok_actions: List of SNS topic ARNs to notify when alarm clears
        description: Human-readable alarm description
        region: AWS region
    """
    try:
        cloudwatch = _get_boto_client('cloudwatch', region)
        params: Dict = {
            'AlarmName': alarm_name,
            'MetricName': metric_name,
            'Namespace': namespace,
            'Threshold': threshold,
            'ComparisonOperator': comparison_operator,
            'EvaluationPeriods': evaluation_periods,
            'Period': period,
            'Statistic': statistic
        }
        if dimensions:
            params['Dimensions'] = dimensions
        if alarm_actions:
            params['AlarmActions'] = alarm_actions
        if ok_actions:
            params['OKActions'] = ok_actions
        if description:
            params['AlarmDescription'] = description

        cloudwatch.put_metric_alarm(**params)
        effective_region = _get_effective_region(region)
        return {
            'success': True,
            'alarm_name': alarm_name,
            'metric': f'{namespace}/{metric_name}',
            'threshold': threshold,
            'comparison_operator': comparison_operator,
            'region': effective_region,
            'message': f'CloudWatch alarm "{alarm_name}" created in {effective_region} on {namespace}/{metric_name} {comparison_operator} {threshold}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating CloudWatch alarm: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_cloudwatch_alarm(
    alarm_names: List[str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete one or more CloudWatch alarms by name."""
    try:
        cloudwatch = _get_boto_client('cloudwatch', region)
        cloudwatch.delete_alarms(AlarmNames=alarm_names)
        return {
            'success': True,
            'deleted': alarm_names,
            'region': _get_effective_region(region),
            'message': f'Successfully deleted {len(alarm_names)} CloudWatch alarm(s): {", ".join(alarm_names)}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting CloudWatch alarm: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_cloudwatch_alarms(
    state: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """List CloudWatch alarms, optionally filtered by state (OK, ALARM, INSUFFICIENT_DATA)."""
    try:
        cloudwatch = _get_boto_client('cloudwatch', region)
        paginator_kwargs = {}
        if state:
            paginator_kwargs['StateValue'] = state.upper()
        paginator = cloudwatch.get_paginator('describe_alarms')
        alarms = []
        for page in paginator.paginate(**paginator_kwargs):
            for a in page.get('MetricAlarms', []):
                alarms.append({
                    'alarm_name': a['AlarmName'],
                    'alarm_arn': a['AlarmArn'],
                    'state': a.get('StateValue'),
                    'state_reason': a.get('StateReason', ''),
                    'metric': f"{a.get('Namespace')}/{a.get('MetricName')}",
                    'threshold': a.get('Threshold'),
                    'comparison_operator': a.get('ComparisonOperator'),
                    'period_sec': a.get('Period', 60),
                    'evaluation_periods': a.get('EvaluationPeriods', 1),
                    'actions_enabled': a.get('ActionsEnabled', False),
                    'alarm_actions': a.get('AlarmActions', []),
                    'ok_actions': a.get('OKActions', []),
                    'last_updated': str(a.get('StateUpdatedTimestamp', '')),
                })
        counts = {'ALARM': 0, 'OK': 0, 'INSUFFICIENT_DATA': 0}
        for a in alarms:
            counts[a['state']] = counts.get(a['state'], 0) + 1
        return {
            'success': True,
            'count': len(alarms),
            'counts_by_state': counts,
            'alarms': alarms,
            'region': _get_effective_region(region),
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CloudWatch alarms: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def add_tags(
    resource_ids: List[str],
    tags: Dict[str, str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Add or update tags on EC2 resources (instances, volumes, snapshots, AMIs, etc.)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.create_tags(
            Resources=resource_ids,
            Tags=[{'Key': k, 'Value': v} for k, v in tags.items()]
        )
        return {
            'success': True,
            'resource_ids': resource_ids,
            'tags_applied': tags,
            'message': f'Tags applied to {len(resource_ids)} resource(s): {tags}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error adding tags: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def remove_tags(
    resource_ids: List[str],
    tag_keys: List[str],
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Remove specific tags from EC2 resources."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_tags(
            Resources=resource_ids,
            Tags=[{'Key': k} for k in tag_keys]
        )
        return {
            'success': True,
            'resource_ids': resource_ids,
            'tags_removed': tag_keys,
            'message': f'Removed tags {tag_keys} from {len(resource_ids)} resource(s)'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error removing tags: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_resources_by_tag(
    tag_key: str,
    tag_value: Optional[str] = None,
    resource_types: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Find EC2 resources by tag key (and optionally value).

    Args:
        tag_key: Tag key to filter by (e.g. 'Environment', 'Project')
        tag_value: Optional tag value (e.g. 'production'). Omit to match any value.
        resource_types: Optional list of resource types to search:
                       'instance', 'volume', 'snapshot', 'image', 'security-group',
                       'subnet', 'vpc', 'elastic-ip'. Omit to search all.
        region: AWS region
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        filter_value = tag_value if tag_value else '*'
        filters = [{'Name': f'tag:{tag_key}', 'Values': [filter_value]}]

        results: Dict[str, List] = {}
        types_to_check = resource_types or ['instance', 'volume', 'snapshot', 'image']

        if 'instance' in types_to_check:
            resp = ec2.describe_instances(Filters=filters)
            instances = [
                {'id': i['InstanceId'], 'state': i['State']['Name'],
                 'type': i['InstanceType'], 'tags': {t['Key']: t['Value'] for t in i.get('Tags', [])}}
                for r in resp['Reservations'] for i in r['Instances']
            ]
            if instances:
                results['instances'] = instances

        if 'volume' in types_to_check:
            resp = ec2.describe_volumes(Filters=filters)
            volumes = [
                {'id': v['VolumeId'], 'size_gb': v['Size'], 'state': v['State'],
                 'tags': {t['Key']: t['Value'] for t in v.get('Tags', [])}}
                for v in resp['Volumes']
            ]
            if volumes:
                results['volumes'] = volumes

        if 'snapshot' in types_to_check:
            resp = ec2.describe_snapshots(Filters=filters, OwnerIds=['self'])
            snapshots = [
                {'id': s['SnapshotId'], 'size_gb': s['VolumeSize'], 'state': s['State'],
                 'tags': {t['Key']: t['Value'] for t in s.get('Tags', [])}}
                for s in resp['Snapshots']
            ]
            if snapshots:
                results['snapshots'] = snapshots

        total = sum(len(v) for v in results.values())
        return {
            'success': True,
            'tag_filter': {tag_key: tag_value or '*'},
            'total_resources': total,
            'resources': results,
            'message': f'Found {total} resource(s) with tag {tag_key}={tag_value or "*"}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing resources by tag: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# AWS ORGANIZATIONS OPERATIONS
# ============================================================================

def list_organization_accounts() -> Dict[str, Any]:
    """
    List AWS Organization accounts.

    Returns:
        Dictionary with account information
    """
    try:
        orgs = _get_boto_client('organizations')
        response = orgs.list_accounts()

        accounts = []
        for account in response.get('Accounts', []):
            accounts.append({
                'account_id': account['Id'],
                'account_name': account['Name'],
                'email': account['Email'],
                'status': account.get('Status'),
                'joined_method': account.get('JoinedMethod', 'N/A'),
                'joined_timestamp': account.get('JoinedTimestamp').isoformat() if account.get('JoinedTimestamp') else 'N/A'
            })

        return {
            'success': True,
            'count': len(accounts),
            'accounts': accounts
        }

    except ClientError as e:
        if e.response['Error']['Code'] == 'AWSOrganizationsNotInUseException':
            return {
                'success': True,
                'count': 0,
                'accounts': [],
                'message': 'AWS Organizations is not enabled for this account'
            }
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing organization accounts: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SERVICE CATALOG OPERATIONS
# ============================================================================

def list_service_catalog_products(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Service Catalog products.

    Args:
        region: AWS region

    Returns:
        Dictionary with product information
    """
    try:
        sc = _get_boto_client('servicecatalog', region)
        response = sc.search_products_as_admin()

        products = []
        for product in response.get('ProductViewDetails', []):
            view = product.get('ProductViewSummary', {})
            products.append({
                'product_id': view.get('ProductId'),
                'name': view.get('Name'),
                'owner': view.get('Owner', 'N/A'),
                'type': view.get('Type', 'N/A'),
                'distributor': view.get('Distributor', 'N/A'),
                'short_description': view.get('ShortDescription', 'N/A'),
                'support_description': view.get('SupportDescription', 'N/A')
            })

        return {
            'success': True,
            'count': len(products),
            'products': products,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Service Catalog products: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# TRUSTED ADVISOR OPERATIONS
# ============================================================================

def list_trusted_advisor_checks(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Trusted Advisor checks.

    Args:
        region: AWS region (Trusted Advisor is global but region can be specified)

    Returns:
        Dictionary with check information
    """
    try:
        support = _get_boto_client('support', 'us-east-1')  # Trusted Advisor only in us-east-1
        response = support.describe_trusted_advisor_checks(language='en')

        checks = []
        for check in response.get('checks', []):
            # Get check result
            try:
                result = support.describe_trusted_advisor_check_result(checkId=check['id'])
                status = result['result']['status']
                resources_flagged = result['result'].get('flaggedResources', [])
                flagged_count = len(resources_flagged)
            except Exception:
                status = 'unknown'
                flagged_count = 0

            checks.append({
                'check_id': check['id'],
                'name': check['name'],
                'category': check.get('category'),
                'description': check.get('description', 'N/A'),
                'status': status,
                'resources_flagged': flagged_count
            })

        return {
            'success': True,
            'count': len(checks),
            'checks': checks
        }

    except ClientError as e:
        if e.response['Error']['Code'] == 'SubscriptionRequiredException':
            return {
                'success': False,
                'error': 'Trusted Advisor requires AWS Business or Enterprise Support plan',
                'error_code': 'SubscriptionRequired'
            }
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Trusted Advisor checks: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# RESOURCE GROUPS OPERATIONS
# ============================================================================

def list_resource_groups(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Resource Groups.

    Args:
        region: AWS region

    Returns:
        Dictionary with resource group information
    """
    try:
        rg = _get_boto_client('resource-groups', region)
        response = rg.list_groups()

        groups = []
        for group in response.get('GroupIdentifiers', []):
            # Get group details
            try:
                details = rg.get_group(Group=group['GroupArn'])
                group_info = details.get('Group', {})

                # Get resources in group
                resources_response = rg.list_group_resources(Group=group['GroupArn'])
                resource_count = len(resources_response.get('ResourceIdentifiers', []))
            except Exception:
                group_info = {}
                resource_count = 0

            groups.append({
                'group_name': group.get('GroupName'),
                'group_arn': group.get('GroupArn'),
                'description': group_info.get('Description', 'N/A'),
                'resource_count': resource_count
            })

        return {
            'success': True,
            'count': len(groups),
            'groups': groups,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing resource groups: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# CODEARTIFACT OPERATIONS
# ============================================================================

def list_codeartifact_repositories(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List CodeArtifact repositories.

    Args:
        region: AWS region

    Returns:
        Dictionary with repository information
    """
    try:
        codeartifact = _get_boto_client('codeartifact', region)
        response = codeartifact.list_repositories()

        repositories = []
        for repo in response.get('repositories', []):
            repositories.append({
                'name': repo.get('name'),
                'domain_name': repo.get('domainName'),
                'domain_owner': repo.get('domainOwner'),
                'arn': repo.get('arn'),
                'description': repo.get('description', 'N/A'),
                'administrator_account': repo.get('administratorAccount', 'N/A')
            })

        return {
            'success': True,
            'count': len(repositories),
            'repositories': repositories,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CodeArtifact repositories: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# X-RAY OPERATIONS
# ============================================================================

def list_xray_traces(region: Optional[str] = None, hours: int = 1) -> Dict[str, Any]:
    """
    List X-Ray traces.

    Args:
        region: AWS region
        hours: Number of hours to look back

    Returns:
        Dictionary with trace information
    """
    try:
        xray = _get_boto_client('xray', region)

        # Calculate time range
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)

        response = xray.get_trace_summaries(
            StartTime=start_time,
            EndTime=end_time
        )

        traces = []
        for trace in response.get('TraceSummaries', []):
            traces.append({
                'trace_id': trace.get('Id'),
                'duration': trace.get('Duration', 0),
                'response_time': trace.get('ResponseTime', 0),
                'http_status': trace.get('Http', {}).get('HttpStatus'),
                'http_method': trace.get('Http', {}).get('HttpMethod'),
                'http_url': trace.get('Http', {}).get('HttpURL', 'N/A'),
                'has_error': trace.get('HasError', False),
                'has_fault': trace.get('HasFault', False),
                'has_throttle': trace.get('HasThrottle', False)
            })

        return {
            'success': True,
            'count': len(traces),
            'traces': traces,
            'time_range_hours': hours,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing X-Ray traces: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SERVICE QUOTAS OPERATIONS
# ============================================================================

def list_service_quotas(service_code: str, region: Optional[str] = None) -> Dict[str, Any]:
    """
    List service quotas for a specific service.

    Args:
        service_code: AWS service code (e.g., 'ec2', 's3', 'lambda')
        region: AWS region

    Returns:
        Dictionary with quota information
    """
    try:
        sq = _get_boto_client('service-quotas', region)
        response = sq.list_service_quotas(ServiceCode=service_code)

        quotas = []
        for quota in response.get('Quotas', []):
            quotas.append({
                'quota_name': quota.get('QuotaName'),
                'quota_code': quota.get('QuotaCode'),
                'value': quota.get('Value', 0),
                'unit': quota.get('Unit', 'None'),
                'adjustable': quota.get('Adjustable', False),
                'global_quota': quota.get('GlobalQuota', False),
                'usage_metric': quota.get('UsageMetric', {}).get('MetricName', 'N/A')
            })

        return {
            'success': True,
            'service_code': service_code,
            'count': len(quotas),
            'quotas': quotas,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing service quotas: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SNS (SIMPLE NOTIFICATION SERVICE) OPERATIONS
# ============================================================================

def list_sns_topics(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List SNS topics.

    Args:
        region: AWS region

    Returns:
        Dictionary with SNS topic information
    """
    try:
        sns = _get_boto_client('sns', region)
        response = sns.list_topics()

        topics = []
        for topic in response.get('Topics', []):
            topic_arn = topic['TopicArn']

            # Get topic attributes
            try:
                attrs = sns.get_topic_attributes(TopicArn=topic_arn)
                attributes = attrs.get('Attributes', {})

                # Get subscriptions count
                subs = sns.list_subscriptions_by_topic(TopicArn=topic_arn)
                subscription_count = len(subs.get('Subscriptions', []))
            except Exception:
                attributes = {}
                subscription_count = 0

            topics.append({
                'topic_arn': topic_arn,
                'topic_name': topic_arn.split(':')[-1],
                'display_name': attributes.get('DisplayName', 'N/A'),
                'subscription_count': subscription_count,
                'owner': attributes.get('Owner', 'N/A'),
                'subscriptions_confirmed': attributes.get('SubscriptionsConfirmed', '0'),
                'subscriptions_pending': attributes.get('SubscriptionsPending', '0'),
                'subscriptions_deleted': attributes.get('SubscriptionsDeleted', '0')
            })

        return {
            'success': True,
            'count': len(topics),
            'topics': topics,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SNS topics: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_sns_topic(
    topic_name: str,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an SNS topic."""
    try:
        effective_region = _get_effective_region(region)
        sns = _get_boto_client('sns', region)
        params = {'Name': topic_name}
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = sns.create_topic(**params)
        topic_arn = response['TopicArn']
        return {
            'success': True, 'topic_arn': topic_arn, 'topic_name': topic_name,
            'message': f'Successfully created SNS topic {topic_name} in {effective_region}',
            'region': effective_region,
            'console_url': f'https://{effective_region}.console.aws.amazon.com/sns/v3/home?region={effective_region}#/topics'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating SNS topic: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def publish_sns_message(
    topic_arn: str,
    message: str,
    subject: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Publish a message to an SNS topic."""
    try:
        sns = _get_boto_client('sns', region)
        params = {'TopicArn': topic_arn, 'Message': message}
        if subject:
            params['Subject'] = subject

        response = sns.publish(**params)
        return {
            'success': True, 'message_id': response['MessageId'],
            'message': f'Successfully published message to {topic_arn}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error publishing SNS message: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def subscribe_sns_topic(
    topic_arn: str,
    protocol: str,
    endpoint: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Subscribe to an SNS topic (email, SMS, Lambda, SQS, HTTP/S)."""
    try:
        effective_region = _get_effective_region(region)
        sns = _get_boto_client('sns', region)
        response = sns.subscribe(TopicArn=topic_arn, Protocol=protocol, Endpoint=endpoint)
        msg = f'Successfully subscribed {endpoint} ({protocol}) to topic in {effective_region}'
        if protocol == 'email':
            msg += '. A confirmation email has been sent — the subscriber must click the link to activate.'
        return {
            'success': True, 'subscription_arn': response['SubscriptionArn'],
            'protocol': protocol, 'endpoint': endpoint,
            'message': msg,
            'region': effective_region
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error subscribing to SNS topic: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_sns_topic(topic_arn: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an SNS topic and all its subscriptions."""
    try:
        sns = _get_boto_client('sns', region)
        sns.delete_topic(TopicArn=topic_arn)
        return {
            'success': True, 'topic_arn': topic_arn,
            'message': f'Successfully deleted SNS topic',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting SNS topic: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SQS (SIMPLE QUEUE SERVICE) OPERATIONS
# ============================================================================

def list_sqs_queues(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List SQS queues.

    Args:
        region: AWS region

    Returns:
        Dictionary with SQS queue information
    """
    try:
        sqs = _get_boto_client('sqs', region)
        response = sqs.list_queues()

        queue_urls = response.get('QueueUrls', [])
        queues = []

        for queue_url in queue_urls:
            # Get queue attributes
            try:
                attrs = sqs.get_queue_attributes(
                    QueueUrl=queue_url,
                    AttributeNames=['All']
                )
                attributes = attrs.get('Attributes', {})
            except Exception:
                attributes = {}

            queue_name = queue_url.split('/')[-1]

            queues.append({
                'queue_name': queue_name,
                'queue_url': queue_url,
                'queue_arn': attributes.get('QueueArn', 'N/A'),
                'approximate_messages': int(attributes.get('ApproximateNumberOfMessages', 0)),
                'approximate_messages_not_visible': int(attributes.get('ApproximateNumberOfMessagesNotVisible', 0)),
                'approximate_messages_delayed': int(attributes.get('ApproximateNumberOfMessagesDelayed', 0)),
                'created_timestamp': attributes.get('CreatedTimestamp', 'N/A'),
                'last_modified_timestamp': attributes.get('LastModifiedTimestamp', 'N/A'),
                'visibility_timeout': int(attributes.get('VisibilityTimeout', 30)),
                'message_retention_period': int(attributes.get('MessageRetentionPeriod', 345600)),
                'delay_seconds': int(attributes.get('DelaySeconds', 0)),
                'is_fifo': queue_name.endswith('.fifo')
            })

        return {
            'success': True,
            'count': len(queues),
            'queues': queues,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SQS queues: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_sqs_queue(
    queue_name: str,
    fifo: bool = False,
    visibility_timeout: int = 30,
    message_retention_period: int = 345600,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an SQS queue (standard or FIFO)."""
    try:
        sqs = _get_boto_client('sqs', region)
        attributes = {
            'VisibilityTimeout': str(visibility_timeout),
            'MessageRetentionPeriod': str(message_retention_period),
        }
        if fifo:
            attributes['FifoQueue'] = 'true'
            if not queue_name.endswith('.fifo'):
                queue_name += '.fifo'

        params = {'QueueName': queue_name, 'Attributes': attributes}
        if tags:
            params['tags'] = tags

        response = sqs.create_queue(**params)
        return {
            'success': True, 'queue_url': response['QueueUrl'], 'queue_name': queue_name,
            'fifo': fifo,
            'message': f'Successfully created SQS queue {queue_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating SQS queue: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def send_sqs_message(
    queue_url: str,
    message_body: str,
    delay_seconds: int = 0,
    message_group_id: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Send a message to an SQS queue."""
    try:
        sqs = _get_boto_client('sqs', region)
        params = {'QueueUrl': queue_url, 'MessageBody': message_body, 'DelaySeconds': delay_seconds}
        if message_group_id:
            params['MessageGroupId'] = message_group_id

        response = sqs.send_message(**params)
        return {
            'success': True, 'message_id': response['MessageId'],
            'md5': response.get('MD5OfMessageBody'),
            'message': f'Successfully sent message to queue',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error sending SQS message: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_sqs_queue(queue_url: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an SQS queue."""
    try:
        sqs = _get_boto_client('sqs', region)
        sqs.delete_queue(QueueUrl=queue_url)
        return {
            'success': True, 'queue_url': queue_url,
            'message': f'Successfully deleted SQS queue: {queue_url}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting SQS queue: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ECR (ELASTIC CONTAINER REGISTRY) OPERATIONS
# ============================================================================

def list_ecr_repositories(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List ECR repositories.

    Args:
        region: AWS region

    Returns:
        Dictionary with ECR repository information
    """
    try:
        ecr = _get_boto_client('ecr', region)
        response = ecr.describe_repositories()

        repositories = []
        for repo in response.get('repositories', []):
            # Get image count
            try:
                images = ecr.list_images(repositoryName=repo['repositoryName'])
                image_count = len(images.get('imageIds', []))
            except Exception:
                image_count = 0

            repositories.append({
                'repository_name': repo['repositoryName'],
                'repository_arn': repo['repositoryArn'],
                'repository_uri': repo['repositoryUri'],
                'created_at': repo.get('createdAt').isoformat() if repo.get('createdAt') else 'N/A',
                'image_count': image_count,
                'image_tag_mutability': repo.get('imageTagMutability', 'MUTABLE'),
                'encryption_type': repo.get('encryptionConfiguration', {}).get('encryptionType', 'AES256'),
                'scan_on_push': repo.get('imageScanningConfiguration', {}).get('scanOnPush', False)
            })

        return {
            'success': True,
            'count': len(repositories),
            'repositories': repositories,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ECR repositories: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ecr_repository(
    repository_name: str,
    image_tag_mutability: str = 'MUTABLE',
    scan_on_push: bool = True,
    encryption_type: str = 'AES256',
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an ECR repository for Docker images."""
    try:
        ecr = _get_boto_client('ecr', region)
        params = {
            'repositoryName': repository_name,
            'imageTagMutability': image_tag_mutability,
            'imageScanningConfiguration': {'scanOnPush': scan_on_push},
            'encryptionConfiguration': {'encryptionType': encryption_type},
        }
        if tags:
            params['tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = ecr.create_repository(**params)
        repo = response['repository']
        return {
            'success': True, 'repository_name': repo['repositoryName'],
            'repository_uri': repo['repositoryUri'], 'arn': repo['repositoryArn'],
            'registry_id': repo.get('registryId'),
            'message': f'Successfully created ECR repository {repository_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating ECR repository: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ecr_repository(
    repository_name: str,
    force: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete an ECR repository. Use force=True to delete even if it contains images."""
    try:
        ecr = _get_boto_client('ecr', region)
        ecr.delete_repository(repositoryName=repository_name, force=force)
        return {
            'success': True, 'repository_name': repository_name,
            'message': f'Successfully deleted ECR repository {repository_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting ECR repository: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SECRETS MANAGER OPERATIONS
# ============================================================================

def list_secrets_manager_secrets(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Secrets Manager secrets.

    Args:
        region: AWS region

    Returns:
        Dictionary with secrets information
    """
    try:
        sm = _get_boto_client('secretsmanager', region)
        response = sm.list_secrets()

        secrets = []
        for secret in response.get('SecretList', []):
            secrets.append({
                'secret_name': secret['Name'],
                'secret_arn': secret['ARN'],
                'description': secret.get('Description', 'N/A'),
                'created_date': secret.get('CreatedDate').isoformat() if secret.get('CreatedDate') else 'N/A',
                'last_accessed_date': secret.get('LastAccessedDate').isoformat() if secret.get('LastAccessedDate') else 'N/A',
                'last_changed_date': secret.get('LastChangedDate').isoformat() if secret.get('LastChangedDate') else 'N/A',
                'last_rotated_date': secret.get('LastRotatedDate').isoformat() if secret.get('LastRotatedDate') else 'N/A',
                'rotation_enabled': secret.get('RotationEnabled', False),
                'rotation_lambda_arn': secret.get('RotationLambdaARN', 'N/A'),
                'tags': secret.get('Tags', [])
            })

        return {
            'success': True,
            'count': len(secrets),
            'secrets': secrets,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Secrets Manager secrets: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_secret(
    secret_name: str,
    secret_value: str,
    description: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a secret in Secrets Manager."""
    try:
        sm = _get_boto_client('secretsmanager', region)
        params = {'Name': secret_name, 'SecretString': secret_value}
        if description:
            params['Description'] = description
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = sm.create_secret(**params)
        return {
            'success': True, 'secret_name': response['Name'],
            'arn': response['ARN'], 'version_id': response.get('VersionId'),
            'message': f'Successfully created secret {secret_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating secret: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def update_secret(
    secret_name: str,
    secret_value: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Update the value of a secret in Secrets Manager."""
    try:
        sm = _get_boto_client('secretsmanager', region)
        response = sm.update_secret(SecretId=secret_name, SecretString=secret_value)
        return {
            'success': True, 'secret_name': response['Name'],
            'arn': response['ARN'], 'version_id': response.get('VersionId'),
            'message': f'Successfully updated secret {secret_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error updating secret: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_secret(
    secret_name: str,
    force_delete: bool = False,
    recovery_window_days: int = 30,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete a secret from Secrets Manager."""
    try:
        sm = _get_boto_client('secretsmanager', region)
        params = {'SecretId': secret_name}
        if force_delete:
            params['ForceDeleteWithoutRecovery'] = True
        else:
            params['RecoveryWindowInDays'] = recovery_window_days

        response = sm.delete_secret(**params)
        return {
            'success': True, 'secret_name': response['Name'],
            'arn': response['ARN'],
            'deletion_date': response.get('DeletionDate', '').isoformat() if response.get('DeletionDate') else 'N/A',
            'message': f'Successfully scheduled deletion of secret {secret_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting secret: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# LOAD BALANCER OPERATIONS (ALB, NLB, CLB)
# ============================================================================

def list_load_balancers(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List all load balancers (Application, Network, and Classic).

    Args:
        region: AWS region

    Returns:
        Dictionary with load balancer information
    """
    try:
        elbv2 = _get_boto_client('elbv2', region)
        elb = _get_boto_client('elb', region)

        # Get ALB and NLB (ELBv2)
        modern_lbs = []
        try:
            response = elbv2.describe_load_balancers()
            for lb in response.get('LoadBalancers', []):
                # Get target groups
                try:
                    tgs = elbv2.describe_target_groups(LoadBalancerArn=lb['LoadBalancerArn'])
                    target_group_count = len(tgs.get('TargetGroups', []))
                except Exception:
                    target_group_count = 0

                modern_lbs.append({
                    'name': lb['LoadBalancerName'],
                    'arn': lb['LoadBalancerArn'],
                    'dns_name': lb['DNSName'],
                    'type': lb.get('Type', 'application'),  # application, network, or gateway
                    'scheme': lb.get('Scheme', 'internet-facing'),
                    'vpc_id': lb.get('VpcId'),
                    'state': lb.get('State', {}).get('Code', 'unknown'),
                    'availability_zones': [az.get('ZoneName') for az in lb.get('AvailabilityZones', [])],
                    'created_time': lb.get('CreatedTime').isoformat() if lb.get('CreatedTime') else 'N/A',
                    'target_groups': target_group_count,
                    'ip_address_type': lb.get('IpAddressType', 'ipv4')
                })
        except Exception:
            pass

        # Get Classic Load Balancers
        classic_lbs = []
        try:
            response = elb.describe_load_balancers()
            for lb in response.get('LoadBalancerDescriptions', []):
                classic_lbs.append({
                    'name': lb['LoadBalancerName'],
                    'dns_name': lb['DNSName'],
                    'type': 'classic',
                    'scheme': lb.get('Scheme', 'internet-facing'),
                    'vpc_id': lb.get('VPCId', 'EC2-Classic'),
                    'availability_zones': lb.get('AvailabilityZones', []),
                    'instances': len(lb.get('Instances', [])),
                    'created_time': lb.get('CreatedTime').isoformat() if lb.get('CreatedTime') else 'N/A',
                    'health_check_target': lb.get('HealthCheck', {}).get('Target', 'N/A'),
                    'health_check_interval': lb.get('HealthCheck', {}).get('Interval', 30)
                })
        except Exception:
            pass

        all_lbs = modern_lbs + classic_lbs

        return {
            'success': True,
            'count': len(all_lbs),
            'load_balancers': all_lbs,
            'breakdown': {
                'modern': len(modern_lbs),
                'classic': len(classic_lbs)
            },
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing load balancers: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_load_balancer(
    name: str,
    subnets: List[str],
    security_groups: Optional[List[str]] = None,
    scheme: str = 'internet-facing',
    lb_type: str = 'application',
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an Application or Network Load Balancer.

    Args:
        name: Load balancer name
        subnets: List of subnet IDs (minimum 2 for ALB)
        security_groups: List of security group IDs (ALB only)
        scheme: 'internet-facing' or 'internal'
        lb_type: 'application' or 'network'
        tags: Dictionary of tags
        region: AWS region

    Returns:
        Dictionary with created load balancer information
    """
    try:
        elbv2 = _get_boto_client('elbv2', region)

        create_params = {
            'Name': name,
            'Subnets': subnets,
            'Scheme': scheme,
            'Type': lb_type,
        }

        if security_groups and lb_type == 'application':
            create_params['SecurityGroups'] = security_groups

        if tags:
            create_params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = elbv2.create_load_balancer(**create_params)
        lb = response['LoadBalancers'][0]

        return {
            'success': True,
            'name': lb['LoadBalancerName'],
            'arn': lb['LoadBalancerArn'],
            'dns_name': lb['DNSName'],
            'type': lb.get('Type', lb_type),
            'scheme': lb.get('Scheme', scheme),
            'vpc_id': lb.get('VpcId'),
            'state': lb.get('State', {}).get('Code', 'provisioning'),
            'availability_zones': [az.get('ZoneName') for az in lb.get('AvailabilityZones', [])],
            'message': f'Successfully created {lb_type} load balancer {name}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating load balancer: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_target_group(
    name: str,
    protocol: str = 'HTTP',
    port: int = 80,
    vpc_id: Optional[str] = None,
    target_type: str = 'instance',
    health_check_path: Optional[str] = None,
    health_check_interval_seconds: int = 30,
    health_check_protocol: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a target group for a load balancer.

    Args:
        name: Target group name
        protocol: Protocol (HTTP, HTTPS, TCP, TLS, UDP, TCP_UDP)
        port: Port number
        vpc_id: VPC ID (required for instance/ip target types)
        target_type: Target type - 'instance', 'ip', or 'lambda'
        health_check_path: Health check path (e.g., '/' or '/health')
        health_check_interval_seconds: Health check interval (5-300)
        health_check_protocol: Health check protocol (defaults to target protocol)
        tags: Dictionary of tags
        region: AWS region

    Returns:
        Dictionary with created target group information
    """
    try:
        elbv2 = _get_boto_client('elbv2', region)

        create_params = {
            'Name': name,
            'Protocol': protocol,
            'Port': port,
            'TargetType': target_type,
        }

        if vpc_id:
            create_params['VpcId'] = vpc_id

        if health_check_path:
            create_params['HealthCheckPath'] = health_check_path

        if health_check_protocol:
            create_params['HealthCheckProtocol'] = health_check_protocol

        create_params['HealthCheckIntervalSeconds'] = health_check_interval_seconds

        if tags:
            create_params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = elbv2.create_target_group(**create_params)
        tg = response['TargetGroups'][0]

        return {
            'success': True,
            'name': tg['TargetGroupName'],
            'arn': tg['TargetGroupArn'],
            'protocol': tg.get('Protocol'),
            'port': tg.get('Port'),
            'vpc_id': tg.get('VpcId'),
            'target_type': tg.get('TargetType'),
            'health_check': {
                'protocol': tg.get('HealthCheckProtocol'),
                'path': tg.get('HealthCheckPath'),
                'interval': tg.get('HealthCheckIntervalSeconds'),
                'healthy_threshold': tg.get('HealthyThresholdCount'),
                'unhealthy_threshold': tg.get('UnhealthyThresholdCount'),
            },
            'message': f'Successfully created target group {name}',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating target group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_listener(
    load_balancer_arn: str,
    protocol: str = 'HTTP',
    port: int = 80,
    default_target_group_arn: str = '',
    ssl_certificate_arn: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a listener on a load balancer to forward traffic to a target group.

    Args:
        load_balancer_arn: ARN of the load balancer
        protocol: Listener protocol (HTTP, HTTPS, TCP, TLS)
        port: Listener port
        default_target_group_arn: ARN of the default target group to forward to
        ssl_certificate_arn: ACM certificate ARN (required for HTTPS/TLS)
        region: AWS region

    Returns:
        Dictionary with created listener information
    """
    try:
        elbv2 = _get_boto_client('elbv2', region)

        create_params = {
            'LoadBalancerArn': load_balancer_arn,
            'Protocol': protocol,
            'Port': port,
            'DefaultActions': [
                {
                    'Type': 'forward',
                    'TargetGroupArn': default_target_group_arn,
                }
            ]
        }

        if ssl_certificate_arn and protocol in ('HTTPS', 'TLS'):
            create_params['Certificates'] = [{'CertificateArn': ssl_certificate_arn}]

        response = elbv2.create_listener(**create_params)
        listener = response['Listeners'][0]

        return {
            'success': True,
            'listener_arn': listener['ListenerArn'],
            'load_balancer_arn': listener['LoadBalancerArn'],
            'protocol': listener['Protocol'],
            'port': listener['Port'],
            'default_action': {
                'type': listener['DefaultActions'][0]['Type'],
                'target_group_arn': listener['DefaultActions'][0].get('TargetGroupArn', 'N/A'),
            },
            'message': f'Successfully created {protocol}:{port} listener on load balancer',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating listener: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_listener(listener_arn: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a listener from a load balancer."""
    try:
        elbv2 = _get_boto_client('elbv2', region)
        elbv2.delete_listener(ListenerArn=listener_arn)
        return {
            'success': True, 'listener_arn': listener_arn,
            'message': f'Successfully deleted listener: {listener_arn}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting listener: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def register_targets(
    target_group_arn: str,
    targets: List[Dict[str, Any]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Register targets (instances/IPs) with a target group.

    Args:
        target_group_arn: ARN of the target group
        targets: List of targets [{'id': 'i-xxxx', 'port': 80}, ...]. Port is optional.
        region: AWS region

    Returns:
        Dictionary with registration result
    """
    try:
        if not targets:
            return {'success': False, 'error': 'No targets specified'}

        elbv2 = _get_boto_client('elbv2', region)

        target_list = []
        for t in targets:
            entry = {'Id': t['id']}
            if 'port' in t:
                entry['Port'] = t['port']
            target_list.append(entry)

        elbv2.register_targets(
            TargetGroupArn=target_group_arn,
            Targets=target_list
        )

        return {
            'success': True,
            'target_group_arn': target_group_arn,
            'registered_count': len(target_list),
            'targets': [{'id': t['Id'], 'port': t.get('Port', 'default')} for t in target_list],
            'message': f'Successfully registered {len(target_list)} target(s) with target group',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error registering targets: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def describe_target_health(
    target_group_arn: str,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Describe the health of targets in a target group.

    Args:
        target_group_arn: ARN of the target group
        region: AWS region

    Returns:
        Dictionary with target health information
    """
    try:
        elbv2 = _get_boto_client('elbv2', region)

        response = elbv2.describe_target_health(TargetGroupArn=target_group_arn)

        targets = []
        for desc in response.get('TargetHealthDescriptions', []):
            target = desc.get('Target', {})
            health = desc.get('TargetHealth', {})
            targets.append({
                'id': target.get('Id'),
                'port': target.get('Port'),
                'health_check_port': desc.get('HealthCheckPort'),
                'state': health.get('State', 'unknown'),
                'reason': health.get('Reason', ''),
                'description': health.get('Description', ''),
            })

        healthy = sum(1 for t in targets if t['state'] == 'healthy')
        unhealthy = sum(1 for t in targets if t['state'] == 'unhealthy')

        return {
            'success': True,
            'target_group_arn': target_group_arn,
            'total_targets': len(targets),
            'healthy': healthy,
            'unhealthy': unhealthy,
            'targets': targets,
            'message': f'{len(targets)} target(s): {healthy} healthy, {unhealthy} unhealthy',
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error describing target health: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_load_balancer(load_balancer_arn: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a load balancer."""
    try:
        elbv2 = _get_boto_client('elbv2', region)
        elbv2.delete_load_balancer(LoadBalancerArn=load_balancer_arn)
        return {
            'success': True, 'load_balancer_arn': load_balancer_arn,
            'message': f'Successfully deleted load balancer',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting load balancer: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_target_group(target_group_arn: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a target group."""
    try:
        elbv2 = _get_boto_client('elbv2', region)
        elbv2.delete_target_group(TargetGroupArn=target_group_arn)
        return {
            'success': True, 'target_group_arn': target_group_arn,
            'message': f'Successfully deleted target group',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting target group: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def deregister_targets(
    target_group_arn: str,
    targets: List[Dict[str, Any]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Deregister targets from a target group."""
    try:
        if not targets:
            return {'success': False, 'error': 'No targets specified'}

        elbv2 = _get_boto_client('elbv2', region)
        target_list = []
        for t in targets:
            entry = {'Id': t['id']}
            if 'port' in t:
                entry['Port'] = t['port']
            target_list.append(entry)

        elbv2.deregister_targets(TargetGroupArn=target_group_arn, Targets=target_list)
        return {
            'success': True, 'target_group_arn': target_group_arn,
            'deregistered_count': len(target_list),
            'message': f'Successfully deregistered {len(target_list)} target(s)',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deregistering targets: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# EFS (ELASTIC FILE SYSTEM) OPERATIONS
# ============================================================================

def list_efs_file_systems(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List EFS file systems.

    Args:
        region: AWS region

    Returns:
        Dictionary with EFS file system information
    """
    try:
        efs = _get_boto_client('efs', region)
        response = efs.describe_file_systems()

        file_systems = []
        for fs in response.get('FileSystems', []):
            # Get mount targets
            try:
                mts = efs.describe_mount_targets(FileSystemId=fs['FileSystemId'])
                mount_target_count = len(mts.get('MountTargets', []))
            except Exception:
                mount_target_count = 0

            file_systems.append({
                'file_system_id': fs['FileSystemId'],
                'file_system_arn': fs.get('FileSystemArn', 'N/A'),
                'name': fs.get('Name', 'N/A'),
                'creation_token': fs.get('CreationToken'),
                'creation_time': fs.get('CreationTime').isoformat() if fs.get('CreationTime') else 'N/A',
                'life_cycle_state': fs.get('LifeCycleState'),
                'number_of_mount_targets': fs.get('NumberOfMountTargets', mount_target_count),
                'size_in_bytes': fs.get('SizeInBytes', {}).get('Value', 0),
                'performance_mode': fs.get('PerformanceMode', 'generalPurpose'),
                'throughput_mode': fs.get('ThroughputMode', 'bursting'),
                'encrypted': fs.get('Encrypted', False),
                'kms_key_id': fs.get('KmsKeyId', 'N/A'),
                'tags': fs.get('Tags', [])
            })

        return {
            'success': True,
            'count': len(file_systems),
            'file_systems': file_systems,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EFS file systems: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_efs_file_system(
    creation_token: Optional[str] = None,
    performance_mode: str = 'generalPurpose',
    throughput_mode: str = 'bursting',
    encrypted: bool = True,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EFS file system."""
    try:
        efs = _get_boto_client('efs', region)
        import time
        params = {
            'CreationToken': creation_token or f'efs-{int(time.time())}',
            'PerformanceMode': performance_mode,
            'ThroughputMode': throughput_mode,
            'Encrypted': encrypted,
        }
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = efs.create_file_system(**params)
        return {
            'success': True, 'file_system_id': response['FileSystemId'],
            'lifecycle_state': response['LifeCycleState'],
            'performance_mode': response['PerformanceMode'],
            'encrypted': response['Encrypted'],
            'message': f'Successfully created EFS file system {response["FileSystemId"]}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EFS file system: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_efs_file_system(file_system_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an EFS file system. All mount targets must be deleted first."""
    try:
        efs = _get_boto_client('efs', region)
        efs.delete_file_system(FileSystemId=file_system_id)
        return {
            'success': True, 'file_system_id': file_system_id,
            'message': f'Successfully deleted EFS file system {file_system_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting EFS file system: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# EVENTBRIDGE OPERATIONS
# ============================================================================

def list_eventbridge_rules(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List EventBridge rules.

    Args:
        region: AWS region

    Returns:
        Dictionary with EventBridge rule information
    """
    try:
        events = _get_boto_client('events', region)
        response = events.list_rules()

        rules = []
        for rule in response.get('Rules', []):
            # Get targets for this rule
            try:
                targets = events.list_targets_by_rule(Rule=rule['Name'])
                target_count = len(targets.get('Targets', []))
            except Exception:
                target_count = 0

            rules.append({
                'name': rule['Name'],
                'arn': rule['Arn'],
                'state': rule.get('State', 'ENABLED'),
                'description': rule.get('Description', 'N/A'),
                'schedule_expression': rule.get('ScheduleExpression', 'N/A'),
                'event_pattern': rule.get('EventPattern', 'N/A'),
                'event_bus_name': rule.get('EventBusName', 'default'),
                'target_count': target_count,
                'managed_by': rule.get('ManagedBy', 'user'),
                'created_by': rule.get('CreatedBy', 'N/A')
            })

        return {
            'success': True,
            'count': len(rules),
            'rules': rules,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EventBridge rules: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_eventbridge_event_buses(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List EventBridge event buses.

    Args:
        region: AWS region

    Returns:
        Dictionary with event bus information
    """
    try:
        events = _get_boto_client('events', region)
        response = events.list_event_buses()

        event_buses = []
        for bus in response.get('EventBuses', []):
            # Count rules for this event bus
            try:
                rules = events.list_rules(EventBusName=bus['Name'])
                rule_count = len(rules.get('Rules', []))
            except Exception:
                rule_count = 0

            event_buses.append({
                'name': bus['Name'],
                'arn': bus['Arn'],
                'policy': bus.get('Policy', 'N/A'),
                'rule_count': rule_count,
                'created_by': bus.get('CreatedBy', 'N/A')
            })

        return {
            'success': True,
            'count': len(event_buses),
            'event_buses': event_buses,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EventBridge event buses: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_eventbridge_rule(
    rule_name: str,
    schedule_expression: Optional[str] = None,
    event_pattern: Optional[str] = None,
    state: str = 'ENABLED',
    description: Optional[str] = None,
    event_bus_name: Optional[str] = None,
    targets: Optional[List[Dict[str, str]]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EventBridge rule (schedule or event pattern based)."""
    try:
        eb = _get_boto_client('events', region)
        params = {'Name': rule_name, 'State': state}
        if schedule_expression:
            params['ScheduleExpression'] = schedule_expression
        elif event_pattern:
            params['EventPattern'] = event_pattern
        else:
            return {'success': False, 'error': 'Must specify schedule_expression or event_pattern'}
        if description:
            params['Description'] = description
        if event_bus_name:
            params['EventBusName'] = event_bus_name

        response = eb.put_rule(**params)
        rule_arn = response['RuleArn']

        targets_added = 0
        if targets:
            target_list = [{'Id': t['id'], 'Arn': t['arn']} for t in targets]
            eb.put_targets(Rule=rule_name, Targets=target_list)
            targets_added = len(target_list)

        return {
            'success': True, 'rule_name': rule_name, 'rule_arn': rule_arn,
            'targets_added': targets_added,
            'message': f'Successfully created EventBridge rule {rule_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EventBridge rule: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_eventbridge_rule(
    rule_name: str,
    event_bus_name: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Delete an EventBridge rule. Targets are removed automatically."""
    try:
        eb = _get_boto_client('events', region)
        params = {'Rule': rule_name}
        if event_bus_name:
            params['EventBusName'] = event_bus_name

        # Remove targets first
        try:
            targets_response = eb.list_targets_by_rule(**params)
            target_ids = [t['Id'] for t in targets_response.get('Targets', [])]
            if target_ids:
                remove_params = {'Rule': rule_name, 'Ids': target_ids}
                if event_bus_name:
                    remove_params['EventBusName'] = event_bus_name
                eb.remove_targets(**remove_params)
        except Exception:
            pass

        delete_params = {'Name': rule_name}
        if event_bus_name:
            delete_params['EventBusName'] = event_bus_name
        eb.delete_rule(**delete_params)

        return {
            'success': True, 'rule_name': rule_name,
            'message': f'Successfully deleted EventBridge rule {rule_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting EventBridge rule: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# STEP FUNCTIONS OPERATIONS
# ============================================================================

def list_step_functions(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Step Functions state machines.

    Args:
        region: AWS region

    Returns:
        Dictionary with state machine information
    """
    try:
        sfn = _get_boto_client('stepfunctions', region)
        response = sfn.list_state_machines()

        state_machines = []
        for sm in response.get('stateMachines', []):
            # Get execution stats
            try:
                executions = sfn.list_executions(
                    stateMachineArn=sm['stateMachineArn'],
                    maxResults=10
                )
                execution_count = len(executions.get('executions', []))
            except Exception:
                execution_count = 0

            state_machines.append({
                'name': sm['name'],
                'arn': sm['stateMachineArn'],
                'type': sm.get('type', 'STANDARD'),
                'status': sm.get('status', 'ACTIVE'),
                'creation_date': sm.get('creationDate').isoformat() if sm.get('creationDate') else 'N/A',
                'recent_executions': execution_count
            })

        return {
            'success': True,
            'count': len(state_machines),
            'state_machines': state_machines,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Step Functions: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def start_step_function_execution(
    state_machine_arn: str,
    execution_name: Optional[str] = None,
    input_data: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Start an execution of a Step Functions state machine."""
    try:
        sfn = _get_boto_client('stepfunctions', region)
        params = {'stateMachineArn': state_machine_arn}
        if execution_name:
            params['name'] = execution_name
        if input_data:
            params['input'] = input_data

        response = sfn.start_execution(**params)
        return {
            'success': True, 'execution_arn': response['executionArn'],
            'start_date': response['startDate'].isoformat(),
            'message': f'Successfully started Step Functions execution',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error starting Step Functions execution: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# KINESIS OPERATIONS
# ============================================================================

def list_kinesis_streams(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Kinesis data streams.

    Args:
        region: AWS region

    Returns:
        Dictionary with Kinesis stream information
    """
    try:
        kinesis = _get_boto_client('kinesis', region)
        response = kinesis.list_streams()

        streams = []
        for stream_name in response.get('StreamNames', []):
            # Get stream details
            try:
                details = kinesis.describe_stream(StreamName=stream_name)
                stream_desc = details.get('StreamDescription', {})

                streams.append({
                    'stream_name': stream_name,
                    'stream_arn': stream_desc.get('StreamARN'),
                    'status': stream_desc.get('StreamStatus'),
                    'shard_count': len(stream_desc.get('Shards', [])),
                    'retention_period_hours': stream_desc.get('RetentionPeriodHours', 24),
                    'encryption_type': stream_desc.get('EncryptionType', 'NONE'),
                    'creation_timestamp': stream_desc.get('StreamCreationTimestamp').isoformat() if stream_desc.get('StreamCreationTimestamp') else 'N/A',
                    'enhanced_monitoring': stream_desc.get('EnhancedMonitoring', [])
                })
            except Exception:
                streams.append({
                    'stream_name': stream_name,
                    'stream_arn': 'N/A',
                    'status': 'UNKNOWN',
                    'shard_count': 0
                })

        return {
            'success': True,
            'count': len(streams),
            'streams': streams,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Kinesis streams: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_kinesis_stream(
    stream_name: str,
    shard_count: int = 1,
    stream_mode: str = 'PROVISIONED',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a Kinesis data stream."""
    try:
        kinesis = _get_boto_client('kinesis', region)
        params = {'StreamName': stream_name}
        if stream_mode == 'ON_DEMAND':
            params['StreamModeDetails'] = {'StreamMode': 'ON_DEMAND'}
        else:
            params['ShardCount'] = shard_count

        kinesis.create_stream(**params)
        return {
            'success': True, 'stream_name': stream_name,
            'shard_count': shard_count, 'stream_mode': stream_mode,
            'message': f'Successfully created Kinesis stream {stream_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating Kinesis stream: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_kinesis_stream(stream_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a Kinesis data stream."""
    try:
        kinesis = _get_boto_client('kinesis', region)
        kinesis.delete_stream(StreamName=stream_name, EnforceConsumerDeletion=True)
        return {
            'success': True, 'stream_name': stream_name,
            'message': f'Successfully initiated deletion of Kinesis stream {stream_name}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting Kinesis stream: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ACM (CERTIFICATE MANAGER) OPERATIONS
# ============================================================================

def list_acm_certificates(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List ACM SSL/TLS certificates.

    Args:
        region: AWS region

    Returns:
        Dictionary with certificate information
    """
    try:
        acm = _get_boto_client('acm', region)
        response = acm.list_certificates()

        certificates = []
        for cert in response.get('CertificateSummaryList', []):
            # Get detailed certificate info
            try:
                details = acm.describe_certificate(CertificateArn=cert['CertificateArn'])
                cert_details = details.get('Certificate', {})

                certificates.append({
                    'domain_name': cert.get('DomainName'),
                    'certificate_arn': cert.get('CertificateArn'),
                    'status': cert_details.get('Status', 'N/A'),
                    'type': cert_details.get('Type', 'N/A'),
                    'in_use': len(cert_details.get('InUseBy', [])) > 0,
                    'subject_alternative_names': cert_details.get('SubjectAlternativeNames', []),
                    'issuer': cert_details.get('Issuer', 'N/A'),
                    'created_at': cert_details.get('CreatedAt').isoformat() if cert_details.get('CreatedAt') else 'N/A',
                    'not_before': cert_details.get('NotBefore').isoformat() if cert_details.get('NotBefore') else 'N/A',
                    'not_after': cert_details.get('NotAfter').isoformat() if cert_details.get('NotAfter') else 'N/A',
                    'renewal_eligibility': cert_details.get('RenewalEligibility', 'N/A')
                })
            except Exception:
                certificates.append({
                    'domain_name': cert.get('DomainName'),
                    'certificate_arn': cert.get('CertificateArn'),
                    'status': 'UNKNOWN'
                })

        return {
            'success': True,
            'count': len(certificates),
            'certificates': certificates,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ACM certificates: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def request_acm_certificate(
    domain_name: str,
    validation_method: str = 'DNS',
    subject_alternative_names: Optional[List[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Request an SSL/TLS certificate from AWS Certificate Manager."""
    try:
        acm = _get_boto_client('acm', region)
        params = {'DomainName': domain_name, 'ValidationMethod': validation_method}
        if subject_alternative_names:
            params['SubjectAlternativeNames'] = subject_alternative_names
        if tags:
            params['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]

        response = acm.request_certificate(**params)
        return {
            'success': True, 'certificate_arn': response['CertificateArn'],
            'domain_name': domain_name, 'validation_method': validation_method,
            'message': f'Successfully requested certificate for {domain_name}. Complete {validation_method} validation to activate.',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error requesting ACM certificate: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# WAF (WEB APPLICATION FIREWALL) OPERATIONS
# ============================================================================

def list_waf_web_acls(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List WAF Web ACLs.

    Args:
        region: AWS region

    Returns:
        Dictionary with WAF Web ACL information
    """
    try:
        wafv2 = _get_boto_client('wafv2', region)

        # List regional Web ACLs
        web_acls = []
        try:
            response = wafv2.list_web_acls(Scope='REGIONAL')
            for acl in response.get('WebACLs', []):
                web_acls.append({
                    'name': acl['Name'],
                    'id': acl['Id'],
                    'arn': acl['ARN'],
                    'scope': 'REGIONAL',
                    'description': acl.get('Description', 'N/A'),
                    'lock_token': acl.get('LockToken', 'N/A')
                })
        except Exception:
            pass

        # List CloudFront (global) Web ACLs
        try:
            response = wafv2.list_web_acls(Scope='CLOUDFRONT')
            for acl in response.get('WebACLs', []):
                web_acls.append({
                    'name': acl['Name'],
                    'id': acl['Id'],
                    'arn': acl['ARN'],
                    'scope': 'CLOUDFRONT',
                    'description': acl.get('Description', 'N/A'),
                    'lock_token': acl.get('LockToken', 'N/A')
                })
        except Exception:
            pass

        return {
            'success': True,
            'count': len(web_acls),
            'web_acls': web_acls,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing WAF Web ACLs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# BACKUP OPERATIONS
# ============================================================================

def list_backup_plans(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List AWS Backup plans.

    Args:
        region: AWS region

    Returns:
        Dictionary with backup plan information
    """
    try:
        backup = _get_boto_client('backup', region)
        response = backup.list_backup_plans()

        plans = []
        for plan in response.get('BackupPlansList', []):
            # Get plan details
            try:
                details = backup.get_backup_plan(BackupPlanId=plan['BackupPlanId'])
                plan_details = details.get('BackupPlan', {})

                plans.append({
                    'backup_plan_id': plan['BackupPlanId'],
                    'backup_plan_arn': plan['BackupPlanArn'],
                    'backup_plan_name': plan['BackupPlanName'],
                    'version_id': plan.get('VersionId'),
                    'creation_date': plan.get('CreationDate').isoformat() if plan.get('CreationDate') else 'N/A',
                    'last_execution_date': plan.get('LastExecutionDate').isoformat() if plan.get('LastExecutionDate') else 'N/A',
                    'rule_count': len(plan_details.get('Rules', [])),
                    'advanced_backup_settings': plan_details.get('AdvancedBackupSettings', [])
                })
            except Exception:
                plans.append({
                    'backup_plan_id': plan['BackupPlanId'],
                    'backup_plan_name': plan['BackupPlanName'],
                    'backup_plan_arn': plan['BackupPlanArn']
                })

        return {
            'success': True,
            'count': len(plans),
            'backup_plans': plans,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Backup plans: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# EBS VOLUME OPERATIONS
# ============================================================================

def list_ebs_volumes(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List EBS volumes.

    Args:
        region: AWS region

    Returns:
        Dictionary with EBS volume information
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_volumes()

        volumes = []
        for vol in response.get('Volumes', []):
            # Get attachments info
            attachments = vol.get('Attachments', [])
            attached_to = attachments[0].get('InstanceId') if attachments else None
            device = attachments[0].get('Device') if attachments else None

            volumes.append({
                'volume_id': vol['VolumeId'],
                'size': vol.get('Size', 0),
                'volume_type': vol.get('VolumeType', 'gp2'),
                'state': vol.get('State'),
                'iops': vol.get('Iops', 0),
                'throughput': vol.get('Throughput', 0),
                'encrypted': vol.get('Encrypted', False),
                'kms_key_id': vol.get('KmsKeyId', 'N/A'),
                'availability_zone': vol.get('AvailabilityZone'),
                'attached_to': attached_to or 'Not attached',
                'device': device or 'N/A',
                'created_time': vol.get('CreateTime').isoformat() if vol.get('CreateTime') else 'N/A',
                'snapshot_id': vol.get('SnapshotId', 'N/A'),
                'multi_attach_enabled': vol.get('MultiAttachEnabled', False),
                'tags': {tag['Key']: tag['Value'] for tag in vol.get('Tags', [])}
            })

        return {
            'success': True,
            'count': len(volumes),
            'volumes': volumes,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EBS volumes: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ebs_volume(
    availability_zone: str,
    size: int = 20,
    volume_type: str = 'gp3',
    encrypted: bool = True,
    iops: Optional[int] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an EBS volume."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params = {
            'AvailabilityZone': availability_zone,
            'Size': size,
            'VolumeType': volume_type,
            'Encrypted': encrypted,
        }
        if iops and volume_type in ('io1', 'io2', 'gp3'):
            params['Iops'] = iops
        if tags:
            params['TagSpecifications'] = [{
                'ResourceType': 'volume',
                'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
            }]

        response = ec2.create_volume(**params)
        return {
            'success': True, 'volume_id': response['VolumeId'],
            'size': response['Size'], 'volume_type': response['VolumeType'],
            'availability_zone': response['AvailabilityZone'],
            'encrypted': response['Encrypted'], 'state': response['State'],
            'message': f'Successfully created EBS volume {response["VolumeId"]} ({size} GB)',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def attach_ebs_volume(
    volume_id: str,
    instance_id: str,
    device: str = '/dev/sdf',
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Attach an EBS volume to an EC2 instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.attach_volume(VolumeId=volume_id, InstanceId=instance_id, Device=device)
        return {
            'success': True, 'volume_id': response['VolumeId'],
            'instance_id': response['InstanceId'], 'device': response['Device'],
            'state': response['State'],
            'message': f'Successfully attached {volume_id} to {instance_id} as {device}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error attaching EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def detach_ebs_volume(
    volume_id: str,
    instance_id: Optional[str] = None,
    force: bool = False,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Detach an EBS volume from an EC2 instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params = {'VolumeId': volume_id, 'Force': force}
        if instance_id:
            params['InstanceId'] = instance_id

        response = ec2.detach_volume(**params)
        return {
            'success': True, 'volume_id': response['VolumeId'],
            'instance_id': response.get('InstanceId'),
            'device': response.get('Device'),
            'state': response['State'],
            'message': f'Successfully detaching {volume_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error detaching EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ebs_snapshot(
    volume_id: str,
    description: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a snapshot of an EBS volume."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params = {'VolumeId': volume_id}
        if description:
            params['Description'] = description
        if tags:
            params['TagSpecifications'] = [{
                'ResourceType': 'snapshot',
                'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
            }]

        response = ec2.create_snapshot(**params)
        return {
            'success': True, 'snapshot_id': response['SnapshotId'],
            'volume_id': response['VolumeId'], 'state': response['State'],
            'volume_size': response.get('VolumeSize'),
            'message': f'Successfully created snapshot {response["SnapshotId"]} of {volume_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating EBS snapshot: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ebs_snapshot(snapshot_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an EBS snapshot."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_snapshot(SnapshotId=snapshot_id)
        return {
            'success': True,
            'snapshot_id': snapshot_id,
            'message': f'Snapshot {snapshot_id} deleted successfully'
        }
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidSnapshot.InUse':
            # Snapshot is still backing a registered AMI — find which one(s)
            try:
                images = ec2.describe_images(Filters=[
                    {'Name': 'block-device-mapping.snapshot-id', 'Values': [snapshot_id]}
                ]).get('Images', [])
                ami_ids = [img['ImageId'] for img in images]
            except Exception:
                ami_ids = []
            ami_hint = f' AMI(s) still using it: {ami_ids}.' if ami_ids else ''
            return {
                'success': False,
                'error': (
                    f'Snapshot {snapshot_id} cannot be deleted because it is still associated with a registered AMI.{ami_hint} '
                    f'Call deregister_ami with delete_snapshots=True (e.g. deregister_ami("{ami_ids[0] if ami_ids else "<ami-id>"}",delete_snapshots=True)) '
                    f'to deregister the AMI and delete this snapshot in one step.'
                ),
                'error_code': error_code,
                'blocking_amis': ami_ids
            }
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': error_code}
    except Exception as e:
        logger.error(f"Error deleting snapshot: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def copy_snapshot(
    snapshot_id: str,
    source_region: str,
    destination_region: str,
    description: Optional[str] = None,
    encrypted: bool = False
) -> Dict[str, Any]:
    """Copy an EBS snapshot to another region."""
    try:
        ec2 = _get_boto_client('ec2', destination_region)
        params: Dict = {
            'SourceSnapshotId': snapshot_id,
            'SourceRegion': source_region,
            'Encrypted': encrypted
        }
        if description:
            params['Description'] = description

        response = ec2.copy_snapshot(**params)
        return {
            'success': True,
            'source_snapshot_id': snapshot_id,
            'new_snapshot_id': response['SnapshotId'],
            'source_region': source_region,
            'destination_region': destination_region,
            'message': f'Snapshot {snapshot_id} copy initiated in {destination_region} as {response["SnapshotId"]}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error copying snapshot: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_ebs_volume(volume_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete an EBS volume (must be detached first)."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_volume(VolumeId=volume_id)
        return {
            'success': True,
            'volume_id': volume_id,
            'message': f'EBS volume {volume_id} deleted successfully'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def cleanup_ebs_volume(volume_id: str, force: bool = False, region: Optional[str] = None) -> Dict[str, Any]:
    """Detach (if attached) then delete an EBS volume in one step."""
    try:
        ec2 = _get_boto_client('ec2', region)
        effective_region = _get_effective_region(region)

        volumes = ec2.describe_volumes(VolumeIds=[volume_id]).get('Volumes', [])
        if not volumes:
            return {'success': False, 'error': f'Volume {volume_id} not found in {effective_region}'}

        volume = volumes[0]
        state = volume.get('State')
        attachments = volume.get('Attachments', [])

        detached_from = None
        if attachments and state == 'in-use':
            instance_id = attachments[0].get('InstanceId')
            ec2.detach_volume(VolumeId=volume_id, Force=force)
            detached_from = instance_id
            for _ in range(15):
                time.sleep(1)
                v = ec2.describe_volumes(VolumeIds=[volume_id])['Volumes'][0]
                if v['State'] == 'available':
                    break

        ec2.delete_volume(VolumeId=volume_id)
        return {
            'success': True,
            'volume_id': volume_id,
            'detached_from': detached_from,
            'region': effective_region,
            'message': (
                f'Volume {volume_id} '
                + (f'detached from {detached_from} and ' if detached_from else '')
                + 'deleted successfully'
            )
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error cleaning up EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def resize_ebs_volume(
    volume_id: str,
    new_size_gb: Optional[int] = None,
    new_volume_type: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resize an EBS volume (size and/or type). Changes take effect immediately;
    OS-level partition expansion may be required after resize.
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        params: Dict = {'VolumeId': volume_id}
        if new_size_gb:
            params['Size'] = new_size_gb
        if new_volume_type:
            params['VolumeType'] = new_volume_type

        response = ec2.modify_volume(**params)
        mod = response['VolumeModification']
        return {
            'success': True,
            'volume_id': volume_id,
            'modification_state': mod['ModificationState'],
            'target_size': mod.get('TargetSize'),
            'target_volume_type': mod.get('TargetVolumeType'),
            'message': f'Volume {volume_id} modification initiated — state: {mod["ModificationState"]}'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error resizing EBS volume: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_ami(
    instance_id: str,
    name: str,
    description: Optional[str] = None,
    no_reboot: bool = True,
    tags: Optional[Dict[str, str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create an AMI (Amazon Machine Image) from a running or stopped instance."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params: Dict = {
            'InstanceId': instance_id,
            'Name': name,
            'NoReboot': no_reboot
        }
        if description:
            params['Description'] = description
        if tags:
            params['TagSpecifications'] = [{
                'ResourceType': 'image',
                'Tags': [{'Key': k, 'Value': v} for k, v in tags.items()]
            }]

        response = ec2.create_image(**params)
        return {
            'success': True,
            'image_id': response['ImageId'],
            'instance_id': instance_id,
            'name': name,
            'message': f'AMI creation initiated: {response["ImageId"]} from {instance_id} (state: pending)'
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating AMI: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def deregister_ami(image_id: str, delete_snapshots: bool = False, region: Optional[str] = None) -> Dict[str, Any]:
    """Deregister an AMI and optionally delete its backing snapshots."""
    try:
        ec2 = _get_boto_client('ec2', region)

        # Always collect snapshot IDs — needed for follow-up deletion or to inform the user
        images = ec2.describe_images(ImageIds=[image_id]).get('Images', [])
        snapshot_ids: List[str] = []
        if images:
            for mapping in images[0].get('BlockDeviceMappings', []):
                if 'Ebs' in mapping and 'SnapshotId' in mapping['Ebs']:
                    snapshot_ids.append(mapping['Ebs']['SnapshotId'])

        ec2.deregister_image(ImageId=image_id)

        deleted_snapshots = []
        failed_snapshots = []
        if delete_snapshots:
            for snap_id in snapshot_ids:
                try:
                    ec2.delete_snapshot(SnapshotId=snap_id)
                    deleted_snapshots.append(snap_id)
                except ClientError as snap_err:
                    failed_snapshots.append({'snapshot_id': snap_id, 'error': str(snap_err)})

        msg = f'AMI {image_id} deregistered'
        if deleted_snapshots:
            msg += f', deleted snapshots: {deleted_snapshots}'
        if failed_snapshots:
            msg += f', failed to delete snapshots: {[s["snapshot_id"] for s in failed_snapshots]}'
        if snapshot_ids and not delete_snapshots:
            msg += f'. Backing snapshots NOT deleted (pass delete_snapshots=True to also remove them): {snapshot_ids}'

        return {
            'success': True,
            'image_id': image_id,
            'backing_snapshot_ids': snapshot_ids,
            'deleted_snapshots': deleted_snapshots,
            'failed_snapshots': failed_snapshots,
            'message': msg
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deregistering AMI: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_ec2_console_output(instance_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the console output (boot log) for an EC2 instance. Useful for debugging boot failures."""
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.get_console_output(InstanceId=instance_id)
        output = response.get('Output', '')
        import base64
        try:
            decoded = base64.b64decode(output).decode('utf-8', errors='replace')
        except Exception:
            decoded = output

        return {
            'success': True,
            'instance_id': instance_id,
            'output': decoded or '(no output available — instance may be too new or stopped)',
            'timestamp': str(response.get('Timestamp', ''))
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error fetching console output: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ELASTIC IP OPERATIONS
# ============================================================================

def list_elastic_ips(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Elastic IP addresses.

    Args:
        region: AWS region

    Returns:
        Dictionary with Elastic IP information
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_addresses()

        elastic_ips = []
        for eip in response.get('Addresses', []):
            elastic_ips.append({
                'public_ip': eip.get('PublicIp'),
                'allocation_id': eip.get('AllocationId', 'N/A'),
                'association_id': eip.get('AssociationId', 'N/A'),
                'domain': eip.get('Domain', 'vpc'),
                'instance_id': eip.get('InstanceId', 'Not associated'),
                'network_interface_id': eip.get('NetworkInterfaceId', 'N/A'),
                'private_ip_address': eip.get('PrivateIpAddress', 'N/A'),
                'network_interface_owner_id': eip.get('NetworkInterfaceOwnerId', 'N/A'),
                'public_ipv4_pool': eip.get('PublicIpv4Pool', 'amazon'),
                'tags': {tag['Key']: tag['Value'] for tag in eip.get('Tags', [])}
            })

        return {
            'success': True,
            'count': len(elastic_ips),
            'elastic_ips': elastic_ips,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Elastic IPs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# NAT GATEWAY OPERATIONS
# ============================================================================

def list_nat_gateways(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List NAT Gateways.

    Args:
        region: AWS region

    Returns:
        Dictionary with NAT Gateway information
    """
    try:
        ec2 = _get_boto_client('ec2', region)
        response = ec2.describe_nat_gateways()

        nat_gateways = []
        for nat in response.get('NatGateways', []):
            # Get NAT Gateway addresses
            addresses = nat.get('NatGatewayAddresses', [])
            public_ip = addresses[0].get('PublicIp') if addresses else 'N/A'
            private_ip = addresses[0].get('PrivateIp') if addresses else 'N/A'

            nat_gateways.append({
                'nat_gateway_id': nat['NatGatewayId'],
                'state': nat.get('State'),
                'subnet_id': nat.get('SubnetId'),
                'vpc_id': nat.get('VpcId'),
                'public_ip': public_ip,
                'private_ip': private_ip,
                'connectivity_type': nat.get('ConnectivityType', 'public'),
                'created_time': nat.get('CreateTime').isoformat() if nat.get('CreateTime') else 'N/A',
                'delete_time': nat.get('DeleteTime').isoformat() if nat.get('DeleteTime') else 'N/A',
                'failure_code': nat.get('FailureCode', 'N/A'),
                'failure_message': nat.get('FailureMessage', 'N/A'),
                'tags': {tag['Key']: tag['Value'] for tag in nat.get('Tags', [])}
            })

        return {
            'success': True,
            'count': len(nat_gateways),
            'nat_gateways': nat_gateways,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing NAT Gateways: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def create_nat_gateway(
    subnet_id: str,
    allocation_id: Optional[str] = None,
    connectivity_type: str = 'public',
    name: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """Create a NAT gateway in a subnet. For public NAT, provide an Elastic IP allocation ID."""
    try:
        ec2 = _get_boto_client('ec2', region)
        params = {'SubnetId': subnet_id, 'ConnectivityType': connectivity_type}
        if allocation_id and connectivity_type == 'public':
            params['AllocationId'] = allocation_id
        if name:
            params['TagSpecifications'] = [{
                'ResourceType': 'natgateway',
                'Tags': [{'Key': 'Name', 'Value': name}]
            }]

        response = ec2.create_nat_gateway(**params)
        ngw = response['NatGateway']
        return {
            'success': True, 'nat_gateway_id': ngw['NatGatewayId'],
            'subnet_id': ngw['SubnetId'], 'state': ngw['State'],
            'connectivity_type': connectivity_type,
            'message': f'Successfully created NAT gateway {ngw["NatGatewayId"]}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error creating NAT gateway: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def delete_nat_gateway(nat_gateway_id: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Delete a NAT gateway."""
    try:
        ec2 = _get_boto_client('ec2', region)
        ec2.delete_nat_gateway(NatGatewayId=nat_gateway_id)
        return {
            'success': True, 'nat_gateway_id': nat_gateway_id,
            'message': f'Successfully initiated deletion of NAT gateway {nat_gateway_id}',
            'region': _get_effective_region(region)
        }
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error deleting NAT gateway: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# REDSHIFT OPERATIONS
# ============================================================================

def list_redshift_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Redshift data warehouse clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with Redshift cluster information
    """
    try:
        redshift = _get_boto_client('redshift', region)
        response = redshift.describe_clusters()

        clusters = []
        for cluster in response.get('Clusters', []):
            clusters.append({
                'cluster_identifier': cluster['ClusterIdentifier'],
                'node_type': cluster.get('NodeType'),
                'cluster_status': cluster.get('ClusterStatus'),
                'database_name': cluster.get('DBName'),
                'master_username': cluster.get('MasterUsername'),
                'endpoint': cluster.get('Endpoint', {}).get('Address', 'N/A'),
                'port': cluster.get('Endpoint', {}).get('Port', 5439),
                'cluster_create_time': cluster.get('ClusterCreateTime').isoformat() if cluster.get('ClusterCreateTime') else 'N/A',
                'number_of_nodes': cluster.get('NumberOfNodes', 1),
                'availability_zone': cluster.get('AvailabilityZone'),
                'encrypted': cluster.get('Encrypted', False),
                'vpc_id': cluster.get('VpcId', 'N/A'),
                'publicly_accessible': cluster.get('PubliclyAccessible', False),
                'cluster_version': cluster.get('ClusterVersion', 'N/A')
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Redshift clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# ATHENA OPERATIONS
# ============================================================================

def list_athena_workgroups(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Athena workgroups.

    Args:
        region: AWS region

    Returns:
        Dictionary with Athena workgroup information
    """
    try:
        athena = _get_boto_client('athena', region)
        response = athena.list_work_groups()

        workgroups = []
        for wg in response.get('WorkGroups', []):
            # Get workgroup details
            try:
                details = athena.get_work_group(WorkGroup=wg['Name'])
                wg_details = details.get('WorkGroup', {})
                config = wg_details.get('Configuration', {})

                workgroups.append({
                    'name': wg['Name'],
                    'state': wg.get('State', 'ENABLED'),
                    'description': wg.get('Description', 'N/A'),
                    'creation_time': wg.get('CreationTime').isoformat() if wg.get('CreationTime') else 'N/A',
                    'output_location': config.get('ResultConfiguration', {}).get('OutputLocation', 'N/A'),
                    'bytes_scanned_cutoff': config.get('BytesScannedCutoffPerQuery', 0),
                    'enforce_workgroup_config': config.get('EnforceWorkGroupConfiguration', False)
                })
            except Exception:
                workgroups.append({
                    'name': wg['Name'],
                    'state': wg.get('State', 'ENABLED'),
                    'description': wg.get('Description', 'N/A')
                })

        return {
            'success': True,
            'count': len(workgroups),
            'workgroups': workgroups,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Athena workgroups: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# GLUE OPERATIONS
# ============================================================================

def list_glue_jobs(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Glue ETL jobs.

    Args:
        region: AWS region

    Returns:
        Dictionary with Glue job information
    """
    try:
        glue = _get_boto_client('glue', region)
        response = glue.get_jobs()

        jobs = []
        for job in response.get('Jobs', []):
            jobs.append({
                'name': job['Name'],
                'description': job.get('Description', 'N/A'),
                'role': job.get('Role'),
                'created_on': job.get('CreatedOn').isoformat() if job.get('CreatedOn') else 'N/A',
                'last_modified_on': job.get('LastModifiedOn').isoformat() if job.get('LastModifiedOn') else 'N/A',
                'execution_class': job.get('ExecutionClass', 'STANDARD'),
                'command': job.get('Command', {}).get('Name', 'N/A'),
                'max_retries': job.get('MaxRetries', 0),
                'timeout': job.get('Timeout', 0),
                'max_capacity': job.get('MaxCapacity', 0),
                'glue_version': job.get('GlueVersion', 'N/A')
            })

        return {
            'success': True,
            'count': len(jobs),
            'jobs': jobs,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Glue jobs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_glue_crawlers(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Glue crawlers.

    Args:
        region: AWS region

    Returns:
        Dictionary with Glue crawler information
    """
    try:
        glue = _get_boto_client('glue', region)
        response = glue.get_crawlers()

        crawlers = []
        for crawler in response.get('Crawlers', []):
            crawlers.append({
                'name': crawler['Name'],
                'role': crawler.get('Role'),
                'state': crawler.get('State', 'READY'),
                'database_name': crawler.get('DatabaseName'),
                'description': crawler.get('Description', 'N/A'),
                'creation_time': crawler.get('CreationTime').isoformat() if crawler.get('CreationTime') else 'N/A',
                'last_updated': crawler.get('LastUpdated').isoformat() if crawler.get('LastUpdated') else 'N/A',
                'last_crawl_status': crawler.get('LastCrawl', {}).get('Status', 'N/A'),
                'crawler_security_configuration': crawler.get('CrawlerSecurityConfiguration', 'N/A')
            })

        return {
            'success': True,
            'count': len(crawlers),
            'crawlers': crawlers,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Glue crawlers: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# SAGEMAKER OPERATIONS
# ============================================================================

def list_sagemaker_endpoints(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List SageMaker endpoints.

    Args:
        region: AWS region

    Returns:
        Dictionary with SageMaker endpoint information
    """
    try:
        sagemaker = _get_boto_client('sagemaker', region)
        response = sagemaker.list_endpoints()

        endpoints = []
        for endpoint in response.get('Endpoints', []):
            endpoints.append({
                'endpoint_name': endpoint['EndpointName'],
                'endpoint_arn': endpoint['EndpointArn'],
                'creation_time': endpoint.get('CreationTime').isoformat() if endpoint.get('CreationTime') else 'N/A',
                'last_modified_time': endpoint.get('LastModifiedTime').isoformat() if endpoint.get('LastModifiedTime') else 'N/A',
                'endpoint_status': endpoint.get('EndpointStatus')
            })

        return {
            'success': True,
            'count': len(endpoints),
            'endpoints': endpoints,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SageMaker endpoints: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# MSK (MANAGED STREAMING FOR KAFKA) OPERATIONS
# ============================================================================

def list_msk_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List MSK (Managed Streaming for Kafka) clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with MSK cluster information
    """
    try:
        kafka = _get_boto_client('kafka', region)
        response = kafka.list_clusters()

        clusters = []
        for cluster in response.get('ClusterInfoList', []):
            clusters.append({
                'cluster_name': cluster['ClusterName'],
                'cluster_arn': cluster['ClusterArn'],
                'state': cluster.get('State'),
                'creation_time': cluster.get('CreationTime').isoformat() if cluster.get('CreationTime') else 'N/A',
                'kafka_version': cluster.get('CurrentBrokerSoftwareInfo', {}).get('KafkaVersion', 'N/A'),
                'number_of_broker_nodes': cluster.get('NumberOfBrokerNodes', 0),
                'enhanced_monitoring': cluster.get('EnhancedMonitoring', 'DEFAULT'),
                'zookeeper_connect_string': cluster.get('ZookeeperConnectString', 'N/A'),
                'bootstrap_brokers': cluster.get('CurrentVersion', 'N/A')
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing MSK clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# OPENSEARCH (ELASTICSEARCH) OPERATIONS
# ============================================================================

def list_opensearch_domains(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List OpenSearch (formerly Elasticsearch) domains.

    Args:
        region: AWS region

    Returns:
        Dictionary with OpenSearch domain information
    """
    try:
        opensearch = _get_boto_client('opensearch', region)
        response = opensearch.list_domain_names()

        domains = []
        for domain in response.get('DomainNames', []):
            # Get domain details
            try:
                details = opensearch.describe_domain(DomainName=domain['DomainName'])
                domain_status = details.get('DomainStatus', {})

                domains.append({
                    'domain_name': domain['DomainName'],
                    'domain_id': domain_status.get('DomainId'),
                    'arn': domain_status.get('ARN'),
                    'created': domain_status.get('Created', False),
                    'deleted': domain_status.get('Deleted', False),
                    'endpoint': domain_status.get('Endpoint', 'N/A'),
                    'engine_version': domain_status.get('EngineVersion', 'N/A'),
                    'processing': domain_status.get('Processing', False),
                    'upgrade_processing': domain_status.get('UpgradeProcessing', False),
                    'instance_type': domain_status.get('ClusterConfig', {}).get('InstanceType', 'N/A'),
                    'instance_count': domain_status.get('ClusterConfig', {}).get('InstanceCount', 0)
                })
            except Exception:
                domains.append({
                    'domain_name': domain['DomainName'],
                    'engine_type': domain.get('EngineType', 'OpenSearch')
                })

        return {
            'success': True,
            'count': len(domains),
            'domains': domains,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing OpenSearch domains: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# NEPTUNE OPERATIONS
# ============================================================================

def list_neptune_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Neptune graph database clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with Neptune cluster information
    """
    try:
        neptune = _get_boto_client('neptune', region)
        response = neptune.describe_db_clusters()

        clusters = []
        for cluster in response.get('DBClusters', []):
            clusters.append({
                'cluster_identifier': cluster['DBClusterIdentifier'],
                'status': cluster.get('Status'),
                'engine': cluster.get('Engine'),
                'engine_version': cluster.get('EngineVersion'),
                'endpoint': cluster.get('Endpoint'),
                'reader_endpoint': cluster.get('ReaderEndpoint'),
                'port': cluster.get('Port', 8182),
                'database_name': cluster.get('DatabaseName', 'N/A'),
                'cluster_create_time': cluster.get('ClusterCreateTime').isoformat() if cluster.get('ClusterCreateTime') else 'N/A',
                'availability_zones': cluster.get('AvailabilityZones', []),
                'multi_az': cluster.get('MultiAZ', False),
                'storage_encrypted': cluster.get('StorageEncrypted', False)
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Neptune clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# DOCUMENTDB OPERATIONS
# ============================================================================

def list_documentdb_clusters(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List DocumentDB (MongoDB-compatible) clusters.

    Args:
        region: AWS region

    Returns:
        Dictionary with DocumentDB cluster information
    """
    try:
        docdb = _get_boto_client('docdb', region)
        response = docdb.describe_db_clusters()

        clusters = []
        for cluster in response.get('DBClusters', []):
            clusters.append({
                'cluster_identifier': cluster['DBClusterIdentifier'],
                'status': cluster.get('Status'),
                'engine': cluster.get('Engine'),
                'engine_version': cluster.get('EngineVersion'),
                'endpoint': cluster.get('Endpoint'),
                'reader_endpoint': cluster.get('ReaderEndpoint'),
                'port': cluster.get('Port', 27017),
                'master_username': cluster.get('MasterUsername'),
                'cluster_create_time': cluster.get('ClusterCreateTime').isoformat() if cluster.get('ClusterCreateTime') else 'N/A',
                'availability_zones': cluster.get('AvailabilityZones', []),
                'multi_az': cluster.get('MultiAZ', False),
                'storage_encrypted': cluster.get('StorageEncrypted', False),
                'db_cluster_members': len(cluster.get('DBClusterMembers', []))
            })

        return {
            'success': True,
            'count': len(clusters),
            'clusters': clusters,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing DocumentDB clusters: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# APPSYNC OPERATIONS
# ============================================================================

def list_appsync_apis(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List AppSync GraphQL APIs.

    Args:
        region: AWS region

    Returns:
        Dictionary with AppSync API information
    """
    try:
        appsync = _get_boto_client('appsync', region)
        response = appsync.list_graphql_apis()

        apis = []
        for api in response.get('graphqlApis', []):
            apis.append({
                'api_id': api['apiId'],
                'name': api['name'],
                'authentication_type': api.get('authenticationType'),
                'arn': api.get('arn'),
                'uris': api.get('uris', {}),
                'created_date': api.get('createdDate', 'N/A'),
                'xray_enabled': api.get('xrayEnabled', False),
                'waf_web_acl_arn': api.get('wafWebAclArn', 'N/A')
            })

        return {
            'success': True,
            'count': len(apis),
            'apis': apis,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing AppSync APIs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# AMAZON BEDROCK OPERATIONS (Generative AI)
# ============================================================================

def list_bedrock_foundation_models(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock foundation models available in the region.

    Args:
        region: AWS region

    Returns:
        Dictionary with Bedrock foundation models information
    """
    try:
        bedrock = _get_boto_client('bedrock', region)
        response = bedrock.list_foundation_models()

        models = []
        for model in response.get('modelSummaries', []):
            models.append({
                'model_id': model.get('modelId'),
                'model_name': model.get('modelName'),
                'provider_name': model.get('providerName'),
                'model_arn': model.get('modelArn'),
                'input_modalities': model.get('inputModalities', []),
                'output_modalities': model.get('outputModalities', []),
                'response_streaming_supported': model.get('responseStreamingSupported', False),
                'customizations_supported': model.get('customizationsSupported', []),
                'inference_types_supported': model.get('inferenceTypesSupported', [])
            })

        # Group by provider
        providers = {}
        for model in models:
            provider = model['provider_name']
            if provider not in providers:
                providers[provider] = []
            providers[provider].append(model['model_name'])

        return {
            'success': True,
            'count': len(models),
            'models': models,
            'providers': providers,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock foundation models: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_bedrock_custom_models(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock custom models (fine-tuned models).

    Args:
        region: AWS region

    Returns:
        Dictionary with Bedrock custom models information
    """
    try:
        bedrock = _get_boto_client('bedrock', region)
        response = bedrock.list_custom_models()

        models = []
        for model in response.get('modelSummaries', []):
            models.append({
                'model_arn': model.get('modelArn'),
                'model_name': model.get('modelName'),
                'creation_time': model.get('creationTime').isoformat() if model.get('creationTime') else 'N/A',
                'base_model_arn': model.get('baseModelArn'),
                'base_model_name': model.get('baseModelName'),
                'customization_type': model.get('customizationType')
            })

        return {
            'success': True,
            'count': len(models),
            'custom_models': models,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock custom models: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_bedrock_model_customization_jobs(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock model customization (fine-tuning) jobs.

    Args:
        region: AWS region

    Returns:
        Dictionary with Bedrock customization jobs information
    """
    try:
        bedrock = _get_boto_client('bedrock', region)
        response = bedrock.list_model_customization_jobs()

        jobs = []
        for job in response.get('modelCustomizationJobSummaries', []):
            jobs.append({
                'job_arn': job.get('jobArn'),
                'job_name': job.get('jobName'),
                'status': job.get('status'),
                'creation_time': job.get('creationTime').isoformat() if job.get('creationTime') else 'N/A',
                'end_time': job.get('endTime').isoformat() if job.get('endTime') else 'In Progress',
                'base_model_arn': job.get('baseModelArn'),
                'custom_model_arn': job.get('customModelArn'),
                'customization_type': job.get('customizationType')
            })

        # Count by status
        status_counts = {}
        for job in jobs:
            status = job['status']
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            'success': True,
            'count': len(jobs),
            'jobs': jobs,
            'status_counts': status_counts,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock customization jobs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_bedrock_knowledge_bases(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock knowledge bases (for RAG - Retrieval Augmented Generation).

    Args:
        region: AWS region

    Returns:
        Dictionary with Bedrock knowledge bases information
    """
    try:
        bedrock_agent = _get_boto_client('bedrock-agent', region)
        response = bedrock_agent.list_knowledge_bases()

        knowledge_bases = []
        for kb in response.get('knowledgeBaseSummaries', []):
            knowledge_bases.append({
                'knowledge_base_id': kb.get('knowledgeBaseId'),
                'name': kb.get('name'),
                'description': kb.get('description', 'N/A'),
                'status': kb.get('status'),
                'created_at': kb.get('createdAt').isoformat() if kb.get('createdAt') else 'N/A',
                'updated_at': kb.get('updatedAt').isoformat() if kb.get('updatedAt') else 'N/A'
            })

        return {
            'success': True,
            'count': len(knowledge_bases),
            'knowledge_bases': knowledge_bases,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock knowledge bases: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_bedrock_agents(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock agents (AI agents that can use tools and APIs).

    Args:
        region: AWS region

    Returns:
        Dictionary with Bedrock agents information
    """
    try:
        bedrock_agent = _get_boto_client('bedrock-agent', region)
        response = bedrock_agent.list_agents()

        agents = []
        for agent in response.get('agentSummaries', []):
            agents.append({
                'agent_id': agent.get('agentId'),
                'agent_name': agent.get('agentName'),
                'agent_status': agent.get('agentStatus'),
                'description': agent.get('description', 'N/A'),
                'created_at': agent.get('createdAt').isoformat() if agent.get('createdAt') else 'N/A',
                'updated_at': agent.get('updatedAt').isoformat() if agent.get('updatedAt') else 'N/A',
                'latest_agent_version': agent.get('latestAgentVersion', 'N/A')
            })

        return {
            'success': True,
            'count': len(agents),
            'agents': agents,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock agents: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_bedrock_provisioned_model_throughputs(region: Optional[str] = None) -> Dict[str, Any]:
    """
    List Amazon Bedrock provisioned model throughput configurations.

    Args:
        region: AWS region

    Returns:
        Dictionary with provisioned throughput information
    """
    try:
        bedrock = _get_boto_client('bedrock', region)
        response = bedrock.list_provisioned_model_throughputs()

        throughputs = []
        for throughput in response.get('provisionedModelSummaries', []):
            throughputs.append({
                'provisioned_model_arn': throughput.get('provisionedModelArn'),
                'provisioned_model_name': throughput.get('provisionedModelName'),
                'model_arn': throughput.get('modelArn'),
                'status': throughput.get('status'),
                'creation_time': throughput.get('creationTime').isoformat() if throughput.get('creationTime') else 'N/A',
                'commitment_duration': throughput.get('commitmentDuration', 'N/A'),
                'commitment_expiration_time': throughput.get('commitmentExpirationTime').isoformat() if throughput.get('commitmentExpirationTime') else 'N/A',
                'desired_model_units': throughput.get('desiredModelUnits', 0),
                'model_units': throughput.get('modelUnits', 0)
            })

        return {
            'success': True,
            'count': len(throughputs),
            'provisioned_throughputs': throughputs,
            'region': _get_effective_region(region)
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Bedrock provisioned throughputs: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ============================================================================
# COMPREHENSIVE RESOURCE INVENTORY
# ============================================================================

def get_aws_resource_inventory(
    services: Optional[List[str]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get comprehensive inventory of AWS resources across multiple services.

    Args:
        services: List of services to scan (if None, scans all supported services)
        region: AWS region (if None, uses default region)

    Returns:
        Dictionary with inventory of all resources
    """
    try:
        logger.info(f"Starting AWS resource inventory scan in region {region or 'default'}")

        # Default to all services if not specified
        all_services = services or [
            'ec2', 's3', 'rds', 'dynamodb', 'lambda', 'eks', 'ecs',
            'elasticache', 'beanstalk', 'vpc', 'cloudfront', 'route53',
            'apigateway', 'iam', 'sns', 'sqs', 'ecr', 'secrets',
            'elb', 'efs', 'eventbridge', 'cloudformation', 'ssm', 'autoscaling',
            'stepfunctions', 'kinesis', 'acm', 'waf', 'backup', 'ebs',
            'elasticip', 'natgateway', 'redshift', 'athena', 'glue',
            'sagemaker', 'msk', 'opensearch', 'neptune', 'documentdb', 'appsync',
            'bedrock'
        ]

        inventory = {
            'success': True,
            'region': _get_effective_region(region),
            'scan_time': datetime.utcnow().isoformat(),
            'services': {}
        }

        # EC2 Instances
        if 'ec2' in all_services:
            logger.info("Scanning EC2 instances...")
            ec2_result = get_ec2_instances(region=region)
            if ec2_result.get('success'):
                inventory['services']['ec2'] = {
                    'count': ec2_result.get('count', 0),
                    'instances': ec2_result.get('instances', [])
                }

        # S3 Buckets
        if 's3' in all_services:
            logger.info("Scanning S3 buckets...")
            s3_result = list_s3_buckets(region=region)
            if s3_result.get('success'):
                inventory['services']['s3'] = {
                    'count': s3_result.get('count', 0),
                    'buckets': s3_result.get('buckets', [])
                }

        # RDS Instances
        if 'rds' in all_services:
            logger.info("Scanning RDS instances...")
            rds_result = list_rds_instances(region=region)
            if rds_result.get('success'):
                inventory['services']['rds'] = {
                    'count': rds_result.get('count', 0),
                    'instances': rds_result.get('instances', [])
                }

        # DynamoDB Tables
        if 'dynamodb' in all_services:
            logger.info("Scanning DynamoDB tables...")
            dynamodb_result = list_dynamodb_tables(region=region)
            if dynamodb_result.get('success'):
                inventory['services']['dynamodb'] = {
                    'count': dynamodb_result.get('count', 0),
                    'tables': dynamodb_result.get('tables', [])
                }

        # Lambda Functions
        if 'lambda' in all_services:
            logger.info("Scanning Lambda functions...")
            lambda_result = list_lambda_functions(region=region)
            if lambda_result.get('success'):
                inventory['services']['lambda'] = {
                    'count': lambda_result.get('count', 0),
                    'functions': lambda_result.get('functions', [])
                }

        # EKS Clusters
        if 'eks' in all_services:
            logger.info("Scanning EKS clusters...")
            eks_result = get_eks_clusters(region=region)
            if eks_result.get('success'):
                inventory['services']['eks'] = {
                    'count': eks_result.get('count', 0),
                    'clusters': eks_result.get('clusters', [])
                }

        # ECS Clusters
        if 'ecs' in all_services:
            logger.info("Scanning ECS clusters...")
            ecs_result = list_ecs_clusters(region=region)
            if ecs_result.get('success'):
                inventory['services']['ecs'] = {
                    'count': ecs_result.get('count', 0),
                    'clusters': ecs_result.get('clusters', [])
                }

        # ElastiCache
        if 'elasticache' in all_services:
            logger.info("Scanning ElastiCache clusters...")
            cache_result = list_elasticache_clusters(region=region)
            if cache_result.get('success'):
                inventory['services']['elasticache'] = {
                    'count': cache_result.get('count', 0),
                    'clusters': cache_result.get('clusters', [])
                }

        # Elastic Beanstalk
        if 'beanstalk' in all_services:
            logger.info("Scanning Elastic Beanstalk...")
            beanstalk_result = list_beanstalk_environments(region=region)
            if beanstalk_result.get('success'):
                inventory['services']['beanstalk'] = {
                    'count': beanstalk_result.get('count', 0),
                    'environments': beanstalk_result.get('environments', [])
                }

        # VPC
        if 'vpc' in all_services:
            logger.info("Scanning VPCs...")
            vpc_result = list_vpcs(region=region)
            if vpc_result.get('success'):
                inventory['services']['vpc'] = {
                    'count': vpc_result.get('count', 0),
                    'vpcs': vpc_result.get('vpcs', [])
                }

        # CloudFront
        if 'cloudfront' in all_services:
            logger.info("Scanning CloudFront distributions...")
            cf_result = list_cloudfront_distributions(region=region)
            if cf_result.get('success'):
                inventory['services']['cloudfront'] = {
                    'count': cf_result.get('count', 0),
                    'distributions': cf_result.get('distributions', [])
                }

        # Route 53
        if 'route53' in all_services:
            logger.info("Scanning Route 53 hosted zones...")
            r53_result = list_route53_zones(region=region)
            if r53_result.get('success'):
                inventory['services']['route53'] = {
                    'count': r53_result.get('count', 0),
                    'hosted_zones': r53_result.get('hosted_zones', [])
                }

        # API Gateway
        if 'apigateway' in all_services:
            logger.info("Scanning API Gateways...")
            api_result = list_api_gateways(region=region)
            if api_result.get('success'):
                inventory['services']['apigateway'] = {
                    'count': api_result.get('count', 0),
                    'apis': api_result.get('apis', [])
                }

        # IAM
        if 'iam' in all_services:
            logger.info("Scanning IAM users and roles...")
            users_result = list_iam_users()
            roles_result = list_iam_roles()
            inventory['services']['iam'] = {
                'users_count': users_result.get('count', 0) if users_result.get('success') else 0,
                'roles_count': roles_result.get('count', 0) if roles_result.get('success') else 0,
                'users': users_result.get('users', []) if users_result.get('success') else [],
                'roles': roles_result.get('roles', []) if roles_result.get('success') else []
            }

        # SNS Topics
        if 'sns' in all_services:
            logger.info("Scanning SNS topics...")
            sns_result = list_sns_topics(region=region)
            if sns_result.get('success'):
                inventory['services']['sns'] = {
                    'count': sns_result.get('count', 0),
                    'topics': sns_result.get('topics', [])
                }

        # SQS Queues
        if 'sqs' in all_services:
            logger.info("Scanning SQS queues...")
            sqs_result = list_sqs_queues(region=region)
            if sqs_result.get('success'):
                inventory['services']['sqs'] = {
                    'count': sqs_result.get('count', 0),
                    'queues': sqs_result.get('queues', [])
                }

        # ECR Repositories
        if 'ecr' in all_services:
            logger.info("Scanning ECR repositories...")
            ecr_result = list_ecr_repositories(region=region)
            if ecr_result.get('success'):
                inventory['services']['ecr'] = {
                    'count': ecr_result.get('count', 0),
                    'repositories': ecr_result.get('repositories', [])
                }

        # Secrets Manager
        if 'secrets' in all_services:
            logger.info("Scanning Secrets Manager secrets...")
            secrets_result = list_secrets_manager_secrets(region=region)
            if secrets_result.get('success'):
                inventory['services']['secrets'] = {
                    'count': secrets_result.get('count', 0),
                    'secrets': secrets_result.get('secrets', [])
                }

        # Load Balancers
        if 'elb' in all_services:
            logger.info("Scanning Load Balancers...")
            elb_result = list_load_balancers(region=region)
            if elb_result.get('success'):
                inventory['services']['elb'] = {
                    'count': elb_result.get('count', 0),
                    'load_balancers': elb_result.get('load_balancers', [])
                }

        # EFS File Systems
        if 'efs' in all_services:
            logger.info("Scanning EFS file systems...")
            efs_result = list_efs_file_systems(region=region)
            if efs_result.get('success'):
                inventory['services']['efs'] = {
                    'count': efs_result.get('count', 0),
                    'file_systems': efs_result.get('file_systems', [])
                }

        # EventBridge Rules
        if 'eventbridge' in all_services:
            logger.info("Scanning EventBridge rules...")
            eb_result = list_eventbridge_rules(region=region)
            if eb_result.get('success'):
                inventory['services']['eventbridge'] = {
                    'count': eb_result.get('count', 0),
                    'rules': eb_result.get('rules', [])
                }

        # CloudFormation Stacks
        if 'cloudformation' in all_services:
            logger.info("Scanning CloudFormation stacks...")
            cfn_result = list_cloudformation_stacks(region=region)
            if cfn_result.get('success'):
                inventory['services']['cloudformation'] = {
                    'count': cfn_result.get('count', 0),
                    'stacks': cfn_result.get('stacks', [])
                }

        # Systems Manager Parameters
        if 'ssm' in all_services:
            logger.info("Scanning SSM parameters...")
            ssm_result = list_ssm_parameters(region=region)
            if ssm_result.get('success'):
                inventory['services']['ssm'] = {
                    'count': ssm_result.get('count', 0),
                    'parameters': ssm_result.get('parameters', [])
                }

        # Auto Scaling Groups
        if 'autoscaling' in all_services:
            logger.info("Scanning Auto Scaling groups...")
            asg_result = list_autoscaling_groups(region=region)
            if asg_result.get('success'):
                inventory['services']['autoscaling'] = {
                    'count': asg_result.get('count', 0),
                    'groups': asg_result.get('groups', [])
                }

        # Step Functions
        if 'stepfunctions' in all_services:
            logger.info("Scanning Step Functions...")
            sfn_result = list_step_functions(region=region)
            if sfn_result.get('success'):
                inventory['services']['stepfunctions'] = {
                    'count': sfn_result.get('count', 0),
                    'state_machines': sfn_result.get('state_machines', [])
                }

        # Kinesis Streams
        if 'kinesis' in all_services:
            logger.info("Scanning Kinesis streams...")
            kinesis_result = list_kinesis_streams(region=region)
            if kinesis_result.get('success'):
                inventory['services']['kinesis'] = {
                    'count': kinesis_result.get('count', 0),
                    'streams': kinesis_result.get('streams', [])
                }

        # ACM Certificates
        if 'acm' in all_services:
            logger.info("Scanning ACM certificates...")
            acm_result = list_acm_certificates(region=region)
            if acm_result.get('success'):
                inventory['services']['acm'] = {
                    'count': acm_result.get('count', 0),
                    'certificates': acm_result.get('certificates', [])
                }

        # WAF Web ACLs
        if 'waf' in all_services:
            logger.info("Scanning WAF Web ACLs...")
            waf_result = list_waf_web_acls(region=region)
            if waf_result.get('success'):
                inventory['services']['waf'] = {
                    'count': waf_result.get('count', 0),
                    'web_acls': waf_result.get('web_acls', [])
                }

        # Backup Plans
        if 'backup' in all_services:
            logger.info("Scanning Backup plans...")
            backup_result = list_backup_plans(region=region)
            if backup_result.get('success'):
                inventory['services']['backup'] = {
                    'count': backup_result.get('count', 0),
                    'backup_plans': backup_result.get('backup_plans', [])
                }

        # EBS Volumes
        if 'ebs' in all_services:
            logger.info("Scanning EBS volumes...")
            ebs_result = list_ebs_volumes(region=region)
            if ebs_result.get('success'):
                inventory['services']['ebs'] = {
                    'count': ebs_result.get('count', 0),
                    'volumes': ebs_result.get('volumes', [])
                }

        # Elastic IPs
        if 'elasticip' in all_services:
            logger.info("Scanning Elastic IPs...")
            eip_result = list_elastic_ips(region=region)
            if eip_result.get('success'):
                inventory['services']['elasticip'] = {
                    'count': eip_result.get('count', 0),
                    'elastic_ips': eip_result.get('elastic_ips', [])
                }

        # NAT Gateways
        if 'natgateway' in all_services:
            logger.info("Scanning NAT Gateways...")
            nat_result = list_nat_gateways(region=region)
            if nat_result.get('success'):
                inventory['services']['natgateway'] = {
                    'count': nat_result.get('count', 0),
                    'nat_gateways': nat_result.get('nat_gateways', [])
                }

        # Redshift Clusters
        if 'redshift' in all_services:
            logger.info("Scanning Redshift clusters...")
            redshift_result = list_redshift_clusters(region=region)
            if redshift_result.get('success'):
                inventory['services']['redshift'] = {
                    'count': redshift_result.get('count', 0),
                    'clusters': redshift_result.get('clusters', [])
                }

        # Athena Workgroups
        if 'athena' in all_services:
            logger.info("Scanning Athena workgroups...")
            athena_result = list_athena_workgroups(region=region)
            if athena_result.get('success'):
                inventory['services']['athena'] = {
                    'count': athena_result.get('count', 0),
                    'workgroups': athena_result.get('workgroups', [])
                }

        # Glue Jobs and Crawlers
        if 'glue' in all_services:
            logger.info("Scanning Glue jobs and crawlers...")
            jobs_result = list_glue_jobs(region=region)
            crawlers_result = list_glue_crawlers(region=region)
            inventory['services']['glue'] = {
                'jobs_count': jobs_result.get('count', 0) if jobs_result.get('success') else 0,
                'crawlers_count': crawlers_result.get('count', 0) if crawlers_result.get('success') else 0,
                'jobs': jobs_result.get('jobs', []) if jobs_result.get('success') else [],
                'crawlers': crawlers_result.get('crawlers', []) if crawlers_result.get('success') else []
            }

        # SageMaker Endpoints
        if 'sagemaker' in all_services:
            logger.info("Scanning SageMaker endpoints...")
            sagemaker_result = list_sagemaker_endpoints(region=region)
            if sagemaker_result.get('success'):
                inventory['services']['sagemaker'] = {
                    'count': sagemaker_result.get('count', 0),
                    'endpoints': sagemaker_result.get('endpoints', [])
                }

        # MSK Clusters
        if 'msk' in all_services:
            logger.info("Scanning MSK clusters...")
            msk_result = list_msk_clusters(region=region)
            if msk_result.get('success'):
                inventory['services']['msk'] = {
                    'count': msk_result.get('count', 0),
                    'clusters': msk_result.get('clusters', [])
                }

        # OpenSearch Domains
        if 'opensearch' in all_services:
            logger.info("Scanning OpenSearch domains...")
            opensearch_result = list_opensearch_domains(region=region)
            if opensearch_result.get('success'):
                inventory['services']['opensearch'] = {
                    'count': opensearch_result.get('count', 0),
                    'domains': opensearch_result.get('domains', [])
                }

        # Neptune Clusters
        if 'neptune' in all_services:
            logger.info("Scanning Neptune clusters...")
            neptune_result = list_neptune_clusters(region=region)
            if neptune_result.get('success'):
                inventory['services']['neptune'] = {
                    'count': neptune_result.get('count', 0),
                    'clusters': neptune_result.get('clusters', [])
                }

        # DocumentDB Clusters
        if 'documentdb' in all_services:
            logger.info("Scanning DocumentDB clusters...")
            documentdb_result = list_documentdb_clusters(region=region)
            if documentdb_result.get('success'):
                inventory['services']['documentdb'] = {
                    'count': documentdb_result.get('count', 0),
                    'clusters': documentdb_result.get('clusters', [])
                }

        # AppSync APIs
        if 'appsync' in all_services:
            logger.info("Scanning AppSync APIs...")
            appsync_result = list_appsync_apis(region=region)
            if appsync_result.get('success'):
                inventory['services']['appsync'] = {
                    'count': appsync_result.get('count', 0),
                    'apis': appsync_result.get('apis', [])
                }

        # Bedrock (Generative AI)
        if 'bedrock' in all_services:
            logger.info("Scanning Bedrock resources...")
            bedrock_data = {}

            # Foundation models
            models_result = list_bedrock_foundation_models(region=region)
            if models_result.get('success'):
                bedrock_data['foundation_models'] = {
                    'count': models_result.get('count', 0),
                    'providers': models_result.get('providers', {})
                }

            # Custom models
            custom_models_result = list_bedrock_custom_models(region=region)
            if custom_models_result.get('success'):
                bedrock_data['custom_models'] = {
                    'count': custom_models_result.get('count', 0),
                    'models': custom_models_result.get('custom_models', [])
                }

            # Customization jobs
            jobs_result = list_bedrock_model_customization_jobs(region=region)
            if jobs_result.get('success'):
                bedrock_data['customization_jobs'] = {
                    'count': jobs_result.get('count', 0),
                    'status_counts': jobs_result.get('status_counts', {})
                }

            # Knowledge bases
            kb_result = list_bedrock_knowledge_bases(region=region)
            if kb_result.get('success'):
                bedrock_data['knowledge_bases'] = {
                    'count': kb_result.get('count', 0),
                    'knowledge_bases': kb_result.get('knowledge_bases', [])
                }

            # Agents
            agents_result = list_bedrock_agents(region=region)
            if agents_result.get('success'):
                bedrock_data['agents'] = {
                    'count': agents_result.get('count', 0),
                    'agents': agents_result.get('agents', [])
                }

            # Provisioned throughputs
            throughput_result = list_bedrock_provisioned_model_throughputs(region=region)
            if throughput_result.get('success'):
                bedrock_data['provisioned_throughputs'] = {
                    'count': throughput_result.get('count', 0),
                    'throughputs': throughput_result.get('provisioned_throughputs', [])
                }

            if bedrock_data:
                inventory['services']['bedrock'] = bedrock_data

        # Calculate totals
        total_resources = sum([
            inventory['services'].get(svc, {}).get('count', 0)
            for svc in inventory['services']
        ])

        inventory['total_resources'] = total_resources
        inventory['message'] = f'Found {total_resources} resources across {len(inventory["services"])} AWS services'

        logger.info(f"AWS resource inventory scan completed: {total_resources} resources found")

        return inventory

    except Exception as e:
        logger.error(f"Error getting AWS resource inventory: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to complete AWS resource inventory scan'
        }


# ── Read-only operations that are always safe to call without confirmation ──
_READ_PREFIXES = ('describe_', 'list_', 'get_', 'head_', 'check_', 'search_', 'scan_', 'query_', 'select_', 'batch_get_')

def aws_api_read(
    service: str,
    operation: str,
    params: Optional[Dict[str, Any]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call ANY AWS read-only API operation (describe/list/get/head).

    Use this when no dedicated tool exists for a read operation.
    Examples: aws_api_read('ecs','describe_task_definition',{'taskDefinition':'my-task'})
              aws_api_read('route53','list_hosted_zones')
              aws_api_read('acm','list_certificates')
    """
    op_lower = operation.lower()
    if not any(op_lower.startswith(p) for p in _READ_PREFIXES):
        return {
            'success': False,
            'error': f'"{operation}" does not look like a read-only operation. '
                     'Use aws_api_write for create/update/delete/put operations.'
        }
    try:
        client = _get_boto_client(service.lower(), region)
        method = getattr(client, op_lower, None)
        if method is None:
            return {'success': False, 'error': f'boto3.client("{service}") has no method "{operation}"'}
        result = method(**(params or {}))
        result.pop('ResponseMetadata', None)
        return {
            'success': True,
            'service': service,
            'operation': operation,
            'region': _get_effective_region(region),
            'result': result
        }
    except ClientError as e:
        logger.error(f"AWS API error ({service}.{operation}): {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"aws_api_read error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def aws_api_write(
    service: str,
    operation: str,
    params: Optional[Dict[str, Any]] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Call ANY AWS write API operation (create/update/delete/put/modify/attach/detach/enable/disable).

    Use this when no dedicated tool exists for a write operation.
    Requires user confirmation (high-risk). Always describe the change to the user before calling.
    Examples: aws_api_write('cloudwatch','delete_alarms',{'AlarmNames':['my-alarm']})
              aws_api_write('ec2','modify_instance_attribute',{'InstanceId':'i-xxx','InstanceType':{'Value':'t3.small'}})
              aws_api_write('route53','change_resource_record_sets',{...})
    """
    op_lower = operation.lower()
    if any(op_lower.startswith(p) for p in _READ_PREFIXES):
        return {
            'success': False,
            'error': f'"{operation}" looks like a read operation. Use aws_api_read instead.'
        }
    try:
        client = _get_boto_client(service.lower(), region)
        method = getattr(client, op_lower, None)
        if method is None:
            return {'success': False, 'error': f'boto3.client("{service}") has no method "{operation}"'}
        result = method(**(params or {}))
        result.pop('ResponseMetadata', None)
        return {
            'success': True,
            'service': service,
            'operation': operation,
            'region': _get_effective_region(region),
            'result': result,
            'message': f'Successfully executed {service}.{operation}'
        }
    except ClientError as e:
        logger.error(f"AWS API error ({service}.{operation}): {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"aws_api_write error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_ec2_all_regions(
    state_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List EC2 instances across ALL AWS regions in parallel.

    Much faster than calling list_ec2_instances per region — scans all regions
    concurrently using threads and returns a unified summary.

    Args:
        state_filter: Optional instance state to filter by (e.g. 'running', 'stopped').
                      If omitted, returns all instances.

    Returns:
        Dictionary with per-region instance counts and a flat list of all instances.
    """
    try:
        import boto3 as _boto3
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from services.credential_service import get_user_aws_credentials, _get_boto_kwargs

        user_id = get_current_user_id()
        if user_id is None:
            return {'success': False, 'error': 'Authentication required.'}

        # Resolve credentials ONCE on the main thread (requires Flask context)
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured. Please configure them in Settings.'}

        # Pre-build boto3 kwargs (resolves STS AssumeRole if needed, also on main thread)
        base_kwargs = _get_boto_kwargs(creds, 'us-east-1')

        # Fetch region list using pre-resolved credentials (no Flask context needed)
        ec2_meta = _boto3.client('ec2', **base_kwargs)
        regions = [r['RegionName'] for r in ec2_meta.describe_regions(AllRegions=False)['Regions']]

        boto_filters = []
        if state_filter:
            boto_filters = [{'Name': 'instance-state-name', 'Values': [state_filter]}]

        def _scan_region(region_name: str):
            try:
                # Build per-region kwargs using pre-resolved credentials — no Flask context needed
                region_kwargs = dict(base_kwargs)
                region_kwargs['region_name'] = region_name
                client = _boto3.client('ec2', **region_kwargs)
                resp = client.describe_instances(Filters=boto_filters)
                instances = []
                for res in resp['Reservations']:
                    for inst in res['Instances']:
                        tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                        instances.append({
                            'instance_id': inst['InstanceId'],
                            'instance_type': inst['InstanceType'],
                            'state': inst['State']['Name'],
                            'public_ip': inst.get('PublicIpAddress', 'N/A'),
                            'private_ip': inst.get('PrivateIpAddress', 'N/A'),
                            'name': tags.get('Name', ''),
                            'region': region_name,
                            'az': inst['Placement']['AvailabilityZone'],
                            'launch_time': inst['LaunchTime'].isoformat(),
                        })
                return region_name, instances, None
            except Exception as e:
                return region_name, [], str(e)

        all_instances = []
        per_region = {}
        errors = {}

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {pool.submit(_scan_region, r): r for r in regions}
            for future in as_completed(futures, timeout=25):
                region_name, instances, err = future.result()
                if err:
                    errors[region_name] = err
                else:
                    per_region[region_name] = len(instances)
                    all_instances.extend(instances)

        # Sort results by region for readability
        all_instances.sort(key=lambda x: (x['region'], x['instance_id']))

        return {
            'success': True,
            'total_instances': len(all_instances),
            'regions_scanned': len(regions),
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'empty_regions': [r for r, c in per_region.items() if c == 0],
            'instances': all_instances,
            'errors': errors if errors else None,
            'filter_applied': state_filter or 'none',
        }

    except ClientError as e:
        logger.error(f"AWS error in list_ec2_all_regions: {e}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error in list_ec2_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def _parallel_region_scan(service: str, scan_fn, creds: Dict) -> tuple:
    """
    Helper: resolve region list and run scan_fn(boto3_client, region) across all regions in parallel.
    Returns (all_items: list, per_region_count: dict, errors: dict, regions_scanned: int).
    """
    import boto3 as _boto3
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from services.credential_service import _get_boto_kwargs

    base_kwargs = _get_boto_kwargs(creds, 'us-east-1')
    meta_client = _boto3.client('ec2', **base_kwargs)
    regions = [r['RegionName'] for r in meta_client.describe_regions(AllRegions=False)['Regions']]

    def _worker(region_name):
        try:
            rk = dict(base_kwargs)
            rk['region_name'] = region_name
            client = _boto3.client(service, **rk)
            items = scan_fn(client, region_name)
            return region_name, items, None
        except Exception as e:
            return region_name, [], str(e)

    all_items, per_region, errors = [], {}, {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_worker, r): r for r in regions}
        for future in futures:
            region_name, items, err = future.result()
            if err:
                errors[region_name] = err
            else:
                per_region[region_name] = len(items)
                all_items.extend(items)

    return all_items, per_region, errors, len(regions)


def list_dynamodb_all_regions() -> Dict[str, Any]:
    """
    List DynamoDB tables across ALL AWS regions in parallel.
    Use this when the user asks about DynamoDB tables globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            names = client.list_tables().get('TableNames', [])
            items = []
            for name in names:
                try:
                    info = client.describe_table(TableName=name)['Table']
                    items.append({
                        'table_name': name,
                        'status': info.get('TableStatus'),
                        'item_count': info.get('ItemCount', 0),
                        'size_bytes': info.get('TableSizeBytes', 0),
                        'billing_mode': info.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED'),
                        'region': region,
                    })
                except Exception:
                    items.append({'table_name': name, 'status': 'unknown', 'region': region})
            return items

        items, per_region, errors, n_regions = _parallel_region_scan('dynamodb', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['table_name']))
        return {
            'success': True,
            'total_tables': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'tables': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_dynamodb_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_elasticache_all_regions() -> Dict[str, Any]:
    """
    List ElastiCache clusters across ALL AWS regions in parallel.
    Use this when the user asks about ElastiCache/Redis/Memcached globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            clusters = client.describe_cache_clusters().get('CacheClusters', [])
            return [{
                'cluster_id': c['CacheClusterId'],
                'engine': c.get('Engine'),
                'node_type': c.get('CacheNodeType'),
                'num_nodes': c.get('NumCacheNodes'),
                'status': c.get('CacheClusterStatus'),
                'region': region,
            } for c in clusters]

        items, per_region, errors, n_regions = _parallel_region_scan('elasticache', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['cluster_id']))
        return {
            'success': True,
            'total_clusters': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'clusters': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_elasticache_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_api_gateways_all_regions() -> Dict[str, Any]:
    """
    List API Gateway REST APIs across ALL AWS regions in parallel.
    Use this when the user asks about API Gateways globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            apis = client.get_rest_apis().get('items', [])
            return [{
                'api_id': a['id'],
                'name': a['name'],
                'description': a.get('description', ''),
                'endpoint_types': a.get('endpointConfiguration', {}).get('types', []),
                'created_date': a.get('createdDate').isoformat() if a.get('createdDate') else 'N/A',
                'region': region,
            } for a in apis]

        items, per_region, errors, n_regions = _parallel_region_scan('apigateway', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['name']))
        return {
            'success': True,
            'total_apis': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'apis': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_api_gateways_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_beanstalk_all_regions() -> Dict[str, Any]:
    """
    List Elastic Beanstalk environments across ALL AWS regions in parallel.
    Use this when the user asks about Beanstalk globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            envs = client.describe_environments().get('Environments', [])
            return [{
                'environment_name': e['EnvironmentName'],
                'application_name': e.get('ApplicationName', ''),
                'status': e.get('Status'),
                'health': e.get('Health'),
                'solution_stack': e.get('SolutionStackName', ''),
                'region': region,
            } for e in envs]

        items, per_region, errors, n_regions = _parallel_region_scan('elasticbeanstalk', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['environment_name']))
        return {
            'success': True,
            'total_environments': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'environments': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_beanstalk_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_lambda_all_regions() -> Dict[str, Any]:
    """
    List Lambda functions across ALL AWS regions in parallel.
    Use this when the user asks about Lambda functions globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            items = []
            paginator = client.get_paginator('list_functions')
            for page in paginator.paginate():
                for f in page.get('Functions', []):
                    items.append({
                        'function_name': f['FunctionName'],
                        'runtime': f.get('Runtime', 'N/A'),
                        'memory_size': f.get('MemorySize', 128),
                        'timeout': f.get('Timeout', 3),
                        'state': f.get('State', 'Active'),
                        'last_modified': f.get('LastModified', 'N/A'),
                        'region': region,
                    })
            return items

        items, per_region, errors, n_regions = _parallel_region_scan('lambda', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['function_name']))
        return {
            'success': True,
            'total_functions': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'functions': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_lambda_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_rds_all_regions() -> Dict[str, Any]:
    """
    List RDS instances across ALL AWS regions in parallel.
    Use this when the user asks about RDS databases globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            items = []
            paginator = client.get_paginator('describe_db_instances')
            for page in paginator.paginate():
                for db in page.get('DBInstances', []):
                    items.append({
                        'db_instance_identifier': db['DBInstanceIdentifier'],
                        'engine': db.get('Engine'),
                        'engine_version': db.get('EngineVersion'),
                        'db_instance_class': db.get('DBInstanceClass'),
                        'status': db.get('DBInstanceStatus'),
                        'multi_az': db.get('MultiAZ', False),
                        'publicly_accessible': db.get('PubliclyAccessible', False),
                        'region': region,
                    })
            return items

        items, per_region, errors, n_regions = _parallel_region_scan('rds', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['db_instance_identifier']))
        return {
            'success': True,
            'total_instances': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'instances': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_rds_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_ecs_all_regions() -> Dict[str, Any]:
    """
    List ECS clusters across ALL AWS regions in parallel.
    Use this when the user asks about ECS clusters globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            arns = client.list_clusters().get('clusterArns', [])
            if not arns:
                return []
            clusters = client.describe_clusters(clusters=arns).get('clusters', [])
            return [{
                'cluster_name': c['clusterName'],
                'status': c.get('status'),
                'running_tasks': c.get('runningTasksCount', 0),
                'active_services': c.get('activeServicesCount', 0),
                'region': region,
            } for c in clusters]

        items, per_region, errors, n_regions = _parallel_region_scan('ecs', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['cluster_name']))
        return {
            'success': True,
            'total_clusters': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'clusters': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_ecs_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_eks_all_regions() -> Dict[str, Any]:
    """
    List EKS clusters across ALL AWS regions in parallel.
    Use this when the user asks about EKS clusters globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            paginator = client.get_paginator('list_clusters')
            names = []
            for page in paginator.paginate():
                names.extend(page.get('clusters', []))
            items = []
            for name in names:
                try:
                    desc = client.describe_cluster(name=name)['cluster']
                    items.append({
                        'name': name,
                        'status': desc.get('status', ''),
                        'k8s_version': desc.get('version', ''),
                        'region': region,
                    })
                except Exception:
                    items.append({'name': name, 'status': 'unknown', 'region': region})
            return items

        items, per_region, errors, n_regions = _parallel_region_scan('eks', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['name']))
        return {
            'success': True,
            'total_clusters': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'clusters': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_eks_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_vpcs_all_regions() -> Dict[str, Any]:
    """
    List VPCs across ALL AWS regions in parallel.
    Use this when the user asks about VPCs globally or 'across all regions'.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            vpcs = client.describe_vpcs().get('Vpcs', [])
            return [{
                'vpc_id': v['VpcId'],
                'cidr_block': v['CidrBlock'],
                'state': v['State'],
                'is_default': v.get('IsDefault', False),
                'name': {t['Key']: t['Value'] for t in v.get('Tags', [])}.get('Name', 'N/A'),
                'region': region,
            } for v in vpcs]

        items, per_region, errors, n_regions = _parallel_region_scan('ec2', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['vpc_id']))
        return {
            'success': True,
            'total_vpcs': len(items),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'vpcs': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_vpcs_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def list_security_groups_all_regions() -> Dict[str, Any]:
    """
    List security groups across ALL AWS regions in parallel.
    Use this when the user asks about security groups globally or 'across all regions'.
    Excludes default security groups to reduce noise.
    """
    try:
        from services.credential_service import get_user_aws_credentials
        user_id = get_current_user_id()
        if not user_id:
            return {'success': False, 'error': 'Authentication required.'}
        creds = get_user_aws_credentials(user_id)
        if not creds:
            return {'success': False, 'error': 'AWS credentials not configured.'}

        def _scan(client, region):
            sgs = client.describe_security_groups().get('SecurityGroups', [])
            return [{
                'group_id': sg['GroupId'],
                'group_name': sg['GroupName'],
                'description': sg['Description'],
                'vpc_id': sg.get('VpcId', 'N/A'),
                'ingress_rules': len(sg.get('IpPermissions', [])),
                'egress_rules': len(sg.get('IpPermissionsEgress', [])),
                'is_default': sg['GroupName'] == 'default',
                'region': region,
            } for sg in sgs]

        items, per_region, errors, n_regions = _parallel_region_scan('ec2', _scan, creds)
        items.sort(key=lambda x: (x['region'], x['group_id']))
        non_default = [i for i in items if not i['is_default']]
        return {
            'success': True,
            'total_security_groups': len(items),
            'non_default_count': len(non_default),
            'regions_scanned': n_regions,
            'per_region_count': {r: c for r, c in sorted(per_region.items()) if c > 0},
            'security_groups': items,
            'errors': errors or None,
        }
    except Exception as e:
        logger.error(f"Error in list_security_groups_all_regions: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def get_tools() -> List[Dict[str, Any]]:
    """
    Get AWS tool definitions.

    Returns:
        List of tool definitions
    """
    return [
        # EC2 Operations
        {
            'name': 'list_ec2_all_regions',
            'description': (
                'List EC2 instances across ALL AWS regions in parallel. '
                'ONLY call this when the user explicitly asks about "all regions", "every region", or "global" EC2 inventory. '
                'Do NOT call this as a pre-flight step before creating, stopping, or modifying an instance in a specific region — '
                'use list_ec2_instances with the target region instead. '
                'Calling this unnecessarily causes long delays and server timeouts.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'state_filter': {
                        'type': 'string',
                        'description': 'Optional: filter by instance state — "running", "stopped", "terminated", etc. Omit for all states.'
                    }
                }
            },
            'handler': list_ec2_all_regions
        },
        {
            'name': 'list_dynamodb_all_regions',
            'description': 'List DynamoDB tables across ALL AWS regions in parallel. Use when user asks about DynamoDB globally or across all regions.',
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_dynamodb_all_regions,
        },
        {
            'name': 'list_elasticache_all_regions',
            'description': 'List ElastiCache (Redis/Memcached) clusters across ALL AWS regions in parallel. Use when user asks about ElastiCache globally or across all regions.',
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_elasticache_all_regions,
        },
        {
            'name': 'list_api_gateways_all_regions',
            'description': 'List API Gateway REST APIs across ALL AWS regions in parallel. Use when user asks about API Gateways globally or across all regions.',
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_api_gateways_all_regions,
        },
        {
            'name': 'list_beanstalk_all_regions',
            'description': 'List Elastic Beanstalk environments across ALL AWS regions in parallel. Use when user asks about Beanstalk globally or across all regions.',
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_beanstalk_all_regions,
        },
        {
            'name': 'list_lambda_all_regions',
            'description': (
                'List Lambda functions across ALL AWS regions in parallel. '
                'Use this instead of calling list_lambda_functions per region when the user asks '
                'about Lambda "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_lambda_all_regions,
        },
        {
            'name': 'list_rds_all_regions',
            'description': (
                'List RDS instances across ALL AWS regions in parallel. '
                'Use this instead of calling list_rds_instances per region when the user asks '
                'about RDS "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_rds_all_regions,
        },
        {
            'name': 'list_ecs_all_regions',
            'description': (
                'List ECS clusters across ALL AWS regions in parallel. '
                'Use this instead of calling list_ecs_clusters per region when the user asks '
                'about ECS "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_ecs_all_regions,
        },
        {
            'name': 'list_eks_all_regions',
            'description': (
                'List EKS clusters across ALL AWS regions in parallel. '
                'Use this instead of calling list_eks_clusters per region when the user asks '
                'about EKS "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_eks_all_regions,
        },
        {
            'name': 'list_vpcs_all_regions',
            'description': (
                'List VPCs across ALL AWS regions in parallel. '
                'Use this instead of calling list_vpcs per region when the user asks '
                'about VPCs "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_vpcs_all_regions,
        },
        {
            'name': 'list_security_groups_all_regions',
            'description': (
                'List security groups across ALL AWS regions in parallel. '
                'Use this instead of calling list_security_groups per region when the user asks '
                'about security groups "across all regions", "globally", or "everywhere". Fast — concurrent scan.'
            ),
            'input_schema': {'type': 'object', 'properties': {}},
            'handler': list_security_groups_all_regions,
        },
        {
            'name': 'get_ec2_instances',
            'description': 'List EC2 instances with optional filtering by tags, state, etc.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'filters': {
                        'type': 'object',
                        'description': 'Filters as key-value pairs (e.g., {"instance-state-name": "running"})'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (e.g., us-east-1)'
                    }
                }
            },
            'handler': get_ec2_instances
        },
        {
            'name': 'create_ec2_instance',
            'description': (
                'Create one or more EC2 instances with specified configuration. '
                'IMPORTANT: By default, this creates exactly ONE instance. '
                'Only specify count parameter if multiple instances are explicitly requested. '
                'If user asks for "an instance" or "one instance", use count=1 (the default).'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'ami_id': {
                        'type': 'string',
                        'description': 'AMI ID to use (e.g., ami-0c55b159cbfafe1f0 for Amazon Linux 2)'
                    },
                    'instance_type': {
                        'type': 'string',
                        'description': 'Instance type (e.g., t2.micro, t3.small, m5.large)'
                    },
                    'count': {
                        'type': 'integer',
                        'description': 'Number of instances to create (default: 1, max: 10). ONLY specify if explicitly asked for multiple instances.',
                        'default': 1,
                        'minimum': 1,
                        'maximum': 10
                    },
                    'key_name': {
                        'type': 'string',
                        'description': 'SSH key pair name for instance access'
                    },
                    'security_group_ids': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of security group IDs'
                    },
                    'subnet_id': {
                        'type': 'string',
                        'description': 'Subnet ID for VPC placement'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Tags to apply (e.g., {"Name": "web-server", "Environment": "prod"})'
                    },
                    'user_data': {
                        'type': 'string',
                        'description': 'User data script to run on launch'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['ami_id', 'instance_type']
            },
            'handler': create_ec2_instance
        },
        {
            'name': 'delete_ec2_instance',
            'description': 'Delete (terminate) an EC2 instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {
                        'type': 'string',
                        'description': 'EC2 instance ID to terminate'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['instance_id']
            },
            'handler': delete_ec2_instance
        },
        {
            'name': 'manage_ec2_instance',
            'description': 'Manage EC2 instance - start, stop, reboot, or terminate',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {
                        'type': 'string',
                        'description': 'EC2 instance ID'
                    },
                    'action': {
                        'type': 'string',
                        'enum': ['start', 'stop', 'reboot', 'terminate'],
                        'description': 'Action to perform'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['instance_id', 'action']
            },
            'handler': manage_ec2_instance
        },
        {
            'name': 'create_ec2_keypair',
            'description': (
                'Create a new EC2 key pair for SSH access to instances. '
                'The private key will be automatically downloaded to your browser. '
                'IMPORTANT: Save the private key securely - this is the only time it will be available. '
                'Use this tool when user wants to create a new SSH keypair for EC2 access.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'key_name': {
                        'type': 'string',
                        'description': 'Name for the key pair (must be unique within the region)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (e.g., us-east-1, us-west-2)'
                    }
                },
                'required': ['key_name']
            },
            'handler': create_ec2_keypair
        },
        {
            'name': 'delete_ec2_keypair',
            'description': 'Delete an EC2 key pair by name',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'key_name': {'type': 'string', 'description': 'Name of the key pair to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['key_name']
            },
            'handler': delete_ec2_keypair
        },
        # S3 Operations
        {
            'name': 'list_s3_buckets',
            'description': 'List all S3 buckets in the account',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_s3_buckets
        },
        {
            'name': 'create_s3_bucket',
            'description': 'Create a new S3 bucket with security best practices',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Name of the bucket (must be globally unique, lowercase, no spaces)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (e.g., us-east-1, us-west-2)'
                    },
                    'versioning_enabled': {
                        'type': 'boolean',
                        'description': 'Enable versioning for the bucket'
                    },
                    'encryption_enabled': {
                        'type': 'boolean',
                        'description': 'Enable server-side encryption (default: true)'
                    },
                    'public_access_block': {
                        'type': 'boolean',
                        'description': 'Block all public access (default: true, recommended)'
                    }
                },
                'required': ['bucket_name']
            },
            'handler': create_s3_bucket
        },
        {
            'name': 'delete_s3_bucket',
            'description': 'Delete an S3 bucket (optionally with all contents)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Name of the bucket to delete'
                    },
                    'force': {
                        'type': 'boolean',
                        'description': 'If true, delete all objects in bucket first'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_bucket
        },
        {
            'name': 'create_rds_instance',
            'description': 'Create a new RDS database instance (MySQL, PostgreSQL, MariaDB, Oracle, SQL Server)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {
                        'type': 'string',
                        'description': 'Unique identifier for the database instance'
                    },
                    'db_instance_class': {
                        'type': 'string',
                        'description': 'Instance class (e.g., db.t3.micro, db.r5.large)'
                    },
                    'engine': {
                        'type': 'string',
                        'description': 'Database engine (mysql, postgres, mariadb, oracle-ee, sqlserver-ex)'
                    },
                    'master_username': {
                        'type': 'string',
                        'description': 'Master username for database'
                    },
                    'master_password': {
                        'type': 'string',
                        'description': 'Master password (must meet complexity requirements)'
                    },
                    'allocated_storage': {
                        'type': 'integer',
                        'description': 'Storage size in GB (default: 20)',
                        'default': 20
                    },
                    'db_name': {
                        'type': 'string',
                        'description': 'Initial database name (optional)'
                    },
                    'engine_version': {
                        'type': 'string',
                        'description': 'Specific engine version (optional)'
                    },
                    'multi_az': {
                        'type': 'boolean',
                        'description': 'Enable Multi-AZ deployment for high availability (default: false)',
                        'default': False
                    },
                    'publicly_accessible': {
                        'type': 'boolean',
                        'description': 'Make database publicly accessible (default: false)',
                        'default': False
                    },
                    'backup_retention_period': {
                        'type': 'integer',
                        'description': 'Days to retain backups (0-35, default: 7)',
                        'default': 7
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['db_instance_identifier', 'db_instance_class', 'engine', 'master_username', 'master_password']
            },
            'handler': create_rds_instance
        },
        {
            'name': 'create_security_group',
            'description': 'Create a new security group with optional ingress rules',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {
                        'type': 'string',
                        'description': 'Name for the security group'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Description of the security group purpose'
                    },
                    'vpc_id': {
                        'type': 'string',
                        'description': 'VPC ID (optional, uses default VPC if not specified)'
                    },
                    'ingress_rules': {
                        'type': 'array',
                        'description': 'List of ingress rules to add',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'protocol': {'type': 'string', 'description': 'Protocol (tcp, udp, icmp)', 'default': 'tcp'},
                                'port': {'type': 'integer', 'description': 'Port number', 'default': 80},
                                'cidr': {'type': 'string', 'description': 'CIDR block (default: 0.0.0.0/0)', 'default': '0.0.0.0/0'}
                            }
                        }
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['group_name', 'description']
            },
            'handler': create_security_group
        },
        {
            'name': 'create_lambda_function',
            'description': 'Create a new Lambda function from a ZIP file',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'function_name': {
                        'type': 'string',
                        'description': 'Name for the Lambda function'
                    },
                    'runtime': {
                        'type': 'string',
                        'description': 'Runtime environment (python3.9, python3.11, nodejs18.x, nodejs20.x, java17, dotnet6, go1.x, ruby3.2)'
                    },
                    'role_arn': {
                        'type': 'string',
                        'description': 'ARN of IAM role for Lambda execution'
                    },
                    'handler': {
                        'type': 'string',
                        'description': 'Function handler (e.g., index.handler, lambda_function.lambda_handler)'
                    },
                    'zip_file_path': {
                        'type': 'string',
                        'description': 'Path to ZIP file containing function code'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Function description (optional)'
                    },
                    'timeout': {
                        'type': 'integer',
                        'description': 'Function timeout in seconds (1-900, default: 3)',
                        'default': 3
                    },
                    'memory_size': {
                        'type': 'integer',
                        'description': 'Memory allocation in MB (128-10240, default: 128)',
                        'default': 128
                    },
                    'environment_variables': {
                        'type': 'object',
                        'description': 'Environment variables as key-value pairs'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['function_name', 'runtime', 'role_arn', 'handler', 'zip_file_path']
            },
            'handler': create_lambda_function
        },
        {
            'name': 'get_s3_bucket_info',
            'description': 'Get detailed information about an S3 bucket including size and object count',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Name of the S3 bucket'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['bucket_name']
            },
            'handler': get_s3_bucket_info
        },
        {
            'name': 'put_s3_lifecycle_policy',
            'description': 'Set lifecycle policies on an S3 bucket to automatically transition objects to cheaper storage classes or delete them after a specified number of days',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Name of the S3 bucket'
                    },
                    'rules': {
                        'type': 'array',
                        'description': 'List of lifecycle rules. Each rule: {id, status, prefix, transitions:[{days,storage_class}], expiration_days, noncurrent_version_expiration_days}',
                        'items': {'type': 'object'}
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['bucket_name', 'rules']
            },
            'handler': put_s3_lifecycle_policy
        },
        {
            'name': 'put_s3_replication',
            'description': 'Configure cross-region replication on an S3 bucket to automatically copy objects to a bucket in another region for backup or compliance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Source bucket name'
                    },
                    'destination_bucket': {
                        'type': 'string',
                        'description': 'Destination bucket name (must already exist with versioning enabled)'
                    },
                    'destination_region': {
                        'type': 'string',
                        'description': 'AWS region of the destination bucket'
                    },
                    'iam_role_arn': {
                        'type': 'string',
                        'description': 'IAM role ARN that S3 will assume to replicate objects'
                    },
                    'prefix': {
                        'type': 'string',
                        'description': 'Optional key prefix to replicate (omit to replicate all objects)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region of the source bucket'
                    }
                },
                'required': ['bucket_name', 'destination_bucket', 'destination_region', 'iam_role_arn']
            },
            'handler': put_s3_replication
        },
        {
            'name': 'put_s3_bucket_policy',
            'description': 'Apply an IAM bucket policy to an S3 bucket for fine-grained access control (e.g. restrict to specific IAM roles, enforce HTTPS, allow cross-account access)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {
                        'type': 'string',
                        'description': 'Name of the S3 bucket'
                    },
                    'policy': {
                        'type': 'object',
                        'description': 'IAM policy document as JSON with Version and Statement fields'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['bucket_name', 'policy']
            },
            'handler': put_s3_bucket_policy
        },
        # S3 Extended Operations
        {
            'name': 'list_s3_objects',
            'description': 'List objects in an S3 bucket, optionally filtered by prefix or delimiter',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'prefix': {'type': 'string', 'description': 'Filter by key prefix, e.g. "logs/2024/"'},
                    'delimiter': {'type': 'string', 'description': 'Group keys by delimiter, e.g. "/"'},
                    'max_keys': {'type': 'integer', 'description': 'Max objects to return (default 100, max 1000)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': list_s3_objects
        },
        {
            'name': 'upload_s3_object',
            'description': 'Upload text or JSON content as an S3 object',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Destination bucket'},
                    'key': {'type': 'string', 'description': 'Object key (path), e.g. "configs/app.json"'},
                    'content': {'type': 'string', 'description': 'Text or JSON content to upload'},
                    'content_type': {'type': 'string', 'description': 'MIME type, e.g. text/plain, application/json (default text/plain)'},
                    'storage_class': {'type': 'string', 'description': 'STANDARD, STANDARD_IA, GLACIER, INTELLIGENT_TIERING (default STANDARD)'},
                    'metadata': {'type': 'object', 'description': 'Custom metadata key-value pairs'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'key', 'content']
            },
            'handler': upload_s3_object
        },
        {
            'name': 'download_s3_object',
            'description': 'Download and return the text content of an S3 object (up to 100KB). Returns a presigned URL suggestion for binary files.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Source bucket'},
                    'key': {'type': 'string', 'description': 'Object key'},
                    'max_bytes': {'type': 'integer', 'description': 'Max bytes to read (default 102400 = 100KB)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'key']
            },
            'handler': download_s3_object
        },
        {
            'name': 'delete_s3_object',
            'description': 'Delete a single object from an S3 bucket (optionally a specific version)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'key': {'type': 'string', 'description': 'Object key to delete'},
                    'version_id': {'type': 'string', 'description': 'Specific version ID to delete (for versioned buckets)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'key']
            },
            'handler': delete_s3_object
        },
        {
            'name': 'delete_s3_objects_batch',
            'description': 'Delete multiple S3 objects in a single request (up to 1000 at once)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'keys': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of object keys to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'keys']
            },
            'handler': delete_s3_objects_batch
        },
        {
            'name': 'copy_s3_object',
            'description': 'Copy an S3 object within or across buckets without downloading it',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'source_bucket': {'type': 'string', 'description': 'Source bucket name'},
                    'source_key': {'type': 'string', 'description': 'Source object key'},
                    'dest_bucket': {'type': 'string', 'description': 'Destination bucket name'},
                    'dest_key': {'type': 'string', 'description': 'Destination object key'},
                    'storage_class': {'type': 'string', 'description': 'Storage class for the copy (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['source_bucket', 'source_key', 'dest_bucket', 'dest_key']
            },
            'handler': copy_s3_object
        },
        {
            'name': 'get_s3_object_metadata',
            'description': 'Get metadata for an S3 object (ContentType, ETag, size, storage class, encryption) without downloading it',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'key': {'type': 'string', 'description': 'Object key'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'key']
            },
            'handler': get_s3_object_metadata
        },
        {
            'name': 'generate_s3_presigned_url',
            'description': 'Generate a time-limited pre-signed URL for secure access to an S3 object without requiring AWS credentials',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'key': {'type': 'string', 'description': 'Object key'},
                    'operation': {'type': 'string', 'description': 'get_object (download) or put_object (upload) — default: get_object'},
                    'expires_in': {'type': 'integer', 'description': 'Expiry in seconds (default 3600 = 1 hour, max 604800 = 7 days)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'key']
            },
            'handler': generate_s3_presigned_url
        },
        {
            'name': 'get_s3_bucket_policy',
            'description': 'Read the current IAM bucket policy on an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': get_s3_bucket_policy
        },
        {
            'name': 'delete_s3_bucket_policy',
            'description': 'Remove the bucket policy from an S3 bucket (reverts to default IAM-only access)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_bucket_policy
        },
        {
            'name': 'set_s3_public_access_block',
            'description': 'Enable or configure public access block settings on an S3 bucket. Recommended: enable all 4 settings to prevent public exposure.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'block_public_acls': {'type': 'boolean', 'description': 'Block new public ACLs (default true)'},
                    'ignore_public_acls': {'type': 'boolean', 'description': 'Ignore existing public ACLs (default true)'},
                    'block_public_policy': {'type': 'boolean', 'description': 'Block public bucket policies (default true)'},
                    'restrict_public_buckets': {'type': 'boolean', 'description': 'Restrict public access via bucket policy (default true)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': set_s3_public_access_block
        },
        {
            'name': 'set_s3_versioning',
            'description': 'Enable or suspend versioning on an S3 bucket. Versioning keeps all versions of objects for recovery and audit.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'status': {'type': 'string', 'enum': ['Enabled', 'Suspended'], 'description': 'Versioning status (default Enabled)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': set_s3_versioning
        },
        {
            'name': 'list_s3_object_versions',
            'description': 'List all versions and delete markers for objects in a versioned S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'prefix': {'type': 'string', 'description': 'Filter by key prefix'},
                    'max_keys': {'type': 'integer', 'description': 'Max versions to return (default 100)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': list_s3_object_versions
        },
        {
            'name': 'set_s3_default_encryption',
            'description': 'Enable default server-side encryption on an S3 bucket. Use SSE-S3 (AES256) for AWS-managed keys or SSE-KMS for customer-managed keys.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'sse_algorithm': {'type': 'string', 'enum': ['AES256', 'aws:kms'], 'description': 'Encryption algorithm: AES256 (SSE-S3) or aws:kms (SSE-KMS). Default: AES256'},
                    'kms_key_id': {'type': 'string', 'description': 'KMS key ARN or ID (only for aws:kms algorithm)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': set_s3_default_encryption
        },
        {
            'name': 'set_s3_website',
            'description': 'Enable static website hosting on an S3 bucket to serve HTML files publicly',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'index_document': {'type': 'string', 'description': 'Index document filename (default index.html)'},
                    'error_document': {'type': 'string', 'description': 'Error document filename (default error.html)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': set_s3_website
        },
        {
            'name': 'delete_s3_website',
            'description': 'Disable static website hosting on an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_website
        },
        {
            'name': 'set_s3_cors',
            'description': 'Configure CORS rules on an S3 bucket to allow cross-origin web requests (e.g. from a React app)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'allowed_origins': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Allowed origins, e.g. ["https://example.com"] or ["*"]'},
                    'allowed_methods': {'type': 'array', 'items': {'type': 'string'}, 'description': 'HTTP methods: GET, HEAD, PUT, POST, DELETE (default [GET, HEAD])'},
                    'allowed_headers': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Allowed request headers, e.g. ["Content-Type", "Authorization"]'},
                    'max_age_seconds': {'type': 'integer', 'description': 'Browser cache duration for preflight responses (default 3600)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'allowed_origins']
            },
            'handler': set_s3_cors
        },
        {
            'name': 'set_s3_logging',
            'description': 'Enable server access logging on an S3 bucket, writing request logs to a target bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Source bucket to enable logging on'},
                    'target_bucket': {'type': 'string', 'description': 'Destination bucket to receive log files'},
                    'target_prefix': {'type': 'string', 'description': 'Key prefix for log files (default: source bucket name + "/")'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'target_bucket']
            },
            'handler': set_s3_logging
        },
        {
            'name': 'tag_s3_bucket',
            'description': 'Apply metadata tags to an S3 bucket (replaces all existing tags)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'tags': {'type': 'object', 'description': 'Tag key-value pairs, e.g. {"Environment":"production","Team":"platform"}'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name', 'tags']
            },
            'handler': tag_s3_bucket
        },
        {
            'name': 'get_s3_bucket_tags',
            'description': 'Read all tags on an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': get_s3_bucket_tags
        },
        {
            'name': 'delete_s3_bucket_tags',
            'description': 'Remove all tags from an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_bucket_tags
        },
        {
            'name': 'set_s3_notification',
            'description': 'Configure event notifications on an S3 bucket to trigger Lambda, SQS, or SNS on object events (create, delete, restore, etc.)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'lambda_arn': {'type': 'string', 'description': 'Lambda function ARN to invoke on events'},
                    'sqs_arn': {'type': 'string', 'description': 'SQS queue ARN to send events to'},
                    'sns_arn': {'type': 'string', 'description': 'SNS topic ARN to publish events to'},
                    'events': {'type': 'array', 'items': {'type': 'string'}, 'description': 'S3 event types, e.g. ["s3:ObjectCreated:*", "s3:ObjectRemoved:*"] (default: ObjectCreated:*)'},
                    'prefix_filter': {'type': 'string', 'description': 'Only trigger for keys with this prefix'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': set_s3_notification
        },
        {
            'name': 'get_s3_lifecycle_policy',
            'description': 'Read the current lifecycle configuration (rules) on an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': get_s3_lifecycle_policy
        },
        {
            'name': 'delete_s3_lifecycle_policy',
            'description': 'Remove all lifecycle rules from an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_lifecycle_policy
        },
        {
            'name': 'get_s3_replication',
            'description': 'Read the current replication configuration on an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': get_s3_replication
        },
        {
            'name': 'delete_s3_replication',
            'description': 'Remove the replication configuration from an S3 bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_s3_replication
        },
        {
            'name': 'get_eks_clusters',
            'description': 'List EKS (Kubernetes) clusters in AWS',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': get_eks_clusters
        },
        {
            'name': 'list_eks_clusters',
            'description': 'List all EKS Kubernetes clusters with their node group details including instance types, scaling config, and AMI type.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_eks_clusters
        },
        {
            'name': 'get_cloudwatch_logs',
            'description': 'Retrieve CloudWatch logs from a log group',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'log_group': {
                        'type': 'string',
                        'description': 'CloudWatch log group name'
                    },
                    'log_stream': {
                        'type': 'string',
                        'description': 'Specific log stream (optional)'
                    },
                    'hours': {
                        'type': 'integer',
                        'description': 'Number of hours to look back (default: 1)',
                        'default': 1
                    },
                    'filter_pattern': {
                        'type': 'string',
                        'description': 'Filter pattern for log events'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['log_group']
            },
            'handler': get_cloudwatch_logs
        },
        {
            'name': 'list_iam_users',
            'description': 'List all IAM users in the account',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': list_iam_users
        },
        {
            'name': 'list_iam_roles',
            'description': 'List all IAM roles in the account',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': list_iam_roles
        },
        # VPC Operations
        {
            'name': 'list_vpcs',
            'description': 'List all VPCs (Virtual Private Clouds) in the account with CIDR blocks and tags',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_vpcs
        },
        {
            'name': 'list_subnets',
            'description': 'List subnets, optionally filtered by VPC ID',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {
                        'type': 'string',
                        'description': 'VPC ID to filter by (optional)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_subnets
        },
        {
            'name': 'list_security_groups',
            'description': 'List security groups, optionally filtered by VPC ID',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {
                        'type': 'string',
                        'description': 'VPC ID to filter by (optional)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_security_groups
        },
        # DynamoDB Operations
        {
            'name': 'list_dynamodb_tables',
            'description': 'List all DynamoDB tables with status, item count, and billing mode',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_dynamodb_tables
        },
        # ElastiCache Operations
        {
            'name': 'list_elasticache_clusters',
            'description': 'List ElastiCache clusters (Redis and Memcached) with engine info and status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_elasticache_clusters
        },
        # ECS Operations
        {
            'name': 'list_ecs_clusters',
            'description': 'List ECS (Elastic Container Service) clusters with task and service counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_ecs_clusters
        },
        {
            'name': 'list_ecs_services',
            'description': 'List ECS services within a specific cluster',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster': {
                        'type': 'string',
                        'description': 'ECS cluster name or ARN'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['cluster']
            },
            'handler': list_ecs_services
        },
        # Elastic Beanstalk Operations
        {
            'name': 'list_beanstalk_applications',
            'description': 'List Elastic Beanstalk applications',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_beanstalk_applications
        },
        {
            'name': 'list_beanstalk_environments',
            'description': 'List Elastic Beanstalk environments with health status and URLs',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'application_name': {
                        'type': 'string',
                        'description': 'Filter by application name (optional)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_beanstalk_environments
        },
        # CloudFront Operations
        {
            'name': 'list_cloudfront_distributions',
            'description': 'List CloudFront CDN distributions with domain names and status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (CloudFront is global)'
                    }
                }
            },
            'handler': list_cloudfront_distributions
        },
        # Route 53 Operations
        {
            'name': 'list_route53_zones',
            'description': 'List Route 53 DNS hosted zones (both public and private)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (Route 53 is global)'
                    }
                }
            },
            'handler': list_route53_zones
        },
        # API Gateway Operations
        {
            'name': 'list_api_gateways',
            'description': 'List API Gateway REST APIs',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_api_gateways
        },
        {
            'name': 'list_api_gateway_v2',
            'description': 'List API Gateway V2 APIs (HTTP and WebSocket)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_api_gateway_v2
        },
        # Lambda Operations
        {
            'name': 'list_lambda_functions',
            'description': 'List Lambda functions with runtime, memory, and timeout information',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_lambda_functions
        },
        # RDS Operations
        {
            'name': 'list_rds_instances',
            'description': 'List RDS database instances with engine, status, and endpoint information',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_rds_instances
        },
        # SNS Operations
        {
            'name': 'list_sns_topics',
            'description': 'List SNS (Simple Notification Service) topics with subscription counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_sns_topics
        },
        # SQS Operations
        {
            'name': 'list_sqs_queues',
            'description': 'List SQS (Simple Queue Service) queues with message counts and configuration',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_sqs_queues
        },
        # ECR Operations
        {
            'name': 'list_ecr_repositories',
            'description': 'List ECR (Elastic Container Registry) repositories with image counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_ecr_repositories
        },
        # Secrets Manager Operations
        {
            'name': 'list_secrets_manager_secrets',
            'description': 'List Secrets Manager secrets with rotation status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_secrets_manager_secrets
        },
        # Load Balancer Operations
        {
            'name': 'list_load_balancers',
            'description': 'List all load balancers (Application, Network, and Classic Load Balancers)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_load_balancers
        },
        # EFS Operations
        {
            'name': 'list_efs_file_systems',
            'description': 'List EFS (Elastic File System) file systems with size and mount targets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_efs_file_systems
        },
        # EventBridge Operations
        {
            'name': 'list_eventbridge_rules',
            'description': 'List EventBridge rules with schedules and targets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_eventbridge_rules
        },
        {
            'name': 'list_eventbridge_event_buses',
            'description': 'List EventBridge event buses',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_eventbridge_event_buses
        },
        # CloudFormation Operations
        {
            'name': 'list_cloudformation_stacks',
            'description': 'List CloudFormation stacks with status and drift information',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_cloudformation_stacks
        },
        # Systems Manager Operations
        {
            'name': 'list_ssm_parameters',
            'description': 'List Systems Manager (SSM) Parameter Store parameters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_ssm_parameters
        },
        {
            'name': 'list_ssm_managed_instances',
            'description': 'List Systems Manager managed instances with agent status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_ssm_managed_instances
        },
        # Auto Scaling Operations
        {
            'name': 'list_autoscaling_groups',
            'description': 'List Auto Scaling groups with capacity and instance counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_autoscaling_groups
        },
        # Step Functions Operations
        {
            'name': 'list_step_functions',
            'description': 'List Step Functions state machines with execution counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_step_functions
        },
        # Kinesis Operations
        {
            'name': 'list_kinesis_streams',
            'description': 'List Kinesis data streams with shard counts and retention',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_kinesis_streams
        },
        # ACM Operations
        {
            'name': 'list_acm_certificates',
            'description': 'List ACM SSL/TLS certificates with expiration and renewal status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_acm_certificates
        },
        # WAF Operations
        {
            'name': 'list_waf_web_acls',
            'description': 'List WAF Web ACLs (both regional and CloudFront/global)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_waf_web_acls
        },
        # Backup Operations
        {
            'name': 'list_backup_plans',
            'description': 'List AWS Backup plans with rule counts',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_backup_plans
        },
        # EBS Volume Operations
        {
            'name': 'list_ebs_volumes',
            'description': 'List EBS volumes with size, type, encryption, and attachment info',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_ebs_volumes
        },
        # Elastic IP Operations
        {
            'name': 'list_elastic_ips',
            'description': 'List Elastic IP addresses with association and allocation info',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_elastic_ips
        },
        {
            'name': 'associate_elastic_ip',
            'description': 'Associate an existing Elastic IP (by allocation ID) with an EC2 instance or network interface',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'allocation_id': {'type': 'string', 'description': 'Elastic IP allocation ID (eipalloc-xxxx)'},
                    'instance_id': {'type': 'string', 'description': 'EC2 instance ID to associate with'},
                    'network_interface_id': {'type': 'string', 'description': 'ENI ID (alternative to instance_id)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['allocation_id']
            },
            'handler': associate_elastic_ip
        },
        {
            'name': 'disassociate_elastic_ip',
            'description': 'Disassociate an Elastic IP from an instance or network interface (does not release it)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'association_id': {'type': 'string', 'description': 'Elastic IP association ID (eipassoc-xxxx)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['association_id']
            },
            'handler': disassociate_elastic_ip
        },
        # NAT Gateway Operations
        {
            'name': 'list_nat_gateways',
            'description': 'List NAT Gateways with state, VPC, subnet, and IP information',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_nat_gateways
        },
        # Redshift Operations
        {
            'name': 'list_redshift_clusters',
            'description': 'List Redshift data warehouse clusters with node types and status',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_redshift_clusters
        },
        # Athena Operations
        {
            'name': 'list_athena_workgroups',
            'description': 'List Athena workgroups for SQL queries on S3',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_athena_workgroups
        },
        # Glue Operations
        {
            'name': 'list_glue_jobs',
            'description': 'List Glue ETL jobs with execution details',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_glue_jobs
        },
        {
            'name': 'list_glue_crawlers',
            'description': 'List Glue crawlers for data catalog discovery',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_glue_crawlers
        },
        # SageMaker Operations
        {
            'name': 'list_sagemaker_endpoints',
            'description': 'List SageMaker ML model endpoints',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_sagemaker_endpoints
        },
        # MSK Operations
        {
            'name': 'list_msk_clusters',
            'description': 'List MSK (Managed Streaming for Kafka) clusters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_msk_clusters
        },
        # OpenSearch Operations
        {
            'name': 'list_opensearch_domains',
            'description': 'List OpenSearch (Elasticsearch) search and analytics domains',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_opensearch_domains
        },
        # Neptune Operations
        {
            'name': 'list_neptune_clusters',
            'description': 'List Neptune graph database clusters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_neptune_clusters
        },
        # DocumentDB Operations
        {
            'name': 'list_documentdb_clusters',
            'description': 'List DocumentDB (MongoDB-compatible) clusters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_documentdb_clusters
        },
        # AppSync Operations
        {
            'name': 'list_appsync_apis',
            'description': 'List AppSync GraphQL APIs',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_appsync_apis
        },
        # Amazon Bedrock Operations (Generative AI)
        {
            'name': 'list_bedrock_foundation_models',
            'description': 'List Amazon Bedrock foundation models (Claude, Titan, Llama, etc.)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_foundation_models
        },
        {
            'name': 'list_bedrock_custom_models',
            'description': 'List Amazon Bedrock custom models (fine-tuned models)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_custom_models
        },
        {
            'name': 'list_bedrock_model_customization_jobs',
            'description': 'List Amazon Bedrock model customization (fine-tuning) jobs',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_model_customization_jobs
        },
        {
            'name': 'list_bedrock_knowledge_bases',
            'description': 'List Amazon Bedrock knowledge bases for RAG (Retrieval Augmented Generation)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_knowledge_bases
        },
        {
            'name': 'list_bedrock_agents',
            'description': 'List Amazon Bedrock agents (AI agents that can use tools and APIs)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_agents
        },
        {
            'name': 'list_bedrock_provisioned_model_throughputs',
            'description': 'List Amazon Bedrock provisioned model throughput configurations',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                }
            },
            'handler': list_bedrock_provisioned_model_throughputs
        },
        # Comprehensive Resource Inventory
        {
            'name': 'get_aws_resource_inventory',
            'description': (
                'Get comprehensive inventory of AWS resources across ALL 47 supported services. '
                'This is the BEST tool for answering questions like "list all my AWS resources", '
                '"show me my AWS environment", or "audit my AWS infrastructure". '
                'Scans: Compute (EC2, Lambda, ECS, EKS, Beanstalk, Auto Scaling), '
                'Storage (S3, EBS, EFS), Databases (RDS, DynamoDB, ElastiCache, Redshift, Neptune, DocumentDB), '
                'Networking (VPC, CloudFront, Route 53, Load Balancers, NAT Gateways, Elastic IPs), '
                'Messaging (SNS, SQS, Kinesis, MSK, EventBridge), Containers (ECR), '
                'Security (Secrets Manager, ACM, WAF, IAM), Infrastructure (CloudFormation, Step Functions), '
                'Analytics (Athena, Glue, OpenSearch), ML (SageMaker), APIs (API Gateway, AppSync), '
                'Management (SSM, Backup, CloudTrail, Config), Generative AI (Bedrock).'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'services': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': (
                            'List of services to scan (optional). Options: ec2, s3, rds, dynamodb, '
                            'lambda, eks, ecs, elasticache, beanstalk, vpc, cloudfront, route53, '
                            'apigateway, iam, sns, sqs, ecr, secrets, elb, efs, eventbridge, '
                            'cloudformation, ssm, autoscaling, stepfunctions, kinesis, acm, waf, '
                            'backup, ebs, elasticip, natgateway, redshift, athena, glue, sagemaker, '
                            'msk, opensearch, neptune, documentdb, appsync, bedrock. If not specified, scans all 42 services.'
                        )
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region (if not specified, uses default region)'
                    }
                }
            },
            'handler': get_aws_resource_inventory
        },
        # Spot Instance Operations
        {
            'name': 'create_spot_instance',
            'description': (
                'Create EC2 spot instance(s) for cost-effective compute. '
                'Spot instances can save up to 90% compared to on-demand pricing. '
                'Use when user asks for spot instances, cheap instances, or cost-effective compute.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'ami_id': {
                        'type': 'string',
                        'description': 'AMI ID to use (e.g., ami-0c55b159cbfafe1f0)'
                    },
                    'instance_type': {
                        'type': 'string',
                        'description': 'Instance type (e.g., t3.medium, m5.large)'
                    },
                    'spot_price': {
                        'type': 'string',
                        'description': 'Maximum hourly price in USD (e.g., "0.05"). If not set, uses on-demand price as max.'
                    },
                    'spot_type': {
                        'type': 'string',
                        'enum': ['one-time', 'persistent'],
                        'description': 'Spot request type (default: one-time)',
                        'default': 'one-time'
                    },
                    'key_name': {
                        'type': 'string',
                        'description': 'SSH key pair name'
                    },
                    'security_group_ids': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of security group IDs'
                    },
                    'subnet_id': {
                        'type': 'string',
                        'description': 'Subnet ID for VPC placement'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Tags to apply (e.g., {"Name": "web-server"})'
                    },
                    'user_data': {
                        'type': 'string',
                        'description': 'User data script to run on launch'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    },
                    'count': {
                        'type': 'integer',
                        'description': 'Number of instances (1-10, default: 1)',
                        'default': 1,
                        'minimum': 1,
                        'maximum': 10
                    }
                },
                'required': ['ami_id', 'instance_type']
            },
            'handler': create_spot_instance
        },
        # Security Group Ingress
        {
            'name': 'authorize_security_group_ingress',
            'description': (
                'Add an ingress rule to an existing security group. '
                'Supports both CIDR-based rules (e.g., 10.0.0.0/16) and source-security-group-based rules. '
                'Use source_security_group_id to allow traffic from another security group instead of opening to a CIDR. '
                'This is the secure way to allow traffic from a load balancer or bastion host.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {
                        'type': 'string',
                        'description': 'Security group ID to add the rule to'
                    },
                    'protocol': {
                        'type': 'string',
                        'description': 'Protocol (tcp, udp, icmp, -1 for all)',
                        'default': 'tcp'
                    },
                    'from_port': {
                        'type': 'integer',
                        'description': 'Start of port range'
                    },
                    'to_port': {
                        'type': 'integer',
                        'description': 'End of port range (defaults to from_port for single port)'
                    },
                    'cidr': {
                        'type': 'string',
                        'description': 'CIDR block (e.g., "10.0.0.0/16", "0.0.0.0/0"). Mutually exclusive with source_security_group_id.'
                    },
                    'source_security_group_id': {
                        'type': 'string',
                        'description': 'Source security group ID to allow traffic from. Use this for SG-to-SG rules (e.g., allow ALB SG to reach instance SG).'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Rule description (e.g., "Allow HTTP from ALB")'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['group_id', 'protocol', 'from_port']
            },
            'handler': authorize_security_group_ingress
        },
        # Load Balancer Management
        {
            'name': 'create_load_balancer',
            'description': (
                'Create an Application Load Balancer (ALB) or Network Load Balancer (NLB). '
                'Requires at least 2 subnets in different availability zones. '
                'For ALB, specify security groups. For internal services, set scheme to "internal".'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'Load balancer name'
                    },
                    'subnets': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of subnet IDs (minimum 2 for ALB, in different AZs)'
                    },
                    'security_groups': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'List of security group IDs (ALB only)'
                    },
                    'scheme': {
                        'type': 'string',
                        'enum': ['internet-facing', 'internal'],
                        'description': 'Load balancer scheme (default: internet-facing)',
                        'default': 'internet-facing'
                    },
                    'lb_type': {
                        'type': 'string',
                        'enum': ['application', 'network'],
                        'description': 'Load balancer type (default: application)',
                        'default': 'application'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Tags to apply'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['name', 'subnets']
            },
            'handler': create_load_balancer
        },
        {
            'name': 'create_target_group',
            'description': (
                'Create a target group for a load balancer. '
                'Target groups route requests to registered targets (instances, IPs, or Lambda functions). '
                'Configure health checks to monitor target availability.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {
                        'type': 'string',
                        'description': 'Target group name'
                    },
                    'protocol': {
                        'type': 'string',
                        'enum': ['HTTP', 'HTTPS', 'TCP', 'TLS', 'UDP', 'TCP_UDP'],
                        'description': 'Protocol (default: HTTP)',
                        'default': 'HTTP'
                    },
                    'port': {
                        'type': 'integer',
                        'description': 'Port number (default: 80)',
                        'default': 80
                    },
                    'vpc_id': {
                        'type': 'string',
                        'description': 'VPC ID (required for instance/ip target types)'
                    },
                    'target_type': {
                        'type': 'string',
                        'enum': ['instance', 'ip', 'lambda'],
                        'description': 'Target type (default: instance)',
                        'default': 'instance'
                    },
                    'health_check_path': {
                        'type': 'string',
                        'description': 'Health check path (e.g., "/" or "/health")'
                    },
                    'health_check_interval_seconds': {
                        'type': 'integer',
                        'description': 'Health check interval in seconds (5-300, default: 30)',
                        'default': 30
                    },
                    'health_check_protocol': {
                        'type': 'string',
                        'description': 'Health check protocol (defaults to target protocol)'
                    },
                    'tags': {
                        'type': 'object',
                        'description': 'Tags to apply'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['name', 'vpc_id']
            },
            'handler': create_target_group
        },
        {
            'name': 'create_listener',
            'description': (
                'Create a listener on a load balancer to forward traffic to a target group. '
                'A listener checks for connection requests and routes them to targets. '
                'For HTTPS, provide an ACM certificate ARN.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'load_balancer_arn': {
                        'type': 'string',
                        'description': 'ARN of the load balancer'
                    },
                    'protocol': {
                        'type': 'string',
                        'enum': ['HTTP', 'HTTPS', 'TCP', 'TLS'],
                        'description': 'Listener protocol (default: HTTP)',
                        'default': 'HTTP'
                    },
                    'port': {
                        'type': 'integer',
                        'description': 'Listener port (default: 80)',
                        'default': 80
                    },
                    'default_target_group_arn': {
                        'type': 'string',
                        'description': 'ARN of the default target group to forward traffic to'
                    },
                    'ssl_certificate_arn': {
                        'type': 'string',
                        'description': 'ACM certificate ARN (required for HTTPS/TLS listeners)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['load_balancer_arn', 'default_target_group_arn']
            },
            'handler': create_listener
        },
        {
            'name': 'register_targets',
            'description': (
                'Register instances or IPs with a target group. '
                'After registering, the load balancer starts routing traffic to these targets. '
                'Each target needs an id (instance ID or IP) and optionally a port.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target_group_arn': {
                        'type': 'string',
                        'description': 'ARN of the target group'
                    },
                    'targets': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {
                                    'type': 'string',
                                    'description': 'Instance ID (e.g., i-xxxx) or IP address'
                                },
                                'port': {
                                    'type': 'integer',
                                    'description': 'Port override (optional, uses target group default if not specified)'
                                }
                            },
                            'required': ['id']
                        },
                        'description': 'List of targets to register'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['target_group_arn', 'targets']
            },
            'handler': register_targets
        },
        {
            'name': 'describe_target_health',
            'description': (
                'Check the health status of targets in a target group. '
                'Shows whether each target is healthy, unhealthy, draining, or unused. '
                'Use this to verify targets are receiving traffic after registration.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target_group_arn': {
                        'type': 'string',
                        'description': 'ARN of the target group'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['target_group_arn']
            },
            'handler': describe_target_health
        },
        # ---- Security Group Management ----
        {
            'name': 'revoke_security_group_ingress',
            'description': 'Remove an ingress rule from a security group. Supports CIDR or source security group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {'type': 'string', 'description': 'Security group ID'},
                    'protocol': {'type': 'string', 'description': 'Protocol (tcp, udp, icmp, -1)', 'default': 'tcp'},
                    'from_port': {'type': 'integer', 'description': 'Start of port range'},
                    'to_port': {'type': 'integer', 'description': 'End of port range'},
                    'cidr': {'type': 'string', 'description': 'CIDR block to revoke'},
                    'source_security_group_id': {'type': 'string', 'description': 'Source SG to revoke'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_id', 'protocol', 'from_port']
            },
            'handler': revoke_security_group_ingress
        },
        {
            'name': 'delete_security_group',
            'description': 'Delete a security group. Cannot delete if in use by instances.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {'type': 'string', 'description': 'Security group ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_id']
            },
            'handler': delete_security_group
        },
        # ---- IAM Management ----
        {
            'name': 'create_iam_role',
            'description': 'Create an IAM role with a trust policy (assume role policy document as JSON string).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'Name for the IAM role'},
                    'assume_role_policy': {'type': 'string', 'description': 'Trust policy JSON document (who can assume this role)'},
                    'description': {'type': 'string', 'description': 'Role description'},
                    'tags': {'type': 'object', 'description': 'Tags to apply'}
                },
                'required': ['role_name', 'assume_role_policy']
            },
            'handler': create_iam_role
        },
        {
            'name': 'create_iam_policy',
            'description': 'Create an IAM policy from a JSON policy document.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'policy_name': {'type': 'string', 'description': 'Name for the policy'},
                    'policy_document': {'type': 'string', 'description': 'IAM policy JSON document'},
                    'description': {'type': 'string', 'description': 'Policy description'},
                    'path': {'type': 'string', 'description': 'Path prefix (e.g., /app/)'}
                },
                'required': ['policy_name', 'policy_document']
            },
            'handler': create_iam_policy
        },
        {
            'name': 'attach_iam_role_policy',
            'description': 'Attach a managed policy to an IAM role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'},
                    'policy_arn': {'type': 'string', 'description': 'ARN of the policy to attach'}
                },
                'required': ['role_name', 'policy_arn']
            },
            'handler': attach_iam_role_policy
        },
        # ---- IAM Extended Operations ----
        {
            'name': 'create_iam_user',
            'description': 'Create a new IAM user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'path': {'type': 'string', 'description': 'Path for the user (default: /)'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'}
                },
                'required': ['username']
            },
            'handler': create_iam_user
        },
        {
            'name': 'get_iam_user',
            'description': 'Get details of an IAM user including groups and attached policies.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'}
                },
                'required': ['username']
            },
            'handler': get_iam_user
        },
        {
            'name': 'delete_iam_user',
            'description': 'Delete an IAM user and all associated resources (access keys, group memberships, attached policies, login profile).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username to delete'}
                },
                'required': ['username']
            },
            'handler': delete_iam_user
        },
        {
            'name': 'create_iam_login_profile',
            'description': 'Enable AWS Console access for an IAM user by setting a password.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'password': {'type': 'string', 'description': 'Console password'},
                    'password_reset_required': {'type': 'boolean', 'description': 'Force password reset on first login (default: true)'}
                },
                'required': ['username', 'password']
            },
            'handler': create_iam_login_profile
        },
        {
            'name': 'delete_iam_login_profile',
            'description': 'Remove AWS Console access from an IAM user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'}
                },
                'required': ['username']
            },
            'handler': delete_iam_login_profile
        },
        {
            'name': 'tag_iam_user',
            'description': 'Add or update tags on an IAM user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'}
                },
                'required': ['username', 'tags']
            },
            'handler': tag_iam_user
        },
        {
            'name': 'create_iam_access_key',
            'description': 'Create a new IAM access key for a user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'}
                },
                'required': ['username']
            },
            'handler': create_iam_access_key
        },
        {
            'name': 'list_iam_access_keys',
            'description': 'List IAM access keys for a user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'}
                },
                'required': ['username']
            },
            'handler': list_iam_access_keys
        },
        {
            'name': 'delete_iam_access_key',
            'description': 'Delete an IAM access key.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'access_key_id': {'type': 'string', 'description': 'Access key ID to delete'}
                },
                'required': ['username', 'access_key_id']
            },
            'handler': delete_iam_access_key
        },
        {
            'name': 'update_iam_access_key',
            'description': 'Activate or deactivate an IAM access key.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'access_key_id': {'type': 'string', 'description': 'Access key ID'},
                    'status': {'type': 'string', 'description': 'Active or Inactive', 'enum': ['Active', 'Inactive']}
                },
                'required': ['username', 'access_key_id', 'status']
            },
            'handler': update_iam_access_key
        },
        {
            'name': 'get_access_key_last_used',
            'description': 'Get when an IAM access key was last used and for which service/region.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'access_key_id': {'type': 'string', 'description': 'Access key ID'}
                },
                'required': ['access_key_id']
            },
            'handler': get_access_key_last_used
        },
        {
            'name': 'create_iam_group',
            'description': 'Create a new IAM group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'IAM group name'},
                    'path': {'type': 'string', 'description': 'Path for the group (default: /)'}
                },
                'required': ['group_name']
            },
            'handler': create_iam_group
        },
        {
            'name': 'list_iam_groups',
            'description': 'List all IAM groups in the account.',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': list_iam_groups
        },
        {
            'name': 'delete_iam_group',
            'description': 'Delete an IAM group (removes all users and detaches all policies first).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'IAM group name to delete'}
                },
                'required': ['group_name']
            },
            'handler': delete_iam_group
        },
        {
            'name': 'add_iam_user_to_group',
            'description': 'Add an IAM user to a group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'group_name': {'type': 'string', 'description': 'IAM group name'}
                },
                'required': ['username', 'group_name']
            },
            'handler': add_iam_user_to_group
        },
        {
            'name': 'remove_iam_user_from_group',
            'description': 'Remove an IAM user from a group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'group_name': {'type': 'string', 'description': 'IAM group name'}
                },
                'required': ['username', 'group_name']
            },
            'handler': remove_iam_user_from_group
        },
        {
            'name': 'list_iam_groups_for_user',
            'description': 'List all IAM groups a user belongs to.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'}
                },
                'required': ['username']
            },
            'handler': list_iam_groups_for_user
        },
        {
            'name': 'get_iam_role',
            'description': 'Get details of an IAM role including trust policy and attached policies.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'}
                },
                'required': ['role_name']
            },
            'handler': get_iam_role
        },
        {
            'name': 'update_iam_role_trust_policy',
            'description': 'Update the trust relationship (assume role policy) of an IAM role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'},
                    'trust_policy': {'type': 'object', 'description': 'New trust policy document as JSON object'}
                },
                'required': ['role_name', 'trust_policy']
            },
            'handler': update_iam_role_trust_policy
        },
        {
            'name': 'assume_iam_role',
            'description': 'Assume an IAM role via STS and return temporary credentials.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_arn': {'type': 'string', 'description': 'ARN of the role to assume'},
                    'session_name': {'type': 'string', 'description': 'Name for the assumed role session'},
                    'duration_seconds': {'type': 'integer', 'description': 'Duration of credentials in seconds (900-43200, default: 3600)'},
                    'external_id': {'type': 'string', 'description': 'External ID for cross-account role assumption'}
                },
                'required': ['role_arn', 'session_name']
            },
            'handler': assume_iam_role
        },
        {
            'name': 'tag_iam_role',
            'description': 'Add or update tags on an IAM role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'}
                },
                'required': ['role_name', 'tags']
            },
            'handler': tag_iam_role
        },
        {
            'name': 'list_iam_policies',
            'description': 'List IAM policies in the account.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'scope': {'type': 'string', 'description': 'Local (customer-managed), AWS (managed), or All (default: Local)', 'enum': ['Local', 'AWS', 'All']},
                    'max_items': {'type': 'integer', 'description': 'Maximum number of policies to return (default: 100)'}
                }
            },
            'handler': list_iam_policies
        },
        {
            'name': 'get_iam_policy',
            'description': 'Get an IAM policy and its default version document.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'policy_arn': {'type': 'string', 'description': 'Policy ARN'}
                },
                'required': ['policy_arn']
            },
            'handler': get_iam_policy
        },
        {
            'name': 'delete_iam_policy',
            'description': 'Delete a customer-managed IAM policy (detaches from all entities first).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'policy_arn': {'type': 'string', 'description': 'Policy ARN to delete'}
                },
                'required': ['policy_arn']
            },
            'handler': delete_iam_policy
        },
        {
            'name': 'attach_iam_user_policy',
            'description': 'Attach a managed policy directly to an IAM user.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'username': {'type': 'string', 'description': 'IAM username'},
                    'policy_arn': {'type': 'string', 'description': 'Policy ARN to attach'}
                },
                'required': ['username', 'policy_arn']
            },
            'handler': attach_iam_user_policy
        },
        {
            'name': 'attach_iam_group_policy',
            'description': 'Attach a managed policy to an IAM group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'IAM group name'},
                    'policy_arn': {'type': 'string', 'description': 'Policy ARN to attach'}
                },
                'required': ['group_name', 'policy_arn']
            },
            'handler': attach_iam_group_policy
        },
        {
            'name': 'detach_iam_policy',
            'description': 'Detach a managed policy from a user, group, or role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'entity_type': {'type': 'string', 'description': 'user, group, or role', 'enum': ['user', 'group', 'role']},
                    'entity_name': {'type': 'string', 'description': 'Name of the user, group, or role'},
                    'policy_arn': {'type': 'string', 'description': 'Policy ARN to detach'}
                },
                'required': ['entity_type', 'entity_name', 'policy_arn']
            },
            'handler': detach_iam_policy
        },
        {
            'name': 'put_iam_inline_policy',
            'description': 'Create or update an inline policy on a user, group, or role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'entity_type': {'type': 'string', 'description': 'user, group, or role', 'enum': ['user', 'group', 'role']},
                    'entity_name': {'type': 'string', 'description': 'Name of the user, group, or role'},
                    'policy_name': {'type': 'string', 'description': 'Name of the inline policy'},
                    'policy_document': {'type': 'object', 'description': 'IAM policy document as JSON object'}
                },
                'required': ['entity_type', 'entity_name', 'policy_name', 'policy_document']
            },
            'handler': put_iam_inline_policy
        },
        {
            'name': 'delete_iam_inline_policy',
            'description': 'Delete an inline policy from a user, group, or role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'entity_type': {'type': 'string', 'description': 'user, group, or role', 'enum': ['user', 'group', 'role']},
                    'entity_name': {'type': 'string', 'description': 'Name of the user, group, or role'},
                    'policy_name': {'type': 'string', 'description': 'Name of the inline policy to delete'}
                },
                'required': ['entity_type', 'entity_name', 'policy_name']
            },
            'handler': delete_iam_inline_policy
        },
        {
            'name': 'list_attached_role_policies',
            'description': 'List all managed policies attached to an IAM role.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'}
                },
                'required': ['role_name']
            },
            'handler': list_attached_role_policies
        },
        {
            'name': 'generate_iam_credential_report',
            'description': 'Generate an IAM credential report for all users in the account.',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': generate_iam_credential_report
        },
        {
            'name': 'get_iam_credential_report',
            'description': 'Download the latest IAM credential report (generate first if needed).',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': get_iam_credential_report
        },
        {
            'name': 'get_iam_account_summary',
            'description': 'Get a summary of IAM entity counts and limits for the AWS account.',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': get_iam_account_summary
        },
        {
            'name': 'list_iam_services_last_accessed',
            'description': 'List services that an IAM entity (user, role, group, or policy) has accessed, for least-privilege analysis.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'arn': {'type': 'string', 'description': 'ARN of the IAM user, role, group, or policy'}
                },
                'required': ['arn']
            },
            'handler': list_iam_services_last_accessed
        },
        # ---- VPC & Networking ----
        {
            'name': 'create_vpc',
            'description': 'Create a VPC with DNS support and hostnames enabled.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cidr_block': {'type': 'string', 'description': 'CIDR block (e.g., 10.0.0.0/16)'},
                    'name': {'type': 'string', 'description': 'Name tag for the VPC'},
                    'enable_dns_support': {'type': 'boolean', 'description': 'Enable DNS support (default: true)', 'default': True},
                    'enable_dns_hostnames': {'type': 'boolean', 'description': 'Enable DNS hostnames (default: true)', 'default': True},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cidr_block']
            },
            'handler': create_vpc
        },
        {
            'name': 'delete_vpc',
            'description': 'Delete a VPC. All dependent resources (subnets, IGWs, etc.) must be deleted first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': delete_vpc
        },
        {
            'name': 'create_subnet',
            'description': 'Create a subnet in a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'cidr_block': {'type': 'string', 'description': 'Subnet CIDR (e.g., 10.0.1.0/24)'},
                    'availability_zone': {'type': 'string', 'description': 'AZ (e.g., us-east-1a)'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'map_public_ip': {'type': 'boolean', 'description': 'Auto-assign public IPs (default: false)', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id', 'cidr_block']
            },
            'handler': create_subnet
        },
        {
            'name': 'create_internet_gateway',
            'description': 'Create an internet gateway and attach it to a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID to attach the IGW to'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': create_internet_gateway
        },
        {
            'name': 'create_route_table',
            'description': (
                'Create a route table, optionally add routes and associate with subnets. '
                'Routes format: [{"cidr": "0.0.0.0/0", "gateway_id": "igw-xxx"}]'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'routes': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'cidr': {'type': 'string', 'description': 'Destination CIDR'},
                                'gateway_id': {'type': 'string', 'description': 'Internet gateway ID'},
                                'nat_gateway_id': {'type': 'string', 'description': 'NAT gateway ID'},
                                'instance_id': {'type': 'string', 'description': 'Instance ID'}
                            },
                            'required': ['cidr']
                        },
                        'description': 'Routes to add'
                    },
                    'subnet_ids': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': 'Subnet IDs to associate'
                    },
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': create_route_table
        },
        {
            'name': 'allocate_elastic_ip',
            'description': 'Allocate an Elastic IP and optionally associate with an instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {'type': 'string', 'description': 'Instance ID to associate with (optional)'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': allocate_elastic_ip
        },
        {
            'name': 'release_elastic_ip',
            'description': 'Release an Elastic IP address back to AWS.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'allocation_id': {'type': 'string', 'description': 'Allocation ID of the Elastic IP'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['allocation_id']
            },
            'handler': release_elastic_ip
        },
        # ---- VPC Extended Operations ----
        {
            'name': 'describe_vpc',
            'description': 'Get detailed information about a VPC including CIDR blocks, DNS settings, and state.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': describe_vpc
        },
        {
            'name': 'modify_vpc_attribute',
            'description': 'Enable or disable DNS resolution and DNS hostnames for a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'enable_dns_support': {'type': 'boolean', 'description': 'Enable DNS resolution'},
                    'enable_dns_hostnames': {'type': 'boolean', 'description': 'Enable DNS hostnames'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': modify_vpc_attribute
        },
        {
            'name': 'associate_vpc_cidr',
            'description': 'Add a secondary CIDR block to an existing VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'cidr_block': {'type': 'string', 'description': 'Additional CIDR block to add'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id', 'cidr_block']
            },
            'handler': associate_vpc_cidr
        },
        {
            'name': 'disassociate_vpc_cidr',
            'description': 'Remove a secondary CIDR block from a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'association_id': {'type': 'string', 'description': 'CIDR block association ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['association_id']
            },
            'handler': disassociate_vpc_cidr
        },
        {
            'name': 'tag_vpc',
            'description': 'Add or update tags on a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id', 'tags']
            },
            'handler': tag_vpc
        },
        {
            'name': 'enable_vpc_flow_logs',
            'description': 'Enable VPC Flow Logs to CloudWatch Logs or S3 for network traffic analysis.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'destination_type': {'type': 'string', 'enum': ['cloud-watch-logs', 's3'], 'description': 'Log destination type (default: cloud-watch-logs)'},
                    'log_group_name': {'type': 'string', 'description': 'CloudWatch log group name'},
                    's3_bucket_arn': {'type': 'string', 'description': 'S3 bucket ARN for flow logs'},
                    'iam_role_arn': {'type': 'string', 'description': 'IAM role ARN for CloudWatch delivery'},
                    'traffic_type': {'type': 'string', 'enum': ['ACCEPT', 'REJECT', 'ALL'], 'description': 'Traffic to log (default: ALL)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': enable_vpc_flow_logs
        },
        {
            'name': 'list_vpc_flow_logs',
            'description': 'List VPC Flow Log configurations.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_vpc_flow_logs
        },
        {
            'name': 'disable_vpc_flow_logs',
            'description': 'Delete a VPC Flow Log configuration.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'flow_log_id': {'type': 'string', 'description': 'Flow log ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['flow_log_id']
            },
            'handler': disable_vpc_flow_logs
        },
        {
            'name': 'modify_subnet_attribute',
            'description': 'Enable or disable auto-assign public IP or IPv6 for a subnet.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID'},
                    'map_public_ip_on_launch': {'type': 'boolean', 'description': 'Auto-assign public IP on launch'},
                    'assign_ipv6_address_on_creation': {'type': 'boolean', 'description': 'Auto-assign IPv6 on creation'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['subnet_id']
            },
            'handler': modify_subnet_attribute
        },
        {
            'name': 'tag_subnet',
            'description': 'Add or update tags on a subnet.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['subnet_id', 'tags']
            },
            'handler': tag_subnet
        },
        {
            'name': 'list_internet_gateways',
            'description': 'List all Internet Gateways and their attachment status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_internet_gateways
        },
        {
            'name': 'attach_internet_gateway',
            'description': 'Attach an existing Internet Gateway to a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'igw_id': {'type': 'string', 'description': 'Internet Gateway ID'},
                    'vpc_id': {'type': 'string', 'description': 'VPC ID to attach to'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['igw_id', 'vpc_id']
            },
            'handler': attach_internet_gateway
        },
        {
            'name': 'detach_internet_gateway',
            'description': 'Detach an Internet Gateway from a VPC without deleting it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'igw_id': {'type': 'string', 'description': 'Internet Gateway ID'},
                    'vpc_id': {'type': 'string', 'description': 'VPC ID to detach from'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['igw_id', 'vpc_id']
            },
            'handler': detach_internet_gateway
        },
        {
            'name': 'delete_internet_gateway',
            'description': 'Delete an Internet Gateway (must be detached from all VPCs first).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'igw_id': {'type': 'string', 'description': 'Internet Gateway ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['igw_id']
            },
            'handler': delete_internet_gateway
        },
        {
            'name': 'list_route_tables',
            'description': 'List all route tables in a VPC or region, with routes and subnet associations.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_route_tables
        },
        {
            'name': 'delete_route_table',
            'description': 'Delete a route table (must have no subnet associations).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id']
            },
            'handler': delete_route_table
        },
        {
            'name': 'add_route',
            'description': 'Add a route to a route table (e.g., 0.0.0.0/0 via IGW for internet access).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID'},
                    'destination_cidr': {'type': 'string', 'description': 'Destination CIDR (e.g., 0.0.0.0/0)'},
                    'gateway_id': {'type': 'string', 'description': 'Internet Gateway ID'},
                    'nat_gateway_id': {'type': 'string', 'description': 'NAT Gateway ID'},
                    'instance_id': {'type': 'string', 'description': 'EC2 Instance ID'},
                    'vpc_peering_connection_id': {'type': 'string', 'description': 'VPC Peering Connection ID'},
                    'transit_gateway_id': {'type': 'string', 'description': 'Transit Gateway ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id', 'destination_cidr']
            },
            'handler': add_route
        },
        {
            'name': 'delete_route',
            'description': 'Remove a route from a route table by destination CIDR.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID'},
                    'destination_cidr': {'type': 'string', 'description': 'Destination CIDR to remove'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id', 'destination_cidr']
            },
            'handler': delete_route
        },
        {
            'name': 'replace_route',
            'description': 'Update the target of an existing route in a route table.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID'},
                    'destination_cidr': {'type': 'string', 'description': 'Destination CIDR of the route to update'},
                    'gateway_id': {'type': 'string', 'description': 'New Internet Gateway ID'},
                    'nat_gateway_id': {'type': 'string', 'description': 'New NAT Gateway ID'},
                    'instance_id': {'type': 'string', 'description': 'New Instance ID'},
                    'transit_gateway_id': {'type': 'string', 'description': 'New Transit Gateway ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id', 'destination_cidr']
            },
            'handler': replace_route
        },
        {
            'name': 'associate_route_table',
            'description': 'Associate a subnet with a route table.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID'},
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID to associate'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id', 'subnet_id']
            },
            'handler': associate_route_table
        },
        {
            'name': 'disassociate_route_table',
            'description': 'Disassociate a subnet from a route table (reverts to main route table).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'association_id': {'type': 'string', 'description': 'Route table association ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['association_id']
            },
            'handler': disassociate_route_table
        },
        {
            'name': 'set_main_route_table',
            'description': 'Change the main (default) route table for a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'route_table_id': {'type': 'string', 'description': 'Route table ID to set as main'},
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['route_table_id', 'vpc_id']
            },
            'handler': set_main_route_table
        },
        {
            'name': 'authorize_security_group_egress',
            'description': 'Add an outbound (egress) rule to a security group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {'type': 'string', 'description': 'Security group ID'},
                    'protocol': {'type': 'string', 'description': 'Protocol: tcp, udp, icmp, or -1 for all'},
                    'from_port': {'type': 'integer', 'description': 'Start of port range'},
                    'to_port': {'type': 'integer', 'description': 'End of port range'},
                    'cidr_ip': {'type': 'string', 'description': 'CIDR block (default: 0.0.0.0/0)'},
                    'description': {'type': 'string', 'description': 'Rule description'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_id', 'protocol', 'from_port', 'to_port']
            },
            'handler': authorize_security_group_egress
        },
        {
            'name': 'revoke_security_group_egress',
            'description': 'Remove an outbound (egress) rule from a security group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {'type': 'string', 'description': 'Security group ID'},
                    'protocol': {'type': 'string', 'description': 'Protocol: tcp, udp, icmp, or -1 for all'},
                    'from_port': {'type': 'integer', 'description': 'Start of port range'},
                    'to_port': {'type': 'integer', 'description': 'End of port range'},
                    'cidr_ip': {'type': 'string', 'description': 'CIDR block'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_id', 'protocol', 'from_port', 'to_port']
            },
            'handler': revoke_security_group_egress
        },
        {
            'name': 'audit_security_group_rules',
            'description': 'Find overly permissive security group inbound rules with 0.0.0.0/0 on sensitive ports.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': audit_security_group_rules
        },
        {
            'name': 'tag_security_group',
            'description': 'Add or update tags on a security group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {'type': 'string', 'description': 'Security group ID'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_id', 'tags']
            },
            'handler': tag_security_group
        },
        {
            'name': 'create_network_acl',
            'description': 'Create a Network ACL (stateless subnet-level firewall) in a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id']
            },
            'handler': create_network_acl
        },
        {
            'name': 'list_network_acls',
            'description': 'List Network ACLs in a VPC or region with their rules and subnet associations.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_network_acls
        },
        {
            'name': 'delete_network_acl',
            'description': 'Delete a Network ACL (must have no subnet associations).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_acl_id': {'type': 'string', 'description': 'Network ACL ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_acl_id']
            },
            'handler': delete_network_acl
        },
        {
            'name': 'create_nacl_entry',
            'description': 'Add an inbound or outbound rule to a Network ACL.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_acl_id': {'type': 'string', 'description': 'Network ACL ID'},
                    'rule_number': {'type': 'integer', 'description': 'Rule number (1-32766, lower = higher priority)'},
                    'protocol': {'type': 'string', 'description': 'Protocol number: 6 (TCP), 17 (UDP), -1 (all)'},
                    'rule_action': {'type': 'string', 'enum': ['allow', 'deny'], 'description': 'Allow or deny'},
                    'egress': {'type': 'boolean', 'description': 'True for outbound, False for inbound'},
                    'cidr_block': {'type': 'string', 'description': 'CIDR block'},
                    'from_port': {'type': 'integer', 'description': 'Start of port range'},
                    'to_port': {'type': 'integer', 'description': 'End of port range'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_acl_id', 'rule_number', 'protocol', 'rule_action', 'egress', 'cidr_block']
            },
            'handler': create_nacl_entry
        },
        {
            'name': 'delete_nacl_entry',
            'description': 'Delete a specific rule from a Network ACL by rule number.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_acl_id': {'type': 'string', 'description': 'Network ACL ID'},
                    'rule_number': {'type': 'integer', 'description': 'Rule number to delete'},
                    'egress': {'type': 'boolean', 'description': 'True for outbound rule, False for inbound'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_acl_id', 'rule_number', 'egress']
            },
            'handler': delete_nacl_entry
        },
        {
            'name': 'associate_nacl_with_subnet',
            'description': 'Apply a Network ACL to a subnet (replaces the existing NACL association).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_acl_id': {'type': 'string', 'description': 'Network ACL ID to apply'},
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_acl_id', 'subnet_id']
            },
            'handler': associate_nacl_with_subnet
        },
        {
            'name': 'create_vpc_peering',
            'description': 'Initiate a VPC peering connection request between two VPCs (same or cross-account/region).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Requester VPC ID'},
                    'peer_vpc_id': {'type': 'string', 'description': 'Accepter VPC ID'},
                    'peer_owner_id': {'type': 'string', 'description': 'Accepter AWS account ID (for cross-account)'},
                    'peer_region': {'type': 'string', 'description': 'Accepter region (for cross-region)'},
                    'region': {'type': 'string', 'description': 'Requester AWS region'}
                },
                'required': ['vpc_id', 'peer_vpc_id']
            },
            'handler': create_vpc_peering
        },
        {
            'name': 'list_vpc_peerings',
            'description': 'List all VPC peering connections and their status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_vpc_peerings
        },
        {
            'name': 'accept_vpc_peering',
            'description': 'Accept an incoming VPC peering connection request.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'peering_connection_id': {'type': 'string', 'description': 'VPC Peering Connection ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['peering_connection_id']
            },
            'handler': accept_vpc_peering
        },
        {
            'name': 'delete_vpc_peering',
            'description': 'Delete a VPC peering connection.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'peering_connection_id': {'type': 'string', 'description': 'VPC Peering Connection ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['peering_connection_id']
            },
            'handler': delete_vpc_peering
        },
        {
            'name': 'create_vpc_endpoint',
            'description': 'Create a VPC endpoint — Gateway (free, for S3/DynamoDB) or Interface (PrivateLink, for other AWS services).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'VPC ID'},
                    'service_name': {'type': 'string', 'description': 'Service name (e.g., com.amazonaws.us-east-1.s3)'},
                    'endpoint_type': {'type': 'string', 'enum': ['Gateway', 'Interface'], 'description': 'Endpoint type (default: Gateway)'},
                    'route_table_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Route table IDs (Gateway endpoints)'},
                    'subnet_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs (Interface endpoints)'},
                    'security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs (Interface endpoints)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['vpc_id', 'service_name']
            },
            'handler': create_vpc_endpoint
        },
        {
            'name': 'list_vpc_endpoints',
            'description': 'List VPC endpoints and their service associations.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_vpc_endpoints
        },
        {
            'name': 'delete_vpc_endpoint',
            'description': 'Delete a VPC endpoint.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'endpoint_id': {'type': 'string', 'description': 'VPC Endpoint ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['endpoint_id']
            },
            'handler': delete_vpc_endpoint
        },
        {
            'name': 'create_eni',
            'description': 'Create an Elastic Network Interface (ENI) in a subnet.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID'},
                    'description': {'type': 'string', 'description': 'Description of the ENI'},
                    'security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs'},
                    'private_ip': {'type': 'string', 'description': 'Private IP address (auto-assigned if omitted)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['subnet_id']
            },
            'handler': create_eni
        },
        {
            'name': 'list_enis',
            'description': 'List Elastic Network Interfaces (ENIs) with attachment details.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Filter by subnet ID'},
                    'vpc_id': {'type': 'string', 'description': 'Filter by VPC ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_enis
        },
        {
            'name': 'attach_eni',
            'description': 'Attach a network interface to an EC2 instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_interface_id': {'type': 'string', 'description': 'Network Interface ID'},
                    'instance_id': {'type': 'string', 'description': 'EC2 Instance ID'},
                    'device_index': {'type': 'integer', 'description': 'Device index (default: 1 for secondary interface)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_interface_id', 'instance_id']
            },
            'handler': attach_eni
        },
        {
            'name': 'detach_eni',
            'description': 'Detach a network interface from an EC2 instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'attachment_id': {'type': 'string', 'description': 'Attachment ID'},
                    'force': {'type': 'boolean', 'description': 'Force detachment (default: false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['attachment_id']
            },
            'handler': detach_eni
        },
        {
            'name': 'delete_eni',
            'description': 'Delete an Elastic Network Interface (must be detached first).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'network_interface_id': {'type': 'string', 'description': 'Network Interface ID to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['network_interface_id']
            },
            'handler': delete_eni
        },
        # ---- Route 53 DNS ----
        {
            'name': 'create_route53_record',
            'description': 'Create or update a DNS record in Route 53 (UPSERT by default).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'hosted_zone_id': {'type': 'string', 'description': 'Hosted zone ID'},
                    'record_name': {'type': 'string', 'description': 'DNS record name (e.g., app.example.com)'},
                    'record_type': {'type': 'string', 'enum': ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SOA', 'SRV'], 'description': 'Record type'},
                    'record_value': {'type': 'string', 'description': 'Record value (IP, hostname, etc.)'},
                    'ttl': {'type': 'integer', 'description': 'TTL in seconds (default: 300)', 'default': 300},
                    'action': {'type': 'string', 'enum': ['CREATE', 'UPSERT'], 'description': 'Action (default: UPSERT)', 'default': 'UPSERT'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['hosted_zone_id', 'record_name', 'record_type', 'record_value']
            },
            'handler': create_route53_record
        },
        {
            'name': 'delete_route53_record',
            'description': 'Delete a DNS record from Route 53. Must specify exact current values.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'hosted_zone_id': {'type': 'string', 'description': 'Hosted zone ID'},
                    'record_name': {'type': 'string', 'description': 'DNS record name'},
                    'record_type': {'type': 'string', 'description': 'Record type (A, CNAME, etc.)'},
                    'record_value': {'type': 'string', 'description': 'Current record value'},
                    'ttl': {'type': 'integer', 'description': 'Current TTL (default: 300)', 'default': 300},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['hosted_zone_id', 'record_name', 'record_type', 'record_value']
            },
            'handler': delete_route53_record
        },
        # ---- CloudFormation ----
        {
            'name': 'create_cloudformation_stack',
            'description': 'Create a CloudFormation stack from a template body or S3 URL.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'stack_name': {'type': 'string', 'description': 'Stack name'},
                    'template_body': {'type': 'string', 'description': 'Template body (JSON/YAML string)'},
                    'template_url': {'type': 'string', 'description': 'S3 URL to template (alternative to template_body)'},
                    'parameters': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {'key': {'type': 'string'}, 'value': {'type': 'string'}},
                            'required': ['key', 'value']
                        },
                        'description': 'Stack parameters'
                    },
                    'capabilities': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': 'Capabilities (e.g., ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"])'
                    },
                    'tags': {'type': 'object', 'description': 'Tags to apply'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['stack_name']
            },
            'handler': create_cloudformation_stack
        },
        {
            'name': 'update_cloudformation_stack',
            'description': 'Update an existing CloudFormation stack with new template or parameters.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'stack_name': {'type': 'string', 'description': 'Stack name'},
                    'template_body': {'type': 'string', 'description': 'Updated template body'},
                    'template_url': {'type': 'string', 'description': 'S3 URL to updated template'},
                    'parameters': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {'key': {'type': 'string'}, 'value': {'type': 'string'}},
                            'required': ['key', 'value']
                        }
                    },
                    'capabilities': {'type': 'array', 'items': {'type': 'string'}},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['stack_name']
            },
            'handler': update_cloudformation_stack
        },
        {
            'name': 'delete_cloudformation_stack',
            'description': 'Delete a CloudFormation stack and all its resources.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'stack_name': {'type': 'string', 'description': 'Stack name or ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['stack_name']
            },
            'handler': delete_cloudformation_stack
        },
        # ---- ECS Container Management ----
        {
            'name': 'create_ecs_cluster',
            'description': 'Create an ECS cluster for running containerized applications.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'Cluster name'},
                    'capacity_providers': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': 'Capacity providers (e.g., ["FARGATE", "FARGATE_SPOT"])'
                    },
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': create_ecs_cluster
        },
        {
            'name': 'run_ecs_task',
            'description': 'Run a task on an ECS cluster (Fargate or EC2 launch type).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster': {'type': 'string', 'description': 'Cluster name or ARN'},
                    'task_definition': {'type': 'string', 'description': 'Task definition family:revision or ARN'},
                    'count': {'type': 'integer', 'description': 'Number of tasks (default: 1)', 'default': 1},
                    'launch_type': {'type': 'string', 'enum': ['FARGATE', 'EC2'], 'default': 'FARGATE'},
                    'subnets': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs (required for Fargate)'},
                    'security_groups': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs'},
                    'assign_public_ip': {'type': 'boolean', 'description': 'Assign public IP (default: true)', 'default': True},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster', 'task_definition']
            },
            'handler': run_ecs_task
        },
        {
            'name': 'update_ecs_service',
            'description': 'Update an ECS service (desired count, task definition, or force new deployment).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster': {'type': 'string', 'description': 'Cluster name or ARN'},
                    'service': {'type': 'string', 'description': 'Service name or ARN'},
                    'desired_count': {'type': 'integer', 'description': 'New desired task count'},
                    'task_definition': {'type': 'string', 'description': 'New task definition'},
                    'force_new_deployment': {'type': 'boolean', 'description': 'Force new deployment (default: false)', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster', 'service']
            },
            'handler': update_ecs_service
        },
        # ---- SNS Messaging ----
        {
            'name': 'create_sns_topic',
            'description': 'Create an SNS topic for pub/sub messaging.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_name': {'type': 'string', 'description': 'Topic name'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['topic_name']
            },
            'handler': create_sns_topic
        },
        {
            'name': 'publish_sns_message',
            'description': 'Publish a message to an SNS topic.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_arn': {'type': 'string', 'description': 'SNS topic ARN'},
                    'message': {'type': 'string', 'description': 'Message body'},
                    'subject': {'type': 'string', 'description': 'Message subject (for email subscribers)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['topic_arn', 'message']
            },
            'handler': publish_sns_message
        },
        {
            'name': 'subscribe_sns_topic',
            'description': 'Subscribe an endpoint to an SNS topic (email, SMS, Lambda, SQS, HTTP/S).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_arn': {'type': 'string', 'description': 'SNS topic ARN'},
                    'protocol': {'type': 'string', 'enum': ['email', 'sms', 'lambda', 'sqs', 'http', 'https'], 'description': 'Subscription protocol'},
                    'endpoint': {'type': 'string', 'description': 'Endpoint (email address, phone, Lambda ARN, SQS ARN, URL)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['topic_arn', 'protocol', 'endpoint']
            },
            'handler': subscribe_sns_topic
        },
        # ---- SQS Messaging ----
        {
            'name': 'create_sqs_queue',
            'description': 'Create an SQS queue (standard or FIFO).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'queue_name': {'type': 'string', 'description': 'Queue name'},
                    'fifo': {'type': 'boolean', 'description': 'Create FIFO queue (default: false)', 'default': False},
                    'visibility_timeout': {'type': 'integer', 'description': 'Visibility timeout in seconds (default: 30)', 'default': 30},
                    'message_retention_period': {'type': 'integer', 'description': 'Message retention in seconds (default: 345600 = 4 days)', 'default': 345600},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['queue_name']
            },
            'handler': create_sqs_queue
        },
        {
            'name': 'send_sqs_message',
            'description': 'Send a message to an SQS queue.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'queue_url': {'type': 'string', 'description': 'SQS queue URL'},
                    'message_body': {'type': 'string', 'description': 'Message body'},
                    'delay_seconds': {'type': 'integer', 'description': 'Delay in seconds (0-900)', 'default': 0},
                    'message_group_id': {'type': 'string', 'description': 'Message group ID (FIFO queues only)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['queue_url', 'message_body']
            },
            'handler': send_sqs_message
        },
        # ---- DynamoDB ----
        {
            'name': 'create_dynamodb_table',
            'description': 'Create a DynamoDB table with partition key and optional sort key.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'table_name': {'type': 'string', 'description': 'Table name'},
                    'partition_key': {'type': 'string', 'description': 'Partition key attribute name'},
                    'partition_key_type': {'type': 'string', 'enum': ['S', 'N', 'B'], 'description': 'Partition key type (S=String, N=Number, B=Binary)', 'default': 'S'},
                    'sort_key': {'type': 'string', 'description': 'Sort key attribute name (optional)'},
                    'sort_key_type': {'type': 'string', 'enum': ['S', 'N', 'B'], 'description': 'Sort key type', 'default': 'S'},
                    'billing_mode': {'type': 'string', 'enum': ['PAY_PER_REQUEST', 'PROVISIONED'], 'default': 'PAY_PER_REQUEST'},
                    'read_capacity': {'type': 'integer', 'description': 'Read capacity units (provisioned mode)', 'default': 5},
                    'write_capacity': {'type': 'integer', 'description': 'Write capacity units (provisioned mode)', 'default': 5},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['table_name', 'partition_key']
            },
            'handler': create_dynamodb_table
        },
        {
            'name': 'delete_dynamodb_table',
            'description': 'Delete a DynamoDB table and all its data.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'table_name': {'type': 'string', 'description': 'Table name to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['table_name']
            },
            'handler': delete_dynamodb_table
        },
        # ---- SSM Operations ----
        {
            'name': 'ssm_run_command',
            'description': 'Run a shell command on EC2 instances via SSM (no SSH required). Instances must have SSM agent.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Instance IDs to run on'},
                    'commands': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Shell commands to run'},
                    'document_name': {'type': 'string', 'description': 'SSM document (default: AWS-RunShellScript)', 'default': 'AWS-RunShellScript'},
                    'comment': {'type': 'string', 'description': 'Comment for the command'},
                    'timeout_seconds': {'type': 'integer', 'description': 'Timeout in seconds (default: 600)', 'default': 600},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['instance_ids', 'commands']
            },
            'handler': ssm_run_command
        },
        {
            'name': 'ssm_put_parameter',
            'description': 'Create or update an SSM Parameter Store parameter.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'Parameter name (e.g., /app/db/password)'},
                    'value': {'type': 'string', 'description': 'Parameter value'},
                    'param_type': {'type': 'string', 'enum': ['String', 'StringList', 'SecureString'], 'default': 'String'},
                    'description': {'type': 'string', 'description': 'Parameter description'},
                    'overwrite': {'type': 'boolean', 'description': 'Overwrite if exists (default: false)', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['name', 'value']
            },
            'handler': ssm_put_parameter
        },
        # ---- Auto Scaling ----
        {
            'name': 'create_launch_template',
            'description': 'Create an EC2 launch template for use with Auto Scaling groups.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'template_name': {'type': 'string', 'description': 'Launch template name'},
                    'ami_id': {'type': 'string', 'description': 'AMI ID'},
                    'instance_type': {'type': 'string', 'description': 'Instance type'},
                    'key_name': {'type': 'string', 'description': 'SSH key pair name'},
                    'security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs'},
                    'user_data': {'type': 'string', 'description': 'User data script (plain text, will be base64 encoded)'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['template_name', 'ami_id', 'instance_type']
            },
            'handler': create_launch_template
        },
        {
            'name': 'create_auto_scaling_group',
            'description': 'Create an Auto Scaling group from a launch template.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'ASG name'},
                    'launch_template_id': {'type': 'string', 'description': 'Launch template ID'},
                    'launch_template_name': {'type': 'string', 'description': 'Launch template name (alternative to ID)'},
                    'min_size': {'type': 'integer', 'description': 'Minimum instances (default: 1)', 'default': 1},
                    'max_size': {'type': 'integer', 'description': 'Maximum instances (default: 1)', 'default': 1},
                    'desired_capacity': {'type': 'integer', 'description': 'Desired instances (default: 1)', 'default': 1},
                    'subnet_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs for placement'},
                    'target_group_arns': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Target group ARNs for ALB'},
                    'health_check_type': {'type': 'string', 'enum': ['EC2', 'ELB'], 'default': 'EC2'},
                    'health_check_grace_period': {'type': 'integer', 'description': 'Grace period in seconds (default: 300)', 'default': 300},
                    'tags': {'type': 'object', 'description': 'Tags (propagated to instances)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name']
            },
            'handler': create_auto_scaling_group
        },
        {
            'name': 'update_auto_scaling_group',
            'description': 'Update Auto Scaling group capacity (min, max, desired).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'ASG name'},
                    'min_size': {'type': 'integer', 'description': 'New minimum'},
                    'max_size': {'type': 'integer', 'description': 'New maximum'},
                    'desired_capacity': {'type': 'integer', 'description': 'New desired capacity'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name']
            },
            'handler': update_auto_scaling_group
        },
        {
            'name': 'create_scaling_policy',
            'description': 'Create a scaling policy for an Auto Scaling Group. TargetTracking (recommended) auto-adjusts capacity to maintain a target metric like 50% CPU. SimpleScaling adds/removes a fixed number of instances.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'asg_name': {'type': 'string', 'description': 'Auto Scaling Group name'},
                    'policy_name': {'type': 'string', 'description': 'Name for this policy'},
                    'policy_type': {'type': 'string', 'enum': ['TargetTrackingScaling', 'SimpleScaling', 'StepScaling'], 'description': 'Policy type (default: TargetTrackingScaling)'},
                    'target_value': {'type': 'number', 'description': 'Target metric value for TargetTracking (e.g. 50.0 for 50% CPU)'},
                    'predefined_metric': {'type': 'string', 'description': 'TargetTracking metric: ASGAverageCPUUtilization, ASGAverageNetworkIn, ASGAverageNetworkOut, ALBRequestCountPerTarget'},
                    'adjustment_type': {'type': 'string', 'description': 'SimpleScaling: ChangeInCapacity, ExactCapacity, or PercentChangeInCapacity'},
                    'scaling_adjustment': {'type': 'integer', 'description': 'SimpleScaling: instances to add (positive) or remove (negative)'},
                    'cooldown': {'type': 'integer', 'description': 'SimpleScaling cooldown in seconds (default 300)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['asg_name', 'policy_name']
            },
            'handler': create_scaling_policy
        },
        {
            'name': 'create_cloudwatch_alarm',
            'description': 'Create a CloudWatch alarm on any AWS metric (EC2 CPU, RDS connections, Lambda errors, etc.) with optional SNS notification',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alarm_name': {'type': 'string', 'description': 'Unique alarm name'},
                    'metric_name': {'type': 'string', 'description': 'Metric name, e.g. CPUUtilization, NetworkIn, StatusCheckFailed, DatabaseConnections'},
                    'namespace': {'type': 'string', 'description': 'Metric namespace, e.g. AWS/EC2, AWS/RDS, AWS/Lambda, AWS/ECS'},
                    'threshold': {'type': 'number', 'description': 'Numeric threshold value'},
                    'comparison_operator': {'type': 'string', 'enum': ['GreaterThanThreshold', 'LessThanThreshold', 'GreaterThanOrEqualToThreshold', 'LessThanOrEqualToThreshold'], 'description': 'How to compare metric to threshold'},
                    'evaluation_periods': {'type': 'integer', 'description': 'Number of consecutive periods before alarming (default 2)'},
                    'period': {'type': 'integer', 'description': 'Evaluation period in seconds: 60, 300, 3600 (default 300)'},
                    'statistic': {'type': 'string', 'description': 'Average, Sum, Maximum, Minimum, SampleCount (default Average)'},
                    'dimensions': {'type': 'array', 'items': {'type': 'object'}, 'description': 'Metric dimensions, e.g. [{"Name":"InstanceId","Value":"i-0abc123"}]'},
                    'alarm_actions': {'type': 'array', 'items': {'type': 'string'}, 'description': 'SNS topic ARNs to notify when alarm fires'},
                    'ok_actions': {'type': 'array', 'items': {'type': 'string'}, 'description': 'SNS topic ARNs to notify when alarm clears'},
                    'description': {'type': 'string', 'description': 'Human-readable alarm description'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['alarm_name', 'metric_name', 'namespace', 'threshold', 'comparison_operator']
            },
            'handler': create_cloudwatch_alarm
        },
        {
            'name': 'list_cloudwatch_alarms',
            'description': 'List CloudWatch alarms with their current state (OK, ALARM, INSUFFICIENT_DATA), metric, threshold, and linked SNS actions. Use before deleting to confirm alarm names.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'state': {'type': 'string', 'enum': ['OK', 'ALARM', 'INSUFFICIENT_DATA'], 'description': 'Filter by alarm state'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_cloudwatch_alarms
        },
        {
            'name': 'delete_cloudwatch_alarm',
            'description': 'Delete one or more CloudWatch alarms by name. Always call list_cloudwatch_alarms first to confirm the alarm names.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'alarm_names': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of alarm names to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['alarm_names']
            },
            'handler': delete_cloudwatch_alarm
        },
        {
            'name': 'add_tags',
            'description': 'Add or update tags on EC2 resources (instances, volumes, snapshots, AMIs, security groups, etc.)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of resource IDs to tag'},
                    'tags': {'type': 'object', 'description': 'Key-value tag pairs, e.g. {"Environment":"production","Team":"platform"}'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['resource_ids', 'tags']
            },
            'handler': add_tags
        },
        {
            'name': 'remove_tags',
            'description': 'Remove specific tags from EC2 resources',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'List of resource IDs'},
                    'tag_keys': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Tag keys to remove, e.g. ["OldKey","TempTag"]'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['resource_ids', 'tag_keys']
            },
            'handler': remove_tags
        },
        {
            'name': 'list_resources_by_tag',
            'description': 'Find EC2 resources (instances, volumes, snapshots, images) by tag key and optional value. Useful for finding all resources in an environment or project.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'tag_key': {'type': 'string', 'description': 'Tag key to search for, e.g. "Environment" or "Project"'},
                    'tag_value': {'type': 'string', 'description': 'Tag value to match (omit to match all values)'},
                    'resource_types': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Resource types to search: instance, volume, snapshot, image (default: all)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['tag_key']
            },
            'handler': list_resources_by_tag
        },
        # ---- ALB Lifecycle (Delete) ----
        {
            'name': 'delete_load_balancer',
            'description': 'Delete a load balancer.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'load_balancer_arn': {'type': 'string', 'description': 'Load balancer ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['load_balancer_arn']
            },
            'handler': delete_load_balancer
        },
        {
            'name': 'delete_target_group',
            'description': 'Delete a target group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target_group_arn': {'type': 'string', 'description': 'Target group ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['target_group_arn']
            },
            'handler': delete_target_group
        },
        {
            'name': 'deregister_targets',
            'description': 'Deregister targets from a target group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target_group_arn': {'type': 'string', 'description': 'Target group ARN'},
                    'targets': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'string', 'description': 'Instance ID or IP'},
                                'port': {'type': 'integer', 'description': 'Port (optional)'}
                            },
                            'required': ['id']
                        },
                        'description': 'Targets to deregister'
                    },
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['target_group_arn', 'targets']
            },
            'handler': deregister_targets
        },
        # ---- EBS Storage ----
        {
            'name': 'create_ebs_volume',
            'description': 'Create an EBS volume (encrypted by default).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'availability_zone': {'type': 'string', 'description': 'AZ (e.g., us-east-1a) - must match instance AZ'},
                    'size': {'type': 'integer', 'description': 'Volume size in GB (default: 20)', 'default': 20},
                    'volume_type': {'type': 'string', 'enum': ['gp3', 'gp2', 'io1', 'io2', 'st1', 'sc1', 'standard'], 'default': 'gp3'},
                    'encrypted': {'type': 'boolean', 'description': 'Encrypt volume (default: true)', 'default': True},
                    'iops': {'type': 'integer', 'description': 'IOPS (for io1/io2/gp3)'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['availability_zone']
            },
            'handler': create_ebs_volume
        },
        {
            'name': 'attach_ebs_volume',
            'description': 'Attach an EBS volume to an EC2 instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID'},
                    'instance_id': {'type': 'string', 'description': 'EC2 instance ID'},
                    'device': {'type': 'string', 'description': 'Device name (e.g., /dev/sdf)', 'default': '/dev/sdf'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id', 'instance_id']
            },
            'handler': attach_ebs_volume
        },
        {
            'name': 'create_ebs_snapshot',
            'description': 'Create a snapshot of an EBS volume for backup.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID'},
                    'description': {'type': 'string', 'description': 'Snapshot description'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id']
            },
            'handler': create_ebs_snapshot
        },
        {
            'name': 'delete_ebs_snapshot',
            'description': 'Delete an EBS snapshot by snapshot ID',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'snapshot_id': {'type': 'string', 'description': 'Snapshot ID (snap-xxxx)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['snapshot_id']
            },
            'handler': delete_ebs_snapshot
        },
        {
            'name': 'copy_snapshot',
            'description': 'Copy an EBS snapshot to another region for disaster recovery or regional backup',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'snapshot_id': {'type': 'string', 'description': 'Source snapshot ID'},
                    'source_region': {'type': 'string', 'description': 'Region where the source snapshot lives'},
                    'destination_region': {'type': 'string', 'description': 'Region to copy the snapshot to'},
                    'description': {'type': 'string', 'description': 'Description for the copied snapshot'},
                    'encrypted': {'type': 'boolean', 'description': 'Encrypt the copied snapshot (default false)'}
                },
                'required': ['snapshot_id', 'source_region', 'destination_region']
            },
            'handler': copy_snapshot
        },
        {
            'name': 'delete_ebs_volume',
            'description': 'Delete an EBS volume. The volume must be detached from all instances first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID (vol-xxxx)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id']
            },
            'handler': delete_ebs_volume
        },
        {
            'name': 'cleanup_ebs_volume',
            'description': 'Detach (if attached) and delete an EBS volume in one step. Use instead of calling detach_ebs_volume + delete_ebs_volume separately.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID, e.g. vol-0abc12345'},
                    'force': {'type': 'boolean', 'description': 'Force detach from running instance (default false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id']
            },
            'handler': cleanup_ebs_volume
        },
        {
            'name': 'resize_ebs_volume',
            'description': 'Resize an EBS volume (increase size or change type, e.g. gp2 to gp3). Changes take effect immediately but OS partition expansion may be needed.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID'},
                    'new_size_gb': {'type': 'integer', 'description': 'New size in GB (must be >= current size)'},
                    'new_volume_type': {'type': 'string', 'description': 'New volume type: gp2, gp3, io1, io2, st1, sc1'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id']
            },
            'handler': resize_ebs_volume
        },
        {
            'name': 'create_ami',
            'description': 'Create an Amazon Machine Image (AMI) from a running or stopped EC2 instance for use as a template or backup',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {'type': 'string', 'description': 'Source EC2 instance ID'},
                    'name': {'type': 'string', 'description': 'Name for the AMI (must be unique in region)'},
                    'description': {'type': 'string', 'description': 'AMI description'},
                    'no_reboot': {'type': 'boolean', 'description': 'Do not reboot instance during AMI creation (default true — may cause filesystem inconsistency)'},
                    'tags': {'type': 'object', 'description': 'Tags to apply to the AMI'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['instance_id', 'name']
            },
            'handler': create_ami
        },
        {
            'name': 'deregister_ami',
            'description': 'Deregister (delete) an AMI and optionally delete its backing EBS snapshots',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'image_id': {'type': 'string', 'description': 'AMI ID (ami-xxxx)'},
                    'delete_snapshots': {'type': 'boolean', 'description': 'Also delete backing EBS snapshots (default false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['image_id']
            },
            'handler': deregister_ami
        },
        {
            'name': 'get_ec2_console_output',
            'description': 'Retrieve the serial console output (boot log) for an EC2 instance. Useful for diagnosing boot failures, kernel panics, or SSH issues.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {'type': 'string', 'description': 'EC2 instance ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['instance_id']
            },
            'handler': get_ec2_console_output
        },
        # ---- ACM Certificates ----
        {
            'name': 'request_acm_certificate',
            'description': 'Request an SSL/TLS certificate from AWS Certificate Manager.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'domain_name': {'type': 'string', 'description': 'Primary domain (e.g., example.com)'},
                    'validation_method': {'type': 'string', 'enum': ['DNS', 'EMAIL'], 'default': 'DNS'},
                    'subject_alternative_names': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': 'SANs (e.g., ["*.example.com", "api.example.com"])'
                    },
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['domain_name']
            },
            'handler': request_acm_certificate
        },
        # ---- Previously Unregistered Existing Tools ----
        {
            'name': 'list_cloudtrail_trails',
            'description': 'List CloudTrail trails for audit logging.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_cloudtrail_trails
        },
        {
            'name': 'list_config_rules',
            'description': 'List AWS Config rules for compliance monitoring.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_config_rules
        },
        {
            'name': 'list_organization_accounts',
            'description': 'List AWS Organization member accounts.',
            'input_schema': {
                'type': 'object',
                'properties': {}
            },
            'handler': list_organization_accounts
        },
        {
            'name': 'list_service_catalog_products',
            'description': 'List AWS Service Catalog products.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_service_catalog_products
        },
        {
            'name': 'list_trusted_advisor_checks',
            'description': 'List AWS Trusted Advisor checks for cost optimization, security, and performance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_trusted_advisor_checks
        },
        {
            'name': 'list_aws_resource_groups',
            'description': 'List AWS Resource Groups.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_resource_groups
        },
        {
            'name': 'list_codeartifact_repositories',
            'description': 'List AWS CodeArtifact repositories for package management.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_codeartifact_repositories
        },
        {
            'name': 'list_xray_traces',
            'description': 'List recent AWS X-Ray traces for distributed tracing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_xray_traces
        },
        # ---- EKS Kubernetes ----
        {
            'name': 'create_eks_cluster',
            'description': 'Create an EKS (Kubernetes) cluster. Requires a service role ARN and subnets.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'Cluster name'},
                    'role_arn': {'type': 'string', 'description': 'IAM role ARN for the EKS service'},
                    'subnet_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs (at least 2)'},
                    'security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs'},
                    'kubernetes_version': {'type': 'string', 'description': 'K8s version (e.g., 1.28)'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'role_arn', 'subnet_ids']
            },
            'handler': create_eks_cluster
        },
        {
            'name': 'delete_eks_cluster',
            'description': 'Delete an EKS cluster. All node groups must be deleted first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'Cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': delete_eks_cluster
        },
        {
            'name': 'create_eks_node_group',
            'description': 'Create a managed node group for an EKS cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'node_group_name': {'type': 'string', 'description': 'Node group name'},
                    'node_role_arn': {'type': 'string', 'description': 'IAM role ARN for worker nodes'},
                    'subnet_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs'},
                    'instance_types': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Instance types (e.g., ["t3.medium"])'},
                    'scaling_config_min': {'type': 'integer', 'description': 'Min nodes (default: 1)', 'default': 1},
                    'scaling_config_max': {'type': 'integer', 'description': 'Max nodes (default: 3)', 'default': 3},
                    'scaling_config_desired': {'type': 'integer', 'description': 'Desired nodes (default: 2)', 'default': 2},
                    'disk_size': {'type': 'integer', 'description': 'Disk size GB (default: 20)', 'default': 20},
                    'ami_type': {'type': 'string', 'enum': ['AL2_x86_64', 'AL2_x86_64_GPU', 'AL2_ARM_64'], 'default': 'AL2_x86_64'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'node_group_name', 'node_role_arn', 'subnet_ids']
            },
            'handler': create_eks_node_group
        },
        # ---- EKS Extended ----
        {
            'name': 'describe_eks_cluster',
            'description': 'Get detailed info about an EKS cluster including endpoint, version, OIDC issuer, logging config, and VPC settings.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': describe_eks_cluster
        },
        {
            'name': 'update_eks_cluster_version',
            'description': 'Upgrade the Kubernetes control plane version of an EKS cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'kubernetes_version': {'type': 'string', 'description': 'Target K8s version (e.g., "1.29")'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'kubernetes_version']
            },
            'handler': update_eks_cluster_version
        },
        {
            'name': 'update_eks_cluster_config',
            'description': 'Modify EKS API server endpoint access (public/private) and allowed CIDRs.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'endpoint_public_access': {'type': 'boolean', 'description': 'Enable/disable public endpoint'},
                    'endpoint_private_access': {'type': 'boolean', 'description': 'Enable/disable private endpoint'},
                    'public_access_cidrs': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Allowed CIDRs for public access'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': update_eks_cluster_config
        },
        {
            'name': 'enable_eks_control_plane_logging',
            'description': 'Enable EKS control plane logging to CloudWatch (api, audit, authenticator, controllerManager, scheduler).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'log_types': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Log types to enable (default: all)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': enable_eks_control_plane_logging
        },
        {
            'name': 'associate_eks_oidc_provider',
            'description': 'Associate OIDC identity provider with EKS cluster to enable IAM Roles for Service Accounts (IRSA).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': associate_eks_oidc_provider
        },
        {
            'name': 'delete_eks_node_group',
            'description': 'Delete a managed node group from an EKS cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'node_group_name': {'type': 'string', 'description': 'Node group name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'node_group_name']
            },
            'handler': delete_eks_node_group
        },
        {
            'name': 'list_eks_node_groups',
            'description': 'List all node groups in an EKS cluster with instance types, scaling config, and status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': list_eks_node_groups
        },
        {
            'name': 'describe_eks_node_group',
            'description': 'Get full details of an EKS node group: AMI type, instance types, scaling config, labels, and status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'node_group_name': {'type': 'string', 'description': 'Node group name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'node_group_name']
            },
            'handler': describe_eks_node_group
        },
        {
            'name': 'update_eks_node_group_version',
            'description': 'Upgrade node group AMI or Kubernetes version.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'node_group_name': {'type': 'string', 'description': 'Node group name'},
                    'kubernetes_version': {'type': 'string', 'description': 'Target K8s version'},
                    'release_version': {'type': 'string', 'description': 'Specific AMI release version'},
                    'force': {'type': 'boolean', 'description': 'Force update even if pods cannot be evicted', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'node_group_name']
            },
            'handler': update_eks_node_group_version
        },
        {
            'name': 'update_eks_node_group_config',
            'description': 'Modify min/max/desired scaling values and labels for an EKS node group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'node_group_name': {'type': 'string', 'description': 'Node group name'},
                    'min_size': {'type': 'integer', 'description': 'Minimum node count'},
                    'max_size': {'type': 'integer', 'description': 'Maximum node count'},
                    'desired_size': {'type': 'integer', 'description': 'Desired node count'},
                    'labels_add': {'type': 'object', 'description': 'Labels to add or update'},
                    'labels_remove': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Label keys to remove'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'node_group_name']
            },
            'handler': update_eks_node_group_config
        },
        {
            'name': 'create_eks_fargate_profile',
            'description': 'Create a Fargate profile to run pods serverlessly without managing EC2 nodes.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'profile_name': {'type': 'string', 'description': 'Fargate profile name'},
                    'pod_execution_role_arn': {'type': 'string', 'description': 'IAM role ARN for Fargate pod execution'},
                    'selectors': {'type': 'array', 'description': 'Namespace/label selectors [{namespace, labels}]', 'items': {'type': 'object'}},
                    'subnets': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Private subnet IDs'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'profile_name', 'pod_execution_role_arn', 'selectors']
            },
            'handler': create_eks_fargate_profile
        },
        {
            'name': 'delete_eks_fargate_profile',
            'description': 'Delete an EKS Fargate profile.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'profile_name': {'type': 'string', 'description': 'Fargate profile name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'profile_name']
            },
            'handler': delete_eks_fargate_profile
        },
        {
            'name': 'list_eks_fargate_profiles',
            'description': 'List all Fargate profiles for an EKS cluster with selectors and status.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': list_eks_fargate_profiles
        },
        {
            'name': 'create_eks_access_entry',
            'description': 'Add an IAM principal (user or role) to EKS cluster access using the EKS Access API.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'principal_arn': {'type': 'string', 'description': 'IAM user or role ARN'},
                    'username': {'type': 'string', 'description': 'Kubernetes username override'},
                    'groups': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Kubernetes group memberships'},
                    'entry_type': {'type': 'string', 'enum': ['STANDARD', 'FARGATE_LINUX', 'EC2_LINUX', 'EC2_WINDOWS'], 'default': 'STANDARD'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'principal_arn']
            },
            'handler': create_eks_access_entry
        },
        {
            'name': 'delete_eks_access_entry',
            'description': 'Remove an IAM principal from EKS cluster access.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'principal_arn': {'type': 'string', 'description': 'IAM user or role ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'principal_arn']
            },
            'handler': delete_eks_access_entry
        },
        {
            'name': 'associate_eks_access_policy',
            'description': 'Bind an EKS access policy (AmazonEKSClusterAdminPolicy, AmazonEKSAdminPolicy, etc.) to an IAM principal.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'principal_arn': {'type': 'string', 'description': 'IAM user or role ARN'},
                    'policy_arn': {'type': 'string', 'description': 'EKS policy ARN (e.g., arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy)'},
                    'access_scope_type': {'type': 'string', 'enum': ['cluster', 'namespace'], 'default': 'cluster'},
                    'namespaces': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Namespaces (only for namespace scope)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'principal_arn', 'policy_arn']
            },
            'handler': associate_eks_access_policy
        },
        {
            'name': 'generate_eks_kubeconfig',
            'description': 'Generate kubeconfig content for kubectl access to an EKS cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'},
                    'role_arn': {'type': 'string', 'description': 'IAM role ARN to assume when authenticating'}
                },
                'required': ['cluster_name']
            },
            'handler': generate_eks_kubeconfig
        },
        {
            'name': 'create_eks_addon',
            'description': 'Install a managed EKS add-on (CoreDNS, kube-proxy, vpc-cni, aws-ebs-csi-driver).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'addon_name': {'type': 'string', 'description': 'Add-on name (e.g., "coredns", "kube-proxy", "vpc-cni", "aws-ebs-csi-driver")'},
                    'addon_version': {'type': 'string', 'description': 'Specific version (omit for latest)'},
                    'service_account_role_arn': {'type': 'string', 'description': 'IAM role ARN for IRSA'},
                    'resolve_conflicts': {'type': 'string', 'enum': ['OVERWRITE', 'NONE', 'PRESERVE'], 'default': 'OVERWRITE'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'addon_name']
            },
            'handler': create_eks_addon
        },
        {
            'name': 'delete_eks_addon',
            'description': 'Remove an installed EKS add-on from a cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'addon_name': {'type': 'string', 'description': 'Add-on name'},
                    'preserve': {'type': 'boolean', 'description': 'Preserve add-on software on cluster', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'addon_name']
            },
            'handler': delete_eks_addon
        },
        {
            'name': 'list_eks_addons',
            'description': 'List all installed EKS add-ons and their versions for a cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': list_eks_addons
        },
        {
            'name': 'update_eks_addon',
            'description': 'Upgrade an EKS add-on to a newer version.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'EKS cluster name'},
                    'addon_name': {'type': 'string', 'description': 'Add-on name'},
                    'addon_version': {'type': 'string', 'description': 'Target version'},
                    'resolve_conflicts': {'type': 'string', 'enum': ['OVERWRITE', 'NONE', 'PRESERVE'], 'default': 'OVERWRITE'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name', 'addon_name', 'addon_version']
            },
            'handler': update_eks_addon
        },
        {
            'name': 'describe_eks_addon_versions',
            'description': 'List all available versions for a given EKS add-on and compatible Kubernetes versions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'addon_name': {'type': 'string', 'description': 'Add-on name'},
                    'kubernetes_version': {'type': 'string', 'description': 'Filter by compatible K8s version (e.g., "1.29")'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['addon_name']
            },
            'handler': describe_eks_addon_versions
        },
        # ---- ECR Container Registry ----
        {
            'name': 'create_ecr_repository',
            'description': 'Create an ECR repository for Docker container images.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repository_name': {'type': 'string', 'description': 'Repository name'},
                    'image_tag_mutability': {'type': 'string', 'enum': ['MUTABLE', 'IMMUTABLE'], 'default': 'MUTABLE'},
                    'scan_on_push': {'type': 'boolean', 'description': 'Scan images on push (default: true)', 'default': True},
                    'encryption_type': {'type': 'string', 'enum': ['AES256', 'KMS'], 'default': 'AES256'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['repository_name']
            },
            'handler': create_ecr_repository
        },
        {
            'name': 'delete_ecr_repository',
            'description': 'Delete an ECR repository. Use force=true to delete even with images.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repository_name': {'type': 'string', 'description': 'Repository name'},
                    'force': {'type': 'boolean', 'description': 'Force delete with images (default: false)', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['repository_name']
            },
            'handler': delete_ecr_repository
        },
        # ---- Secrets Manager ----
        {
            'name': 'create_secret',
            'description': 'Create a secret in AWS Secrets Manager.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_name': {'type': 'string', 'description': 'Secret name'},
                    'secret_value': {'type': 'string', 'description': 'Secret value (string or JSON)'},
                    'description': {'type': 'string', 'description': 'Description'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['secret_name', 'secret_value']
            },
            'handler': create_secret
        },
        {
            'name': 'update_secret',
            'description': 'Update the value of a secret in Secrets Manager.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_name': {'type': 'string', 'description': 'Secret name or ARN'},
                    'secret_value': {'type': 'string', 'description': 'New secret value'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['secret_name', 'secret_value']
            },
            'handler': update_secret
        },
        {
            'name': 'delete_secret',
            'description': 'Delete a secret from Secrets Manager (30-day recovery window by default).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_name': {'type': 'string', 'description': 'Secret name or ARN'},
                    'force_delete': {'type': 'boolean', 'description': 'Skip recovery window (default: false)', 'default': False},
                    'recovery_window_days': {'type': 'integer', 'description': 'Recovery window in days (7-30, default: 30)', 'default': 30},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['secret_name']
            },
            'handler': delete_secret
        },
        # ---- CloudFront ----
        {
            'name': 'create_cloudfront_invalidation',
            'description': 'Invalidate CloudFront cache for specified paths (e.g., ["/*"] for all).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'distribution_id': {'type': 'string', 'description': 'CloudFront distribution ID'},
                    'paths': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Paths to invalidate (e.g., ["/*", "/images/*"])'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['distribution_id', 'paths']
            },
            'handler': create_cloudfront_invalidation
        },
        # ---- NAT Gateway ----
        {
            'name': 'create_nat_gateway',
            'description': 'Create a NAT gateway in a public subnet for private subnet internet access.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Public subnet ID'},
                    'allocation_id': {'type': 'string', 'description': 'Elastic IP allocation ID (required for public NAT)'},
                    'connectivity_type': {'type': 'string', 'enum': ['public', 'private'], 'default': 'public'},
                    'name': {'type': 'string', 'description': 'Name tag'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['subnet_id']
            },
            'handler': create_nat_gateway
        },
        {
            'name': 'delete_nat_gateway',
            'description': 'Delete a NAT gateway.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'nat_gateway_id': {'type': 'string', 'description': 'NAT gateway ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['nat_gateway_id']
            },
            'handler': delete_nat_gateway
        },
        # ---- ElastiCache ----
        {
            'name': 'create_elasticache_cluster',
            'description': 'Create an ElastiCache cluster (Redis or Memcached).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_id': {'type': 'string', 'description': 'Cluster ID'},
                    'engine': {'type': 'string', 'enum': ['redis', 'memcached'], 'default': 'redis'},
                    'node_type': {'type': 'string', 'description': 'Node type (default: cache.t3.micro)', 'default': 'cache.t3.micro'},
                    'num_nodes': {'type': 'integer', 'description': 'Number of nodes (default: 1)', 'default': 1},
                    'engine_version': {'type': 'string', 'description': 'Engine version'},
                    'security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Security group IDs'},
                    'subnet_group_name': {'type': 'string', 'description': 'Cache subnet group name'},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_id']
            },
            'handler': create_elasticache_cluster
        },
        {
            'name': 'delete_elasticache_cluster',
            'description': 'Delete an ElastiCache cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_id': {'type': 'string', 'description': 'Cluster ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_id']
            },
            'handler': delete_elasticache_cluster
        },
        # ---- EFS File System ----
        {
            'name': 'create_efs_file_system',
            'description': 'Create an EFS file system (encrypted by default).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'creation_token': {'type': 'string', 'description': 'Unique creation token (auto-generated if not specified)'},
                    'performance_mode': {'type': 'string', 'enum': ['generalPurpose', 'maxIO'], 'default': 'generalPurpose'},
                    'throughput_mode': {'type': 'string', 'enum': ['bursting', 'provisioned', 'elastic'], 'default': 'bursting'},
                    'encrypted': {'type': 'boolean', 'description': 'Encrypt at rest (default: true)', 'default': True},
                    'tags': {'type': 'object', 'description': 'Tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': create_efs_file_system
        },
        {
            'name': 'delete_efs_file_system',
            'description': 'Delete an EFS file system. Mount targets must be deleted first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'file_system_id': {'type': 'string', 'description': 'EFS file system ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['file_system_id']
            },
            'handler': delete_efs_file_system
        },
        # ---- EventBridge ----
        {
            'name': 'create_eventbridge_rule',
            'description': (
                'Create an EventBridge rule for scheduling or event matching. '
                'Schedule examples: "rate(5 minutes)", "cron(0 12 * * ? *)".'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rule_name': {'type': 'string', 'description': 'Rule name'},
                    'schedule_expression': {'type': 'string', 'description': 'Schedule (e.g., "rate(1 hour)", "cron(0 12 * * ? *)")'},
                    'event_pattern': {'type': 'string', 'description': 'Event pattern JSON (alternative to schedule)'},
                    'state': {'type': 'string', 'enum': ['ENABLED', 'DISABLED'], 'default': 'ENABLED'},
                    'description': {'type': 'string', 'description': 'Rule description'},
                    'event_bus_name': {'type': 'string', 'description': 'Event bus name (default: default)'},
                    'targets': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'string', 'description': 'Target ID'},
                                'arn': {'type': 'string', 'description': 'Target ARN (Lambda, SNS, SQS, etc.)'}
                            },
                            'required': ['id', 'arn']
                        },
                        'description': 'Targets to invoke when rule matches'
                    },
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['rule_name']
            },
            'handler': create_eventbridge_rule
        },
        {
            'name': 'delete_eventbridge_rule',
            'description': 'Delete an EventBridge rule and its targets.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'rule_name': {'type': 'string', 'description': 'Rule name'},
                    'event_bus_name': {'type': 'string', 'description': 'Event bus name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['rule_name']
            },
            'handler': delete_eventbridge_rule
        },
        # ---- Step Functions ----
        {
            'name': 'start_step_function_execution',
            'description': 'Start an execution of a Step Functions state machine.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'state_machine_arn': {'type': 'string', 'description': 'State machine ARN'},
                    'execution_name': {'type': 'string', 'description': 'Execution name (auto-generated if not specified)'},
                    'input_data': {'type': 'string', 'description': 'Input JSON string for the execution'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['state_machine_arn']
            },
            'handler': start_step_function_execution
        },
        # ---- Kinesis ----
        {
            'name': 'create_kinesis_stream',
            'description': 'Create a Kinesis data stream for real-time data processing.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'stream_name': {'type': 'string', 'description': 'Stream name'},
                    'shard_count': {'type': 'integer', 'description': 'Number of shards (default: 1)', 'default': 1},
                    'stream_mode': {'type': 'string', 'enum': ['PROVISIONED', 'ON_DEMAND'], 'default': 'PROVISIONED'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['stream_name']
            },
            'handler': create_kinesis_stream
        },
        {
            'name': 'delete_kinesis_stream',
            'description': 'Delete a Kinesis data stream.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'stream_name': {'type': 'string', 'description': 'Stream name'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['stream_name']
            },
            'handler': delete_kinesis_stream
        },
        # ---- Round 4: Delete/Update completions ----
        {
            'name': 'delete_rds_instance',
            'description': 'Delete an RDS database instance. Optionally skip final snapshot.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_id': {'type': 'string', 'description': 'DB instance identifier'},
                    'skip_final_snapshot': {'type': 'boolean', 'description': 'Skip final snapshot (default: False)', 'default': False},
                    'final_snapshot_id': {'type': 'string', 'description': 'Final snapshot identifier (required if skip_final_snapshot is False)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_id']
            },
            'handler': delete_rds_instance
        },
        # ---- RDS Extended Operations ----
        {
            'name': 'describe_rds_instance',
            'description': 'Get full details of a specific RDS instance (engine, class, endpoints, storage, Multi-AZ, etc.).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': describe_rds_instance
        },
        {
            'name': 'start_rds_instance',
            'description': 'Start a stopped RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': start_rds_instance
        },
        {
            'name': 'stop_rds_instance',
            'description': 'Stop a running RDS instance to save costs.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'db_snapshot_identifier': {'type': 'string', 'description': 'Optional snapshot to create on stop'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': stop_rds_instance
        },
        {
            'name': 'reboot_rds_instance',
            'description': 'Reboot a DB instance, optionally forcing a Multi-AZ failover.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'force_failover': {'type': 'boolean', 'description': 'Force failover to standby (Multi-AZ only, default: false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': reboot_rds_instance
        },
        {
            'name': 'modify_rds_instance',
            'description': 'Modify RDS instance settings — class, storage, Multi-AZ, engine version, backup window, deletion protection.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'db_instance_class': {'type': 'string', 'description': 'New instance class (e.g., db.t3.medium)'},
                    'allocated_storage': {'type': 'integer', 'description': 'New storage in GB'},
                    'backup_retention_period': {'type': 'integer', 'description': 'Backup retention days (1-35)'},
                    'preferred_backup_window': {'type': 'string', 'description': 'Backup window (e.g., 03:00-04:00)'},
                    'preferred_maintenance_window': {'type': 'string', 'description': 'Maintenance window (e.g., Mon:05:00-Mon:06:00)'},
                    'multi_az': {'type': 'boolean', 'description': 'Enable Multi-AZ'},
                    'auto_minor_version_upgrade': {'type': 'boolean', 'description': 'Enable auto minor version upgrades'},
                    'deletion_protection': {'type': 'boolean', 'description': 'Enable deletion protection'},
                    'engine_version': {'type': 'string', 'description': 'Target engine version for upgrade'},
                    'apply_immediately': {'type': 'boolean', 'description': 'Apply immediately vs next maintenance window (default: false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': modify_rds_instance
        },
        {
            'name': 'tag_rds_instance',
            'description': 'Add or update tags on an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'tags': {'type': 'object', 'description': 'Key-value tags to apply'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier', 'tags']
            },
            'handler': tag_rds_instance
        },
        {
            'name': 'create_rds_snapshot',
            'description': 'Take a manual point-in-time snapshot of an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'Source DB instance identifier'},
                    'db_snapshot_identifier': {'type': 'string', 'description': 'Name for the snapshot'},
                    'tags': {'type': 'object', 'description': 'Key-value tags'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier', 'db_snapshot_identifier']
            },
            'handler': create_rds_snapshot
        },
        {
            'name': 'list_rds_snapshots',
            'description': 'List DB snapshots (manual or automated).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'Filter by DB instance (optional)'},
                    'snapshot_type': {'type': 'string', 'enum': ['manual', 'automated', 'shared', 'public'], 'description': 'Snapshot type (default: manual)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_rds_snapshots
        },
        {
            'name': 'delete_rds_snapshot',
            'description': 'Delete a manual RDS snapshot.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_snapshot_identifier': {'type': 'string', 'description': 'Snapshot identifier to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_snapshot_identifier']
            },
            'handler': delete_rds_snapshot
        },
        {
            'name': 'restore_rds_from_snapshot',
            'description': 'Launch a new RDS instance from a snapshot.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_snapshot_identifier': {'type': 'string', 'description': 'Snapshot to restore from'},
                    'db_instance_identifier': {'type': 'string', 'description': 'Name for the new DB instance'},
                    'db_instance_class': {'type': 'string', 'description': 'Instance class (e.g., db.t3.medium)'},
                    'db_subnet_group_name': {'type': 'string', 'description': 'DB subnet group'},
                    'vpc_security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'VPC security group IDs'},
                    'publicly_accessible': {'type': 'boolean', 'description': 'Make publicly accessible (default: false)'},
                    'multi_az': {'type': 'boolean', 'description': 'Enable Multi-AZ (default: false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_snapshot_identifier', 'db_instance_identifier']
            },
            'handler': restore_rds_from_snapshot
        },
        {
            'name': 'copy_rds_snapshot',
            'description': 'Duplicate a DB snapshot within or across regions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'source_snapshot_identifier': {'type': 'string', 'description': 'Source snapshot identifier or ARN'},
                    'target_snapshot_identifier': {'type': 'string', 'description': 'Name for the copy'},
                    'source_region': {'type': 'string', 'description': 'Source region (for cross-region copy)'},
                    'kms_key_id': {'type': 'string', 'description': 'KMS key for encrypting the copy'},
                    'region': {'type': 'string', 'description': 'Target AWS region'}
                },
                'required': ['source_snapshot_identifier', 'target_snapshot_identifier']
            },
            'handler': copy_rds_snapshot
        },
        {
            'name': 'restore_rds_to_point_in_time',
            'description': 'Launch a new DB instance from any point within the backup retention window.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'source_db_instance_identifier': {'type': 'string', 'description': 'Source DB instance'},
                    'target_db_instance_identifier': {'type': 'string', 'description': 'Name for the restored instance'},
                    'restore_time': {'type': 'string', 'description': 'ISO 8601 timestamp to restore to (e.g., 2026-01-14T12:00:00)'},
                    'use_latest_restorable_time': {'type': 'boolean', 'description': 'Restore to latest restorable time (overrides restore_time)'},
                    'db_instance_class': {'type': 'string', 'description': 'Instance class for restored instance'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['source_db_instance_identifier', 'target_db_instance_identifier']
            },
            'handler': restore_rds_to_point_in_time
        },
        {
            'name': 'create_db_parameter_group',
            'description': 'Create a DB parameter group for custom engine configuration.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'Parameter group name'},
                    'family': {'type': 'string', 'description': 'Parameter group family (e.g., mysql8.0, postgres15, aurora-mysql8.0)'},
                    'description': {'type': 'string', 'description': 'Description'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name', 'family', 'description']
            },
            'handler': create_db_parameter_group
        },
        {
            'name': 'list_db_parameter_groups',
            'description': 'List all DB parameter groups in the account.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_db_parameter_groups
        },
        {
            'name': 'modify_db_parameter_group',
            'description': 'Update parameter values in a DB parameter group. Parameters format: [{"name": "max_connections", "value": "200", "apply_method": "immediate"}]',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'Parameter group name'},
                    'parameters': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string', 'description': 'Parameter name'},
                                'value': {'type': 'string', 'description': 'Parameter value'},
                                'apply_method': {'type': 'string', 'enum': ['immediate', 'pending-reboot'], 'description': 'When to apply'}
                            },
                            'required': ['name', 'value']
                        },
                        'description': 'List of parameters to modify'
                    },
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name', 'parameters']
            },
            'handler': modify_db_parameter_group
        },
        {
            'name': 'delete_db_parameter_group',
            'description': 'Delete a custom DB parameter group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'Parameter group name to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name']
            },
            'handler': delete_db_parameter_group
        },
        {
            'name': 'create_db_subnet_group',
            'description': 'Create a DB subnet group to define which subnets RDS can use for Multi-AZ deployments.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'Subnet group name'},
                    'description': {'type': 'string', 'description': 'Description'},
                    'subnet_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Subnet IDs (at least 2 different AZs required)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name', 'description', 'subnet_ids']
            },
            'handler': create_db_subnet_group
        },
        {
            'name': 'list_db_subnet_groups',
            'description': 'List all DB subnet groups with their AZ coverage.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_db_subnet_groups
        },
        {
            'name': 'delete_db_subnet_group',
            'description': 'Delete a DB subnet group.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_name': {'type': 'string', 'description': 'Subnet group name to delete'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['group_name']
            },
            'handler': delete_db_subnet_group
        },
        {
            'name': 'rotate_rds_master_password',
            'description': 'Update the master user password on an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'new_password': {'type': 'string', 'description': 'New master password (min 8 chars)'},
                    'apply_immediately': {'type': 'boolean', 'description': 'Apply immediately (default: true)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier', 'new_password']
            },
            'handler': rotate_rds_master_password
        },
        {
            'name': 'enable_rds_iam_auth',
            'description': 'Enable or disable IAM database authentication on an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'enable': {'type': 'boolean', 'description': 'True to enable, False to disable (default: true)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': enable_rds_iam_auth
        },
        {
            'name': 'list_rds_log_files',
            'description': 'List available log files on an RDS instance (error, slow query, general).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': list_rds_log_files
        },
        {
            'name': 'download_rds_log_file',
            'description': 'Download a specific log file from an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'DB instance identifier'},
                    'log_file_name': {'type': 'string', 'description': 'Log file name (from list_rds_log_files)'},
                    'max_lines': {'type': 'integer', 'description': 'Maximum lines to return (default: 500)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier', 'log_file_name']
            },
            'handler': download_rds_log_file
        },
        {
            'name': 'list_rds_events',
            'description': 'List recent RDS events (failovers, backups, maintenance, errors).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'Filter by DB instance (optional)'},
                    'duration_minutes': {'type': 'integer', 'description': 'How far back to look in minutes (default: 60)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_rds_events
        },
        {
            'name': 'create_rds_read_replica',
            'description': 'Create a read-only replica of an RDS instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'source_db_instance_identifier': {'type': 'string', 'description': 'Source DB instance to replicate'},
                    'replica_identifier': {'type': 'string', 'description': 'Name for the replica instance'},
                    'db_instance_class': {'type': 'string', 'description': 'Instance class (defaults to source class)'},
                    'availability_zone': {'type': 'string', 'description': 'AZ for the replica'},
                    'publicly_accessible': {'type': 'boolean', 'description': 'Make publicly accessible (default: false)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['source_db_instance_identifier', 'replica_identifier']
            },
            'handler': create_rds_read_replica
        },
        {
            'name': 'promote_rds_read_replica',
            'description': 'Promote a read replica to a standalone DB instance (breaks replication).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'Replica instance identifier'},
                    'backup_retention_period': {'type': 'integer', 'description': 'Backup retention for the promoted instance (default: 1)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_instance_identifier']
            },
            'handler': promote_rds_read_replica
        },
        {
            'name': 'create_aurora_cluster',
            'description': 'Provision an Aurora MySQL or PostgreSQL cluster.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_cluster_identifier': {'type': 'string', 'description': 'Cluster identifier'},
                    'engine': {'type': 'string', 'enum': ['aurora-mysql', 'aurora-postgresql'], 'description': 'Engine type'},
                    'master_username': {'type': 'string', 'description': 'Master username'},
                    'master_password': {'type': 'string', 'description': 'Master password'},
                    'db_subnet_group_name': {'type': 'string', 'description': 'DB subnet group name'},
                    'vpc_security_group_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'VPC security group IDs'},
                    'availability_zones': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Availability zones'},
                    'backup_retention_period': {'type': 'integer', 'description': 'Backup retention days (default: 7)'},
                    'database_name': {'type': 'string', 'description': 'Initial database name'},
                    'engine_version': {'type': 'string', 'description': 'Engine version'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_cluster_identifier', 'engine', 'master_username', 'master_password']
            },
            'handler': create_aurora_cluster
        },
        {
            'name': 'list_aurora_clusters',
            'description': 'List all Aurora DB clusters with endpoints and member counts.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': list_aurora_clusters
        },
        {
            'name': 'delete_aurora_cluster',
            'description': 'Delete an Aurora cluster (all cluster instances must be deleted first).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_cluster_identifier': {'type': 'string', 'description': 'Cluster identifier'},
                    'skip_final_snapshot': {'type': 'boolean', 'description': 'Skip final snapshot (default: false)'},
                    'final_snapshot_identifier': {'type': 'string', 'description': 'Name for final snapshot'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_cluster_identifier']
            },
            'handler': delete_aurora_cluster
        },
        {
            'name': 'failover_aurora_cluster',
            'description': 'Trigger a failover for an Aurora cluster (promotes a reader to writer).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_cluster_identifier': {'type': 'string', 'description': 'Cluster identifier'},
                    'target_db_instance_identifier': {'type': 'string', 'description': 'Specific reader to promote (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['db_cluster_identifier']
            },
            'handler': failover_aurora_cluster
        },
        {
            'name': 'describe_pending_rds_maintenance',
            'description': 'View queued maintenance actions for RDS instances (OS patches, engine upgrades).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'db_instance_identifier': {'type': 'string', 'description': 'Filter by DB instance (optional)'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': describe_pending_rds_maintenance
        },
        {
            'name': 'describe_rds_engine_versions',
            'description': 'List supported RDS engine versions, their features, and upgrade paths.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'engine': {'type': 'string', 'description': 'Filter by engine (e.g., mysql, postgres, aurora-mysql)'},
                    'engine_version': {'type': 'string', 'description': 'Filter by specific version'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                }
            },
            'handler': describe_rds_engine_versions
        },
        {
            'name': 'delete_lambda_function',
            'description': 'Delete a Lambda function.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'function_name': {'type': 'string', 'description': 'Function name or ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['function_name']
            },
            'handler': delete_lambda_function
        },
        {
            'name': 'update_lambda_function_config',
            'description': 'Update a Lambda function configuration (memory, timeout, env vars, runtime).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'function_name': {'type': 'string', 'description': 'Function name or ARN'},
                    'memory_size': {'type': 'integer', 'description': 'Memory in MB (128-10240)'},
                    'timeout': {'type': 'integer', 'description': 'Timeout in seconds (1-900)'},
                    'runtime': {'type': 'string', 'description': 'Runtime (e.g., python3.12, nodejs20.x)'},
                    'environment': {'type': 'object', 'description': 'Environment variables as key-value pairs'},
                    'description': {'type': 'string', 'description': 'Function description'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['function_name']
            },
            'handler': update_lambda_function_config
        },
        {
            'name': 'delete_ecs_cluster',
            'description': 'Delete an ECS cluster (must have no running services or tasks).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cluster_name': {'type': 'string', 'description': 'Cluster name or ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['cluster_name']
            },
            'handler': delete_ecs_cluster
        },
        {
            'name': 'delete_sns_topic',
            'description': 'Delete an SNS topic and all its subscriptions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_arn': {'type': 'string', 'description': 'SNS topic ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['topic_arn']
            },
            'handler': delete_sns_topic
        },
        {
            'name': 'delete_sqs_queue',
            'description': 'Delete an SQS queue.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'queue_url': {'type': 'string', 'description': 'SQS queue URL'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['queue_url']
            },
            'handler': delete_sqs_queue
        },
        {
            'name': 'delete_iam_role',
            'description': 'Delete an IAM role. Automatically detaches all policies and removes from instance profiles first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'role_name': {'type': 'string', 'description': 'IAM role name'}
                },
                'required': ['role_name']
            },
            'handler': delete_iam_role
        },
        {
            'name': 'delete_listener',
            'description': 'Delete a listener from a load balancer.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'listener_arn': {'type': 'string', 'description': 'Listener ARN'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['listener_arn']
            },
            'handler': delete_listener
        },
        {
            'name': 'delete_subnet',
            'description': 'Delete a subnet from a VPC.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'subnet_id': {'type': 'string', 'description': 'Subnet ID'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['subnet_id']
            },
            'handler': delete_subnet
        },
        {
            'name': 'detach_ebs_volume',
            'description': 'Detach an EBS volume from an EC2 instance.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'volume_id': {'type': 'string', 'description': 'EBS volume ID'},
                    'instance_id': {'type': 'string', 'description': 'Instance ID (optional, detaches from current)'},
                    'force': {'type': 'boolean', 'description': 'Force detach (default: False)', 'default': False},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['volume_id']
            },
            'handler': detach_ebs_volume
        },
        {
            'name': 'list_service_quotas',
            'description': 'List AWS service quotas (limits) for a specific service like EC2, S3, Lambda, etc.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service_code': {'type': 'string', 'description': 'AWS service code (e.g., "ec2", "s3", "lambda", "rds")'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['service_code']
            },
            'handler': list_service_quotas
        },
        {
            'name': 'resize_ec2_instance',
            'description': 'Resize an EC2 instance by changing its type. Stops the instance, modifies type, then restarts it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_id': {
                        'type': 'string',
                        'description': 'EC2 instance ID (e.g., i-0123456789abcdef0)'
                    },
                    'new_instance_type': {
                        'type': 'string',
                        'description': 'Target instance type (e.g., t3.small, t3.medium, m5.large)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['instance_id', 'new_instance_type']
            },
            'handler': resize_ec2_instance
        },
        {
            'name': 'describe_security_group',
            'description': 'Get full details of a security group including all ingress and egress rules.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group_id': {
                        'type': 'string',
                        'description': 'Security group ID (e.g., sg-0123456789abcdef0)'
                    },
                    'region': {
                        'type': 'string',
                        'description': 'AWS region'
                    }
                },
                'required': ['group_id']
            },
            'handler': describe_security_group
        },
        {
            'name': 'aws_api_read',
            'description': (
                'Call ANY AWS read-only API operation when no dedicated tool exists. '
                'Use for describe/list/get/head operations across any AWS service. '
                'Examples: describe_task_definition (ECS), list_hosted_zones (Route53), '
                'list_certificates (ACM), describe_vpc_endpoints (EC2), '
                'get_function_configuration (Lambda), describe_log_groups (CloudWatch Logs). '
                'Never use for create/update/delete — use aws_api_write for those.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service': {'type': 'string', 'description': 'AWS service name (e.g. ec2, s3, ecs, route53, acm, cloudwatch, logs, iam, ssm)'},
                    'operation': {'type': 'string', 'description': 'boto3 method name (e.g. describe_instances, list_hosted_zones, get_function)'},
                    'params': {'type': 'object', 'description': 'Method parameters as key-value pairs'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['service', 'operation']
            },
            'handler': aws_api_read
        },
        {
            'name': 'aws_api_write',
            'description': (
                'Call ANY AWS write API operation when no dedicated tool exists. '
                'Use for create/update/delete/put/modify/attach/detach/enable/disable operations. '
                'Examples: delete_alarms (CloudWatch), modify_db_instance (RDS), '
                'update_function_configuration (Lambda), change_resource_record_sets (Route53), '
                'put_bucket_lifecycle_configuration (S3). '
                'Always confirm the exact operation and params with the user before calling.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'service': {'type': 'string', 'description': 'AWS service name (e.g. ec2, rds, lambda, s3, cloudwatch, iam)'},
                    'operation': {'type': 'string', 'description': 'boto3 method name (e.g. delete_alarms, modify_db_instance, update_function_configuration)'},
                    'params': {'type': 'object', 'description': 'Method parameters as key-value pairs'},
                    'region': {'type': 'string', 'description': 'AWS region'}
                },
                'required': ['service', 'operation']
            },
            'handler': aws_api_write
        },
    ]
