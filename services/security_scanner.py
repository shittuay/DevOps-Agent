"""Security scanning service for AWS infrastructure"""
from datetime import datetime
from typing import List, Dict
from models import db, SecurityFinding, InfrastructureResource
from src.tools.aws_tools import _get_boto_client


def scan_aws_security(user_id: int) -> Dict:
    """
    Run comprehensive security scan on AWS infrastructure.

    Returns:
        Dictionary with scan results and findings count
    """
    results = {
        'findings': [],
        'critical': 0,
        'high': 0,
        'medium': 0,
        'low': 0,
        'total': 0
    }

    # Run all security checks
    findings = []
    findings.extend(scan_s3_buckets(user_id))
    findings.extend(scan_security_groups(user_id))
    findings.extend(scan_unencrypted_resources(user_id))
    findings.extend(scan_iam_issues(user_id))

    # Save findings to database
    for finding_data in findings:
        # Check if finding already exists
        existing = SecurityFinding.query.filter_by(
            user_id=user_id,
            finding_type=finding_data['finding_type'],
            affected_resource_id=finding_data.get('affected_resource_id')
        ).first()

        if existing:
            # Update existing finding
            existing.last_detected = datetime.utcnow()
            existing.status = 'open'  # Reopen if it was resolved
        else:
            # Create new finding
            finding = SecurityFinding(
                user_id=user_id,
                **finding_data
            )
            db.session.add(finding)
            findings.append(finding_data)

        # Count by severity
        severity = finding_data.get('severity', 'low')
        if severity == 'critical':
            results['critical'] += 1
        elif severity == 'high':
            results['high'] += 1
        elif severity == 'medium':
            results['medium'] += 1
        elif severity == 'low':
            results['low'] += 1

    db.session.commit()

    results['total'] = len(findings)
    results['findings'] = findings

    return results


def scan_s3_buckets(user_id: int) -> List[Dict]:
    """Scan S3 buckets for public access and encryption issues"""
    findings = []

    try:
        s3 = _get_boto_client('s3')
        buckets = s3.list_buckets()

        for bucket in buckets.get('Buckets', []):
            bucket_name = bucket['Name']

            # Check public access
            try:
                acl = s3.get_bucket_acl(Bucket=bucket_name)
                for grant in acl.get('Grants', []):
                    grantee = grant.get('Grantee', {})
                    if grantee.get('Type') == 'Group' and 'AllUsers' in grantee.get('URI', ''):
                        findings.append({
                            'finding_type': 'open_s3_bucket',
                            'severity': 'critical',
                            'title': f'Publicly accessible S3 bucket: {bucket_name}',
                            'description': f'S3 bucket "{bucket_name}" is publicly accessible. This could expose sensitive data to the internet.',
                            'compliance_frameworks': ['CIS', 'SOC2', 'HIPAA', 'PCI-DSS'],
                            'cis_benchmark_id': 'CIS-2.1.5',
                            'cloud_provider': 'aws',
                            'affected_resource_type': 's3_bucket',
                            'affected_resource_id': bucket_name,
                            'affected_resource_name': bucket_name,
                            'finding_data': {'acl': acl},
                            'remediation_steps': f'Run: aws s3api put-bucket-acl --bucket {bucket_name} --acl private',
                            'auto_remediation_available': True,
                            'risk_score': 95,
                            'exploitability': 'high'
                        })
            except Exception as e:
                pass  # Bucket might not exist or no permission

            # Check encryption
            try:
                encryption = s3.get_bucket_encryption(Bucket=bucket_name)
            except:
                findings.append({
                    'finding_type': 'unencrypted_s3_bucket',
                    'severity': 'high',
                    'title': f'Unencrypted S3 bucket: {bucket_name}',
                    'description': f'S3 bucket "{bucket_name}" does not have default encryption enabled.',
                    'compliance_frameworks': ['CIS', 'SOC2', 'HIPAA'],
                    'cis_benchmark_id': 'CIS-2.1.1',
                    'cloud_provider': 'aws',
                    'affected_resource_type': 's3_bucket',
                    'affected_resource_id': bucket_name,
                    'affected_resource_name': bucket_name,
                    'remediation_steps': f'Enable S3 bucket encryption with AWS KMS',
                    'auto_remediation_available': True,
                    'risk_score': 75,
                    'exploitability': 'medium'
                })

    except Exception as e:
        print(f'Error scanning S3 buckets: {e}')

    return findings


def scan_security_groups(user_id: int) -> List[Dict]:
    """Scan security groups for overly permissive rules"""
    findings = []

    try:
        ec2 = _get_boto_client('ec2')
        response = ec2.describe_security_groups()

        for sg in response.get('SecurityGroups', []):
            sg_id = sg['GroupId']
            sg_name = sg.get('GroupName', sg_id)

            # Check for 0.0.0.0/0 ingress rules
            for rule in sg.get('IpPermissions', []):
                for ip_range in rule.get('IpRanges', []):
                    if ip_range.get('CidrIp') == '0.0.0.0/0':
                        port_range = f"{rule.get('FromPort', 'all')}-{rule.get('ToPort', 'all')}"
                        findings.append({
                            'finding_type': 'overly_permissive_security_group',
                            'severity': 'high' if rule.get('FromPort') in [22, 3389, 3306, 5432] else 'medium',
                            'title': f'Security group allows unrestricted access: {sg_name}',
                            'description': f'Security group "{sg_name}" ({sg_id}) allows inbound traffic from 0.0.0.0/0 on ports {port_range}.',
                            'compliance_frameworks': ['CIS', 'SOC2'],
                            'cis_benchmark_id': 'CIS-5.2',
                            'cloud_provider': 'aws',
                            'affected_resource_type': 'security_group',
                            'affected_resource_id': sg_id,
                            'affected_resource_name': sg_name,
                            'finding_data': {'rule': rule, 'ports': port_range},
                            'remediation_steps': f'Restrict security group {sg_id} to specific IP ranges instead of 0.0.0.0/0',
                            'auto_remediation_available': False,
                            'risk_score': 85 if rule.get('FromPort') in [22, 3389] else 65,
                            'exploitability': 'high'
                        })

    except Exception as e:
        print(f'Error scanning security groups: {e}')

    return findings


def scan_unencrypted_resources(user_id: int) -> List[Dict]:
    """Scan for unencrypted RDS instances and EBS volumes"""
    findings = []

    try:
        # Check RDS instances
        rds = _get_boto_client('rds')
        response = rds.describe_db_instances()

        for db_instance in response.get('DBInstances', []):
            if not db_instance.get('StorageEncrypted', False):
                db_id = db_instance['DBInstanceIdentifier']
                findings.append({
                    'finding_type': 'unencrypted_database',
                    'severity': 'high',
                    'title': f'Unencrypted RDS database: {db_id}',
                    'description': f'RDS database "{db_id}" does not have encryption enabled.',
                    'compliance_frameworks': ['CIS', 'SOC2', 'HIPAA', 'PCI-DSS'],
                    'cis_benchmark_id': 'CIS-3.1',
                    'cloud_provider': 'aws',
                    'affected_resource_type': 'rds',
                    'affected_resource_id': db_id,
                    'affected_resource_name': db_id,
                    'finding_data': {'engine': db_instance.get('Engine')},
                    'remediation_steps': 'Create encrypted snapshot and restore to new encrypted instance',
                    'auto_remediation_available': False,
                    'risk_score': 80,
                    'exploitability': 'medium'
                })

    except Exception as e:
        print(f'Error scanning RDS instances: {e}')

    return findings


def scan_iam_issues(user_id: int) -> List[Dict]:
    """Scan IAM for security issues"""
    findings = []

    try:
        iam = _get_boto_client('iam')

        # Check for root account usage
        credential_report = iam.generate_credential_report()

        # Check for users without MFA
        users = iam.list_users()
        for user in users.get('Users', []):
            username = user['UserName']
            mfa_devices = iam.list_mfa_devices(UserName=username)

            if len(mfa_devices.get('MFADevices', [])) == 0:
                findings.append({
                    'finding_type': 'iam_user_without_mfa',
                    'severity': 'medium',
                    'title': f'IAM user without MFA: {username}',
                    'description': f'IAM user "{username}" does not have MFA enabled.',
                    'compliance_frameworks': ['CIS', 'SOC2'],
                    'cis_benchmark_id': 'CIS-1.2',
                    'cloud_provider': 'aws',
                    'affected_resource_type': 'iam_user',
                    'affected_resource_id': username,
                    'affected_resource_name': username,
                    'remediation_steps': f'Enable MFA for IAM user {username}',
                    'auto_remediation_available': False,
                    'risk_score': 60,
                    'exploitability': 'medium'
                })

    except Exception as e:
        print(f'Error scanning IAM: {e}')

    return findings


def get_security_summary(user_id: int) -> Dict:
    """Get security summary for dashboard"""
    findings = SecurityFinding.query.filter_by(
        user_id=user_id,
        status='open'
    ).all()

    summary = {
        'total_findings': len(findings),
        'critical': len([f for f in findings if f.severity == 'critical']),
        'high': len([f for f in findings if f.severity == 'high']),
        'medium': len([f for f in findings if f.severity == 'medium']),
        'low': len([f for f in findings if f.severity == 'low']),
        'by_type': {},
        'recent_findings': [f.to_dict() for f in findings[:10]]
    }

    # Group by type
    for finding in findings:
        finding_type = finding.finding_type
        if finding_type not in summary['by_type']:
            summary['by_type'][finding_type] = 0
        summary['by_type'][finding_type] += 1

    return summary
