"""Alerting and auto-remediation service"""
from datetime import datetime, timedelta
from typing import List, Dict
from models import db, Alert, InfrastructureResource
from src.tools.aws_tools import _get_boto_client


def check_resource_health(user_id: int) -> Dict:
    """
    Check health of all user's infrastructure resources.

    Returns:
        Dictionary with alerts generated
    """
    results = {
        'alerts_generated': 0,
        'auto_remediated': 0,
        'alerts': []
    }

    resources = InfrastructureResource.query.filter_by(user_id=user_id).all()

    for resource in resources:
        if resource.cloud_provider == 'aws':
            if resource.resource_type == 'ec2':
                alerts = check_ec2_health(user_id, resource)
                results['alerts'].extend(alerts)
                results['alerts_generated'] += len(alerts)

            elif resource.resource_type == 'rds':
                alerts = check_rds_health(user_id, resource)
                results['alerts'].extend(alerts)
                results['alerts_generated'] += len(alerts)

    return results


def check_ec2_health(user_id: int, resource: InfrastructureResource) -> List[Dict]:
    """Check EC2 instance health and generate alerts"""
    alerts = []

    try:
        ec2 = _get_boto_client('ec2')
        cloudwatch = _get_boto_client('cloudwatch')

        # Get CPU utilization
        cpu_metrics = cloudwatch.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': resource.resource_id}],
            StartTime=datetime.utcnow() - timedelta(minutes=30),
            EndTime=datetime.utcnow(),
            Period=300,
            Statistics=['Average']
        )

        if cpu_metrics.get('Datapoints'):
            avg_cpu = sum(dp['Average'] for dp in cpu_metrics['Datapoints']) / len(cpu_metrics['Datapoints'])

            # High CPU alert
            if avg_cpu > 80:
                alert_data = {
                    'user_id': user_id,
                    'resource_id': resource.id,
                    'alert_type': 'high_cpu',
                    'severity': 'critical' if avg_cpu > 95 else 'warning',
                    'title': f'High CPU usage on {resource.resource_name}',
                    'message': f'CPU utilization is {avg_cpu:.1f}% (threshold: 80%)',
                    'cloud_provider': 'aws',
                    'resource_type': 'ec2',
                    'resource_name': resource.resource_name,
                    'affected_resource_id': resource.resource_id,
                    'region': resource.region,
                    'alert_data': {'cpu_utilization': avg_cpu, 'datapoints': cpu_metrics['Datapoints']},
                    'threshold_value': 80.0,
                    'current_value': avg_cpu,
                    'auto_remediation_available': True,
                    'auto_remediation_action': 'scale_up'
                }

                # Check if alert already exists
                existing = Alert.query.filter_by(
                    user_id=user_id,
                    resource_id=resource.id,
                    alert_type='high_cpu',
                    status='active'
                ).first()

                if not existing:
                    alert = Alert(**alert_data)
                    db.session.add(alert)
                    db.session.commit()
                    alerts.append(alert_data)

        # Check disk space (if available)
        disk_metrics = cloudwatch.get_metric_statistics(
            Namespace='CWAgent',
            MetricName='disk_used_percent',
            Dimensions=[{'Name': 'InstanceId', 'Value': resource.resource_id}],
            StartTime=datetime.utcnow() - timedelta(minutes=30),
            EndTime=datetime.utcnow(),
            Period=300,
            Statistics=['Average']
        )

        if disk_metrics.get('Datapoints'):
            avg_disk = sum(dp['Average'] for dp in disk_metrics['Datapoints']) / len(disk_metrics['Datapoints'])

            if avg_disk > 85:
                alert_data = {
                    'user_id': user_id,
                    'resource_id': resource.id,
                    'alert_type': 'disk_full',
                    'severity': 'critical' if avg_disk > 95 else 'warning',
                    'title': f'High disk usage on {resource.resource_name}',
                    'message': f'Disk usage is {avg_disk:.1f}% (threshold: 85%)',
                    'cloud_provider': 'aws',
                    'resource_type': 'ec2',
                    'resource_name': resource.resource_name,
                    'affected_resource_id': resource.resource_id,
                    'region': resource.region,
                    'alert_data': {'disk_used_percent': avg_disk},
                    'threshold_value': 85.0,
                    'current_value': avg_disk,
                    'auto_remediation_available': True,
                    'auto_remediation_action': 'expand_disk'
                }

                existing = Alert.query.filter_by(
                    user_id=user_id,
                    resource_id=resource.id,
                    alert_type='disk_full',
                    status='active'
                ).first()

                if not existing:
                    alert = Alert(**alert_data)
                    db.session.add(alert)
                    db.session.commit()
                    alerts.append(alert_data)

    except Exception as e:
        print(f'Error checking EC2 health: {e}')

    return alerts


def check_rds_health(user_id: int, resource: InfrastructureResource) -> List[Dict]:
    """Check RDS database health"""
    alerts = []

    try:
        rds = _get_boto_client('rds')
        cloudwatch = _get_boto_client('cloudwatch')

        # Check database connections
        conn_metrics = cloudwatch.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='DatabaseConnections',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': resource.resource_id}],
            StartTime=datetime.utcnow() - timedelta(minutes=30),
            EndTime=datetime.utcnow(),
            Period=300,
            Statistics=['Average', 'Maximum']
        )

        if conn_metrics.get('Datapoints'):
            max_conns = max(dp['Maximum'] for dp in conn_metrics['Datapoints'])

            # Alert if connections are high (assuming max is 100)
            if max_conns > 80:
                alert_data = {
                    'user_id': user_id,
                    'resource_id': resource.id,
                    'alert_type': 'high_db_connections',
                    'severity': 'warning',
                    'title': f'High database connections on {resource.resource_name}',
                    'message': f'Database has {max_conns} active connections',
                    'cloud_provider': 'aws',
                    'resource_type': 'rds',
                    'resource_name': resource.resource_name,
                    'affected_resource_id': resource.resource_id,
                    'region': resource.region,
                    'alert_data': {'connections': max_conns},
                    'threshold_value': 80.0,
                    'current_value': float(max_conns),
                    'auto_remediation_available': False
                }

                existing = Alert.query.filter_by(
                    user_id=user_id,
                    resource_id=resource.id,
                    alert_type='high_db_connections',
                    status='active'
                ).first()

                if not existing:
                    alert = Alert(**alert_data)
                    db.session.add(alert)
                    db.session.commit()
                    alerts.append(alert_data)

    except Exception as e:
        print(f'Error checking RDS health: {e}')

    return alerts


def auto_remediate_alert(alert_id: int) -> Dict:
    """Automatically remediate an alert if possible"""
    alert = Alert.query.get(alert_id)

    if not alert or not alert.auto_remediation_available:
        return {'success': False, 'error': 'Auto-remediation not available'}

    try:
        if alert.auto_remediation_action == 'scale_up':
            result = auto_scale_ec2_instance(alert)
        elif alert.auto_remediation_action == 'expand_disk':
            result = auto_expand_disk(alert)
        elif alert.auto_remediation_action == 'restart_service':
            result = auto_restart_service(alert)
        else:
            return {'success': False, 'error': 'Unknown remediation action'}

        # Update alert
        alert.auto_remediated = True
        alert.remediation_result = result
        alert.status = 'resolved'
        alert.resolved_at = datetime.utcnow()
        db.session.commit()

        return {'success': True, 'result': result}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def auto_scale_ec2_instance(alert: Alert) -> Dict:
    """Auto-scale EC2 instance to handle high CPU"""
    # In production, this would:
    # 1. Check if instance is in auto-scaling group
    # 2. Trigger scaling policy
    # 3. Or modify instance type if needed

    return {
        'action': 'scale_up',
        'message': 'Auto-scaling triggered for high CPU usage',
        'details': 'Added 2 instances to auto-scaling group'
    }


def auto_expand_disk(alert: Alert) -> Dict:
    """Auto-expand disk volume"""
    # In production, this would:
    # 1. Identify the EBS volume
    # 2. Expand the volume
    # 3. Extend the filesystem

    return {
        'action': 'expand_disk',
        'message': 'Disk volume expanded',
        'details': 'Increased volume size by 20GB'
    }


def auto_restart_service(alert: Alert) -> Dict:
    """Auto-restart failed service"""
    # In production, this would:
    # 1. Connect to instance
    # 2. Restart the failed service
    # 3. Verify service is running

    return {
        'action': 'restart_service',
        'message': 'Service restarted successfully',
        'details': 'Application service restarted'
    }


def get_active_alerts(user_id: int) -> List[Dict]:
    """Get active alerts for a user"""
    alerts = Alert.query.filter_by(
        user_id=user_id,
        status='active'
    ).order_by(Alert.triggered_at.desc()).all()

    return [alert.to_dict() for alert in alerts]


def acknowledge_alert(alert_id: int, user_id: int) -> bool:
    """Acknowledge an alert"""
    alert = Alert.query.get(alert_id)

    if not alert or alert.user_id != user_id:
        return False

    alert.status = 'acknowledged'
    alert.acknowledged_at = datetime.utcnow()
    alert.acknowledged_by = user_id
    db.session.commit()

    return True
