"""AWS security checks for the signed-in user's own account.

Seven checks across four areas: public and unencrypted/unversioned S3 buckets,
security groups open to the internet, public or unencrypted RDS databases, and IAM
console users without MFA.

Rules that matter (2026-10-14 audit):
- **A check that could not read the account is not a clean result.** Every area
  reports `ok` or `error` in `checks`; if no area could run at all the scan raises
  `SecurityScanError` instead of returning "no findings". A per-item read failure
  (one bucket's ACL) is a warning on that check, never a pass.
- **Each finding is counted once.** The old loop appended to the list it was
  iterating, so every new finding was counted twice.
- **Fixed problems close.** An open finding that a check which ran successfully no
  longer sees is marked resolved; findings from a check that failed are left alone.
- Security groups and RDS are regional; the region scanned is reported.
"""
import logging
import os as _os
from typing import Dict, List, Tuple

from botocore.exceptions import ClientError

from models import db, SecurityFinding
from services.notification_service import notify_security as _notify_security
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

# finding_type -> the check that produces it (used to resolve findings the
# check no longer sees, but only when that check ran).
CHECK_FOR_TYPE = {
    'open_s3_bucket': 's3',
    'unencrypted_s3_bucket': 's3',
    'unversioned_s3_bucket': 's3',
    'overly_permissive_security_group': 'security_groups',
    'public_rds_instance': 'rds',
    'unencrypted_database': 'rds',
    'iam_user_without_mfa': 'iam',
}

CHECK_LABELS = {
    's3': 'S3 buckets (public access, encryption, versioning)',
    'security_groups': 'Security groups open to the internet',
    'rds': 'RDS databases (public access, encryption)',
    'iam': 'IAM console users without MFA',
}


class SecurityScanError(Exception):
    """None of the checks could read the account; there is no result to report."""


def _get_boto_client(service: str, user_id: int):
    from services.credential_service import get_user_boto_client
    return get_user_boto_client(user_id, service, None)


def _short(e: Exception) -> str:
    if isinstance(e, ClientError):
        err = e.response.get('Error', {})
        return f"{err.get('Code', 'Error')}: {err.get('Message', '')}"[:200]
    return str(e)[:200]


def scan_aws_security(user_id: int) -> Dict:
    """Run every check, store the findings, and return what was found and what ran.

    Raises SecurityScanError when no check could run (no AWS account connected,
    credentials rejected, or every call denied).
    """
    checks: Dict[str, Dict] = {}
    found: List[Dict] = []
    region = None

    for name, fn in (('s3', scan_s3_buckets), ('security_groups', scan_security_groups),
                     ('rds', scan_rds), ('iam', scan_iam_issues)):
        try:
            items, warnings, check_region = fn(user_id)
        except Exception as e:  # the whole area could not be read
            logger.warning("Security check %s failed for user %s: %s", name, user_id, e)
            checks[name] = {'status': 'error', 'error': _short(e), 'label': CHECK_LABELS[name]}
            continue
        checks[name] = {'status': 'ok', 'warnings': warnings, 'label': CHECK_LABELS[name]}
        region = region or check_region
        found.extend(items)

    if not any(c['status'] == 'ok' for c in checks.values()):
        first = next(iter(checks.values()))['error']
        raise SecurityScanError(f"Couldn't read your AWS account: {first}")

    # One finding per (type, resource).
    unique: Dict[Tuple[str, str], Dict] = {}
    for f in found:
        unique.setdefault((f['finding_type'], f.get('affected_resource_id') or ''), f)

    now = utcnow()
    for (ftype, rid), data in unique.items():
        existing = SecurityFinding.query.filter_by(
            user_id=user_id, finding_type=ftype, affected_resource_id=rid or None,
        ).first()
        if existing:
            existing.last_detected = now
            existing.severity = data['severity']
            existing.title = data['title']
            if existing.status == 'resolved':
                existing.status = 'open'
                existing.resolved_at = None
        else:
            db.session.add(SecurityFinding(user_id=user_id, **data))

    # Close what successful checks no longer see.
    ran = {name for name, c in checks.items() if c['status'] == 'ok'}
    seen = set(unique)
    resolved = 0
    for f in SecurityFinding.query.filter_by(user_id=user_id, status='open').all():
        if CHECK_FOR_TYPE.get(f.finding_type) in ran and (f.finding_type, f.affected_resource_id or '') not in seen:
            f.status = 'resolved'
            f.resolved_at = now
            f.resolution_notes = 'No longer detected by the security checks'
            resolved += 1

    db.session.commit()

    findings = list(unique.values())
    counts = {sev: sum(1 for f in findings if f['severity'] == sev) for sev in ('critical', 'high', 'medium', 'low')}
    results = {
        **counts,
        'total': len(findings),
        'findings': findings,
        'checks': checks,
        'region': region,
        'resolved': resolved,
        'scanned_at': now.isoformat(),
    }
    _notify_security(user_id, results, _os.environ.get('BASE_URL', 'https://devopsagent.io'))
    return results


def scan_s3_buckets(user_id: int):
    """Public ACLs, default encryption and versioning on every bucket.

    Returns (findings, warnings, region). Listing buckets failing raises; one
    bucket's read failing is a warning, never a pass.
    """
    s3 = _get_boto_client('s3', user_id)
    findings, warnings = [], []
    for bucket in s3.list_buckets().get('Buckets', []):
        name = bucket['Name']
        base = {'cloud_provider': 'aws', 'affected_resource_type': 's3_bucket',
                'affected_resource_id': name, 'affected_resource_name': name, 'compliance_frameworks': ['CIS']}

        try:
            acl = s3.get_bucket_acl(Bucket=name)
            if any(g.get('Grantee', {}).get('Type') == 'Group' and 'AllUsers' in g.get('Grantee', {}).get('URI', '')
                   for g in acl.get('Grants', [])):
                findings.append({**base, 'finding_type': 'open_s3_bucket', 'severity': 'critical',
                                 'title': f'Publicly readable S3 bucket: {name}',
                                 'description': f'Bucket "{name}" grants access to everyone on the internet through its ACL.',
                                 'cis_benchmark_id': 'CIS-2.1.5',
                                 'remediation_steps': f'aws s3api put-bucket-acl --bucket {name} --acl private, then turn on Block Public Access',
                                 'risk_score': 95, 'exploitability': 'high'})
        except Exception as e:
            warnings.append(f'{name}: could not read its access settings ({_short(e)})')

        try:
            s3.get_bucket_encryption(Bucket=name)
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == 'ServerSideEncryptionConfigurationNotFoundError':
                findings.append({**base, 'finding_type': 'unencrypted_s3_bucket', 'severity': 'high',
                                 'title': f'S3 bucket without default encryption: {name}',
                                 'description': f'Bucket "{name}" has no default encryption setting.',
                                 'cis_benchmark_id': 'CIS-2.1.1',
                                 'remediation_steps': 'Turn on default encryption (SSE-S3 or SSE-KMS) for the bucket',
                                 'risk_score': 75, 'exploitability': 'medium'})
            else:
                warnings.append(f'{name}: could not read its encryption setting ({_short(e)})')
        except Exception as e:
            warnings.append(f'{name}: could not read its encryption setting ({_short(e)})')

        try:
            if s3.get_bucket_versioning(Bucket=name).get('Status') != 'Enabled':
                findings.append({**base, 'finding_type': 'unversioned_s3_bucket', 'severity': 'medium',
                                 'title': f'S3 bucket without versioning: {name}',
                                 'description': f'Bucket "{name}" does not keep old versions, so a deleted or overwritten object cannot be recovered.',
                                 'cis_benchmark_id': 'CIS-2.1.3',
                                 'remediation_steps': f'aws s3api put-bucket-versioning --bucket {name} --versioning-configuration Status=Enabled',
                                 'risk_score': 55, 'exploitability': 'low'})
        except Exception as e:
            warnings.append(f'{name}: could not read its versioning setting ({_short(e)})')
    return findings, warnings, None


_SENSITIVE_PORTS = {22, 3389, 3306, 5432, 1433, 27017, 6379}


def _rule_is_sensitive(rule: Dict) -> bool:
    if rule.get('IpProtocol') == '-1':
        return True
    lo, hi = rule.get('FromPort'), rule.get('ToPort')
    if lo is None:
        return True
    hi = lo if hi is None else hi
    return any(lo <= p <= hi for p in _SENSITIVE_PORTS)


def scan_security_groups(user_id: int):
    """Security group rules that accept traffic from anywhere (IPv4 or IPv6)."""
    ec2 = _get_boto_client('ec2', user_id)
    region = getattr(getattr(ec2, 'meta', None), 'region_name', None)
    findings = []
    for page in ec2.get_paginator('describe_security_groups').paginate():
        for sg in page.get('SecurityGroups', []):
            sg_id, sg_name = sg['GroupId'], sg.get('GroupName', sg['GroupId'])
            open_rules = [r for r in sg.get('IpPermissions', [])
                          if any(x.get('CidrIp') == '0.0.0.0/0' for x in r.get('IpRanges', []))
                          or any(x.get('CidrIpv6') == '::/0' for x in r.get('Ipv6Ranges', []))]
            if not open_rules:
                continue
            ports = sorted({'all' if r.get('IpProtocol') == '-1' else f"{r.get('FromPort')}-{r.get('ToPort')}"
                            for r in open_rules})
            sensitive = any(_rule_is_sensitive(r) for r in open_rules)
            findings.append({
                'finding_type': 'overly_permissive_security_group',
                'severity': 'high' if sensitive else 'medium',
                'title': f'Security group open to the internet: {sg_name}',
                'description': f'Security group "{sg_name}" ({sg_id}) accepts traffic from anywhere on ports {", ".join(ports)}.',
                'compliance_frameworks': ['CIS'], 'cis_benchmark_id': 'CIS-5.2',
                'cloud_provider': 'aws', 'affected_resource_type': 'security_group',
                'affected_resource_id': sg_id, 'affected_resource_name': sg_name, 'region': region,
                'finding_data': {'ports': ports},
                'remediation_steps': f'Limit {sg_id} to the addresses that need it instead of 0.0.0.0/0',
                'risk_score': 85 if sensitive else 65, 'exploitability': 'high'})
    return findings, [], region


def scan_rds(user_id: int):
    """RDS databases that are publicly accessible or unencrypted."""
    rds = _get_boto_client('rds', user_id)
    region = getattr(getattr(rds, 'meta', None), 'region_name', None)
    findings = []
    for page in rds.get_paginator('describe_db_instances').paginate():
        for inst in page.get('DBInstances', []):
            db_id = inst['DBInstanceIdentifier']
            base = {'cloud_provider': 'aws', 'affected_resource_type': 'rds', 'affected_resource_id': db_id,
                    'affected_resource_name': db_id, 'region': region, 'compliance_frameworks': ['CIS'],
                    'finding_data': {'engine': inst.get('Engine')}}
            if inst.get('PubliclyAccessible'):
                findings.append({**base, 'finding_type': 'public_rds_instance', 'severity': 'critical',
                                 'title': f'Publicly accessible database: {db_id}',
                                 'description': f'RDS database "{db_id}" can be reached from the internet.',
                                 'cis_benchmark_id': 'CIS-2.3.3',
                                 'remediation_steps': f'Modify {db_id} to turn off public access',
                                 'risk_score': 90, 'exploitability': 'high'})
            if not inst.get('StorageEncrypted'):
                findings.append({**base, 'finding_type': 'unencrypted_database', 'severity': 'high',
                                 'title': f'Unencrypted database: {db_id}',
                                 'description': f'RDS database "{db_id}" stores data unencrypted.',
                                 'cis_benchmark_id': 'CIS-2.3.1',
                                 'remediation_steps': 'Copy a snapshot with encryption on and restore from it',
                                 'risk_score': 80, 'exploitability': 'medium'})
    return findings, [], region


def scan_iam_issues(user_id: int):
    """IAM users with a console password but no MFA device."""
    iam = _get_boto_client('iam', user_id)
    findings, warnings = [], []
    for page in iam.get_paginator('list_users').paginate():
        for user in page.get('Users', []):
            username = user['UserName']
            try:
                iam.get_login_profile(UserName=username)
            except ClientError as e:
                if e.response.get('Error', {}).get('Code') == 'NoSuchEntity':
                    continue  # no console password, so console MFA does not apply
                warnings.append(f'{username}: could not read console access ({_short(e)})')
                continue
            try:
                if not iam.list_mfa_devices(UserName=username).get('MFADevices'):
                    findings.append({
                        'finding_type': 'iam_user_without_mfa', 'severity': 'medium',
                        'title': f'Console user without MFA: {username}',
                        'description': f'IAM user "{username}" can sign in to the console without MFA.',
                        'compliance_frameworks': ['CIS'], 'cis_benchmark_id': 'CIS-1.10',
                        'cloud_provider': 'aws', 'affected_resource_type': 'iam_user',
                        'affected_resource_id': username, 'affected_resource_name': username,
                        'remediation_steps': f'Assign an MFA device to {username}',
                        'risk_score': 60, 'exploitability': 'medium'})
            except Exception as e:
                warnings.append(f'{username}: could not read MFA devices ({_short(e)})')
    return findings, warnings, None


def get_security_summary(user_id: int) -> Dict:
    """Open findings for the signed-in user, highest risk first."""
    findings = (SecurityFinding.query.filter_by(user_id=user_id, status='open')
                .order_by(SecurityFinding.risk_score.desc()).all())
    last = max((f.last_detected for f in findings if f.last_detected), default=None)
    summary = {
        'total_findings': len(findings),
        'critical': sum(1 for f in findings if f.severity == 'critical'),
        'high': sum(1 for f in findings if f.severity == 'high'),
        'medium': sum(1 for f in findings if f.severity == 'medium'),
        'low': sum(1 for f in findings if f.severity == 'low'),
        'by_type': {},
        'findings': [f.to_dict() for f in findings],
        'last_detected': last.isoformat() if last else None,
    }
    for f in findings:
        summary['by_type'][f.finding_type] = summary['by_type'].get(f.finding_type, 0) + 1
    summary['recent_findings'] = summary['findings'][:10]
    return summary
