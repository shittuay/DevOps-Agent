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
    Sync AWS resources (EC2, RDS) for a user.

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
