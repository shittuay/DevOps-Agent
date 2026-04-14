"""
Change Governance API routes.

Manages infrastructure change requests with risk-based approval routing:
- Low risk (stop dev instance, tag changes) -> auto-approve
- Medium risk (resize instance, modify security groups) -> single approval
- High risk (delete production, modify IAM) -> requires approval
"""

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, InfrastructureChange, InfrastructureResource
from services.rbac import require_permission, Permission, approver_required, user_is_admin
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def _notify_change(change, event):
    """Send notification for change events (best-effort, never fails the request)."""
    try:
        from services.notification_service import get_notification_service
        svc = get_notification_service()
        details = change.change_details or {}
        svc.send_change_notification(change.user_id, {
            'id': change.id,
            'title': change.title,
            'action_type': change.action_type,
            'resource_type': change.resource_type,
            'resource_name': change.resource_name,
            'risk_level': details.get('risk_level', 'unknown'),
            'approval_comment': change.approval_comment,
        }, event=event)
    except Exception as e:
        logger.debug(f"Change notification skipped: {e}")

changes_bp = Blueprint('changes', __name__, url_prefix='/api/changes')

# Risk classification for auto-approval routing
RISK_LEVELS = {
    # action_type -> base risk
    'start': 'low',
    'stop': 'low',
    'tag': 'low',
    'update': 'medium',
    'resize': 'medium',
    'create': 'medium',
    'modify_security_group': 'high',
    'delete': 'high',
    'terminate': 'high',
}

# Resource types that escalate risk when in production
PRODUCTION_ESCALATION = {
    'rds': True,
    'ec2': True,
    'security_group': True,
    'iam': True,
    'vpc': True,
    'load_balancer': True,
}


def classify_risk(action_type: str, resource_type: str, change_details: dict) -> str:
    """
    Classify risk level based on action, resource type, and context.
    Returns: low, medium, or high.
    """
    base_risk = RISK_LEVELS.get(action_type, 'medium')

    # Escalate if resource name/tags indicate production
    resource_name = change_details.get('resource_name', '').lower()
    tags = change_details.get('tags', {})
    env = tags.get('Environment', tags.get('env', '')).lower()

    is_production = (
        'prod' in resource_name or
        'production' in resource_name or
        env in ('production', 'prod')
    )

    if is_production and resource_type in PRODUCTION_ESCALATION:
        if base_risk == 'low':
            base_risk = 'medium'
        elif base_risk == 'medium':
            base_risk = 'high'

    # IAM and delete actions on certain resources are always high
    if resource_type == 'iam' or (action_type in ('delete', 'terminate') and resource_type in ('rds', 'vpc')):
        base_risk = 'high'

    return base_risk


@changes_bp.route('', methods=['POST'])
@login_required
def create_change_request():
    """
    Create a new infrastructure change request.

    Low-risk changes are auto-approved. Higher risk requires approval.
    """
    data = request.get_json()

    required = ['action_type', 'resource_type', 'title']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400

    action_type = data['action_type']
    resource_type = data['resource_type']
    change_details = data.get('change_details', {})

    risk_level = classify_risk(action_type, resource_type, change_details)
    change_details['risk_level'] = risk_level

    change = InfrastructureChange(
        user_id=current_user.id,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=data.get('resource_id'),
        resource_name=data.get('resource_name'),
        cloud_provider=data.get('cloud_provider', 'aws'),
        title=data['title'],
        description=data.get('description'),
        change_details=change_details,
        status='pending'
    )

    # Auto-approve low-risk changes
    if risk_level == 'low':
        change.status = 'approved'
        change.approver_id = current_user.id
        change.approval_comment = 'Auto-approved: low risk'
        change.approved_at = datetime.utcnow()

    db.session.add(change)
    db.session.commit()

    result = change.to_dict()
    result['risk_level'] = risk_level
    result['auto_approved'] = risk_level == 'low'

    _notify_change(change, 'created')

    return jsonify({'success': True, 'change': result}), 201


@changes_bp.route('', methods=['GET'])
@login_required
def list_changes():
    """List change requests. Admins/approvers see all, users see their own."""
    status_filter = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = InfrastructureChange.query

    # Check if user has approve permission - if so, show all team changes
    user_role = getattr(current_user, 'role', 'viewer')
    if user_role in ('admin', 'approver', 'operator'):
        pass  # See all changes
    else:
        query = query.filter_by(user_id=current_user.id)

    if status_filter:
        query = query.filter_by(status=status_filter)

    changes = query.order_by(
        InfrastructureChange.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'changes': [c.to_dict() for c in changes.items],
        'total': changes.total,
        'page': page,
        'pages': changes.pages
    })


@changes_bp.route('/<int:change_id>', methods=['GET'])
@login_required
def get_change(change_id):
    """Get a specific change request with full details."""
    change = InfrastructureChange.query.get_or_404(change_id)

    user_role = getattr(current_user, 'role', 'viewer')
    if change.user_id != current_user.id and user_role not in ('admin', 'approver', 'operator'):
        return jsonify({'error': 'Unauthorized'}), 403

    return jsonify(change.to_dict())


@changes_bp.route('/pending', methods=['GET'])
@login_required
@approver_required
def list_pending_approvals():
    """List changes awaiting approval. Admins see all; approvers/operators see their own."""
    user_role = getattr(current_user, 'role', 'viewer')
    query = InfrastructureChange.query.filter_by(status='pending')
    if user_role != 'admin':
        query = query.filter_by(user_id=current_user.id)
    changes = query.order_by(InfrastructureChange.created_at.asc()).all()

    return jsonify({
        'pending': [c.to_dict() for c in changes],
        'count': len(changes)
    })


@changes_bp.route('/<int:change_id>/approve', methods=['POST'])
@login_required
@approver_required
def approve_change(change_id):
    """Approve a pending change request."""
    change = InfrastructureChange.query.get_or_404(change_id)

    if change.status != 'pending':
        return jsonify({'error': f'Change is already {change.status}'}), 400

    # Non-admin users can't approve their own high-risk changes
    risk_level = (change.change_details or {}).get('risk_level', 'medium')
    if change.user_id == current_user.id and risk_level == 'high' and not user_is_admin(current_user):
        return jsonify({'error': 'Cannot self-approve high-risk changes. An admin must approve this.'}), 403

    data = request.get_json() or {}
    change.status = 'approved'
    change.approver_id = current_user.id
    change.approval_comment = data.get('comment', '')
    change.approved_at = datetime.utcnow()

    db.session.commit()

    _notify_change(change, 'approved')

    return jsonify({
        'success': True,
        'change': change.to_dict(),
        'message': f'Change #{change.id} approved'
    })


@changes_bp.route('/<int:change_id>/reject', methods=['POST'])
@login_required
@approver_required
def reject_change(change_id):
    """Reject a pending change request."""
    change = InfrastructureChange.query.get_or_404(change_id)

    if change.status != 'pending':
        return jsonify({'error': f'Change is already {change.status}'}), 400

    data = request.get_json() or {}
    reason = data.get('reason', '')
    if not reason:
        return jsonify({'error': 'Rejection reason is required'}), 400

    change.status = 'rejected'
    change.approver_id = current_user.id
    change.approval_comment = reason
    change.approved_at = datetime.utcnow()

    db.session.commit()

    _notify_change(change, 'rejected')

    return jsonify({
        'success': True,
        'change': change.to_dict(),
        'message': f'Change #{change.id} rejected'
    })


@changes_bp.route('/<int:change_id>/execute', methods=['POST'])
@login_required
def execute_change(change_id):
    """
    Execute an approved change.

    Saves rollback data before execution so the change can be reverted.
    """
    change = InfrastructureChange.query.get_or_404(change_id)

    if change.user_id != current_user.id:
        user_role = getattr(current_user, 'role', 'viewer')
        if user_role not in ('admin', 'operator'):
            return jsonify({'error': 'Unauthorized'}), 403

    if change.status != 'approved':
        return jsonify({'error': f'Change must be approved before execution (current: {change.status})'}), 400

    try:
        # Capture rollback data before execution and persist it immediately
        # so it's not lost if execution fails or returns no_action
        rollback_data = _capture_rollback_data(change)
        change.rollback_data = rollback_data
        db.session.commit()

        # Execute the change
        result = _execute_change(change)

        if result.get('status') == 'no_action':
            return jsonify({
                'success': False,
                'error': result.get('reason', 'Unsupported action/resource type — no action was taken'),
                'result': result
            }), 400

        change.status = 'executed'
        change.executed_at = datetime.utcnow()
        change.execution_result = result

        # Remove deleted/terminated resources from the sync list immediately
        if change.action_type in ('delete', 'terminate') and change.resource_id:
            _purge_resource_from_sync(change)

        db.session.commit()

        _notify_change(change, 'executed')

        return jsonify({
            'success': True,
            'change': change.to_dict(),
            'result': result,
            'message': f'Change #{change.id} executed successfully'
        })

    except Exception as e:
        err_str = str(e).lower()
        # If the resource no longer exists it was already deleted via chat — treat as executed
        already_gone = any(k in err_str for k in (
            'does not exist', 'not found', 'invalidinstanceid', 'dbinstancenotfound',
            'nosuchbucket', 'notfound', 'resourcenotfound',
        ))
        if already_gone:
            change.status = 'executed'
            change.executed_at = datetime.utcnow()
            change.execution_result = {'note': 'Resource was already deleted (likely via chat)', 'error': str(e)}
            _purge_resource_from_sync(change)
            db.session.commit()
            _notify_change(change, 'executed')
            return jsonify({
                'success': True,
                'change': change.to_dict(),
                'message': f'Change #{change.id} marked executed — resource was already deleted'
            })

        change.status = 'failed'
        change.executed_at = datetime.utcnow()
        change.execution_result = {'error': str(e)}
        db.session.commit()

        _notify_change(change, 'failed')

        return jsonify({
            'success': False,
            'error': str(e),
            'change': change.to_dict()
        }), 500


@changes_bp.route('/<int:change_id>/rollback', methods=['POST'])
@login_required
@approver_required
def rollback_change(change_id):
    """Rollback an executed change using saved rollback data."""
    change = InfrastructureChange.query.get_or_404(change_id)

    if change.status != 'executed':
        return jsonify({'error': 'Only executed changes can be rolled back'}), 400

    if not change.rollback_data:
        return jsonify({'error': 'No rollback data available'}), 400

    try:
        result = _execute_rollback(change)

        # Create a new change record for the rollback
        rollback_change = InfrastructureChange(
            user_id=current_user.id,
            action_type='rollback',
            resource_type=change.resource_type,
            resource_id=change.resource_id,
            resource_name=change.resource_name,
            cloud_provider=change.cloud_provider,
            title=f'Rollback: {change.title}',
            description=f'Rollback of change #{change.id}',
            change_details={'original_change_id': change.id, 'risk_level': 'medium'},
            status='executed',
            approver_id=current_user.id,
            approval_comment='Rollback approved',
            approved_at=datetime.utcnow(),
            executed_at=datetime.utcnow(),
            execution_result=result
        )
        db.session.add(rollback_change)
        db.session.commit()

        _notify_change(rollback_change, 'rollback')

        return jsonify({
            'success': True,
            'message': f'Change #{change.id} rolled back',
            'rollback_change': rollback_change.to_dict()
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _purge_resource_from_sync(change: InfrastructureChange) -> None:
    """Remove a deleted/terminated resource from the infrastructure sync table."""
    try:
        query = InfrastructureResource.query.filter_by(
            user_id=change.user_id,
            cloud_provider=change.cloud_provider,
            resource_type=change.resource_type,
            resource_id=change.resource_id,
        )
        # Scope to region when available to avoid deleting the same resource_id
        # in a different region (e.g. same instance ID reused across regions)
        if change.change_details and change.change_details.get('region'):
            query = query.filter_by(region=change.change_details['region'])
        deleted = query.delete()
        if deleted:
            logger.info(f"Purged {deleted} sync record(s) for {change.resource_type}/{change.resource_id}")
    except Exception as e:
        logger.warning(f"Failed to purge resource from sync after execute: {e}")


def _capture_rollback_data(change: InfrastructureChange) -> dict:
    """Capture current state of the resource before making changes, for rollback."""
    try:
        from services.credential_service import get_user_boto_client

        if change.cloud_provider != 'aws' or not change.resource_id:
            return {'note': 'Rollback data not available for this resource'}

        region = (change.change_details or {}).get('region')

        if change.resource_type == 'ec2':
            ec2 = get_user_boto_client(change.user_id, 'ec2', region)
            response = ec2.describe_instances(InstanceIds=[change.resource_id])
            reservations = response.get('Reservations', [])
            if reservations and reservations[0].get('Instances'):
                instance = reservations[0]['Instances'][0]
                return {
                    'resource_type': 'ec2',
                    'instance_id': change.resource_id,
                    'previous_state': instance['State']['Name'],
                    'instance_type': instance.get('InstanceType'),
                    'tags': instance.get('Tags', [])
                }

        elif change.resource_type == 'rds':
            rds = get_user_boto_client(change.user_id, 'rds', region)
            response = rds.describe_db_instances(DBInstanceIdentifier=change.resource_id)
            instances = response.get('DBInstances', [])
            if instances:
                db_instance = instances[0]
                return {
                    'resource_type': 'rds',
                    'db_identifier': change.resource_id,
                    'instance_class': db_instance.get('DBInstanceClass'),
                    'status': db_instance.get('DBInstanceStatus'),
                    'multi_az': db_instance.get('MultiAZ')
                }

        elif change.resource_type == 'security_group':
            ec2 = get_user_boto_client(change.user_id, 'ec2', region)
            response = ec2.describe_security_groups(GroupIds=[change.resource_id])
            groups = response.get('SecurityGroups', [])
            if groups:
                sg = groups[0]
                return {
                    'resource_type': 'security_group',
                    'group_id': change.resource_id,
                    'group_name': sg.get('GroupName'),
                    'group_description': sg.get('GroupDescription'),
                    'vpc_id': sg.get('VpcId'),
                    'ingress_rules': sg.get('IpPermissions', []),
                    'egress_rules': sg.get('IpPermissionsEgress', []),
                    'tags': sg.get('Tags', [])
                }

    except Exception as e:
        return {'error': f'Failed to capture rollback data: {str(e)}'}

    return {}


def _execute_change(change: InfrastructureChange) -> dict:
    """Execute an approved infrastructure change."""
    from services.credential_service import get_user_boto_client

    if change.cloud_provider != 'aws':
        return {'status': 'skipped', 'reason': 'Only AWS execution is supported'}

    action = change.action_type
    resource_type = change.resource_type
    region = (change.change_details or {}).get('region')

    if resource_type == 'ec2':
        ec2 = get_user_boto_client(change.user_id, 'ec2', region)

        if action == 'stop':
            response = ec2.stop_instances(InstanceIds=[change.resource_id])
            return {'action': 'stop', 'state_change': response['StoppingInstances'][0]['CurrentState']['Name']}

        elif action == 'start':
            response = ec2.start_instances(InstanceIds=[change.resource_id])
            return {'action': 'start', 'state_change': response['StartingInstances'][0]['CurrentState']['Name']}

        elif action == 'terminate':
            response = ec2.terminate_instances(InstanceIds=[change.resource_id])
            return {'action': 'terminate', 'state_change': response['TerminatingInstances'][0]['CurrentState']['Name']}

        elif action == 'resize':
            new_type = (change.change_details or {}).get('new_instance_type')
            if not new_type:
                raise ValueError('new_instance_type required in change_details')

            ec2.stop_instances(InstanceIds=[change.resource_id])
            waiter = ec2.get_waiter('instance_stopped')
            waiter.wait(InstanceIds=[change.resource_id])

            ec2.modify_instance_attribute(
                InstanceId=change.resource_id,
                InstanceType={'Value': new_type}
            )
            ec2.start_instances(InstanceIds=[change.resource_id])
            return {'action': 'resize', 'new_instance_type': new_type}

    elif resource_type == 'rds':
        rds = get_user_boto_client(change.user_id, 'rds', region)

        if action == 'stop':
            rds.stop_db_instance(DBInstanceIdentifier=change.resource_id)
            return {'action': 'stop', 'status': 'stopping'}

        elif action == 'start':
            rds.start_db_instance(DBInstanceIdentifier=change.resource_id)
            return {'action': 'start', 'status': 'starting'}

        elif action == 'resize':
            new_class = (change.change_details or {}).get('new_instance_class')
            if not new_class:
                raise ValueError('new_instance_class required in change_details')

            rds.modify_db_instance(
                DBInstanceIdentifier=change.resource_id,
                DBInstanceClass=new_class,
                ApplyImmediately=True
            )
            return {'action': 'resize', 'new_instance_class': new_class}

    elif resource_type == 's3':
        s3 = get_user_boto_client(change.user_id, 's3', region)
        bucket = change.resource_id if change.resource_id and change.resource_id != 'N/A' else change.resource_name

        if not bucket:
            raise ValueError('Bucket name required (set resource_id or resource_name)')

        if action == 'delete':
            paginator = s3.get_paginator('list_object_versions')
            objects_deleted = 0
            for page in paginator.paginate(Bucket=bucket):
                delete_batch = []
                for obj in page.get('Versions', []):
                    delete_batch.append({'Key': obj['Key'], 'VersionId': obj['VersionId']})
                for marker in page.get('DeleteMarkers', []):
                    delete_batch.append({'Key': marker['Key'], 'VersionId': marker['VersionId']})
                if delete_batch:
                    s3.delete_objects(Bucket=bucket, Delete={'Objects': delete_batch})
                    objects_deleted += len(delete_batch)

            paginator2 = s3.get_paginator('list_objects_v2')
            for page in paginator2.paginate(Bucket=bucket):
                delete_batch = [{'Key': o['Key']} for o in page.get('Contents', [])]
                if delete_batch:
                    s3.delete_objects(Bucket=bucket, Delete={'Objects': delete_batch})
                    objects_deleted += len(delete_batch)

            s3.delete_bucket(Bucket=bucket)
            return {'action': 'delete', 'bucket': bucket, 'objects_deleted': objects_deleted}

    elif resource_type == 'security_group':
        ec2 = get_user_boto_client(change.user_id, 'ec2', region)

        if action == 'modify_security_group':
            rules_to_revoke = (change.change_details or {}).get('rules_to_revoke', [])
            if not rules_to_revoke:
                return {'action': 'modify_security_group', 'status': 'no_rules', 'message': 'No rules to revoke'}

            revoked_count = 0
            errors = []

            for rule in rules_to_revoke:
                try:
                    revoke_params = {
                        'GroupId': change.resource_id,
                        'IpProtocol': rule.get('protocol', 'tcp'),
                        'FromPort': rule.get('from_port', 0),
                        'ToPort': rule.get('to_port', 0),
                    }
                    if rule.get('cidr'):
                        revoke_params['CidrIp'] = rule['cidr']
                    elif rule.get('source_sg_id'):
                        revoke_params['SourceSecurityGroupId'] = rule['source_sg_id']
                    else:
                        errors.append(f"Rule missing cidr or source_sg_id: {rule}")
                        continue

                    ec2.revoke_security_group_ingress(**revoke_params)
                    revoked_count += 1

                except Exception as e:
                    errors.append(f"Failed to revoke rule {rule}: {str(e)}")

            result = {'action': 'modify_security_group', 'rules_revoked': revoked_count}
            if errors:
                result['errors'] = errors
            return result

        elif action == 'delete_security_group':
            try:
                ec2.delete_security_group(GroupId=change.resource_id)
                return {'action': 'delete_security_group', 'group_id': change.resource_id, 'status': 'deleted'}
            except Exception as e:
                if 'InvalidGroup.InUse' in str(e):
                    return {'action': 'delete_security_group', 'status': 'failed', 'error': 'Security group is still in use by network interfaces or other security groups'}
                return {'action': 'delete_security_group', 'status': 'failed', 'error': str(e)}

    return {'status': 'no_action', 'reason': f'Unsupported: {action} on {resource_type}'}


def _execute_rollback(change: InfrastructureChange) -> dict:
    """Rollback a change using saved rollback data."""
    from services.credential_service import get_user_boto_client

    rollback = change.rollback_data
    if not rollback or 'error' in rollback:
        raise ValueError('No valid rollback data')

    resource_type = rollback.get('resource_type')
    region = (change.change_details or {}).get('region')

    if resource_type == 'ec2':
        ec2 = get_user_boto_client(change.user_id, 'ec2', region)
        previous_state = rollback.get('previous_state')

        if change.action_type == 'stop' and previous_state == 'running':
            ec2.start_instances(InstanceIds=[rollback['instance_id']])
            return {'action': 'rollback_start', 'instance_id': rollback['instance_id']}

        elif change.action_type == 'start' and previous_state == 'stopped':
            ec2.stop_instances(InstanceIds=[rollback['instance_id']])
            return {'action': 'rollback_stop', 'instance_id': rollback['instance_id']}

        elif change.action_type == 'resize':
            ec2.stop_instances(InstanceIds=[rollback['instance_id']])
            waiter = ec2.get_waiter('instance_stopped')
            waiter.wait(InstanceIds=[rollback['instance_id']])
            ec2.modify_instance_attribute(
                InstanceId=rollback['instance_id'],
                InstanceType={'Value': rollback['instance_type']}
            )
            ec2.start_instances(InstanceIds=[rollback['instance_id']])
            return {'action': 'rollback_resize', 'restored_type': rollback['instance_type']}

    elif resource_type == 'security_group':
        ec2 = get_user_boto_client(change.user_id, 'ec2', region)
        group_id = rollback['group_id']

        # Check if SG was deleted
        if change.action_type == 'delete_security_group':
            try:
                # Try to describe it - if it fails, it was deleted
                ec2.describe_security_groups(GroupIds=[group_id])
                # If we get here, SG still exists (delete failed or didn't execute)
                return {'action': 'rollback_delete_security_group', 'status': 'noop', 'reason': 'SG still exists'}
            except:
                # SG was deleted, need to recreate it
                vpc_id = rollback.get('vpc_id')
                group_name = rollback.get('group_name')
                group_description = rollback.get('group_description')

                if not all([vpc_id, group_name, group_description]):
                    return {'action': 'rollback_delete_security_group', 'status': 'failed', 'reason': 'Missing SG metadata for recreation'}

                try:
                    # Recreate the SG
                    response = ec2.create_security_group(
                        GroupName=group_name,
                        Description=group_description,
                        VpcId=vpc_id
                    )
                    new_group_id = response['GroupId']

                    # Restore ingress rules
                    ingress_rules = rollback.get('ingress_rules', [])
                    if ingress_rules:
                        ec2.authorize_security_group_ingress(GroupId=new_group_id, IpPermissions=ingress_rules)

                    # Restore egress rules (if not default)
                    egress_rules = rollback.get('egress_rules', [])
                    if egress_rules:
                        # Remove default egress rule first
                        ec2.revoke_security_group_egress(
                            GroupId=new_group_id,
                            IpPermissions=[{
                                'IpProtocol': '-1',
                                'CidrIp': '0.0.0.0/0'
                            }]
                        )
                        # Add back original rules
                        ec2.authorize_security_group_egress(GroupId=new_group_id, IpPermissions=egress_rules)

                    # Restore tags
                    tags = rollback.get('tags', [])
                    if tags:
                        tag_dict = {t['Key']: t['Value'] for t in tags}
                        ec2.create_tags(Resources=[new_group_id], Tags=[{'Key': k, 'Value': v} for k, v in tag_dict.items()])

                    return {'action': 'rollback_delete_security_group', 'status': 'recreated', 'group_id': new_group_id}
                except Exception as e:
                    return {'action': 'rollback_delete_security_group', 'status': 'failed', 'error': str(e)}
        else:
            # Rollback for modify_security_group (restore rules)
            try:
                current = ec2.describe_security_groups(GroupIds=[group_id])
                if current['SecurityGroups']:
                    current_ingress = current['SecurityGroups'][0].get('IpPermissions', [])
                    if current_ingress:
                        ec2.revoke_security_group_ingress(GroupId=group_id, IpPermissions=current_ingress)
                    original_ingress = rollback.get('ingress_rules', [])
                    if original_ingress:
                        ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=original_ingress)
                return {'action': 'rollback_security_group', 'group_id': group_id}
            except Exception as e:
                return {'action': 'rollback_security_group', 'status': 'failed', 'error': str(e)}

    raise ValueError(f'Rollback not supported for resource type: {resource_type}')
