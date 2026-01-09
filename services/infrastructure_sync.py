"""Infrastructure sync service for tracking cloud resources and costs"""
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from models import db, InfrastructureResource, CostOptimization
from src.tools.aws_tools import _get_boto_client
from botocore.exceptions import ClientError, NoCredentialsError


# Simplified cost estimates (USD/month)
# In production, use AWS Pricing API
EC2_PRICING = {
    't2.micro': 8.50,
    't2.small': 17.00,
    't2.medium': 34.00,
    't2.large': 68.00,
    't3.micro': 7.50,
    't3.small': 15.00,
    't3.medium': 30.00,
    't3.large': 60.00,
    't3.xlarge': 120.00,
    't3.2xlarge': 240.00,
    'm5.large': 70.00,
    'm5.xlarge': 140.00,
    'm5.2xlarge': 280.00,
    'c5.large': 62.00,
    'c5.xlarge': 124.00,
    'c5.2xlarge': 248.00,
}

RDS_PRICING = {
    'db.t3.micro': 12.00,
    'db.t3.small': 24.00,
    'db.t3.medium': 48.00,
    'db.t3.large': 96.00,
    'db.m5.large': 120.00,
    'db.m5.xlarge': 240.00,
}

# S3 pricing (USD per GB/month for standard storage)
S3_STANDARD_PRICE_PER_GB = 0.023
S3_BASE_COST = 0.10  # Minimum monthly cost for bucket maintenance

# Lambda pricing (USD per million requests + compute time)
LAMBDA_BASE_REQUESTS = 1000000  # 1M requests/month baseline
LAMBDA_PRICE_PER_MILLION_REQUESTS = 0.20
LAMBDA_PRICE_PER_GB_SECOND = 0.0000166667

# DynamoDB pricing (USD per month)
DYNAMODB_ON_DEMAND_WRITE = 1.25  # Per million write requests
DYNAMODB_ON_DEMAND_READ = 0.25   # Per million read requests
DYNAMODB_BASE_COST = 0.25        # Minimum cost for table

# Load Balancer pricing (USD per month)
ALB_BASE_COST = 16.20  # Application Load Balancer
NLB_BASE_COST = 16.20  # Network Load Balancer
CLB_BASE_COST = 18.25  # Classic Load Balancer

# ECS/Fargate pricing (per vCPU-hour and GB-hour)
FARGATE_VCPU_HOUR = 0.04048
FARGATE_GB_HOUR = 0.004445

# API Gateway pricing
API_GATEWAY_PRICE_PER_MILLION = 3.50

# ElastiCache pricing (USD per month)
ELASTICACHE_PRICING = {
    'cache.t3.micro': 11.00,
    'cache.t3.small': 22.00,
    'cache.t3.medium': 44.00,
    'cache.m5.large': 100.00,
    'cache.r5.large': 125.00,
}

# CloudFront pricing (approximate per GB)
CLOUDFRONT_PRICE_PER_GB = 0.085

# EBS Volume pricing (USD per GB/month)
EBS_GP3_PRICE_PER_GB = 0.08
EBS_GP2_PRICE_PER_GB = 0.10
EBS_IO1_PRICE_PER_GB = 0.125

# Elastic IP pricing (when not attached)
ELASTIC_IP_UNUSED_COST = 3.60  # Per month

# SNS/SQS pricing
SNS_PRICE_PER_MILLION = 0.50
SQS_PRICE_PER_MILLION = 0.40


def sync_user_infrastructure(user_id: int) -> Dict:
    """
    Sync all infrastructure for a user across cloud providers.

    Args:
        user_id: User ID to sync infrastructure for

    Returns:
        Dictionary with sync results
    """
    results = {
        'aws': {'synced': 0, 'errors': []},
        'gcp': {'synced': 0, 'errors': []},
        'azure': {'synced': 0, 'errors': []},
        'total_resources': 0,
        'total_cost': 0.0
    }

    # Sync AWS resources
    aws_result = sync_aws_resources(user_id)
    results['aws'] = aws_result
    results['total_resources'] += aws_result['synced']

    # Calculate total cost
    resources = InfrastructureResource.query.filter_by(user_id=user_id).all()
    results['total_cost'] = sum(r.monthly_cost or 0.0 for r in resources)

    # Generate cost optimization recommendations
    generate_cost_recommendations(user_id)

    return results


def sync_aws_resources(user_id: int) -> Dict:
    """
    Sync all AWS resources for a user.

    Args:
        user_id: User ID

    Returns:
        Dictionary with sync results
    """
    result = {'synced': 0, 'errors': []}

    try:
        # Sync EC2 instances
        ec2_count = sync_aws_ec2_instances(user_id)
        result['synced'] += ec2_count

        # Sync RDS databases
        rds_count = sync_aws_rds_instances(user_id)
        result['synced'] += rds_count

        # Sync S3 buckets
        s3_count = sync_aws_s3_buckets(user_id)
        result['synced'] += s3_count

        # Sync Lambda functions
        lambda_count = sync_aws_lambda_functions(user_id)
        result['synced'] += lambda_count

        # Sync DynamoDB tables
        dynamodb_count = sync_aws_dynamodb_tables(user_id)
        result['synced'] += dynamodb_count

        # Sync Load Balancers
        lb_count = sync_aws_load_balancers(user_id)
        result['synced'] += lb_count

        # Sync ECS services
        ecs_count = sync_aws_ecs_services(user_id)
        result['synced'] += ecs_count

        # Sync API Gateways
        api_count = sync_aws_api_gateways(user_id)
        result['synced'] += api_count

        # Sync SNS topics
        sns_count = sync_aws_sns_topics(user_id)
        result['synced'] += sns_count

        # Sync SQS queues
        sqs_count = sync_aws_sqs_queues(user_id)
        result['synced'] += sqs_count

        # Sync ElastiCache clusters
        cache_count = sync_aws_elasticache_clusters(user_id)
        result['synced'] += cache_count

        # Sync CloudFront distributions
        cf_count = sync_aws_cloudfront_distributions(user_id)
        result['synced'] += cf_count

        # Sync EBS volumes
        ebs_count = sync_aws_ebs_volumes(user_id)
        result['synced'] += ebs_count

        # Sync Elastic IPs
        eip_count = sync_aws_elastic_ips(user_id)
        result['synced'] += eip_count

    except NoCredentialsError:
        result['errors'].append('AWS credentials not configured')
    except ClientError as e:
        result['errors'].append(f'AWS API error: {str(e)}')
    except Exception as e:
        result['errors'].append(f'Unexpected error: {str(e)}')

    return result


def sync_aws_ec2_instances(user_id: int) -> int:
    """Sync AWS EC2 instances"""
    try:
        ec2 = _get_boto_client('ec2')
        response = ec2.describe_instances()

        count = 0
        for reservation in response.get('Reservations', []):
            for instance in reservation.get('Instances', []):
                instance_id = instance['InstanceId']
                instance_type = instance['InstanceType']
                state = instance['State']['Name']

                # Get instance name from tags
                instance_name = instance_id
                for tag in instance.get('Tags', []):
                    if tag['Key'] == 'Name':
                        instance_name = tag['Value']
                        break

                # Get or create resource record
                resource = InfrastructureResource.query.filter_by(
                    user_id=user_id,
                    resource_id=instance_id
                ).first()

                if not resource:
                    resource = InfrastructureResource(
                        user_id=user_id,
                        cloud_provider='aws',
                        resource_type='ec2',
                        resource_id=instance_id
                    )
                    db.session.add(resource)

                # Update resource details
                resource.resource_name = instance_name
                resource.region = instance['Placement']['AvailabilityZone'][:-1]
                resource.status = state
                resource.monthly_cost = calculate_ec2_cost(instance_type, state)
                resource.resource_metadata = {
                    'instance_type': instance_type,
                    'launch_time': instance['LaunchTime'].isoformat(),
                    'private_ip': instance.get('PrivateIpAddress'),
                    'public_ip': instance.get('PublicIpAddress'),
                    'vpc_id': instance.get('VpcId'),
                    'subnet_id': instance.get('SubnetId'),
                }
                resource.last_synced = datetime.utcnow()

                count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing EC2 instances: {e}")
        return 0


def sync_aws_rds_instances(user_id: int) -> int:
    """Sync AWS RDS instances"""
    try:
        rds = _get_boto_client('rds')
        response = rds.describe_db_instances()

        count = 0
        for db_instance in response.get('DBInstances', []):
            db_id = db_instance['DBInstanceIdentifier']
            db_class = db_instance['DBInstanceClass']
            status = db_instance['DBInstanceStatus']

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=db_id
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='rds',
                    resource_id=db_id
                )
                db.session.add(resource)

            # Update resource details
            resource.resource_name = db_id
            resource.region = db_instance['AvailabilityZone'][:-1] if db_instance.get('AvailabilityZone') else 'unknown'
            resource.status = status
            resource.monthly_cost = calculate_rds_cost(db_class, status)
            resource.resource_metadata = {
                'db_class': db_class,
                'engine': db_instance['Engine'],
                'engine_version': db_instance['EngineVersion'],
                'allocated_storage': db_instance['AllocatedStorage'],
                'multi_az': db_instance.get('MultiAZ', False),
                'endpoint': db_instance.get('Endpoint', {}).get('Address'),
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing RDS instances: {e}")
        return 0


def sync_aws_s3_buckets(user_id: int) -> int:
    """Sync AWS S3 buckets"""
    try:
        s3 = _get_boto_client('s3')
        cloudwatch = _get_boto_client('cloudwatch')

        response = s3.list_buckets()

        count = 0
        for bucket in response.get('Buckets', []):
            bucket_name = bucket['Name']

            try:
                # Get bucket region
                location = s3.get_bucket_location(Bucket=bucket_name)
                region = location.get('LocationConstraint') or 'us-east-1'

                # Get bucket size from CloudWatch (approximate)
                bucket_size_bytes = 0
                try:
                    from datetime import datetime, timedelta
                    end_time = datetime.utcnow()
                    start_time = end_time - timedelta(days=1)

                    metrics = cloudwatch.get_metric_statistics(
                        Namespace='AWS/S3',
                        MetricName='BucketSizeBytes',
                        Dimensions=[
                            {'Name': 'BucketName', 'Value': bucket_name},
                            {'Name': 'StorageType', 'Value': 'StandardStorage'}
                        ],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=86400,
                        Statistics=['Average']
                    )

                    if metrics.get('Datapoints'):
                        bucket_size_bytes = metrics['Datapoints'][0].get('Average', 0)
                except Exception as e:
                    print(f"Could not get bucket size for {bucket_name}: {e}")

                # Get or create resource record
                resource = InfrastructureResource.query.filter_by(
                    user_id=user_id,
                    resource_id=bucket_name
                ).first()

                if not resource:
                    resource = InfrastructureResource(
                        user_id=user_id,
                        cloud_provider='aws',
                        resource_type='s3',
                        resource_id=bucket_name
                    )
                    db.session.add(resource)

                # Update resource details
                resource.resource_name = bucket_name
                resource.region = region
                resource.status = 'active'
                resource.monthly_cost = calculate_s3_cost(bucket_size_bytes)
                resource.resource_metadata = {
                    'creation_date': bucket['CreationDate'].isoformat(),
                    'size_bytes': bucket_size_bytes,
                    'size_gb': round(bucket_size_bytes / (1024**3), 2)
                }
                resource.last_synced = datetime.utcnow()

                count += 1

            except Exception as e:
                print(f"Error syncing bucket {bucket_name}: {e}")
                continue

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing S3 buckets: {e}")
        return 0


def calculate_ec2_cost(instance_type: str, state: str) -> float:
    """Calculate monthly cost for EC2 instance"""
    if state != 'running':
        return 5.00  # EBS storage cost when stopped

    return EC2_PRICING.get(instance_type, 100.00)  # Default to $100 if type unknown


def calculate_rds_cost(db_class: str, status: str) -> float:
    """Calculate monthly cost for RDS instance"""
    if status != 'available':
        return 5.00  # Snapshot storage cost

    return RDS_PRICING.get(db_class, 120.00)  # Default to $120 if class unknown


def calculate_s3_cost(size_bytes: float) -> float:
    """Calculate monthly cost for S3 bucket"""
    size_gb = size_bytes / (1024**3)
    storage_cost = size_gb * S3_STANDARD_PRICE_PER_GB
    return max(storage_cost, S3_BASE_COST)  # Minimum cost for bucket maintenance


def sync_aws_lambda_functions(user_id: int) -> int:
    """Sync AWS Lambda functions"""
    try:
        lambda_client = _get_boto_client('lambda')
        response = lambda_client.list_functions()

        count = 0
        for function in response.get('Functions', []):
            function_name = function['FunctionName']
            function_arn = function['FunctionArn']

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=function_arn
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='lambda',
                    resource_id=function_arn
                )
                db.session.add(resource)

            # Update resource details
            memory_mb = function.get('MemorySize', 128)
            estimated_cost = (LAMBDA_PRICE_PER_MILLION_REQUESTS * 1) + (memory_mb / 1024 * 100 * LAMBDA_PRICE_PER_GB_SECOND * 730)

            resource.resource_name = function_name
            resource.region = function_arn.split(':')[3]
            resource.status = function.get('State', 'Active')
            resource.monthly_cost = round(estimated_cost, 2)
            resource.resource_metadata = {
                'runtime': function.get('Runtime'),
                'memory_mb': memory_mb,
                'timeout': function.get('Timeout'),
                'last_modified': function.get('LastModified'),
                'code_size': function.get('CodeSize'),
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing Lambda functions: {e}")
        return 0


def sync_aws_dynamodb_tables(user_id: int) -> int:
    """Sync AWS DynamoDB tables"""
    try:
        dynamodb = _get_boto_client('dynamodb')
        response = dynamodb.list_tables()

        count = 0
        for table_name in response.get('TableNames', []):
            try:
                table_details = dynamodb.describe_table(TableName=table_name)
                table = table_details['Table']

                # Get or create resource record
                resource = InfrastructureResource.query.filter_by(
                    user_id=user_id,
                    resource_id=table['TableArn']
                ).first()

                if not resource:
                    resource = InfrastructureResource(
                        user_id=user_id,
                        cloud_provider='aws',
                        resource_type='dynamodb',
                        resource_id=table['TableArn']
                    )
                    db.session.add(resource)

                # Calculate estimated cost
                billing_mode = table.get('BillingModeSummary', {}).get('BillingMode', 'PROVISIONED')
                if billing_mode == 'PAY_PER_REQUEST':
                    estimated_cost = DYNAMODB_BASE_COST + 2.0  # Estimate $2/month for moderate usage
                else:
                    estimated_cost = DYNAMODB_BASE_COST + 5.0  # Provisioned capacity estimate

                resource.resource_name = table_name
                resource.region = table['TableArn'].split(':')[3]
                resource.status = table['TableStatus']
                resource.monthly_cost = estimated_cost
                resource.resource_metadata = {
                    'item_count': table.get('ItemCount', 0),
                    'table_size_bytes': table.get('TableSizeBytes', 0),
                    'billing_mode': billing_mode,
                    'creation_date': table.get('CreationDateTime').isoformat() if table.get('CreationDateTime') else None,
                }
                resource.last_synced = datetime.utcnow()

                count += 1

            except Exception as e:
                print(f"Error syncing DynamoDB table {table_name}: {e}")
                continue

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing DynamoDB tables: {e}")
        return 0


def sync_aws_load_balancers(user_id: int) -> int:
    """Sync AWS Load Balancers (ALB, NLB, CLB)"""
    try:
        elbv2 = _get_boto_client('elbv2')
        response = elbv2.describe_load_balancers()

        count = 0
        for lb in response.get('LoadBalancers', []):
            lb_arn = lb['LoadBalancerArn']
            lb_type = lb['Type']  # application, network, or classic

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=lb_arn
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='load_balancer',
                    resource_id=lb_arn
                )
                db.session.add(resource)

            # Calculate cost based on type
            if lb_type == 'application':
                monthly_cost = ALB_BASE_COST
            elif lb_type == 'network':
                monthly_cost = NLB_BASE_COST
            else:
                monthly_cost = CLB_BASE_COST

            resource.resource_name = lb['LoadBalancerName']
            resource.region = lb['AvailabilityZones'][0]['ZoneName'][:-1] if lb.get('AvailabilityZones') else 'unknown'
            resource.status = lb['State']['Code']
            resource.monthly_cost = monthly_cost
            resource.resource_metadata = {
                'type': lb_type,
                'scheme': lb.get('Scheme'),
                'dns_name': lb.get('DNSName'),
                'vpc_id': lb.get('VpcId'),
                'created_time': lb.get('CreatedTime').isoformat() if lb.get('CreatedTime') else None,
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing Load Balancers: {e}")
        return 0


def sync_aws_ecs_services(user_id: int) -> int:
    """Sync AWS ECS services"""
    try:
        ecs = _get_boto_client('ecs')
        clusters = ecs.list_clusters()

        count = 0
        for cluster_arn in clusters.get('clusterArns', []):
            try:
                services = ecs.list_services(cluster=cluster_arn)

                for service_arn in services.get('serviceArns', []):
                    try:
                        service_details = ecs.describe_services(cluster=cluster_arn, services=[service_arn])

                        for service in service_details.get('services', []):
                            # Get or create resource record
                            resource = InfrastructureResource.query.filter_by(
                                user_id=user_id,
                                resource_id=service_arn
                            ).first()

                            if not resource:
                                resource = InfrastructureResource(
                                    user_id=user_id,
                                    cloud_provider='aws',
                                    resource_type='ecs',
                                    resource_id=service_arn
                                )
                                db.session.add(resource)

                            # Estimate Fargate cost (simplified)
                            running_count = service.get('runningCount', 0)
                            estimated_cost = running_count * (FARGATE_VCPU_HOUR * 0.25 + FARGATE_GB_HOUR * 0.5) * 730

                            resource.resource_name = service['serviceName']
                            resource.region = service_arn.split(':')[3]
                            resource.status = service['status']
                            resource.monthly_cost = round(estimated_cost, 2)
                            resource.resource_metadata = {
                                'cluster': cluster_arn.split('/')[-1],
                                'running_count': running_count,
                                'desired_count': service.get('desiredCount', 0),
                                'launch_type': service.get('launchType', 'UNKNOWN'),
                            }
                            resource.last_synced = datetime.utcnow()

                            count += 1

                    except Exception as e:
                        print(f"Error syncing ECS service {service_arn}: {e}")
                        continue

            except Exception as e:
                print(f"Error syncing ECS cluster {cluster_arn}: {e}")
                continue

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing ECS services: {e}")
        return 0


def sync_aws_api_gateways(user_id: int) -> int:
    """Sync AWS API Gateways"""
    try:
        apigw = _get_boto_client('apigateway')
        response = apigw.get_rest_apis()

        count = 0
        for api in response.get('items', []):
            api_id = api['id']
            api_arn = f"arn:aws:apigateway:{api.get('region', 'us-east-1')}::/restapis/{api_id}"

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=api_arn
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='api_gateway',
                    resource_id=api_arn
                )
                db.session.add(resource)

            # Estimate cost (1M requests/month baseline)
            estimated_cost = API_GATEWAY_PRICE_PER_MILLION

            resource.resource_name = api['name']
            resource.region = 'us-east-1'  # Default region
            resource.status = 'active'
            resource.monthly_cost = estimated_cost
            resource.resource_metadata = {
                'api_id': api_id,
                'description': api.get('description', ''),
                'created_date': api.get('createdDate').isoformat() if api.get('createdDate') else None,
                'endpoint_configuration': api.get('endpointConfiguration', {}).get('types', []),
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing API Gateways: {e}")
        return 0


def sync_aws_sns_topics(user_id: int) -> int:
    """Sync AWS SNS topics"""
    try:
        sns = _get_boto_client('sns')
        response = sns.list_topics()

        count = 0
        for topic in response.get('Topics', []):
            topic_arn = topic['TopicArn']

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=topic_arn
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='sns',
                    resource_id=topic_arn
                )
                db.session.add(resource)

            # Get topic attributes
            try:
                attrs = sns.get_topic_attributes(TopicArn=topic_arn)
                attributes = attrs.get('Attributes', {})
            except:
                attributes = {}

            # Minimal cost estimate
            estimated_cost = SNS_PRICE_PER_MILLION * 0.1  # 100K messages/month

            resource.resource_name = topic_arn.split(':')[-1]
            resource.region = topic_arn.split(':')[3]
            resource.status = 'active'
            resource.monthly_cost = round(estimated_cost, 2)
            resource.resource_metadata = {
                'subscriptions': attributes.get('SubscriptionsConfirmed', 0),
                'display_name': attributes.get('DisplayName', ''),
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing SNS topics: {e}")
        return 0


def sync_aws_sqs_queues(user_id: int) -> int:
    """Sync AWS SQS queues"""
    try:
        sqs = _get_boto_client('sqs')
        response = sqs.list_queues()

        count = 0
        for queue_url in response.get('QueueUrls', []):
            try:
                attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=['All'])
                attributes = attrs.get('Attributes', {})

                queue_arn = attributes.get('QueueArn', queue_url)

                # Get or create resource record
                resource = InfrastructureResource.query.filter_by(
                    user_id=user_id,
                    resource_id=queue_arn
                ).first()

                if not resource:
                    resource = InfrastructureResource(
                        user_id=user_id,
                        cloud_provider='aws',
                        resource_type='sqs',
                        resource_id=queue_arn
                    )
                    db.session.add(resource)

                # Minimal cost estimate
                estimated_cost = SQS_PRICE_PER_MILLION * 0.1  # 100K messages/month

                resource.resource_name = queue_url.split('/')[-1]
                resource.region = queue_arn.split(':')[3] if ':' in queue_arn else 'us-east-1'
                resource.status = 'active'
                resource.monthly_cost = round(estimated_cost, 2)
                resource.resource_metadata = {
                    'queue_url': queue_url,
                    'messages_available': attributes.get('ApproximateNumberOfMessages', 0),
                    'retention_period': attributes.get('MessageRetentionPeriod', 0),
                }
                resource.last_synced = datetime.utcnow()

                count += 1

            except Exception as e:
                print(f"Error syncing SQS queue {queue_url}: {e}")
                continue

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing SQS queues: {e}")
        return 0


def sync_aws_elasticache_clusters(user_id: int) -> int:
    """Sync AWS ElastiCache clusters"""
    try:
        elasticache = _get_boto_client('elasticache')
        response = elasticache.describe_cache_clusters()

        count = 0
        for cluster in response.get('CacheClusters', []):
            cluster_id = cluster['CacheClusterId']
            cluster_arn = cluster.get('ARN', f"elasticache:{cluster_id}")

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=cluster_arn
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='elasticache',
                    resource_id=cluster_arn
                )
                db.session.add(resource)

            node_type = cluster.get('CacheNodeType', 'cache.t3.micro')
            num_nodes = cluster.get('NumCacheNodes', 1)
            monthly_cost = ELASTICACHE_PRICING.get(node_type, 50.00) * num_nodes

            resource.resource_name = cluster_id
            resource.region = cluster.get('PreferredAvailabilityZone', 'us-east-1')[:-1] if cluster.get('PreferredAvailabilityZone') else 'unknown'
            resource.status = cluster.get('CacheClusterStatus', 'unknown')
            resource.monthly_cost = monthly_cost
            resource.resource_metadata = {
                'engine': cluster.get('Engine'),
                'engine_version': cluster.get('EngineVersion'),
                'node_type': node_type,
                'num_nodes': num_nodes,
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing ElastiCache clusters: {e}")
        return 0


def sync_aws_cloudfront_distributions(user_id: int) -> int:
    """Sync AWS CloudFront distributions"""
    try:
        cloudfront = _get_boto_client('cloudfront')
        response = cloudfront.list_distributions()

        count = 0
        if 'DistributionList' in response and 'Items' in response['DistributionList']:
            for dist in response['DistributionList']['Items']:
                dist_id = dist['Id']
                dist_arn = dist['ARN']

                # Get or create resource record
                resource = InfrastructureResource.query.filter_by(
                    user_id=user_id,
                    resource_id=dist_arn
                ).first()

                if not resource:
                    resource = InfrastructureResource(
                        user_id=user_id,
                        cloud_provider='aws',
                        resource_type='cloudfront',
                        resource_id=dist_arn
                    )
                    db.session.add(resource)

                # Estimate cost (10GB data transfer/month baseline)
                estimated_cost = CLOUDFRONT_PRICE_PER_GB * 10

                resource.resource_name = dist.get('Comment', dist_id) or dist_id
                resource.region = 'global'
                resource.status = dist.get('Status', 'Unknown')
                resource.monthly_cost = round(estimated_cost, 2)
                resource.resource_metadata = {
                    'domain_name': dist.get('DomainName'),
                    'enabled': dist.get('Enabled', False),
                    'price_class': dist.get('PriceClass'),
                }
                resource.last_synced = datetime.utcnow()

                count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing CloudFront distributions: {e}")
        return 0


def sync_aws_ebs_volumes(user_id: int) -> int:
    """Sync AWS EBS volumes"""
    try:
        ec2 = _get_boto_client('ec2')
        response = ec2.describe_volumes()

        count = 0
        for volume in response.get('Volumes', []):
            volume_id = volume['VolumeId']

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=volume_id
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='ebs',
                    resource_id=volume_id
                )
                db.session.add(resource)

            size_gb = volume.get('Size', 0)
            volume_type = volume.get('VolumeType', 'gp2')

            # Calculate cost based on type
            if volume_type == 'gp3':
                monthly_cost = size_gb * EBS_GP3_PRICE_PER_GB
            elif volume_type == 'gp2':
                monthly_cost = size_gb * EBS_GP2_PRICE_PER_GB
            elif volume_type in ['io1', 'io2']:
                monthly_cost = size_gb * EBS_IO1_PRICE_PER_GB
            else:
                monthly_cost = size_gb * EBS_GP2_PRICE_PER_GB

            # Get volume name from tags
            volume_name = volume_id
            for tag in volume.get('Tags', []):
                if tag['Key'] == 'Name':
                    volume_name = tag['Value']
                    break

            attachments = volume.get('Attachments', [])
            status = 'attached' if attachments else 'available'

            resource.resource_name = volume_name
            resource.region = volume.get('AvailabilityZone', 'unknown')[:-1]
            resource.status = status
            resource.monthly_cost = round(monthly_cost, 2)
            resource.resource_metadata = {
                'size_gb': size_gb,
                'volume_type': volume_type,
                'iops': volume.get('Iops'),
                'encrypted': volume.get('Encrypted', False),
                'attached_to': attachments[0].get('InstanceId') if attachments else None,
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing EBS volumes: {e}")
        return 0


def sync_aws_elastic_ips(user_id: int) -> int:
    """Sync AWS Elastic IPs"""
    try:
        ec2 = _get_boto_client('ec2')
        response = ec2.describe_addresses()

        count = 0
        for eip in response.get('Addresses', []):
            allocation_id = eip.get('AllocationId', eip.get('PublicIp'))

            # Get or create resource record
            resource = InfrastructureResource.query.filter_by(
                user_id=user_id,
                resource_id=allocation_id
            ).first()

            if not resource:
                resource = InfrastructureResource(
                    user_id=user_id,
                    cloud_provider='aws',
                    resource_type='elastic_ip',
                    resource_id=allocation_id
                )
                db.session.add(resource)

            # Cost only if not attached
            is_attached = 'InstanceId' in eip or 'NetworkInterfaceId' in eip
            monthly_cost = 0 if is_attached else ELASTIC_IP_UNUSED_COST

            status = 'attached' if is_attached else 'unattached'

            resource.resource_name = eip.get('PublicIp', 'Unknown')
            resource.region = eip.get('Domain', 'vpc')
            resource.status = status
            resource.monthly_cost = monthly_cost
            resource.resource_metadata = {
                'public_ip': eip.get('PublicIp'),
                'instance_id': eip.get('InstanceId'),
                'network_interface_id': eip.get('NetworkInterfaceId'),
            }
            resource.last_synced = datetime.utcnow()

            count += 1

        db.session.commit()
        return count

    except Exception as e:
        print(f"Error syncing Elastic IPs: {e}")
        return 0


def generate_cost_recommendations(user_id: int):
    """Generate cost optimization recommendations for a user"""
    resources = InfrastructureResource.query.filter_by(user_id=user_id).all()

    for resource in resources:
        # Check for idle EC2 instances (mock - in production, query CloudWatch)
        if resource.resource_type == 'ec2' and resource.status == 'running':
            # Simulate low CPU usage detection
            if should_recommend_stopping(resource):
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='idle_resource',
                    title=f"Idle EC2 instance: {resource.resource_name}",
                    description=f"This instance appears to be underutilized. Consider stopping it when not in use or downsizing to a smaller instance type.",
                    savings=resource.monthly_cost * 0.9  # 90% savings if stopped
                )

            # Check for rightsizing opportunities
            rightsizing_savings = check_rightsizing_opportunity(resource)
            if rightsizing_savings > 0:
                instance_type = resource.resource_metadata.get('instance_type', 'unknown')
                smaller_type = get_smaller_instance_type(instance_type)
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='rightsizing',
                    title=f"Rightsizing opportunity: {resource.resource_name}",
                    description=f"Instance {resource.resource_name} ({instance_type}) is underutilized. Downgrade to {smaller_type} to save costs.",
                    savings=rightsizing_savings
                )

            # Check for Spot instance opportunities
            if is_spot_candidate(resource):
                spot_savings = resource.monthly_cost * 0.7  # 70% savings with Spot
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='spot_instance',
                    title=f"Spot instance opportunity: {resource.resource_name}",
                    description=f"This workload appears suitable for Spot instances. Save up to 70% by using Spot instances.",
                    savings=spot_savings
                )

        # Check for stopped instances that have been stopped for a long time
        if resource.resource_type == 'ec2' and resource.status == 'stopped':
            days_stopped = (datetime.utcnow() - resource.last_synced).days
            if days_stopped > 30:
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='unused_resource',
                    title=f"Stopped instance for {days_stopped} days: {resource.resource_name}",
                    description=f"This instance has been stopped for over 30 days. Consider terminating it and creating a snapshot if needed.",
                    savings=5.00  # EBS storage savings
                )

    # Check for S3 optimization opportunities
    for resource in resources:
        if resource.resource_type == 's3':
            size_gb = resource.resource_metadata.get('size_gb', 0)

            # Recommend lifecycle policies for large buckets
            if size_gb > 100:
                glacier_savings = resource.monthly_cost * 0.65  # 65% savings with Glacier
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='s3_lifecycle',
                    title=f"S3 Lifecycle policy: {resource.resource_name}",
                    description=f"Bucket {resource.resource_name} contains {size_gb:.2f}GB. Implement lifecycle policies to move old data to Glacier or Intelligent-Tiering to save costs.",
                    savings=glacier_savings
                )

            # Recommend Intelligent-Tiering for all buckets
            if size_gb > 10:
                intelligent_tiering_savings = resource.monthly_cost * 0.30
                create_or_update_recommendation(
                    user_id=user_id,
                    resource_id=resource.id,
                    rec_type='s3_intelligent_tiering',
                    title=f"Enable S3 Intelligent-Tiering: {resource.resource_name}",
                    description=f"Enable Intelligent-Tiering for {resource.resource_name} to automatically optimize storage costs based on access patterns.",
                    savings=intelligent_tiering_savings
                )

    # Check for Reserved Instance opportunities
    check_reserved_instance_opportunities(user_id, resources)

    # Check for unattached EBS volumes
    check_unattached_volumes(user_id)

    db.session.commit()


def should_recommend_stopping(resource: InfrastructureResource) -> bool:
    """
    Determine if we should recommend stopping a resource.
    In production, this would query CloudWatch metrics.
    For now, we use simple heuristics.
    """
    # Mock logic - in production, check actual CloudWatch CPU metrics
    # For demo purposes, recommend stopping 1 out of every 3 resources
    return resource.id % 3 == 0


def create_or_update_recommendation(
    user_id: int,
    resource_id: int,
    rec_type: str,
    title: str,
    description: str,
    savings: float
):
    """Create or update a cost optimization recommendation"""
    # Check if recommendation already exists
    existing = CostOptimization.query.filter_by(
        user_id=user_id,
        resource_id=resource_id,
        recommendation_type=rec_type,
        status='pending'
    ).first()

    if not existing:
        recommendation = CostOptimization(
            user_id=user_id,
            resource_id=resource_id,
            recommendation_type=rec_type,
            title=title,
            description=description,
            potential_monthly_savings=savings
        )
        db.session.add(recommendation)


def check_rightsizing_opportunity(resource: InfrastructureResource) -> float:
    """Check if instance can be downsized to save costs"""
    instance_type = resource.resource_metadata.get('instance_type', '')

    # Simulate rightsizing logic - in production, check actual CloudWatch metrics
    # If instance family supports smaller size, suggest 30% savings
    if any(size in instance_type for size in ['xlarge', '2xlarge', 'large']):
        return resource.monthly_cost * 0.3

    return 0.0


def get_smaller_instance_type(instance_type: str) -> str:
    """Suggest a smaller instance type"""
    if '2xlarge' in instance_type:
        return instance_type.replace('2xlarge', 'xlarge')
    elif 'xlarge' in instance_type:
        return instance_type.replace('xlarge', 'large')
    elif 'large' in instance_type:
        return instance_type.replace('large', 'medium')
    return instance_type


def is_spot_candidate(resource: InfrastructureResource) -> bool:
    """Determine if workload is suitable for Spot instances"""
    # Simulate spot candidacy - in production, analyze workload patterns
    # Dev/test environments and batch jobs are good candidates
    resource_name = resource.resource_name.lower()
    return any(keyword in resource_name for keyword in ['dev', 'test', 'batch', 'worker'])


def check_reserved_instance_opportunities(user_id: int, resources: List):
    """Check if user should purchase Reserved Instances"""
    # Count running instances by type
    instance_types = {}
    for r in resources:
        if r.resource_type == 'ec2' and r.status == 'running':
            inst_type = r.resource_metadata.get('instance_type', 'unknown')
            if inst_type not in instance_types:
                instance_types[inst_type] = []
            instance_types[inst_type].append(r)

    # If 3+ instances of same type, recommend RI
    for inst_type, instances in instance_types.items():
        if len(instances) >= 3:
            total_cost = sum(i.monthly_cost for i in instances)
            ri_savings = total_cost * 0.35  # 35% savings with 1-year RI

            create_or_update_recommendation(
                user_id=user_id,
                resource_id=None,
                rec_type='reserved_instance',
                title=f"Reserved Instance opportunity for {inst_type}",
                description=f"You're running {len(instances)} {inst_type} instances continuously. Purchase Reserved Instances to save 35-40%.",
                savings=ri_savings
            )


def check_unattached_volumes(user_id: int):
    """Check for unattached EBS volumes"""
    try:
        ec2 = _get_boto_client('ec2')
        volumes = ec2.describe_volumes(
            Filters=[{'Name': 'status', 'Values': ['available']}]
        )

        for volume in volumes.get('Volumes', []):
            volume_id = volume['VolumeId']
            size_gb = volume['Size']
            volume_type = volume.get('VolumeType', 'gp2')

            # Calculate monthly cost (rough estimate)
            cost_per_gb = 0.10 if volume_type == 'gp2' else 0.125
            monthly_cost = size_gb * cost_per_gb

            create_or_update_recommendation(
                user_id=user_id,
                resource_id=None,
                rec_type='unattached_volume',
                title=f"Unattached EBS volume: {volume_id}",
                description=f"EBS volume {volume_id} ({size_gb}GB) is not attached to any instance. Delete it to save ${monthly_cost:.2f}/month.",
                savings=monthly_cost
            )
    except Exception as e:
        print(f'Error checking unattached volumes: {e}')


def get_dashboard_summary(user_id: int) -> Dict:
    """
    Get dashboard summary data for a user.

    Returns:
        Dictionary with summary statistics
    """
    resources = InfrastructureResource.query.filter_by(user_id=user_id).all()
    recommendations = CostOptimization.query.filter_by(
        user_id=user_id,
        status='pending'
    ).order_by(CostOptimization.potential_monthly_savings.desc()).all()

    # Group resources by cloud provider
    resources_by_cloud = {}
    for resource in resources:
        provider = resource.cloud_provider
        if provider not in resources_by_cloud:
            resources_by_cloud[provider] = []
        resources_by_cloud[provider].append(resource.to_dict())

    # Calculate totals
    total_cost = sum(r.monthly_cost or 0.0 for r in resources)
    total_savings = sum(r.potential_monthly_savings or 0.0 for r in recommendations)

    return {
        'total_resources': len(resources),
        'total_monthly_cost': round(total_cost, 2),
        'total_potential_savings': round(total_savings, 2),
        'resources_by_cloud': resources_by_cloud,
        'recommendations': [r.to_dict() for r in recommendations[:10]],  # Top 10
        'last_synced': max([r.last_synced for r in resources]) if resources else None
    }
