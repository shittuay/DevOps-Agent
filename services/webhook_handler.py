"""
Webhook Handler Service

Receives and processes webhooks from external services (GitHub, PagerDuty,
Datadog, AWS SNS, etc.) and triggers automated actions.
"""

import hmac
import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Supported webhook sources and their signature verification methods
WEBHOOK_SOURCES = {
    'github': {
        'header': 'X-Hub-Signature-256',
        'algo': 'sha256',
        'prefix': 'sha256=',
    },
    'pagerduty': {
        'header': 'X-PagerDuty-Signature',
        'algo': 'sha256',
        'prefix': 'v1=',
    },
    'generic': {
        'header': 'X-Webhook-Signature',
        'algo': 'sha256',
        'prefix': '',
    },
}


def verify_webhook_signature(
    payload: bytes, signature: str, secret: str, source: str = 'generic'
) -> bool:
    """Verify webhook payload signature using HMAC."""
    if not secret or not signature:
        return False

    config = WEBHOOK_SOURCES.get(source, WEBHOOK_SOURCES['generic'])
    algo = config['algo']
    prefix = config['prefix']

    if prefix and signature.startswith(prefix):
        signature = signature[len(prefix):]

    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        getattr(hashlib, algo)
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def parse_github_webhook(payload: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    """Parse a GitHub webhook event into a normalized action."""
    action = payload.get('action', '')
    repo = payload.get('repository', {}).get('full_name', 'unknown')

    result = {
        'source': 'github',
        'event': event_type,
        'action': action,
        'repo': repo,
        'timestamp': datetime.utcnow().isoformat(),
        'suggested_actions': [],
    }

    if event_type == 'push':
        branch = payload.get('ref', '').replace('refs/heads/', '')
        commits = payload.get('commits', [])
        result['branch'] = branch
        result['commit_count'] = len(commits)
        result['summary'] = f"{len(commits)} commit(s) pushed to {repo}/{branch}"
        if branch in ('main', 'master', 'production'):
            result['suggested_actions'].append({
                'type': 'deploy',
                'description': f'Deploy {branch} to production',
                'auto': False,
            })

    elif event_type == 'pull_request':
        pr = payload.get('pull_request', {})
        result['pr_number'] = pr.get('number')
        result['pr_title'] = pr.get('title', '')
        result['summary'] = f"PR #{pr.get('number')} {action}: {pr.get('title', '')}"
        if action == 'opened':
            result['suggested_actions'].append({
                'type': 'review',
                'description': 'Run automated code review',
                'auto': True,
            })

    elif event_type == 'workflow_run':
        workflow = payload.get('workflow_run', {})
        conclusion = workflow.get('conclusion', '')
        result['workflow'] = workflow.get('name', '')
        result['conclusion'] = conclusion
        result['summary'] = f"Workflow '{workflow.get('name')}' {conclusion}"
        if conclusion == 'failure':
            result['suggested_actions'].append({
                'type': 'investigate',
                'description': 'Investigate workflow failure',
                'auto': True,
            })

    elif event_type in ('issues', 'issue_comment'):
        issue = payload.get('issue', {})
        result['issue_number'] = issue.get('number')
        result['issue_title'] = issue.get('title', '')
        result['summary'] = f"Issue #{issue.get('number')} {action}: {issue.get('title', '')}"

    else:
        result['summary'] = f"GitHub event: {event_type} ({action})"

    return result


def parse_pagerduty_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a PagerDuty webhook event."""
    messages = payload.get('messages', [])
    if not messages:
        return {
            'source': 'pagerduty',
            'event': 'unknown',
            'summary': 'Empty PagerDuty webhook',
            'suggested_actions': [],
        }

    msg = messages[0]
    incident = msg.get('incident', {})

    return {
        'source': 'pagerduty',
        'event': msg.get('type', 'incident'),
        'incident_id': incident.get('id'),
        'title': incident.get('title', ''),
        'urgency': incident.get('urgency', 'low'),
        'status': incident.get('status', 'triggered'),
        'summary': f"PagerDuty: {incident.get('title', 'Unknown incident')} ({incident.get('urgency', 'low')})",
        'timestamp': datetime.utcnow().isoformat(),
        'suggested_actions': [
            {
                'type': 'acknowledge',
                'description': 'Acknowledge incident and begin investigation',
                'auto': False,
            }
        ],
    }


def parse_generic_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Parse a generic webhook event."""
    return {
        'source': 'generic',
        'event': payload.get('event', 'unknown'),
        'summary': payload.get('message', payload.get('text', str(payload)[:200])),
        'data': payload,
        'timestamp': datetime.utcnow().isoformat(),
        'suggested_actions': [],
    }


def process_webhook(
    source: str, payload: Dict[str, Any], event_type: Optional[str] = None
) -> Dict[str, Any]:
    """Route and process a webhook based on source."""
    if source == 'github':
        return parse_github_webhook(payload, event_type or 'push')
    elif source == 'pagerduty':
        return parse_pagerduty_webhook(payload)
    else:
        return parse_generic_webhook(payload)
