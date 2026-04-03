"""
DevOps Operations Tools - Cost analysis, change governance, and compliance.

Connects the AI chat to real backend services:
- Cost Explorer + CloudWatch metrics
- Change request creation and management
- Security scanning and compliance checks
"""
import threading
from typing import Dict, Any, Optional, List

_user_context = threading.local()


def set_user_context(user_id: Optional[int] = None):
    _user_context.user_id = user_id


def get_current_user_id() -> Optional[int]:
    return getattr(_user_context, 'user_id', None)


def _require_user():
    uid = get_current_user_id()
    if not uid:
        return None, {'success': False, 'error': 'No user context. Please log in.'}
    return uid, None


# ── Cost Analysis Tools ──

def get_cost_summary(days: int = 30) -> Dict[str, Any]:
    """Get real AWS cost breakdown by service with daily trend."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.cost_explorer import get_actual_costs, get_cost_forecast
        costs = get_actual_costs(uid, days=days)
        forecast = get_cost_forecast(uid)
        return {
            'success': True,
            'total_cost': costs.get('total_cost', 0),
            'services': costs.get('services', []),
            'daily_trend': costs.get('daily_trend', []),
            'forecast': forecast,
            'period_days': days
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_optimization_recommendations() -> Dict[str, Any]:
    """Get cost optimization recommendations based on real CloudWatch utilization data."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.cost_explorer import generate_real_cost_recommendations
        recs = generate_real_cost_recommendations(uid)
        return {
            'success': True,
            'recommendations': [{
                'id': r.id,
                'title': r.title,
                'description': r.description,
                'savings': float(r.potential_monthly_savings) if r.potential_monthly_savings else 0,
                'type': r.recommendation_type,
                'resource': r.resource.resource_name if r.resource else None
            } for r in recs],
            'total_potential_savings': sum(
                float(r.potential_monthly_savings or 0) for r in recs
            )
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_resource_utilization(resource_name: str) -> Dict[str, Any]:
    """Get CPU, network, and disk utilization for a specific resource from CloudWatch."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from models import InfrastructureResource
        resource = InfrastructureResource.query.filter_by(
            user_id=uid
        ).filter(
            (InfrastructureResource.resource_name.ilike(f'%{resource_name}%')) |
            (InfrastructureResource.resource_id.ilike(f'%{resource_name}%'))
        ).first()

        if not resource:
            return {'success': False, 'error': f'Resource "{resource_name}" not found'}

        from services.cost_explorer import get_instance_utilization, get_rds_utilization
        if resource.resource_type in ('ec2', 'EC2 Instance'):
            metrics = get_instance_utilization(uid, resource.resource_id)
        elif resource.resource_type in ('rds', 'RDS Instance'):
            metrics = get_rds_utilization(uid, resource.resource_id)
        else:
            return {'success': False, 'error': f'Utilization not available for {resource.resource_type}'}

        return {
            'success': True,
            'resource': resource.resource_name,
            'resource_id': resource.resource_id,
            'type': resource.resource_type,
            'metrics': metrics
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Change Governance Tools ──

def create_change_request(
    title: str,
    action_type: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    resource_name: Optional[str] = None,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """Create an infrastructure change request with automatic risk classification."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from models import db, InfrastructureChange
        from routes.changes import classify_risk
        from datetime import datetime

        change_details = {'resource_name': resource_name or ''}
        risk_level = classify_risk(action_type, resource_type, change_details)
        change_details['risk_level'] = risk_level

        change = InfrastructureChange(
            user_id=uid,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            cloud_provider='aws',
            title=title,
            description=description,
            change_details=change_details,
            status='pending'
        )

        if risk_level == 'low':
            change.status = 'approved'
            change.approver_id = uid
            change.approval_comment = 'Auto-approved: low risk'
            change.approved_at = datetime.utcnow()

        db.session.add(change)
        db.session.commit()

        return {
            'success': True,
            'change_id': change.id,
            'title': change.title,
            'risk_level': risk_level,
            'status': change.status,
            'auto_approved': risk_level == 'low',
            'message': f'Change #{change.id} created ({risk_level} risk' +
                       (', auto-approved)' if risk_level == 'low' else ', requires approval)')
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def list_change_requests(status: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """List infrastructure change requests with optional status filter."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from models import InfrastructureChange
        query = InfrastructureChange.query.filter_by(user_id=uid)
        if status:
            query = query.filter_by(status=status)
        changes = query.order_by(InfrastructureChange.created_at.desc()).limit(limit).all()

        return {
            'success': True,
            'changes': [{
                'id': c.id,
                'title': c.title,
                'action': c.action_type,
                'resource_type': c.resource_type,
                'resource_name': c.resource_name,
                'status': c.status,
                'risk_level': (c.change_details or {}).get('risk_level', 'unknown'),
                'created_at': c.created_at.isoformat() if c.created_at else None
            } for c in changes],
            'count': len(changes)
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Security & Compliance Tools ──

def run_security_scan() -> Dict[str, Any]:
    """Run a real AWS security scan checking S3, security groups, RDS, and IAM."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.security_scanner import scan_aws_security
        results = scan_aws_security(uid)
        return {
            'success': True,
            'total_findings': results['total'],
            'critical': results['critical'],
            'high': results['high'],
            'medium': results['medium'],
            'low': results['low'],
            'findings': [{
                'type': f.get('finding_type'),
                'severity': f.get('severity'),
                'title': f.get('title'),
                'resource': f.get('affected_resource_name'),
                'remediation': f.get('remediation_steps')
            } for f in results.get('findings', [])[:15]]
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def run_compliance_check(framework: str = 'soc2') -> Dict[str, Any]:
    """Run compliance check against a framework (soc2, hipaa, pci_dss)."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.compliance_service import ComplianceService
        service = ComplianceService(uid)
        report = service.run_compliance_check(uid, framework)

        return {
            'success': True,
            'framework': framework,
            'score': report.overall_score,
            'controls_passed': report.controls_passed,
            'controls_failed': report.controls_failed,
            'controls': [{
                'id': c['control_id'],
                'title': c['control_title'],
                'status': c['status'],
                'findings': c['findings_count']
            } for c in (report.findings or [])]
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_security_findings(severity: Optional[str] = None) -> Dict[str, Any]:
    """Get open security findings, optionally filtered by severity."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from models import SecurityFinding
        query = SecurityFinding.query.filter_by(user_id=uid, status='open')
        if severity:
            query = query.filter_by(severity=severity)
        findings = query.order_by(SecurityFinding.risk_score.desc()).limit(20).all()

        return {
            'success': True,
            'findings': [{
                'id': f.id,
                'type': f.finding_type,
                'severity': f.severity,
                'title': f.title,
                'resource': f.affected_resource_name,
                'risk_score': f.risk_score,
                'remediation': f.remediation_steps,
                'frameworks': f.compliance_frameworks or []
            } for f in findings],
            'count': len(findings)
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def sync_infrastructure() -> Dict[str, Any]:
    """Sync infrastructure resources from AWS, update costs, and generate recommendations."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.infrastructure_sync import sync_user_infrastructure
        result = sync_user_infrastructure(uid)

        try:
            from services.cost_explorer import update_resource_costs_from_explorer, generate_real_cost_recommendations
            update_resource_costs_from_explorer(uid)
            generate_real_cost_recommendations(uid)
        except Exception:
            pass

        total = result.get('total_resources', 0)
        aws_synced = result.get('aws', {}).get('synced', 0)
        aws_errors = result.get('aws', {}).get('errors', [])
        return {
            'success': True,
            'resources_synced': total,
            'aws_synced': aws_synced,
            'aws_errors': aws_errors,
            'total_cost': result.get('total_cost', 0.0),
            'message': f'Synced {total} resources (AWS: {aws_synced})'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def get_infrastructure_summary() -> Dict[str, Any]:
    """Get summary of all synced infrastructure resources with costs."""
    uid, err = _require_user()
    if err:
        return err
    try:
        from services.infrastructure_sync import get_dashboard_summary
        summary = get_dashboard_summary(uid)
        return {
            'success': True,
            'total_resources': summary.get('total_resources', 0),
            'monthly_cost': summary.get('total_monthly_cost', 0),
            'potential_savings': summary.get('total_potential_savings', 0),
            'resources_by_cloud': {
                cloud: [{
                    'name': r.get('resource_name'),
                    'type': r.get('resource_type'),
                    'status': r.get('status'),
                    'cost': r.get('monthly_cost')
                } for r in resources]
                for cloud, resources in summary.get('resources_by_cloud', {}).items()
            },
            'recommendations_count': len(summary.get('recommendations', []))
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── Tool Definitions ──

def get_tools() -> List[Dict[str, Any]]:
    return [
        {
            'name': 'get_cost_summary',
            'description': 'Get real AWS cost breakdown by service with daily spending trend from Cost Explorer. Shows total spend, per-service costs, and forecast.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'days': {
                        'type': 'integer',
                        'description': 'Number of days to analyze (default: 30)',
                    }
                },
                'required': []
            },
            'handler': get_cost_summary
        },
        {
            'name': 'get_optimization_recommendations',
            'description': 'Get cost optimization recommendations based on real CloudWatch CPU/network utilization. Identifies idle instances, rightsizing opportunities, and spot instance candidates.',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': get_optimization_recommendations
        },
        {
            'name': 'get_resource_utilization',
            'description': 'Get real CPU, network, and disk utilization metrics from CloudWatch for a specific resource. Provide resource name or ID.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'resource_name': {
                        'type': 'string',
                        'description': 'Resource name or ID to look up (e.g. "dev-api-server" or "i-0abc123")'
                    }
                },
                'required': ['resource_name']
            },
            'handler': get_resource_utilization
        },
        {
            'name': 'create_change_request',
            'description': 'Create an infrastructure change request with automatic risk classification. Low-risk changes are auto-approved, higher risk requires manual approval.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'title': {
                        'type': 'string',
                        'description': 'Short title for the change (e.g. "Stop idle dev instance")'
                    },
                    'action_type': {
                        'type': 'string',
                        'enum': ['start', 'stop', 'resize', 'terminate', 'delete', 'create', 'update', 'tag', 'modify_security_group'],
                        'description': 'Type of infrastructure action'
                    },
                    'resource_type': {
                        'type': 'string',
                        'enum': ['ec2', 'rds', 's3', 'security_group', 'iam', 'vpc', 'load_balancer', 'lambda'],
                        'description': 'Type of cloud resource'
                    },
                    'resource_id': {
                        'type': 'string',
                        'description': 'Cloud resource ID (e.g. i-0abc123)'
                    },
                    'resource_name': {
                        'type': 'string',
                        'description': 'Human-readable resource name'
                    },
                    'description': {
                        'type': 'string',
                        'description': 'Why this change is needed'
                    }
                },
                'required': ['title', 'action_type', 'resource_type']
            },
            'handler': create_change_request
        },
        {
            'name': 'list_change_requests',
            'description': 'List infrastructure change requests. Filter by status: pending, approved, executed, rejected, failed.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'status': {
                        'type': 'string',
                        'enum': ['pending', 'approved', 'executed', 'rejected', 'failed'],
                        'description': 'Filter by status (optional, shows all if omitted)'
                    },
                    'limit': {
                        'type': 'integer',
                        'description': 'Max results to return (default: 10)'
                    }
                },
                'required': []
            },
            'handler': list_change_requests
        },
        {
            'name': 'run_security_scan',
            'description': 'Run a real security scan on AWS infrastructure. Checks S3 bucket access/encryption, security group rules, RDS encryption/public access, and IAM MFA status.',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': run_security_scan
        },
        {
            'name': 'run_compliance_check',
            'description': 'Run compliance check against a specific framework. Maps real AWS security findings to framework controls and calculates compliance score.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'framework': {
                        'type': 'string',
                        'enum': ['soc2', 'hipaa', 'pci_dss'],
                        'description': 'Compliance framework to check against (default: soc2)'
                    }
                },
                'required': []
            },
            'handler': run_compliance_check
        },
        {
            'name': 'get_security_findings',
            'description': 'Get open security findings from the latest scan. Optionally filter by severity level.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'severity': {
                        'type': 'string',
                        'enum': ['critical', 'high', 'medium', 'low'],
                        'description': 'Filter by severity (optional, shows all if omitted)'
                    }
                },
                'required': []
            },
            'handler': get_security_findings
        },
        {
            'name': 'sync_infrastructure',
            'description': 'Sync infrastructure resources from AWS. Discovers EC2, RDS, S3, Lambda, security groups, and more. Also updates costs from Cost Explorer and generates optimization recommendations.',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': sync_infrastructure
        },
        {
            'name': 'get_infrastructure_summary',
            'description': 'Get a summary of all synced infrastructure: resource counts by cloud provider, total monthly cost, potential savings, and recommendation count.',
            'input_schema': {
                'type': 'object',
                'properties': {},
                'required': []
            },
            'handler': get_infrastructure_summary
        }
    ]
