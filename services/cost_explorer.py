"""AWS Cost Explorer and CloudWatch integration for real cost and utilization data."""
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from models import db, InfrastructureResource, CostOptimization


def _get_user_boto_client(user_id: int, service: str, region: str = None):
    from services.credential_service import get_user_boto_client
    return get_user_boto_client(user_id, service, region)


def get_actual_costs(user_id: int, days: int = 30) -> Dict:
    """
    Pull real spend data from AWS Cost Explorer API.

    Returns breakdown by service, daily costs, and total spend.
    """
    ce = _get_user_boto_client(user_id, 'ce', region='us-east-1')

    end_date = datetime.utcnow().strftime('%Y-%m-%d')
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    # Total cost by service
    service_costs = ce.get_cost_and_usage(
        TimePeriod={'Start': start_date, 'End': end_date},
        Granularity='MONTHLY',
        Metrics=['UnblendedCost', 'UsageQuantity'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )

    # Daily cost trend
    daily_costs = ce.get_cost_and_usage(
        TimePeriod={'Start': start_date, 'End': end_date},
        Granularity='DAILY',
        Metrics=['UnblendedCost']
    )

    # Parse service breakdown
    services = []
    total_cost = 0.0
    for period in service_costs.get('ResultsByTime', []):
        for group in period.get('Groups', []):
            service_name = group['Keys'][0]
            amount = float(group['Metrics']['UnblendedCost']['Amount'])
            if amount > 0.01:
                services.append({
                    'service': service_name,
                    'cost': round(amount, 2),
                    'unit': group['Metrics']['UnblendedCost']['Unit']
                })
                total_cost += amount

    services.sort(key=lambda x: x['cost'], reverse=True)

    # Parse daily trend
    daily_trend = []
    for period in daily_costs.get('ResultsByTime', []):
        daily_trend.append({
            'date': period['TimePeriod']['Start'],
            'cost': round(float(period['Metrics']['UnblendedCost']['Amount']), 2)
        })

    return {
        'total_cost': round(total_cost, 2),
        'period_days': days,
        'services': services,
        'daily_trend': daily_trend,
        'start_date': start_date,
        'end_date': end_date
    }


def get_cost_forecast(user_id: int, forecast_days: int = 30) -> Dict:
    """Get AWS cost forecast for the next N days."""
    ce = _get_user_boto_client(user_id, 'ce', region='us-east-1')

    start_date = datetime.utcnow().strftime('%Y-%m-%d')
    end_date = (datetime.utcnow() + timedelta(days=forecast_days)).strftime('%Y-%m-%d')

    try:
        forecast = ce.get_cost_forecast(
            TimePeriod={'Start': start_date, 'End': end_date},
            Metric='UNBLENDED_COST',
            Granularity='MONTHLY'
        )

        return {
            'forecast_total': round(float(forecast['Total']['Amount']), 2),
            'forecast_unit': forecast['Total']['Unit'],
            'period': {'start': start_date, 'end': end_date}
        }
    except Exception:
        return {'forecast_total': None, 'error': 'Insufficient data for forecast'}


def get_resource_cost(user_id: int, resource_id: str, days: int = 30) -> Optional[float]:
    """Get actual cost for a specific resource from Cost Explorer."""
    ce = _get_user_boto_client(user_id, 'ce', region='us-east-1')

    end_date = datetime.utcnow().strftime('%Y-%m-%d')
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    try:
        result = ce.get_cost_and_usage(
            TimePeriod={'Start': start_date, 'End': end_date},
            Granularity='MONTHLY',
            Metrics=['UnblendedCost'],
            Filter={
                'Dimensions': {
                    'Key': 'RESOURCE_ID',
                    'Values': [resource_id]
                }
            }
        )

        total = 0.0
        for period in result.get('ResultsByTime', []):
            total += float(period['Metrics']['UnblendedCost']['Amount'])

        return round(total, 2)
    except Exception:
        return None


def get_instance_utilization(user_id: int, instance_id: str, days: int = 14) -> Dict:
    """
    Get real CPU and memory utilization from CloudWatch.

    Returns average, max, and datapoints for the period.
    """
    cw = _get_user_boto_client(user_id, 'cloudwatch')

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)

    # CPU utilization
    cpu_stats = cw.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=3600,  # hourly
        Statistics=['Average', 'Maximum']
    )

    cpu_datapoints = sorted(cpu_stats.get('Datapoints', []), key=lambda x: x['Timestamp'])
    cpu_avg = sum(d['Average'] for d in cpu_datapoints) / len(cpu_datapoints) if cpu_datapoints else None
    cpu_max = max((d['Maximum'] for d in cpu_datapoints), default=None)

    # Network In/Out (proxy for activity)
    net_in = cw.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='NetworkIn',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,  # daily
        Statistics=['Sum']
    )

    net_out = cw.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='NetworkOut',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,
        Statistics=['Sum']
    )

    # Disk read/write operations
    disk_reads = cw.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='DiskReadOps',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,
        Statistics=['Sum']
    )

    return {
        'instance_id': instance_id,
        'period_days': days,
        'cpu': {
            'average': round(cpu_avg, 2) if cpu_avg is not None else None,
            'max': round(cpu_max, 2) if cpu_max is not None else None,
            'datapoints': len(cpu_datapoints),
            'hourly': [
                {
                    'timestamp': d['Timestamp'].isoformat(),
                    'average': round(d['Average'], 2),
                    'max': round(d['Maximum'], 2)
                }
                for d in cpu_datapoints[-72:]  # last 3 days hourly
            ]
        },
        'network': {
            'total_in_gb': round(sum(d['Sum'] for d in net_in.get('Datapoints', [])) / 1e9, 3),
            'total_out_gb': round(sum(d['Sum'] for d in net_out.get('Datapoints', [])) / 1e9, 3)
        },
        'disk': {
            'total_read_ops': sum(d['Sum'] for d in disk_reads.get('Datapoints', []))
        }
    }


def get_rds_utilization(user_id: int, db_identifier: str, days: int = 14) -> Dict:
    """Get real RDS utilization from CloudWatch."""
    cw = _get_user_boto_client(user_id, 'cloudwatch')

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)

    cpu_stats = cw.get_metric_statistics(
        Namespace='AWS/RDS',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
        StartTime=start_time,
        EndTime=end_time,
        Period=3600,
        Statistics=['Average', 'Maximum']
    )

    connections = cw.get_metric_statistics(
        Namespace='AWS/RDS',
        MetricName='DatabaseConnections',
        Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_identifier}],
        StartTime=start_time,
        EndTime=end_time,
        Period=3600,
        Statistics=['Average', 'Maximum']
    )

    cpu_datapoints = sorted(cpu_stats.get('Datapoints', []), key=lambda x: x['Timestamp'])
    conn_datapoints = sorted(connections.get('Datapoints', []), key=lambda x: x['Timestamp'])

    cpu_avg = sum(d['Average'] for d in cpu_datapoints) / len(cpu_datapoints) if cpu_datapoints else None
    conn_avg = sum(d['Average'] for d in conn_datapoints) / len(conn_datapoints) if conn_datapoints else None

    return {
        'db_identifier': db_identifier,
        'period_days': days,
        'cpu': {
            'average': round(cpu_avg, 2) if cpu_avg is not None else None,
            'max': round(max(d['Maximum'] for d in cpu_datapoints), 2) if cpu_datapoints else None
        },
        'connections': {
            'average': round(conn_avg, 1) if conn_avg is not None else None,
            'max': round(max(d['Maximum'] for d in conn_datapoints), 0) if conn_datapoints else None
        }
    }


def generate_real_cost_recommendations(user_id: int):
    """
    Generate cost optimization recommendations using real CloudWatch metrics.

    This replaces the fake "resource.id % 3 == 0" heuristic with actual utilization data.
    """
    resources = InfrastructureResource.query.filter_by(
        user_id=user_id
    ).filter(
        InfrastructureResource.status.notin_(['terminated', 'deleted'])
    ).all()

    for resource in resources:
        if resource.resource_type == 'ec2' and resource.status == 'running':
            _check_ec2_utilization(user_id, resource)

        elif resource.resource_type == 'rds':
            _check_rds_utilization(user_id, resource)


def _check_ec2_utilization(user_id: int, resource: InfrastructureResource):
    """Check EC2 instance utilization and generate recommendations based on real data."""
    instance_id = resource.resource_id

    try:
        utilization = get_instance_utilization(user_id, instance_id, days=14)
    except Exception:
        return  # Can't get metrics, skip

    cpu_avg = utilization['cpu']['average']
    cpu_max = utilization['cpu']['max']
    net_total = utilization['network']['total_in_gb'] + utilization['network']['total_out_gb']

    if cpu_avg is None:
        return

    # Idle resource: avg CPU < 5% and minimal network over 14 days
    if cpu_avg < 5.0 and net_total < 0.1:
        savings = resource.monthly_cost * 0.95
        create_or_update_recommendation(
            user_id=user_id,
            resource_id=resource.id,
            rec_type='idle_resource',
            title=f'Idle instance: {resource.resource_name}',
            description=(
                f'{resource.resource_name} averaged {cpu_avg:.1f}% CPU over 14 days '
                f'with {net_total:.3f}GB network traffic. '
                f'Stopping it saves ${savings:.2f}/month.'
            ),
            savings=savings
        )

    # Rightsizing: avg CPU < 20% and max CPU < 50%
    elif cpu_avg < 20.0 and (cpu_max is not None and cpu_max < 50.0):
        instance_type = resource.resource_metadata.get('instance_type', '')
        smaller_type = _get_smaller_instance_type(instance_type)
        if smaller_type != instance_type:
            savings = resource.monthly_cost * 0.40
            create_or_update_recommendation(
                user_id=user_id,
                resource_id=resource.id,
                rec_type='rightsizing',
                title=f'Rightsize {resource.resource_name}',
                description=(
                    f'{resource.resource_name} ({instance_type}) averaged {cpu_avg:.1f}% CPU '
                    f'with peak {cpu_max:.1f}%. Downgrade to {smaller_type} to save '
                    f'${savings:.2f}/month.'
                ),
                savings=savings
            )


def _check_rds_utilization(user_id: int, resource: InfrastructureResource):
    """Check RDS utilization and generate recommendations based on real data."""
    db_identifier = resource.resource_metadata.get('db_instance_identifier', resource.resource_id)

    try:
        utilization = get_rds_utilization(user_id, db_identifier, days=14)
    except Exception:
        return

    cpu_avg = utilization['cpu']['average']
    conn_avg = utilization['connections']['average']

    if cpu_avg is None:
        return

    if cpu_avg < 5.0 and conn_avg is not None and conn_avg < 1.0:
        savings = resource.monthly_cost * 0.90
        create_or_update_recommendation(
            user_id=user_id,
            resource_id=resource.id,
            rec_type='idle_resource',
            title=f'Idle RDS: {resource.resource_name}',
            description=(
                f'{resource.resource_name} averaged {cpu_avg:.1f}% CPU and '
                f'{conn_avg:.1f} connections over 14 days. '
                f'Consider stopping or downsizing to save ${savings:.2f}/month.'
            ),
            savings=savings
        )

    elif cpu_avg < 15.0:
        instance_class = resource.resource_metadata.get('instance_class', '')
        smaller = _get_smaller_instance_type(instance_class)
        if smaller != instance_class:
            savings = resource.monthly_cost * 0.35
            create_or_update_recommendation(
                user_id=user_id,
                resource_id=resource.id,
                rec_type='rightsizing',
                title=f'Rightsize RDS: {resource.resource_name}',
                description=(
                    f'{resource.resource_name} ({instance_class}) averaged {cpu_avg:.1f}% CPU. '
                    f'Downgrade to {smaller} to save ${savings:.2f}/month.'
                ),
                savings=savings
            )


def update_resource_costs_from_explorer(user_id: int):
    """
    Update InfrastructureResource.monthly_cost with real Cost Explorer data
    instead of hardcoded pricing tables.
    """
    resources = InfrastructureResource.query.filter_by(
        user_id=user_id, cloud_provider='aws'
    ).filter(
        InfrastructureResource.status.notin_(['terminated', 'deleted'])
    ).all()

    for resource in resources:
        real_cost = get_resource_cost(user_id, resource.resource_id)
        if real_cost is not None:
            resource.monthly_cost = real_cost

    db.session.commit()


def create_or_update_recommendation(
    user_id: int, resource_id: int, rec_type: str,
    title: str, description: str, savings: float
):
    """Create or update a cost optimization recommendation."""
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
    else:
        existing.title = title
        existing.description = description
        existing.potential_monthly_savings = savings


def _get_smaller_instance_type(instance_type: str) -> str:
    """Suggest a smaller instance type."""
    if '2xlarge' in instance_type:
        return instance_type.replace('2xlarge', 'xlarge')
    elif 'xlarge' in instance_type:
        return instance_type.replace('xlarge', 'large')
    elif '.large' in instance_type:
        return instance_type.replace('.large', '.medium')
    elif '.medium' in instance_type:
        return instance_type.replace('.medium', '.small')
    return instance_type
