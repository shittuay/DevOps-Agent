"""
System Diagnostics Service (Doctor)

Inspired by OpenClaw's `openclaw doctor` command. Performs health checks
on all system components and reports status.
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


def run_diagnostics(app=None, db=None, agent=None) -> Dict[str, Any]:
    """
    Run comprehensive system diagnostics.

    Returns:
        Dict with check results grouped by category
    """
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'overall': 'healthy',
        'checks': []
    }

    checks = results['checks']

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append({
        'name': 'Python Version',
        'category': 'system',
        'status': 'ok' if sys.version_info >= (3, 10) else 'warning',
        'detail': py_ver,
    })

    # 2. Database connection
    db_status = _check_database(db)
    checks.append(db_status)

    # 3. Anthropic API key
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    checks.append({
        'name': 'Anthropic API Key',
        'category': 'ai',
        'status': 'ok' if api_key.startswith('sk-ant-') else 'error',
        'detail': f"{api_key[:12]}..." if api_key else 'Not configured',
    })

    # 4. Agent status
    checks.append({
        'name': 'AI Agent',
        'category': 'ai',
        'status': 'ok' if agent is not None else 'error',
        'detail': f"{len(agent.list_available_tools())} tools loaded" if agent else 'Not initialized',
    })

    # 5. Stripe configuration
    stripe_key = os.environ.get('STRIPE_SECRET_KEY', '')
    checks.append({
        'name': 'Stripe Payments',
        'category': 'payments',
        'status': 'ok' if stripe_key else 'warning',
        'detail': 'Configured' if stripe_key else 'Not configured (payments disabled)',
    })

    # 6. Secret key
    secret = os.environ.get('SECRET_KEY', '')
    checks.append({
        'name': 'Flask Secret Key',
        'category': 'security',
        'status': 'ok' if secret and len(secret) >= 32 else 'warning',
        'detail': 'Set' if secret else 'Using auto-generated key',
    })

    # 7. AWS Secrets Manager
    use_aws = os.environ.get('USE_AWS_SECRETS', '').lower() == 'true'
    checks.append({
        'name': 'AWS Secrets Manager',
        'category': 'infrastructure',
        'status': 'ok' if use_aws else 'info',
        'detail': 'Enabled' if use_aws else 'Disabled (using .env)',
    })

    # 8. Disk space
    disk_status = _check_disk_space()
    checks.append(disk_status)

    # 9. Log directory
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    checks.append({
        'name': 'Log Directory',
        'category': 'system',
        'status': 'ok' if os.path.isdir(log_dir) else 'warning',
        'detail': 'Writable' if os.path.isdir(log_dir) and os.access(log_dir, os.W_OK) else 'Missing or not writable',
    })

    # 10. Required packages
    pkg_status = _check_packages()
    checks.extend(pkg_status)

    # 11. 2FA service
    try:
        from services.two_factor_service import two_factor_service
        checks.append({
            'name': 'Two-Factor Auth',
            'category': 'security',
            'status': 'ok',
            'detail': 'Service loaded',
        })
    except Exception as e:
        checks.append({
            'name': 'Two-Factor Auth',
            'category': 'security',
            'status': 'error',
            'detail': str(e),
        })

    # 12. Model failover status
    try:
        from services.model_failover import get_provider_status
        providers = get_provider_status()
        available = sum(1 for p in providers.values() if p.get('available'))
        configured = sum(1 for p in providers.values() if p.get('configured'))
        checks.append({
            'name': 'LLM Failover',
            'category': 'ai',
            'status': 'ok' if available >= 2 else ('warning' if available >= 1 else 'error'),
            'detail': f'{available} providers available, {configured} configured',
        })
    except Exception as e:
        checks.append({
            'name': 'LLM Failover',
            'category': 'ai',
            'status': 'info',
            'detail': f'Not loaded: {str(e)[:60]}',
        })

    # 13. Scheduler status
    try:
        from services.scheduler import get_scheduler_status
        sched = get_scheduler_status()
        checks.append({
            'name': 'Background Scheduler',
            'category': 'system',
            'status': 'ok' if sched['running'] else 'warning',
            'detail': 'Running' if sched['running'] else 'Not running',
        })
    except Exception:
        checks.append({
            'name': 'Background Scheduler',
            'category': 'system',
            'status': 'info',
            'detail': 'Not loaded',
        })

    # 14. Docker sandbox
    try:
        from services.sandbox import get_sandbox_status
        sandbox = get_sandbox_status()
        checks.append({
            'name': 'Docker Sandbox',
            'category': 'infrastructure',
            'status': 'ok' if sandbox['available'] else 'info',
            'detail': f"Docker {sandbox.get('docker_version', 'N/A')}" if sandbox['available'] else 'Docker not available',
        })
    except Exception:
        checks.append({
            'name': 'Docker Sandbox',
            'category': 'infrastructure',
            'status': 'info',
            'detail': 'Not loaded',
        })

    # Compute overall status
    statuses = [c['status'] for c in checks]
    if 'error' in statuses:
        results['overall'] = 'unhealthy'
    elif 'warning' in statuses:
        results['overall'] = 'degraded'

    results['summary'] = {
        'ok': statuses.count('ok'),
        'warning': statuses.count('warning'),
        'error': statuses.count('error'),
        'info': statuses.count('info'),
        'total': len(statuses),
    }

    return results


def _check_database(db) -> dict:
    """Check database connectivity."""
    try:
        if db:
            db.session.execute(db.text('SELECT 1'))
            db.session.rollback()
            return {
                'name': 'Database',
                'category': 'database',
                'status': 'ok',
                'detail': 'Connected',
            }
        return {
            'name': 'Database',
            'category': 'database',
            'status': 'error',
            'detail': 'DB not initialized',
        }
    except Exception as e:
        return {
            'name': 'Database',
            'category': 'database',
            'status': 'error',
            'detail': str(e)[:100],
        }


def _check_disk_space() -> dict:
    """Check available disk space."""
    try:
        import shutil
        total, used, free = shutil.disk_usage('/')
        free_gb = free / (1024 ** 3)
        total_gb = total / (1024 ** 3)
        pct_free = (free / total) * 100
        status = 'ok' if pct_free > 10 else ('warning' if pct_free > 5 else 'error')
        return {
            'name': 'Disk Space',
            'category': 'system',
            'status': status,
            'detail': f"{free_gb:.1f} GB free / {total_gb:.1f} GB total ({pct_free:.0f}%)",
        }
    except Exception:
        return {
            'name': 'Disk Space',
            'category': 'system',
            'status': 'info',
            'detail': 'Unable to check',
        }


def _check_packages() -> List[dict]:
    """Check critical Python packages."""
    packages = [
        ('anthropic', 'Anthropic SDK', 'ai'),
        ('pyotp', 'TOTP (2FA)', 'security'),
        ('stripe', 'Stripe SDK', 'payments'),
        ('boto3', 'AWS SDK', 'infrastructure'),
    ]

    results = []
    for pkg_name, display_name, category in packages:
        try:
            mod = __import__(pkg_name)
            version = getattr(mod, '__version__', 'installed')
            results.append({
                'name': display_name,
                'category': category,
                'status': 'ok',
                'detail': f"v{version}",
            })
        except ImportError:
            results.append({
                'name': display_name,
                'category': category,
                'status': 'warning',
                'detail': 'Not installed',
            })

    return results
