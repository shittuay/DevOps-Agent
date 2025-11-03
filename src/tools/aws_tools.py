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
                # Extract key information
                tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}

                instances.append({
                    'instance_id': instance['InstanceId'],
                    'instance_type': instance['InstanceType'],
                    'state': instance['State']['Name'],
                    'private_ip': instance.get('PrivateIpAddress', 'N/A'),
                    'public_ip': instance.get('PublicIpAddress', 'N/A'),
                    'launch_time': instance['LaunchTime'].isoformat(),
                    'availability_zone': instance['Placement']['AvailabilityZone'],
                    'tags': tags,
                    'name': tags.get('Name', 'N/A')
                })

        return {
            'success': True,
            'count': len(instances),
            'instances': instances,
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

def create_ec2_instance(
    ami_id: str,
    instance_type: str,
    key_name: Optional[str] = None,
    security_group_ids: Optional[List[str]] = None,
    subnet_id: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    user_data: Optional[str] = None,
    region: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new EC2 instance.

    Args:
        ami_id: AMI ID to use (e.g., ami-0c55b159cbfafe1f0)
        instance_type: Instance type (e.g., t2.micro, t3.small)
        key_name: SSH key pair name
        security_group_ids: List of security group IDs
        subnet_id: Subnet ID for VPC placement
        tags: Dictionary of tags to apply
        user_data: User data script
        region: AWS region

    Returns:
        Dictionary with created instance information
    """
    try:
        ec2 = _get_boto_client('ec2', region)

        # Build launch parameters
        launch_params = {
            'ImageId': ami_id,
            'InstanceType': instance_type,
            'MinCount': 1,
            'MaxCount': 1
        }

        if key_name:
            launch_params['KeyName'] = key_name

        if security_group_ids:
            launch_params['SecurityGroupIds'] = security_group_ids

        if subnet_id:
            launch_params['SubnetId'] = subnet_id

        if user_data:
            launch_params['UserData'] = user_data

        # Launch instance
        response = ec2.run_instances(**launch_params)
        instance = response['Instances'][0]
        instance_id = instance['InstanceId']

        # Apply tags if provided
        if tags:
            tag_specifications = [{'Key': k, 'Value': v} for k, v in tags.items()]
            ec2.create_tags(
                Resources=[instance_id],
                Tags=tag_specifications
            )

        return {
            'success': True,
            'instance_id': instance_id,
            'instance_type': instance_type,
            'ami_id': ami_id,
            'state': instance['State']['Name'],
            'private_ip': instance.get('PrivateIpAddress', 'Pending'),
            'message': f'Successfully created EC2 instance {instance_id}',
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
            'description': 'Create a new EC2 instance with specified configuration',
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
        }
    ]
