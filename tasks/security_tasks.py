"""
Security Tasks

Background tasks for security scanning and auditing.
"""

import logging
from celery import shared_task
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, time_limit=1800)
def run_security_scan(self, user_id: int, scan_type: str, targets: list = None):
    """
    Run security scan for a user.

    Args:
        user_id: User ID
        scan_type: Type of scan (vulnerability, compliance, pentest)
        targets: List of targets to scan
    """
    try:
        logger.info(f"Running {scan_type} scan for user {user_id}")

        from app import app
        from services.cache_service import cache
        from services.security_scanner import scan_aws_security, get_security_summary

        cache_key = f"scan:{user_id}:{scan_type}"

        with app.app_context():
            cache.set(cache_key, {
                'status': 'in_progress',
                'started_at': datetime.utcnow().isoformat(),
                'progress': 0,
                'scan_type': scan_type,
                'targets': targets or [],
            }, ttl=7200)

            # Run AWS security checks — covers S3, security groups, RDS, IAM
            scan_results = scan_aws_security(user_id)

            # For compliance scans also trigger a compliance check
            if scan_type == 'compliance':
                try:
                    from services.compliance_service import ComplianceService
                    svc = ComplianceService(user_id)
                    for fw in ['soc2', 'pci_dss']:
                        svc.run_compliance_check(user_id, fw)
                except Exception as e:
                    logger.warning(f"Compliance checks failed during scan: {e}")

            summary = get_security_summary(user_id)

            cache.set(cache_key, {
                'status': 'completed',
                'completed_at': datetime.utcnow().isoformat(),
                'progress': 100,
                'scan_type': scan_type,
                'results': {
                    'critical': scan_results['critical'],
                    'high': scan_results['high'],
                    'medium': scan_results['medium'],
                    'low': scan_results['low'],
                    'total': scan_results['total'],
                    'summary': summary,
                }
            }, ttl=86400)

            return {
                'status': 'success',
                'user_id': user_id,
                'scan_type': scan_type,
                'findings': scan_results['total'],
                'critical': scan_results['critical'],
                'high': scan_results['high'],
                'medium': scan_results['medium'],
                'low': scan_results['low'],
            }

    except Exception as e:
        logger.error(f"Security scan error: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True)
def audit_user_activity(self):
    """
    Audit user activity for suspicious patterns.
    Called periodically by Celery Beat.
    """
    try:
        from app import app, db
        from models import User, AuditLog
        from tasks.email_tasks import send_security_alert

        with app.app_context():
            suspicious_activities = []

            # Check for suspicious patterns
            # 1. Multiple failed login attempts
            # 2. Unusual API usage patterns
            # 3. Access from new locations
            # 4. Bulk data operations

            # Get users with recent failed logins
            users_with_failures = User.query.filter(
                User.failed_login_attempts >= 3,
                User.last_failed_login > datetime.utcnow() - timedelta(hours=1)
            ).all()

            for user in users_with_failures:
                suspicious_activities.append({
                    'user_id': user.id,
                    'type': 'multiple_failed_logins',
                    'count': user.failed_login_attempts
                })

                # Send alert
                send_security_alert.delay(
                    user_id=user.id,
                    alert_type='Multiple Failed Login Attempts',
                    details={
                        'attempts': user.failed_login_attempts,
                        'last_attempt': user.last_failed_login.isoformat() if user.last_failed_login else 'Unknown'
                    }
                )

            return {
                'status': 'success',
                'suspicious_activities_found': len(suspicious_activities),
                'alerts_sent': len(suspicious_activities)
            }

    except Exception as e:
        logger.error(f"Audit error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, time_limit=3600)
def run_compliance_check(self, user_id: int, framework: str):
    """
    Run compliance check against a framework.

    Args:
        user_id: User ID
        framework: Compliance framework (soc2, hipaa, gdpr, pci / pci_dss)
    """
    try:
        from app import app
        from services.compliance_service import ComplianceService

        # Normalise alias: task callers may pass 'pci', service expects 'pci_dss'
        framework_name = 'pci_dss' if framework == 'pci' else framework

        logger.info(f"Running {framework_name} compliance check for user {user_id}")

        with app.app_context():
            service = ComplianceService(user_id)
            report = service.run_compliance_check(user_id, framework_name)

            return {
                'status': 'success',
                'framework': framework_name,
                'report_id': report.id,
                'score': report.overall_score,
                'controls_passed': report.controls_passed,
                'controls_failed': report.controls_failed,
                'results': report.findings,
            }

    except Exception as e:
        logger.error(f"Compliance check error: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(bind=True, time_limit=600)
def scan_exposed_secrets(self, user_id: int, repositories: list = None):
    """
    Scan repositories for exposed secrets.

    Shallow-clones each repo to a temp directory, scans all text files
    using secret_detector patterns, then removes the temp directory.

    Args:
        user_id: User ID
        repositories: List of repository URLs to scan
    """
    import os
    import shutil
    import subprocess
    import tempfile
    from services.secret_detector import scan_for_secrets

    if not repositories:
        return {
            'status': 'success',
            'user_id': user_id,
            'repositories_scanned': 0,
            'secrets_found': 0,
            'findings': []
        }

    logger.info(f"Scanning {len(repositories)} repositories for secrets (user {user_id})")

    all_findings = []
    repos_scanned = 0
    repos_failed = []

    import urllib.parse
    _ALLOWED_SCHEMES = {'https', 'http', 'git', 'ssh'}

    for repo_url in repositories:
        # Reject non-allowlisted URL schemes (blocks file://, internal://, etc.)
        try:
            parsed = urllib.parse.urlparse(repo_url)
            if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
                repos_failed.append({'url': repo_url, 'error': f'Disallowed URL scheme: {parsed.scheme}'})
                continue
        except Exception:
            repos_failed.append({'url': repo_url, 'error': 'Invalid URL'})
            continue

        tmp_dir = tempfile.mkdtemp(prefix='devops_secret_scan_')
        try:
            # Shallow clone — history not needed for secret scanning
            result = subprocess.run(
                ['git', 'clone', '--depth=1', '--quiet', repo_url, tmp_dir],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                repos_failed.append({'url': repo_url, 'error': result.stderr.strip()})
                continue

            repo_findings = _scan_directory_for_secrets(tmp_dir, repo_url, scan_for_secrets)
            all_findings.extend(repo_findings)
            repos_scanned += 1

        except subprocess.TimeoutExpired:
            repos_failed.append({'url': repo_url, 'error': 'Clone timed out after 120s'})
        except Exception as e:
            repos_failed.append({'url': repo_url, 'error': str(e)})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        'status': 'success',
        'user_id': user_id,
        'repositories_scanned': repos_scanned,
        'repositories_failed': repos_failed,
        'secrets_found': len(all_findings),
        'findings': all_findings
    }


def _scan_directory_for_secrets(root: str, repo_url: str, scan_fn) -> list:
    """Walk a cloned repo and scan all readable text files for secrets."""
    import os

    findings = []
    skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'vendor', 'dist', 'build'}
    max_file_bytes = 512 * 1024  # skip files > 512 KB

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune dirs in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(filepath, root)

            try:
                if os.path.getsize(filepath) > max_file_bytes:
                    continue

                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                matches = scan_fn(content)
                for match in matches:
                    findings.append({
                        'repository': repo_url,
                        'file': relative_path,
                        'secret_type': match['type'],
                        # Don't expose the actual secret value — just confirm it was found
                        'preview': match['match'][:4] + '...' if len(match.get('match', '')) > 4 else '***',
                    })

            except (OSError, PermissionError):
                continue

    return findings


@shared_task(bind=True)
def check_credential_exposure(self, user_id: int):
    """
    Check if user's email has appeared in known data breaches via HaveIBeenPwned.

    Requires HIBP_API_KEY env var (https://haveibeenpwned.com/API/Key).
    If the key is not configured, returns a skipped result rather than failing.

    Args:
        user_id: User ID
    """
    import os
    import time
    import urllib.request
    import urllib.error
    import json

    try:
        from app import app
        from models import User
        from tasks.email_tasks import send_security_alert

        with app.app_context():
            user = User.query.get(user_id)
            if not user:
                return {'status': 'error', 'message': 'User not found'}

            api_key = os.environ.get('HIBP_API_KEY', '').strip()
            if not api_key:
                logger.info(f"HIBP_API_KEY not configured — skipping breach check for user {user_id}")
                return {
                    'status': 'skipped',
                    'reason': 'HIBP_API_KEY not configured',
                    'user_id': user_id,
                    'exposed': False,
                    'breaches': []
                }

            email = user.email
            breaches = _check_hibp_breaches(email, api_key)

            if breaches:
                breach_names = [b.get('Name', 'Unknown') for b in breaches]
                sensitive_classes = {'Passwords', 'Credit cards', 'Bank account numbers', 'Social security numbers'}
                has_sensitive = any(
                    dc in sensitive_classes
                    for b in breaches
                    for dc in b.get('DataClasses', [])
                )

                logger.warning(
                    f"User {user_id} email found in {len(breaches)} breach(es): {', '.join(breach_names)}"
                )

                send_security_alert.delay(
                    user_id=user_id,
                    alert_type='Credential Exposure Detected',
                    details={
                        'email': email,
                        'breach_count': len(breaches),
                        'breaches': breach_names,
                        'has_sensitive_data': has_sensitive,
                        'recommendation': (
                            'Your email was found in a data breach. '
                            'We strongly recommend enabling MFA and using a unique password '
                            'for this account.' if has_sensitive else
                            'Your email appeared in a data breach. '
                            'Consider reviewing your account security settings.'
                        )
                    }
                )

            return {
                'status': 'success',
                'user_id': user_id,
                'exposed': len(breaches) > 0,
                'breach_count': len(breaches),
                'breaches': [
                    {
                        'name': b.get('Name'),
                        'breach_date': b.get('BreachDate'),
                        'data_classes': b.get('DataClasses', []),
                        'pwn_count': b.get('PwnCount'),
                    }
                    for b in breaches
                ]
            }

    except Exception as e:
        logger.error(f"Credential exposure check error: {e}")
        return {'status': 'error', 'message': str(e)}


def _check_hibp_breaches(email: str, api_key: str) -> list:
    """
    Query HaveIBeenPwned v3 API for breaches containing the given email.

    Returns list of breach dicts, or empty list if not found.
    Raises on network/API errors so the caller can handle retries.
    """
    import urllib.parse
    import urllib.request
    import urllib.error
    import json

    encoded = urllib.parse.quote(email, safe='')
    url = f'https://haveibeenpwned.com/api/v3/breachedaccount/{encoded}?truncateResponse=false'

    req = urllib.request.Request(url, headers={
        'hibp-api-key': api_key,
        'user-agent': 'DevOpsAgent-BreachCheck/1.0',
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # email not found in any breach — good news
        if e.code == 401:
            raise RuntimeError('HIBP API key is invalid or expired') from e
        if e.code == 429:
            raise RuntimeError('HIBP rate limit hit — retry later') from e
        raise
