"""
Prevention Engine — proactive infrastructure recommendation service.
Analyzes incident patterns, monitoring gaps, and resource metadata
to generate actionable recommendations without any AI API calls.
Only generate_agent_spec() uses AI.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'info': 0}


class PreventionEngine:
    """Analyzes infrastructure data to generate proactive recommendations."""

    def __init__(self, app=None):
        self._app = app

    def analyze_incident_patterns(self, user_id: int, lookback_days: int = 30) -> List[Dict]:
        """Group repeated incidents by title prefix and source. Returns upsert-ready dicts."""
        if not self._app:
            return []
        with self._app.app_context():
            from models import db, IncidentModel
            from sqlalchemy import func
            cutoff = datetime.utcnow() - timedelta(days=lookback_days)
            rows = db.session.query(
                IncidentModel.source,
                func.count(IncidentModel.id).label('cnt'),
                func.max(IncidentModel.severity).label('max_sev'),
            ).filter(
                IncidentModel.user_id == user_id,
                IncidentModel.triggered_at >= cutoff,
            ).group_by(IncidentModel.source).all()

            results = []
            for row in rows:
                if row.cnt < 2:
                    continue
                # Pull all incident keys for this source to list as evidence
                incident_rows = IncidentModel.query.filter_by(
                    user_id=user_id, source=row.source
                ).filter(IncidentModel.triggered_at >= cutoff).all()
                keys = [r.incident_key for r in incident_rows]
                results.append({
                    'category': 'code_optimization',
                    'recommendation_type': 'recurring_pod_crash' if 'pod' in row.source.lower() else 'high_restart_count',
                    'title': f'Recurring incidents from source: {row.source}',
                    'description': (
                        f'{row.cnt} incidents from source "{row.source}" in the last {lookback_days} days. '
                        'Investigate root cause to prevent recurrence.'
                    ),
                    'severity': row.max_sev or 'medium',
                    'source_incident_ids': keys,
                    'evidence': {'count': row.cnt, 'source': row.source, 'lookback_days': lookback_days},
                    'remediation_steps': [
                        f'Review incident history for source "{row.source}"',
                        'Identify common contributing factors',
                        'Implement monitoring alert to detect early warning signs',
                        'Document runbook for this incident type',
                    ],
                    'estimated_effort': '1d',
                })
            return results

    def generate_observability_recommendations(self, user_id: int) -> List[Dict]:
        """Find infrastructure resources with no corresponding monitoring rule."""
        if not self._app:
            return []
        with self._app.app_context():
            from models import db, InfrastructureResource, MonitoringRuleModel
            resources = InfrastructureResource.query.filter_by(user_id=user_id).all()
            rules = MonitoringRuleModel.query.filter_by(user_id=user_id).all()
            rule_resource_ids = set()
            for r in rules:
                labels = r.labels or {}
                for v in labels.values():
                    rule_resource_ids.add(str(v))

            unmonitored = []
            for res in resources:
                if str(res.resource_id) not in rule_resource_ids:
                    unmonitored.append(res)

            results = []
            if unmonitored:
                resource_ids = [r.resource_id for r in unmonitored[:20]]
                results.append({
                    'category': 'observability',
                    'recommendation_type': 'missing_alert',
                    'title': f'{len(unmonitored)} resources have no monitoring rule',
                    'description': (
                        f'{len(unmonitored)} infrastructure resources are not covered by any monitoring rule. '
                        'Add CPU, memory, and availability alerts to ensure timely incident detection.'
                    ),
                    'severity': 'high' if len(unmonitored) > 5 else 'medium',
                    'affected_resource_ids': resource_ids,
                    'evidence': {'unmonitored_count': len(unmonitored)},
                    'remediation_steps': [
                        'Go to Monitoring > Rules and create rules for each resource type',
                        'Set CPU alert threshold at 80%, memory at 85%',
                        'Add an uptime/health check endpoint check',
                        'Configure PagerDuty or OpsGenie as the notification channel',
                    ],
                    'estimated_effort': '1h',
                })
            return results

    def generate_governance_recommendations(self, user_id: int) -> List[Dict]:
        """Find untagged resources and oversized/unused resources."""
        if not self._app:
            return []
        with self._app.app_context():
            from models import db, InfrastructureResource
            resources = InfrastructureResource.query.filter_by(user_id=user_id).all()
            results = []

            untagged = []
            for res in resources:
                meta = res.resource_metadata or {}
                tags = meta.get('tags', meta.get('Tags', {}))
                if not tags:
                    untagged.append(res.resource_id)

            if untagged:
                results.append({
                    'category': 'governance',
                    'recommendation_type': 'untagged_resources',
                    'title': f'{len(untagged)} resources have no tags',
                    'description': (
                        f'{len(untagged)} resources are missing tags. '
                        'Tags are required for cost allocation, ownership, and compliance.'
                    ),
                    'severity': 'medium',
                    'affected_resource_ids': untagged[:20],
                    'evidence': {'untagged_count': len(untagged)},
                    'remediation_steps': [
                        'Define a mandatory tag policy: Environment, Owner, Project, CostCenter',
                        'Use AWS Config or Azure Policy to enforce tagging',
                        'Apply tags to all existing untagged resources',
                        'Enable AWS Cost Allocation Tags in the billing console',
                    ],
                    'estimated_effort': '1d',
                })

            # Stale EBS-type resources
            cutoff = datetime.utcnow() - timedelta(days=30)
            stale = [
                r.resource_id for r in resources
                if r.resource_type in ('ebs_volume', 'disk')
                and r.last_synced and r.last_synced < cutoff
                and (r.resource_metadata or {}).get('state', '').lower() == 'available'
            ]
            if stale:
                results.append({
                    'category': 'governance',
                    'recommendation_type': 'unused_resource',
                    'title': f'{len(stale)} unattached storage volumes detected',
                    'description': (
                        f'{len(stale)} EBS volumes or disks appear to be unattached and may be unused. '
                        'Unattached volumes incur charges with no benefit.'
                    ),
                    'severity': 'low',
                    'affected_resource_ids': stale[:20],
                    'evidence': {'stale_count': len(stale)},
                    'remediation_steps': [
                        'Verify volumes are not needed (check snapshots / recent detach events)',
                        'Create a final snapshot before deleting',
                        'Delete unneeded volumes to reduce costs',
                    ],
                    'estimated_effort': '1h',
                })

            return results

    def generate_infrastructure_recommendations(self, user_id: int) -> List[Dict]:
        """Find single-AZ and unencrypted resources."""
        if not self._app:
            return []
        with self._app.app_context():
            from models import db, InfrastructureResource
            resources = InfrastructureResource.query.filter_by(user_id=user_id).all()
            results = []

            single_az = []
            unencrypted = []
            for res in resources:
                meta = res.resource_metadata or {}
                # Single-AZ: RDS or EC2 with availability_zone but no multi_az
                if res.resource_type in ('rds_instance', 'database') and not meta.get('multi_az', False):
                    single_az.append(res.resource_id)
                # Unencrypted storage
                if res.resource_type in ('ebs_volume', 's3_bucket', 'rds_instance'):
                    encrypted = meta.get('encrypted', meta.get('Encrypted', meta.get('encryption', None)))
                    if encrypted is False:
                        unencrypted.append(res.resource_id)

            if single_az:
                results.append({
                    'category': 'infrastructure',
                    'recommendation_type': 'single_az',
                    'title': f'{len(single_az)} databases are single-AZ (no Multi-AZ)',
                    'description': (
                        f'{len(single_az)} RDS instances are not Multi-AZ. '
                        'A single-AZ failure will cause downtime. Enable Multi-AZ for production databases.'
                    ),
                    'severity': 'high',
                    'affected_resource_ids': single_az[:20],
                    'evidence': {'single_az_count': len(single_az)},
                    'remediation_steps': [
                        'Enable Multi-AZ on each RDS instance (requires brief downtime on failover)',
                        'Monitor the modification until status returns to "available"',
                        'Test failover by rebooting with failover in the RDS console',
                    ],
                    'estimated_effort': '1h',
                })

            if unencrypted:
                results.append({
                    'category': 'infrastructure',
                    'recommendation_type': 'unencrypted_storage',
                    'title': f'{len(unencrypted)} storage resources are unencrypted',
                    'description': (
                        f'{len(unencrypted)} resources have encryption disabled. '
                        'Encryption at rest is required for most compliance frameworks.'
                    ),
                    'severity': 'high',
                    'affected_resource_ids': unencrypted[:20],
                    'evidence': {'unencrypted_count': len(unencrypted)},
                    'remediation_steps': [
                        'Enable default EBS encryption in EC2 settings',
                        'Snapshot and re-encrypt existing unencrypted volumes',
                        'Enable S3 default encryption (SSE-S3 or SSE-KMS)',
                        'Enable RDS encryption (requires snapshot and restore for existing instances)',
                    ],
                    'estimated_effort': '1d',
                })

            return results

    def run_full_analysis(self, user_id: int) -> List[Dict]:
        """Run all recommendation generators and return combined results."""
        all_recs = []
        all_recs.extend(self.analyze_incident_patterns(user_id))
        all_recs.extend(self.generate_observability_recommendations(user_id))
        all_recs.extend(self.generate_governance_recommendations(user_id))
        all_recs.extend(self.generate_infrastructure_recommendations(user_id))
        return all_recs

    def generate_agent_spec(self, recommendation_id: int, user_id: int) -> Optional[str]:
        """
        Generate an implementation spec for a recommendation using Claude/Kimi.
        Deducts 1 credit from the user's subscription.
        Returns the spec text or None on failure.
        """
        if not self._app:
            return None
        with self._app.app_context():
            from models import db, ProactiveRecommendation, UserSubscription
            rec = ProactiveRecommendation.query.filter_by(
                id=recommendation_id, user_id=user_id
            ).first()
            if not rec:
                return None

            prompt = (
                f"You are a senior DevOps engineer. Generate a concise implementation spec for this recommendation:\n\n"
                f"Title: {rec.title}\n"
                f"Category: {rec.category}\n"
                f"Description: {rec.description}\n"
                f"Remediation steps: {rec.remediation_steps}\n\n"
                f"Produce a markdown document with sections: ## Objective, ## Prerequisites, "
                f"## Implementation Steps, ## Rollback Plan, ## Success Criteria. Be specific and actionable."
            )

            spec_text = None
            try:
                import anthropic
                api_key = os.environ.get('ANTHROPIC_API_KEY')
                if api_key:
                    client = anthropic.Anthropic(api_key=api_key)
                    response = client.messages.create(
                        model='claude-sonnet-4-6',
                        max_tokens=2000,
                        messages=[{'role': 'user', 'content': prompt}]
                    )
                    spec_text = response.content[0].text
            except Exception as e:
                logger.error(f"Agent spec generation failed: {e}")
                # Fallback to a template if AI unavailable
                spec_text = self._template_spec(rec)

            if spec_text:
                rec.agent_spec = spec_text
                rec.agent_spec_generated_at = datetime.utcnow()
                # Deduct credit
                sub = UserSubscription.query.filter_by(user_id=user_id).first()
                if sub and sub.has_credits():
                    sub.use_credit(commit=False)
                db.session.commit()

            return spec_text

    def _template_spec(self, rec) -> str:
        steps = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(rec.remediation_steps or []))
        return (
            f"## Objective\n\n{rec.description}\n\n"
            f"## Prerequisites\n\n- Cloud credentials configured\n- Appropriate IAM permissions\n\n"
            f"## Implementation Steps\n\n{steps or '1. Review the recommendation details'}\n\n"
            f"## Rollback Plan\n\nRevert any changes made during implementation. "
            f"Take snapshots before modifying storage resources.\n\n"
            f"## Success Criteria\n\n- Recommendation status updated to 'resolved'\n"
            f"- No new related incidents within 7 days"
        )


_engine_instance: Optional[PreventionEngine] = None


def get_prevention_engine(app=None) -> PreventionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PreventionEngine(app=app)
    elif app and not _engine_instance._app:
        _engine_instance._app = app
    return _engine_instance
