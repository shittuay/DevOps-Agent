---
name: security-scan
description: Run security scans across cloud infrastructure, compliance frameworks, credentials, and vulnerabilities. Use when auditing security posture, checking compliance, hunting for leaked secrets, or performing authorized penetration testing.
---

# Security Scan Workflow

## Overview

This skill orchestrates the DevOps Agent's security tooling into structured scan workflows. It covers infrastructure security, compliance assessment, credential leak detection, vulnerability scanning, and audit trail analysis.

**Always confirm authorization before running vulnerability or penetration scans against any target.**

## Scan Types

| Type | What It Covers | Speed |
|------|---------------|-------|
| **Quick scan** | S3 buckets + security groups + secret detection | ~1 min |
| **Full scan** | All phases below, end-to-end | ~10 min |
| **Compliance scan** | Framework checks (SOC2, HIPAA, PCI-DSS, GDPR) | ~3 min |
| **Vulnerability scan** | Port scans, SSL, web app testing (requires auth) | ~5 min |
| **Credential audit** | Secret detection across configs, logs, env files | ~1 min |

---

## Phase 1: Infrastructure Security Scan

Scans AWS resources for misconfigurations using `services/security_scanner.py`.

### Run Full AWS Security Scan

```python
from services.security_scanner import scan_aws_security
results = scan_aws_security(user_id=current_user.id)
# Returns: {'s3': [...], 'security_groups': [...], 'encryption': [...], 'iam': [...]}
```

### Individual Scans

```python
from services.security_scanner import (
    scan_s3_buckets,
    scan_security_groups,
    scan_unencrypted_resources,
    scan_iam_issues,
    get_security_summary
)

# S3: public access, missing encryption
s3_findings = scan_s3_buckets(user_id=current_user.id)

# Security groups: overly permissive rules (0.0.0.0/0)
sg_findings = scan_security_groups(user_id=current_user.id)

# Encryption: unencrypted RDS instances and EBS volumes
enc_findings = scan_unencrypted_resources(user_id=current_user.id)

# IAM: users without MFA
iam_findings = scan_iam_issues(user_id=current_user.id)

# Summary of open findings by severity
summary = get_security_summary(user_id=current_user.id)
```

### What To Look For

- **Critical**: S3 buckets with public read/write, security groups open on 0.0.0.0/0 for SSH/RDP
- **High**: Unencrypted RDS instances, IAM users without MFA
- **Medium**: Overly broad security group rules, unencrypted EBS volumes

---

## Phase 2: Compliance Assessment

Runs checks against compliance frameworks using `services/compliance_service.py`.

### Supported Frameworks

SOC2, HIPAA, PCI-DSS, GDPR, ISO27001, NIST, CIS

### Run Compliance Check

```python
from services.compliance_service import get_compliance_service

service = get_compliance_service(user_id=current_user.id)

# Enable a framework for the user
service.enable_framework(user_id=current_user.id, framework_name='SOC2')

# Run real AWS scan mapped to compliance controls
report = service.run_compliance_check(user_id=current_user.id, framework_name='SOC2')

# Get compliance summary with scores across all frameworks
summary = service.get_compliance_summary(user_id=current_user.id)

# Generate executive summary
exec_summary = service.generate_executive_summary(user_id=current_user.id)
```

### Retrieve Reports

```python
# All reports for a user
reports = service.get_user_reports(user_id=current_user.id)

# Filter by framework
hipaa_reports = service.get_user_reports(user_id=current_user.id, framework_name='HIPAA')

# Single report by ID
report = service.get_compliance_report(report_id=42)
```

### Compliance Policies

```python
# Create a policy
policy = service.create_policy(
    user_id=current_user.id,
    name='Encryption Required',
    policy_type='encryption',
    rules=[{'type': 'require_encryption', 'scope': 'all_storage'}]
)

# List user policies
policies = service.get_user_policies(user_id=current_user.id)

# Create default policy set
service.create_default_policies(user_id=current_user.id)
```

---

## Phase 3: Credential & Secret Scanning

Detects leaked secrets in text, configs, logs, and environment files using `services/secret_detector.py`.

### Detected Secret Types (17 patterns)

AWS access keys, API keys, Anthropic/OpenAI/Stripe keys, GitHub tokens, bearer tokens, private keys, Azure secrets, GCP keys, database passwords, generic passwords, Slack/Discord webhooks.

### Scan Text for Secrets

```python
from services.secret_detector import scan_for_secrets, redact_secrets, contains_secrets

# Quick boolean check
if contains_secrets(config_text):
    print("Secrets detected!")

# Detailed scan — returns list of findings with type, match, position
findings = scan_for_secrets(config_text)
for f in findings:
    print(f"Found {f['type']} at position {f['start']}-{f['end']}")

# Redact secrets for safe logging
safe_text = redact_secrets(config_text)
```

### Scan Files in the Codebase

```python
import os
from services.secret_detector import scan_for_secrets

targets = ['.env', '.env.example', 'docker-compose.yml', 'config.py']
for filepath in targets:
    if os.path.exists(filepath):
        with open(filepath) as f:
            findings = scan_for_secrets(f.read())
        if findings:
            print(f"{filepath}: {len(findings)} secret(s) found")
            for f in findings:
                print(f"  - {f['type']}")
```

---

## Phase 4: Vulnerability Scanning

Uses `src/tools/pentest_tools.py` for authorized penetration testing. **Requires explicit user authorization before execution.**

### Available Scans (11 tools)

| Tool | Purpose |
|------|---------|
| `nmap_port_scan` | TCP/UDP port scanning |
| `nmap_service_detection` | Service version fingerprinting |
| `nikto_web_scan` | Web server vulnerability scan |
| `ssl_scan` | SSL/TLS configuration audit |
| `sqlmap_scan` | SQL injection testing |
| `xss_scan` | Cross-site scripting testing |
| `zap_spider_scan` | Web app crawling and scanning |
| `aws_security_audit` | AWS cloud security audit |
| `azure_security_audit` | Azure cloud security audit |
| `gcp_security_audit` | GCP cloud security audit |
| `kubernetes_security_audit` | K8s cluster security audit |
| `quick_vulnerability_scan` | Optimized 2-4 min combined scan |

### Quick Vulnerability Scan

```python
from src.tools.pentest_tools import quick_vulnerability_scan

# Fast combined scan (2-4 minutes)
result = quick_vulnerability_scan(target='https://example.com', scan_type='web')
```

### Cloud Security Audits

```python
from src.tools.pentest_tools import aws_security_audit, kubernetes_security_audit

# AWS audit
aws_result = aws_security_audit(
    region='us-east-1',
    services=['s3', 'ec2', 'iam', 'rds'],
    user_id=current_user.id
)

# Kubernetes audit
k8s_result = kubernetes_security_audit(
    namespace='production',
    context='prod-cluster'
)
```

### Network and Web Scans

```python
from src.tools.pentest_tools import nmap_port_scan, ssl_scan, nikto_web_scan

# Port scan
ports = nmap_port_scan(target='10.0.1.5', ports='1-1000', scan_type='tcp')

# SSL/TLS audit
ssl_result = ssl_scan(target='example.com', port=443)

# Web vulnerability scan
web_result = nikto_web_scan(target_url='https://example.com', ssl=True)
```

### Target Validation

All pentest tools use `PentestValidator` to check targets against a whitelist before scanning. Configure allowed targets in the pentest config.

```python
from src.tools.pentest_tools import PentestValidator

validator = PentestValidator()
check = validator.validate_target('10.0.1.5')
# {'valid': True/False, 'reason': '...'}
```

---

## Phase 5: Audit Trail Analysis

Reviews audit logs for suspicious patterns using `services/audit_service.py`.

### Query Audit Logs

```python
from services.audit_service import audit_service

# Get logs for a user
logs = audit_service.get_user_logs(user_id=current_user.id, limit=100)

# Get all logs with filters
logs, total = audit_service.get_all_logs(
    limit=50,
    category='security',
    action='login_failed'
)

# Get statistics (last 30 days)
stats = audit_service.get_stats(days=30)
```

### Log Security Events

```python
from services.audit_service import audit_service

audit_service.log_security(
    action='suspicious_activity',
    user_id=current_user.id,
    description='Multiple failed login attempts from unusual IP',
    metadata={'ip': '203.0.113.50', 'attempts': 12}
)
```

### Export for External Review

```python
from services.compliance_service import get_compliance_service
from datetime import datetime, timedelta

service = get_compliance_service(user_id=current_user.id)
export = service.export_audit_logs(
    user_id=current_user.id,
    start_date=datetime.utcnow() - timedelta(days=30),
    end_date=datetime.utcnow(),
    format='json'
)
```

---

## Phase 6: Reporting

Aggregate findings from all phases into a prioritized report.

### Report Structure

When presenting scan results, organize by severity:

1. **Critical** — Immediate action required (public S3 buckets, open SSH to internet, leaked production credentials)
2. **High** — Fix within 24 hours (unencrypted databases, missing MFA, failed compliance controls)
3. **Medium** — Fix within 1 week (overly broad security groups, stale IAM keys, SSL issues)
4. **Low/Info** — Track and address in next sprint (informational findings, minor misconfigurations)

### Compliance Score Summary

```python
service = get_compliance_service(user_id=current_user.id)
summary = service.get_compliance_summary(user_id=current_user.id)
# Returns scores per framework: {'SOC2': 85, 'HIPAA': 72, 'PCI-DSS': 90, ...}
```

### Executive Summary

```python
exec_report = service.generate_executive_summary(user_id=current_user.id)
```

---

## Remediation Guidance

### Common Findings and Fixes

| Finding | Remediation |
|---------|-------------|
| S3 bucket public access | Enable Block Public Access at account level; review bucket policies |
| Security group 0.0.0.0/0 on SSH | Restrict to specific IP ranges or use SSM Session Manager |
| Unencrypted RDS | Enable encryption (requires snapshot + restore for existing instances) |
| IAM user without MFA | Enforce MFA via IAM policy condition `aws:MultiFactorAuthPresent` |
| Leaked AWS key in config | Rotate key immediately via IAM console; use IAM roles instead |
| SSL/TLS weak ciphers | Update server config to TLS 1.2+ only; disable CBC and RC4 |
| SQL injection found | Use parameterized queries; never concatenate user input into SQL |
| XSS vulnerability | Sanitize output with HTML encoding; use Content-Security-Policy headers |

### After Remediation

1. Re-run the relevant scan phase to verify the fix
2. Log the remediation action via `audit_service.log_security()`
3. Update compliance policies if a new control was implemented
4. Run a compliance check to see updated scores

---

## Quick Reference

```bash
# Full AWS security scan
python -c "from services.security_scanner import scan_aws_security; print(scan_aws_security(user_id=1))"

# Check for secrets in a file
python -c "from services.secret_detector import scan_for_secrets; print(scan_for_secrets(open('.env').read()))"

# Compliance summary
python -c "from services.compliance_service import get_compliance_service; s=get_compliance_service(1); print(s.get_compliance_summary(1))"

# Audit log stats
python -c "from services.audit_service import audit_service; print(audit_service.get_stats(30))"
```
