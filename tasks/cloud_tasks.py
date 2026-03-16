"""
Cloud Operation Tasks

Background tasks for long-running cloud operations.
"""

import logging
from celery_app import celery
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, time_limit=300, soft_time_limit=240)
def sync_user_infrastructure_task(self, user_id: int):
    """
    Full infrastructure sync for a single user: all providers + cost recommendations.
    Triggered manually from the dashboard sync button.
    """
    try:
        from app import app, db
        from services.infrastructure_sync import sync_user_infrastructure

        with app.app_context():
            result = sync_user_infrastructure(user_id)

            total_savings = 0
            try:
                from services.cost_explorer import (
                    generate_real_cost_recommendations,
                    update_resource_costs_from_explorer,
                )
                update_resource_costs_from_explorer(user_id)
                generate_real_cost_recommendations(user_id)
                db.session.commit()

                from models import CostOptimization
                active_recs = CostOptimization.query.filter_by(
                    user_id=user_id, status='pending'
                ).all()
                total_savings = sum(r.potential_monthly_savings or 0 for r in active_recs)
            except Exception as e:
                logger.warning(f"Cost explorer unavailable for user {user_id}: {e}")

            if total_savings > 50:
                try:
                    from services.notification_service import get_notification_service
                    svc = get_notification_service()
                    svc.send_cost_alert(user_id, {
                        'amount': total_savings,
                        'threshold': 50,
                        'message': f'Infrastructure sync found ${total_savings:.2f}/month in potential savings',
                        'period': 'Monthly',
                        'top_service': 'AWS',
                    })
                except Exception:
                    pass

            return {
                'status': 'success',
                'total_resources': result.get('total_resources', 0),
                'total_savings': total_savings,
            }

    except Exception as e:
        logger.error(f"sync_user_infrastructure_task failed for user {user_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_cloud_resources(self, user_id: int, provider: str):
    """
    Sync cloud resources for a user.

    Args:
        user_id: User ID
        provider: Cloud provider (aws, gcp, azure)
    """
    try:
        logger.info(f"Syncing {provider} resources for user {user_id}")

        # Import here to avoid circular imports
        from app import app, db
        from models import User

        from services.infrastructure_sync import (
            sync_aws_resources,
            sync_azure_resources,
            sync_gcp_resources,
        )

        with app.app_context():
            user = User.query.get(user_id)
            if not user:
                logger.error(f"User {user_id} not found")
                return {'status': 'error', 'message': 'User not found'}

            if provider == 'aws':
                result = sync_aws_resources(user_id)
            elif provider == 'azure':
                result = sync_azure_resources(user_id)
            elif provider == 'gcp':
                result = sync_gcp_resources(user_id)
            else:
                return {'status': 'error', 'message': f'Unknown provider: {provider}'}

            return {
                'status': 'success',
                'user_id': user_id,
                'provider': provider,
                'resources_synced': result.get('synced', 0),
                'errors': result.get('errors', []),
            }

    except Exception as e:
        logger.error(f"Error syncing resources: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def sync_all_user_resources(self):
    """
    Sync resources for all active users based on their tier's sync interval.
    Called every 15 minutes by Celery Beat.
    Users with sync_interval_minutes=0 (manual only) are skipped.
    """
    try:
        from app import app, db
        from models import User, UserSubscription, UserCloudCredential
        from datetime import datetime, timedelta

        with app.app_context():
            active_users = User.query.filter(
                User.is_active == True
            ).all()

            synced = 0
            skipped = 0
            for user in active_users:
                # Check tier sync interval
                sub = UserSubscription.query.filter_by(user_id=user.id).first()
                if not sub or not sub.tier:
                    skipped += 1
                    continue

                interval = sub.tier.sync_interval_minutes or 0
                if interval == 0:
                    skipped += 1
                    continue

                # Check if enough time has passed since last sync
                from models import InfrastructureResource
                last_resource = InfrastructureResource.query.filter_by(
                    user_id=user.id
                ).order_by(InfrastructureResource.last_synced.desc()).first()

                if last_resource and last_resource.last_synced:
                    next_sync = last_resource.last_synced + timedelta(minutes=interval)
                    if datetime.utcnow() < next_sync:
                        skipped += 1
                        continue

                # Check user has cloud credentials configured
                creds = UserCloudCredential.query.filter_by(
                    user_id=user.id, is_active=True
                ).all()

                for cred in creds:
                    sync_cloud_resources.delay(user.id, cred.cloud_provider)
                    synced += 1

            return {'status': 'success', 'tasks_queued': synced, 'skipped': skipped}

    except Exception as e:
        logger.error(f"Error in sync_all_user_resources: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, max_retries=3, time_limit=600)
def provision_infrastructure(self, user_id: int, config: dict):
    """
    Provision infrastructure based on configuration.

    Args:
        user_id: User ID
        config: Infrastructure configuration dict
    """
    try:
        logger.info(f"Provisioning infrastructure for user {user_id}")

        from app import app
        from services.cache_service import cache

        with app.app_context():
            # Notify via WebSocket that provisioning started
            # socketio.emit('task_progress', {...}, room=f'user_{user_id}')

            steps = config.get('steps', [])
            total = len(steps)

            for i, step in enumerate(steps):
                # Execute step
                logger.info(f"Executing step {i+1}/{total}: {step.get('name')}")

                # Update progress in cache
                cache.set(f"task:provision:{user_id}", {
                    'status': 'in_progress',
                    'step': i + 1,
                    'total': total,
                    'current_step': step.get('name')
                }, ttl=3600)

            # Mark as complete
            cache.set(f"task:provision:{user_id}", {
                'status': 'completed',
                'step': total,
                'total': total
            }, ttl=3600)

            return {'status': 'success', 'steps_completed': total}

    except Exception as e:
        logger.error(f"Error provisioning infrastructure: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, time_limit=300)
def execute_terraform_plan(self, user_id: int, workspace: str, action: str):
    """
    Execute Terraform plan/apply/destroy.

    Args:
        user_id: User ID
        workspace: Terraform workspace name
        action: plan, apply, or destroy
    """
    try:
        logger.info(f"Executing Terraform {action} for user {user_id}")

        # TODO: Implement Terraform execution
        return {
            'status': 'success',
            'action': action,
            'workspace': workspace
        }

    except Exception as e:
        logger.error(f"Terraform error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, time_limit=600)
def run_cost_analysis(self, user_id: int, providers: list = None):
    """
    Run cost analysis across cloud providers.

    Args:
        user_id: User ID
        providers: List of providers to analyze (default: all)
    """
    try:
        providers = providers or ['aws', 'gcp', 'azure']
        logger.info(f"Running cost analysis for user {user_id}: {providers}")

        from app import app, db
        from models import InfrastructureResource, CostOptimization

        with app.app_context():
            results = {}

            for provider in providers:
                if provider == 'aws':
                    results['aws'] = _analyze_aws_costs(user_id)
                else:
                    results[provider] = _analyze_estimated_costs(user_id, provider)

            return {
                'status': 'success',
                'user_id': user_id,
                'analysis': results
            }

    except Exception as e:
        logger.error(f"Cost analysis error: {e}")
        return {'status': 'error', 'message': str(e)}


def _analyze_aws_costs(user_id: int) -> dict:
    """Pull real AWS cost data via Cost Explorer and generate recommendations."""
    from services.cost_explorer import (
        get_actual_costs,
        get_cost_forecast,
        update_resource_costs_from_explorer,
        generate_real_cost_recommendations,
    )
    from models import CostOptimization

    # Update resource cost estimates with real CE data
    try:
        update_resource_costs_from_explorer(user_id)
    except Exception as e:
        logger.warning(f"Could not update resource costs from CE for user {user_id}: {e}")

    # Pull current spend
    try:
        cost_data = get_actual_costs(user_id, days=30)
        current_month = cost_data.get('total_cost', 0.0)
        services = cost_data.get('services', [])
        daily_trend = cost_data.get('daily_trend', [])
    except Exception as e:
        logger.warning(f"Could not fetch AWS actual costs for user {user_id}: {e}")
        current_month = 0.0
        services = []
        daily_trend = []

    # Pull forecast
    try:
        forecast_data = get_cost_forecast(user_id, forecast_days=30)
        projected = forecast_data.get('forecast_total') or 0.0
    except Exception as e:
        logger.warning(f"Could not fetch AWS cost forecast for user {user_id}: {e}")
        projected = 0.0

    # Generate recommendations using real CloudWatch metrics
    try:
        generate_real_cost_recommendations(user_id)
    except Exception as e:
        logger.warning(f"Could not generate real cost recommendations for user {user_id}: {e}")

    # Pull pending savings opportunities
    savings_opportunities = [
        opt.to_dict()
        for opt in CostOptimization.query.filter_by(
            user_id=user_id, status='pending'
        ).all()
        if opt.resource and opt.resource.cloud_provider == 'aws'
    ]

    return {
        'current_month': current_month,
        'projected': projected,
        'services': services,
        'daily_trend': daily_trend,
        'savings_opportunities': savings_opportunities,
    }


def _analyze_estimated_costs(user_id: int, provider: str) -> dict:
    """
    Summarize costs for GCP/Azure using estimated monthly_cost from synced resources.
    These providers lack a dedicated cost API integration, so we use the pricing
    estimates stored during resource sync.
    """
    from models import InfrastructureResource, CostOptimization

    resources = InfrastructureResource.query.filter_by(
        user_id=user_id, cloud_provider=provider
    ).filter(
        InfrastructureResource.status.notin_(['terminated', 'deleted', 'stopped'])
    ).all()

    current_month = sum(r.monthly_cost or 0.0 for r in resources)

    savings_opportunities = [
        opt.to_dict()
        for opt in CostOptimization.query.filter_by(
            user_id=user_id, status='pending'
        ).all()
        if opt.resource and opt.resource.cloud_provider == provider
    ]

    return {
        'current_month': round(current_month, 2),
        'projected': round(current_month, 2),  # no forecast API — use current as estimate
        'resource_count': len(resources),
        'savings_opportunities': savings_opportunities,
    }
