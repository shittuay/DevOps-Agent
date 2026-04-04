---
id: security-hardening
name: Security Hardening
triggers: [security, vulnerability, cis, compliance, iam, permission, public, exposure, encrypt, mfa, access key, role, policy, least privilege, overpermissive, exposed, open port, security group, 0.0.0.0]
compatible_providers: [aws, azure, gcp, kubernetes]
---
# Security Hardening Context

## IAM Least Privilege
- **AdministratorAccess**: Should only exist on break-glass accounts with MFA + CloudTrail alerts
- **Inline policies vs managed**: Prefer AWS managed policies; custom managed over inline for auditability
- **Permission boundaries**: Use on developer IAM roles to cap maximum permissions
- **Access key rotation**: Keys >90 days old should trigger an alert. Prefer IRSA/Workload Identity over keys.
- **Root account**: Should have MFA, no access keys, and never be used for daily operations

## Network Exposure
- Security group rule `0.0.0.0/0` on port 22 (SSH) or 3389 (RDP) → immediate risk
- S3 bucket with public ACL or no "Block Public Access" → data exposure risk
- RDS with `publicly_accessible=true` → should only exist for migration windows
- Kubernetes Services of type LoadBalancer with no NetworkPolicy → exposed internally and externally

## CIS Benchmark Quick Wins (AWS)
1. Enable CloudTrail in all regions with log file validation
2. Enable Config in all regions
3. Enable GuardDuty in all accounts and regions
4. MFA on all IAM users
5. Password policy: 14+ chars, no reuse last 24, max 90-day age
6. No access keys on root
7. S3 Block Public Access at account level
8. EBS default encryption enabled
9. VPC flow logs enabled

## Secrets Management
- Never store secrets in environment variables (visible in ECS task definitions, pod specs)
- Use AWS Secrets Manager or Parameter Store (SecureString) with automatic rotation
- Kubernetes Secrets are base64 not encrypted — use sealed-secrets or External Secrets Operator
- Rotate secrets immediately if exposed in logs or code

## Audit Tools
- `run_security_scan` → comprehensive infrastructure security audit
- `run_compliance_check` → CIS/SOC2/PCI compliance check
- `get_security_findings` → list open findings by severity
