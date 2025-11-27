"""AWS tools for DevOps Agent."""
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from ..utils import get_logger


logger = get_logger(__name__)


def _get_boto_client(service: str, region: Optional[str] = None):
    """
    Get boto3 client for AWS service.

    Args:
        service: AWS service name
        region: AWS region

    Returns:
        Boto3 client instance
    """
    try:
        if region:
            return boto3.client(service, region_name=region)
        return boto3.client(service)
    except NoCredentialsError:
        raise Exception("AWS credentials not found. Please configure AWS credentials.")


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
            'region': region or 'default',
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
            'region': region or 'default'
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
        except:
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
        except:
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            except:
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
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing subnets: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            except:
                # If describe fails, just add basic info
                tables.append({'table_name': table_name, 'status': 'Unknown'})

        return {
            'success': True,
            'count': len(tables),
            'tables': tables,
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing DynamoDB tables: {str(e)}", exc_info=True)
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ElastiCache clusters: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ECS services: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
        response = lambda_client.list_functions()

        functions = []
        for func in response.get('Functions', []):
            functions.append({
                'function_name': func['FunctionName'],
                'function_arn': func['FunctionArn'],
                'runtime': func.get('Runtime', 'N/A'),
                'handler': func.get('Handler', 'N/A'),
                'code_size': func.get('CodeSize', 0),
                'memory_size': func.get('MemorySize', 128),
                'timeout': func.get('Timeout', 3),
                'last_modified': func.get('LastModified', 'N/A'),
                'description': func.get('Description', 'N/A')
            })

        return {
            'success': True,
            'count': len(functions),
            'functions': functions,
            'region': region or 'default'
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
        response = rds.describe_db_instances()

        instances = []
        for db in response.get('DBInstances', []):
            instances.append({
                'db_instance_identifier': db['DBInstanceIdentifier'],
                'engine': db.get('Engine'),
                'engine_version': db.get('EngineVersion'),
                'db_instance_class': db.get('DBInstanceClass'),
                'status': db.get('DBInstanceStatus'),
                'endpoint': db.get('Endpoint', {}).get('Address', 'N/A'),
                'port': db.get('Endpoint', {}).get('Port', 'N/A'),
                'allocated_storage': db.get('AllocatedStorage', 0),
                'multi_az': db.get('MultiAZ', False),
                'publicly_accessible': db.get('PubliclyAccessible', False),
                'created_date': db.get('InstanceCreateTime').isoformat() if db.get('InstanceCreateTime') else 'N/A'
            })

        return {
            'success': True,
            'count': len(instances),
            'instances': instances,
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing RDS instances: {str(e)}", exc_info=True)
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing CloudFormation stacks: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SSM managed instances: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
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
            except:
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
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Auto Scaling groups: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            except:
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
            except:
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SNS topics: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing SQS queues: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ECR repositories: {str(e)}", exc_info=True)
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Secrets Manager secrets: {str(e)}", exc_info=True)
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
                except:
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
        except:
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
        except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing load balancers: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EFS file systems: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EventBridge event buses: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Step Functions: {str(e)}", exc_info=True)
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
            except:
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing Kinesis streams: {str(e)}", exc_info=True)
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
            except:
                certificates.append({
                    'domain_name': cert.get('DomainName'),
                    'certificate_arn': cert.get('CertificateArn'),
                    'status': 'UNKNOWN'
                })

        return {
            'success': True,
            'count': len(certificates),
            'certificates': certificates,
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing ACM certificates: {str(e)}", exc_info=True)
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
        except:
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
        except:
            pass

        return {
            'success': True,
            'count': len(web_acls),
            'web_acls': web_acls,
            'region': region or 'default'
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
            except:
                plans.append({
                    'backup_plan_id': plan['BackupPlanId'],
                    'backup_plan_name': plan['BackupPlanName'],
                    'backup_plan_arn': plan['BackupPlanArn']
                })

        return {
            'success': True,
            'count': len(plans),
            'backup_plans': plans,
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing EBS volumes: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            'region': region or 'default'
        }

    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error listing NAT Gateways: {str(e)}", exc_info=True)
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
            'region': region or 'default'
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
            except:
                workgroups.append({
                    'name': wg['Name'],
                    'state': wg.get('State', 'ENABLED'),
                    'description': wg.get('Description', 'N/A')
                })

        return {
            'success': True,
            'count': len(workgroups),
            'workgroups': workgroups,
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            except:
                domains.append({
                    'domain_name': domain['DomainName'],
                    'engine_type': domain.get('EngineType', 'OpenSearch')
                })

        return {
            'success': True,
            'count': len(domains),
            'domains': domains,
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default'
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
            'region': region or 'default',
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


def get_tools() -> List[Dict[str, Any]]:
    """
    Get AWS tool definitions.

    Returns:
        List of tool definitions
    """
    return [
        # EC2 Operations
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
        }
    ]
