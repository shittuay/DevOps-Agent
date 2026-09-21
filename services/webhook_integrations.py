"""
Webhook Integrations Service for DevOps Agent.

Provides webhook handlers for GitHub, GitLab, and Bitbucket
to process CI/CD events and integrate with incident response.
"""

import logging
import hmac
import hashlib
from datetime import datetime
from typing import Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class WebhookSource(Enum):
    """Supported webhook sources."""
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


class EventType(Enum):
    """Types of CI/CD events."""
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    MERGE_REQUEST = "merge_request"
    PIPELINE_RUN = "pipeline_run"
    WORKFLOW_RUN = "workflow_run"
    DEPLOYMENT = "deployment"
    RELEASE = "release"
    TAG = "tag"
    ISSUE = "issue"
    COMMENT = "comment"


@dataclass
class WebhookEvent:
    """A processed webhook event."""
    id: str
    source: WebhookSource
    event_type: EventType
    repository: str
    branch: Optional[str]
    commit_sha: Optional[str]
    actor: str
    title: str
    description: str
    url: Optional[str]
    status: Optional[str]  # success, failure, pending, etc.
    metadata: dict = field(default_factory=dict)
    received_at: datetime = field(default_factory=datetime.utcnow)


class WebhookIntegrationService:
    """
    Service for processing webhooks from various CI/CD platforms.

    Features:
    - Validates webhook signatures
    - Parses events from GitHub, GitLab, Bitbucket
    - Triggers incident response on failures
    - Provides event history and filtering
    """

    def __init__(self):
        self.event_callbacks: list[Callable[[WebhookEvent], None]] = []

    def set_secret(self, source: str, secret: str):
        """Persist a webhook secret to the DB, shared across all worker processes.

        Previously stored in a per-process dict — see WebhookSecret's docstring
        in models.py for why that silently disabled signature validation on
        every worker but the one that handled the configure request.
        """
        from models import db, WebhookSecret

        row = WebhookSecret.query.filter_by(source=source).first()
        if row is None:
            row = WebhookSecret(source=source)
            db.session.add(row)
        row.set_secret(secret)
        db.session.commit()

    def get_secret(self, source: str) -> Optional[str]:
        """Look up a persisted webhook secret for `source`, or None if unset."""
        from models import WebhookSecret

        row = WebhookSecret.query.filter_by(source=source).first()
        return row.get_secret() if row else None

    def add_event_callback(self, callback: Callable[[WebhookEvent], None]):
        """Add callback for processed events."""
        self.event_callbacks.append(callback)

    def validate_github_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Validate GitHub webhook signature."""
        if not signature:
            return False

        if signature.startswith('sha256='):
            expected = 'sha256=' + hmac.new(
                secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
        elif signature.startswith('sha1='):
            expected = 'sha1=' + hmac.new(
                secret.encode(),
                payload,
                hashlib.sha1
            ).hexdigest()
        else:
            return False

        return hmac.compare_digest(expected, signature)

    def validate_gitlab_token(self, token: str, secret: str) -> bool:
        """Validate GitLab webhook token."""
        return hmac.compare_digest(token or '', secret)

    def process_github_webhook(self, event_type: str, data: dict) -> Optional[WebhookEvent]:
        """Process GitHub webhook payload."""
        import uuid

        event_id = str(uuid.uuid4())[:8]
        repo = data.get('repository', {}).get('full_name', 'unknown')

        if event_type == 'push':
            commits = data.get('commits', [])
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.PUSH,
                repository=repo,
                branch=data.get('ref', '').replace('refs/heads/', ''),
                commit_sha=data.get('after'),
                actor=data.get('pusher', {}).get('name', 'unknown'),
                title=f"Push to {repo}",
                description=f"{len(commits)} commit(s) pushed",
                url=data.get('compare'),
                status='success',
                metadata={
                    'commits': [c.get('id', '')[:7] for c in commits],
                    'forced': data.get('forced', False)
                }
            )

        elif event_type == 'pull_request':
            pr = data.get('pull_request', {})
            action = data.get('action', 'unknown')
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.PULL_REQUEST,
                repository=repo,
                branch=pr.get('head', {}).get('ref'),
                commit_sha=pr.get('head', {}).get('sha'),
                actor=data.get('sender', {}).get('login', 'unknown'),
                title=f"PR {action}: {pr.get('title', 'No title')}",
                description=pr.get('body', '') or '',
                url=pr.get('html_url'),
                status=action,
                metadata={
                    'pr_number': pr.get('number'),
                    'action': action,
                    'merged': pr.get('merged', False),
                    'base_branch': pr.get('base', {}).get('ref')
                }
            )

        elif event_type == 'workflow_run':
            workflow = data.get('workflow_run', {})
            conclusion = workflow.get('conclusion')
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.WORKFLOW_RUN,
                repository=repo,
                branch=workflow.get('head_branch'),
                commit_sha=workflow.get('head_sha'),
                actor=workflow.get('triggering_actor', {}).get('login', 'unknown'),
                title=f"Workflow: {workflow.get('name', 'Unknown')}",
                description=f"Run #{workflow.get('run_number')} - {conclusion or 'in progress'}",
                url=workflow.get('html_url'),
                status=conclusion or 'pending',
                metadata={
                    'workflow_id': workflow.get('id'),
                    'run_number': workflow.get('run_number'),
                    'event': workflow.get('event'),
                    'conclusion': conclusion
                }
            )

        elif event_type == 'check_run':
            check = data.get('check_run', {})
            conclusion = check.get('conclusion')
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.PIPELINE_RUN,
                repository=repo,
                branch=None,
                commit_sha=check.get('head_sha'),
                actor=data.get('sender', {}).get('login', 'unknown'),
                title=f"Check: {check.get('name', 'Unknown')}",
                description=f"{check.get('status', 'unknown')} - {conclusion or 'pending'}",
                url=check.get('html_url'),
                status=conclusion or check.get('status', 'pending'),
                metadata={
                    'check_run_id': check.get('id'),
                    'app': check.get('app', {}).get('name')
                }
            )

        elif event_type == 'deployment':
            deployment = data.get('deployment', {})
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.DEPLOYMENT,
                repository=repo,
                branch=deployment.get('ref'),
                commit_sha=deployment.get('sha'),
                actor=deployment.get('creator', {}).get('login', 'unknown'),
                title=f"Deployment to {deployment.get('environment', 'unknown')}",
                description=deployment.get('description', ''),
                url=deployment.get('url'),
                status='pending',
                metadata={
                    'environment': deployment.get('environment'),
                    'task': deployment.get('task')
                }
            )

        elif event_type == 'deployment_status':
            status = data.get('deployment_status', {})
            deployment = data.get('deployment', {})
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.DEPLOYMENT,
                repository=repo,
                branch=deployment.get('ref'),
                commit_sha=deployment.get('sha'),
                actor=status.get('creator', {}).get('login', 'unknown'),
                title=f"Deployment {status.get('state', 'unknown')}",
                description=status.get('description', ''),
                url=status.get('target_url'),
                status=status.get('state'),
                metadata={
                    'environment': deployment.get('environment'),
                    'state': status.get('state')
                }
            )

        elif event_type == 'release':
            release = data.get('release', {})
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITHUB,
                event_type=EventType.RELEASE,
                repository=repo,
                branch=None,
                commit_sha=release.get('target_commitish'),
                actor=release.get('author', {}).get('login', 'unknown'),
                title=f"Release: {release.get('tag_name', 'unknown')}",
                description=release.get('body', '')[:500] if release.get('body') else '',
                url=release.get('html_url'),
                status=data.get('action'),
                metadata={
                    'tag': release.get('tag_name'),
                    'prerelease': release.get('prerelease', False),
                    'draft': release.get('draft', False)
                }
            )

        return None

    def process_gitlab_webhook(self, event_type: str, data: dict) -> Optional[WebhookEvent]:
        """Process GitLab webhook payload."""
        import uuid

        event_id = str(uuid.uuid4())[:8]
        project = data.get('project', {})
        repo = project.get('path_with_namespace', 'unknown')

        if event_type == 'Push Hook':
            commits = data.get('commits', [])
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.PUSH,
                repository=repo,
                branch=data.get('ref', '').replace('refs/heads/', ''),
                commit_sha=data.get('after'),
                actor=data.get('user_name', 'unknown'),
                title=f"Push to {repo}",
                description=f"{len(commits)} commit(s) pushed",
                url=project.get('web_url'),
                status='success',
                metadata={
                    'commits': [c.get('id', '')[:7] for c in commits],
                    'total_commits_count': data.get('total_commits_count', 0)
                }
            )

        elif event_type == 'Merge Request Hook':
            mr = data.get('object_attributes', {})
            action = mr.get('action', 'unknown')
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.MERGE_REQUEST,
                repository=repo,
                branch=mr.get('source_branch'),
                commit_sha=mr.get('last_commit', {}).get('id'),
                actor=data.get('user', {}).get('username', 'unknown'),
                title=f"MR {action}: {mr.get('title', 'No title')}",
                description=mr.get('description', '') or '',
                url=mr.get('url'),
                status=mr.get('state'),
                metadata={
                    'mr_iid': mr.get('iid'),
                    'action': action,
                    'target_branch': mr.get('target_branch'),
                    'merge_status': mr.get('merge_status')
                }
            )

        elif event_type == 'Pipeline Hook':
            pipeline = data.get('object_attributes', {})
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.PIPELINE_RUN,
                repository=repo,
                branch=pipeline.get('ref'),
                commit_sha=pipeline.get('sha'),
                actor=data.get('user', {}).get('username', 'unknown'),
                title=f"Pipeline #{pipeline.get('id', 'unknown')}",
                description=f"{pipeline.get('status', 'unknown')} - {pipeline.get('duration', 0)}s",
                url=pipeline.get('url'),
                status=pipeline.get('status'),
                metadata={
                    'pipeline_id': pipeline.get('id'),
                    'duration': pipeline.get('duration'),
                    'stages': pipeline.get('stages', []),
                    'source': pipeline.get('source')
                }
            )

        elif event_type == 'Job Hook':
            build = data.get('build', data)
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.PIPELINE_RUN,
                repository=repo,
                branch=build.get('ref'),
                commit_sha=build.get('sha'),
                actor=data.get('user', {}).get('username', 'unknown'),
                title=f"Job: {build.get('name', 'unknown')}",
                description=f"Stage: {build.get('stage', 'unknown')} - {build.get('status', 'unknown')}",
                url=None,
                status=build.get('status'),
                metadata={
                    'build_id': build.get('id'),
                    'stage': build.get('stage'),
                    'runner': build.get('runner', {}).get('description')
                }
            )

        elif event_type == 'Deployment Hook':
            deployment = data.get('object_attributes', {}) or data
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.DEPLOYMENT,
                repository=repo,
                branch=deployment.get('ref'),
                commit_sha=deployment.get('sha'),
                actor=data.get('user', {}).get('username', 'unknown'),
                title=f"Deployment to {deployment.get('environment', 'unknown')}",
                description=f"Status: {deployment.get('status', 'unknown')}",
                url=deployment.get('environment_url'),
                status=deployment.get('status'),
                metadata={
                    'environment': deployment.get('environment'),
                    'deployment_id': deployment.get('deployable_id')
                }
            )

        elif event_type == 'Tag Push Hook':
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.GITLAB,
                event_type=EventType.TAG,
                repository=repo,
                branch=None,
                commit_sha=data.get('checkout_sha'),
                actor=data.get('user_name', 'unknown'),
                title=f"Tag: {data.get('ref', '').replace('refs/tags/', '')}",
                description=data.get('message', '') or '',
                url=project.get('web_url'),
                status='created' if data.get('checkout_sha') else 'deleted',
                metadata={
                    'tag': data.get('ref', '').replace('refs/tags/', '')
                }
            )

        return None

    def process_bitbucket_webhook(self, event_type: str, data: dict) -> Optional[WebhookEvent]:
        """Process Bitbucket webhook payload."""
        import uuid

        event_id = str(uuid.uuid4())[:8]
        repo = data.get('repository', {}).get('full_name', 'unknown')

        if event_type in ['repo:push', 'pullrequest:push']:
            push = data.get('push', {})
            changes = push.get('changes', [])
            if changes:
                change = changes[0]
                new = change.get('new', {})
                commits = change.get('commits', [])
                return WebhookEvent(
                    id=event_id,
                    source=WebhookSource.BITBUCKET,
                    event_type=EventType.PUSH,
                    repository=repo,
                    branch=new.get('name'),
                    commit_sha=new.get('target', {}).get('hash'),
                    actor=data.get('actor', {}).get('display_name', 'unknown'),
                    title=f"Push to {repo}",
                    description=f"{len(commits)} commit(s) pushed",
                    url=new.get('links', {}).get('html', {}).get('href'),
                    status='success',
                    metadata={
                        'commits': [c.get('hash', '')[:7] for c in commits]
                    }
                )

        elif event_type.startswith('pullrequest:'):
            pr = data.get('pullrequest', {})
            action = event_type.split(':')[1]
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.BITBUCKET,
                event_type=EventType.PULL_REQUEST,
                repository=repo,
                branch=pr.get('source', {}).get('branch', {}).get('name'),
                commit_sha=pr.get('source', {}).get('commit', {}).get('hash'),
                actor=data.get('actor', {}).get('display_name', 'unknown'),
                title=f"PR {action}: {pr.get('title', 'No title')}",
                description=pr.get('description', '') or '',
                url=pr.get('links', {}).get('html', {}).get('href'),
                status=pr.get('state'),
                metadata={
                    'pr_id': pr.get('id'),
                    'action': action,
                    'destination_branch': pr.get('destination', {}).get('branch', {}).get('name')
                }
            )

        elif event_type.startswith('repo:commit_status'):
            commit_status = data.get('commit_status', {})
            return WebhookEvent(
                id=event_id,
                source=WebhookSource.BITBUCKET,
                event_type=EventType.PIPELINE_RUN,
                repository=repo,
                branch=None,
                commit_sha=data.get('commit', {}).get('hash'),
                actor=data.get('actor', {}).get('display_name', 'unknown'),
                title=f"Build: {commit_status.get('name', 'unknown')}",
                description=commit_status.get('description', ''),
                url=commit_status.get('url'),
                status=commit_status.get('state'),
                metadata={
                    'key': commit_status.get('key'),
                    'state': commit_status.get('state')
                }
            )

        return None

    def process_webhook(self, source: str, event_type: str, data: dict,
                        app_user_id: Optional[int] = None) -> Optional[WebhookEvent]:
        """Process webhook from any supported source.

        `app_user_id` is this application's `User.id`, used to route any
        resulting incident into the right per-user namespace. Provider
        webhooks (GitHub/GitLab/Bitbucket) authenticate by shared-secret
        signature and carry no application identity, so it is optional; when
        absent, failure events are logged but no incident is created, because
        there is no correct namespace to create one in.
        """
        event = None

        if source == 'github':
            event = self.process_github_webhook(event_type, data)
        elif source == 'gitlab':
            event = self.process_gitlab_webhook(event_type, data)
        elif source == 'bitbucket':
            event = self.process_bitbucket_webhook(event_type, data)

        if event:
            self._persist_event(event)
            logger.info(f"Processed webhook event: {event.source.value}/{event.event_type.value} - {event.title}")

            # Notify callbacks
            for callback in self.event_callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Webhook callback error: {e}")

            # Check for failures that should trigger incidents
            if event.status in ['failure', 'failed', 'error', 'cancelled']:
                self._handle_failure_event(event, app_user_id)

        return event

    def _handle_failure_event(self, event: WebhookEvent, app_user_id: Optional[int] = None):
        """Handle failure events by potentially creating incidents."""
        from services.incident_response import get_incident_engine

        if app_user_id is None:
            # process_alert keys incidents by User.id. Without one there is no
            # correct namespace to write to, and guessing would put another
            # user's incident list in front of this event.
            logger.warning(
                "Failure event %s/%s not converted to an incident: webhook "
                "carried no application user id",
                event.source.value, event.event_type.value,
            )
            return

        engine = get_incident_engine()

        # Create an alert for the failure
        alert_data = {
            'source': f'webhook-{event.source.value}',
            'alert_name': f'{event.source.value.title()} {event.event_type.value.replace("_", " ").title()} Failed',
            'title': event.title,
            'description': f"{event.description}\n\nRepository: {event.repository}\nBranch: {event.branch or 'N/A'}",
            'severity': 'high' if event.event_type == EventType.DEPLOYMENT else 'medium',
            'metadata': event.metadata
        }

        engine.process_alert(app_user_id, alert_data)
        logger.info(f"Created incident for failed {event.source.value} event: {event.title}")

    def _persist_event(self, event: WebhookEvent):
        """Write a processed event to the DB so every worker/deploy sees it."""
        from models import db, WebhookEventRecord

        db.session.add(WebhookEventRecord(
            id=event.id,
            source=event.source.value,
            event_type=event.event_type.value,
            repository=event.repository,
            branch=event.branch,
            commit_sha=event.commit_sha,
            actor=event.actor,
            title=event.title,
            description=event.description,
            url=event.url,
            status=event.status,
            event_metadata=event.metadata,
            received_at=event.received_at,
        ))
        db.session.commit()

    @staticmethod
    def _record_to_event(record) -> WebhookEvent:
        return WebhookEvent(
            id=record.id,
            source=WebhookSource(record.source),
            event_type=EventType(record.event_type),
            repository=record.repository,
            branch=record.branch,
            commit_sha=record.commit_sha,
            actor=record.actor,
            title=record.title,
            description=record.description,
            url=record.url,
            status=record.status,
            metadata=record.event_metadata or {},
            received_at=record.received_at,
        )

    def get_events(self, source: Optional[str] = None, event_type: Optional[str] = None,
                   limit: int = 50) -> list[WebhookEvent]:
        """Get recent webhook events with optional filtering."""
        from models import WebhookEventRecord

        query = WebhookEventRecord.query
        if source:
            query = query.filter_by(source=source)
        if event_type:
            query = query.filter_by(event_type=event_type)

        records = query.order_by(WebhookEventRecord.received_at.desc()).limit(limit).all()
        return [self._record_to_event(r) for r in records]

    def get_stats(self) -> dict:
        """Get webhook statistics."""
        from collections import Counter
        from models import WebhookEventRecord

        records = WebhookEventRecord.query.all()

        source_counts = Counter(r.source for r in records)
        type_counts = Counter(r.event_type for r in records)
        status_counts = Counter(r.status for r in records if r.status)

        return {
            'total_events': len(records),
            'by_source': dict(source_counts),
            'by_type': dict(type_counts),
            'by_status': dict(status_counts),
            'failure_count': sum(1 for r in records if r.status in ['failure', 'failed', 'error'])
        }


# Global instance
_webhook_service: Optional[WebhookIntegrationService] = None


def get_webhook_service() -> WebhookIntegrationService:
    """Get or create the global webhook integration service."""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookIntegrationService()
    return _webhook_service
