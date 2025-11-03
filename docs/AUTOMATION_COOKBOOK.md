# DevOps Agent - Automation Cookbook

Real-world automation scenarios and complete workflows for common DevOps tasks.

## Table of Contents

1. [Multi-Cloud Deployment](#multi-cloud-deployment)
2. [CI/CD Pipeline Automation](#cicd-pipeline-automation)
3. [Incident Response](#incident-response)
4. [Infrastructure Audit](#infrastructure-audit)
5. [Disaster Recovery](#disaster-recovery)
6. [Application Scaling](#application-scaling)
7. [Security Compliance](#security-compliance)
8. [Cost Optimization](#cost-optimization)

---

## Multi-Cloud Deployment

### Scenario: Deploy Application Across AWS, Azure, and GCP

**Goal:** Deploy a microservices application across three cloud providers for redundancy.

**Steps:**

```
1. "List all EC2 instances in AWS region us-east-1"
2. "List all Azure VMs in resource group production"
3. "List all GCE instances in GCP project my-app zone us-central1-a"

4. "Show me EKS clusters in AWS"
5. "List GKE clusters in GCP project my-app"
6. "List Azure container instances in resource group production"

7. "Get Kubernetes pods in namespace production for all clusters"
8. "Scale deployment web-app to 5 replicas in namespace prod"

9. "Check SonarQube quality gate for project my-microservice"
10. "If quality gate passed, trigger Jenkins job deploy-production"
```

**Complete Workflow:**

```bash
# Phase 1: Pre-Deployment Checks
"Show me current resource usage across all clouds"
"List all running pods in production namespace"
"Get Datadog monitors status for production services"

# Phase 2: Code Quality
"Get SonarQube project quality for my-app"
"Show me all critical bugs and vulnerabilities"
"If quality gate is green, proceed to deployment"

# Phase 3: Build
"Trigger GitHub workflow build-and-push on branch main"
"Wait for workflow completion and show me the status"
"Pull latest Docker image for my-app:latest"

# Phase 4: Deploy to Kubernetes
"Scale deployment my-app to 0 replicas in namespace prod"
"Apply new deployment with image my-app:v2.1"
"Scale deployment my-app to 5 replicas in namespace prod"
"Wait for all pods to be ready"

# Phase 5: Verification
"Get pods status in namespace prod for deployment my-app"
"Get logs from pods with label app=my-app for last 5 minutes"
"Query Prometheus for error rate on my-app service"

# Phase 6: Post-Deployment
"Create Datadog event: Deployed my-app v2.1 to production"
"Tag deployment in Git repository"
```

---

## CI/CD Pipeline Automation

### Scenario: Complete CI/CD Pipeline with Quality Gates

**Goal:** Automated build, test, scan, and deploy pipeline with multiple quality gates.

**Pipeline:**

```
Phase 1: Code Analysis
─────────────────────
"Show Git status of repository /projects/my-app"
"Get last 5 commits from main branch"
"List open pull requests for owner/my-app repository"

Phase 2: Build & Test
─────────────────────
"Trigger Jenkins job build-my-app with parameters branch=main"
"Show Jenkins job status for build-my-app build 42"
"Get Jenkins build logs for job build-my-app build 42"

Phase 3: Code Quality
─────────────────────
"Run SonarQube analysis for project my-app"
"Get code coverage metrics for my-app"
"Show all blocker issues in SonarQube project my-app"
"Get security hotspots for project my-app"

Quality Gate Check:
- Coverage > 80%: ✓
- No blocker bugs: ✓
- No critical vulnerabilities: ✓

Phase 4: Container Build
────────────────────────
"Build Docker image my-app:v1.5 from ./Dockerfile"
"Show Docker image details for my-app:v1.5"
"Push image to registry"

Phase 5: Infrastructure Provisioning
────────────────────────────────────
"Run terraform plan in ./infrastructure/staging"
"Review the plan and if looks good:"
"Apply terraform in ./infrastructure/staging with auto-approve"
"Show terraform outputs from staging environment"

Phase 6: Deployment
───────────────────
"Get current pods in staging namespace"
"Update deployment my-app in staging with image my-app:v1.5"
"Wait for rollout to complete"
"Get new pod status"

Phase 7: Smoke Tests
───────────────────
"Get pod logs for my-app in staging namespace last 2 minutes"
"Query Prometheus for HTTP 5xx errors on my-app in staging"
"Check Datadog monitors for my-app-staging"

Phase 8: Production (if staging successful)
──────────────────────────────────────────
"Scale production deployment my-app from 10 to 15 replicas"
"Gradually roll out to production"
"Monitor error rates during rollout"
"If error rate increases, rollback deployment"
```

---

## Incident Response

### Scenario: Application Down - Emergency Response

**Goal:** Quickly diagnose and resolve production outage.

**Response Plan:**

```
Phase 1: Initial Assessment (0-2 minutes)
──────────────────────────────────────────
"Show all Datadog monitors with status alert"
"Get Prometheus alerts that are currently firing"
"List all pods in production namespace with their status"

Quick Check:
"Are there any pods in CrashLoopBackOff status?"
"Show me pods that have restarted more than 3 times"

Phase 2: Log Analysis (2-5 minutes)
───────────────────────────────────
"Get logs from all pods with label app=my-service last 10 minutes"
"Filter logs for ERROR level"
"Show me any OutOfMemory or connection refused errors"

Database Check:
"Query CloudWatch logs for RDS errors in last 15 minutes"
"Check Azure SQL database connection status"

Phase 3: Resource Check (5-8 minutes)
─────────────────────────────────────
"Show resource usage for all pods in production namespace"
"Get node status and resource availability"
"Show Docker container stats for high CPU usage"

Infrastructure:
"List EC2 instances and their health status"
"Check Azure VM status in production resource group"
"Get GCE instance status in production"

Phase 4: Network & Connectivity (8-12 minutes)
──────────────────────────────────────────────
"List Kubernetes services in production namespace"
"Show service endpoints and their availability"
"Check ingress rules and load balancer status"

Phase 5: Recent Changes (12-15 minutes)
───────────────────────────────────────
"Show last 10 deployments in production namespace"
"Get recent Git commits to main branch"
"Show Jenkins build history for production jobs"
"List recent Datadog events tagged with production"

Phase 6: Resolution Actions
────────────────────────────
Option A - Restart:
"Restart deployment my-service in production namespace"
"Wait for pods to become ready"
"Monitor error rates during restart"

Option B - Rollback:
"Show deployment history for my-service"
"Rollback deployment my-service to previous version"
"Monitor service recovery"

Option C - Scale:
"Scale deployment my-service to 20 replicas"
"Check if increased capacity resolves issues"

Phase 7: Verification (Post-Fix)
─────────────────────────────────
"Query Prometheus for service availability last 30 minutes"
"Get current error rates from Datadog"
"Check all pods are healthy and running"
"Verify all services are responding"

Phase 8: Post-Incident
──────────────────────
"Create Datadog event documenting incident resolution"
"Get complete timeline of incident from logs"
"Document root cause and resolution steps"
```

---

## Infrastructure Audit

### Scenario: Complete Cloud Infrastructure Audit

**Goal:** Generate comprehensive inventory and compliance report across all cloud providers.

**Audit Script:**

```
=== CLOUD INVENTORY AUDIT ===

AWS Resources:
──────────────
"List all EC2 instances across all regions"
"Count instances by state (running, stopped, terminated)"
"List instances without required tags"
"Show EC2 instances running for more than 90 days"

"List all S3 buckets"
"Check S3 bucket public access settings"
"Find S3 buckets without versioning enabled"

"List all RDS databases"
"Check RDS databases not using encryption"
"Show RDS instances without backup enabled"

"List all IAM users"
"Show IAM users without MFA enabled"
"List IAM users with unused access keys"

Azure Resources:
────────────────
"List all Azure virtual machines"
"Show VMs without backup configured"
"List VMs with public IP addresses"

"List all Azure storage accounts"
"Check storage accounts without encryption"
"Show storage accounts allowing public blob access"

"List all Azure SQL servers"
"Check SQL servers without firewall rules"
"Show SQL databases not using TDE"

GCP Resources:
──────────────
"List all GCE instances in all zones"
"Show instances without labels"
"List instances with external IPs"

"List all Cloud Storage buckets"
"Check buckets with public access"
"Show buckets without lifecycle policies"

"List all Cloud SQL instances"
"Check instances without backups"
"Show instances not using private IP"

Kubernetes Audit:
─────────────────
"List all pods across all namespaces"
"Show pods running as root"
"List pods without resource limits"
"Show pods with privileged security context"

"List all services of type LoadBalancer"
"Show services with external IPs"

"List all persistent volumes"
"Show PVs not encrypted"

Container Registry:
───────────────────
"List all Docker images"
"Show images older than 6 months"
"List images with known vulnerabilities"

Security Compliance:
────────────────────
"Get all SonarQube projects"
"Show projects with security rating below B"
"List all critical vulnerabilities across projects"

Cost Analysis:
──────────────
"Calculate total running instances across all clouds"
"List largest EC2 instances by type"
"Show resources tagged with cost-center"
"Identify unused resources (stopped instances, unattached volumes)"
```

---

## Disaster Recovery

### Scenario: Complete System Failure - DR Activation

**Goal:** Activate disaster recovery procedures and restore services.

**DR Playbook:**

```
Phase 1: Assess Damage
──────────────────────
"Check health of all cloud regions"
"List all services and their availability status"
"Get status of primary datacenter resources"
"Check backup systems status"

Phase 2: Activate DR Site
─────────────────────────
"List all resources in DR region (us-west-2)"
"Start all stopped instances in DR region"
"Restore latest snapshots for critical volumes"

Azure DR:
"Start all VMs in DR resource group westus-dr"
"Restore Azure SQL databases from geo-replicas"

GCP DR:
"Start all instances in DR zone us-west1-a"
"Promote read-replicas to primary"

Phase 3: Database Recovery
──────────────────────────
"Show latest RDS snapshots"
"Restore RDS from snapshot to DR region"
"Update database endpoints in application config"
"Verify database connectivity"

Phase 4: Application Deployment
────────────────────────────────
"Run terraform apply in ./infrastructure/dr"
"Deploy all services to DR Kubernetes cluster"
"Scale deployments to production capacity"

Phase 5: Traffic Failover
─────────────────────────
"Update Route53 DNS records to point to DR"
"Or: Update Azure Traffic Manager to DR endpoints"
"Or: Update GCP Cloud DNS to DR"
"Verify DNS propagation"

Phase 6: Monitoring
───────────────────
"Set up monitoring in DR region"
"Create Datadog monitors for DR services"
"Configure Prometheus to scrape DR endpoints"
"Set up log aggregation for DR"

Phase 7: Verification
─────────────────────
"Test all critical user flows"
"Verify data integrity"
"Check transaction processing"
"Monitor error rates and latency"

Phase 8: Communication
──────────────────────
"Create Datadog event: DR activated at [timestamp]"
"Document all actions taken"
"Prepare status updates for stakeholders"
```

---

## Application Scaling

### Scenario: Handle Traffic Spike

**Goal:** Automatically scale infrastructure to handle increased load.

**Scaling Strategy:**

```
Phase 1: Detect Load Increase
──────────────────────────────
"Query Prometheus for request rate increase last 15 minutes"
"Get Datadog metrics for CPU usage across services"
"Check current replica count for all deployments"

Phase 2: Quick Scale (Immediate)
─────────────────────────────────
"Scale deployment frontend from 5 to 15 replicas"
"Scale deployment api-server from 3 to 10 replicas"
"Scale deployment worker from 2 to 8 replicas"

Phase 3: Add Compute Resources
──────────────────────────────
AWS:
"Start stopped EC2 instances with tag auto-scale=true"
"Add 3 nodes to EKS cluster"

Azure:
"Start VMs in scale-set frontend-vmss"
"Increase AKS node pool from 3 to 6 nodes"

GCP:
"Add nodes to GKE cluster production"
"Start instances in managed instance group"

Phase 4: Database Scaling
─────────────────────────
"Scale up RDS instance to larger instance type"
"Add read replicas for database load distribution"
"Enable connection pooling"

Phase 5: Cache Layer
────────────────────
"Deploy additional Redis cache instances"
"Increase ElastiCache cluster size"
"Warm up cache with frequent queries"

Phase 6: Monitor Scaling
────────────────────────
"Get pod status and wait for all to be ready"
"Query Prometheus for response times"
"Check error rates during scale-up"
"Monitor queue depths and processing times"

Phase 7: Load Balancing
───────────────────────
"Verify load balancer distributing traffic evenly"
"Check connection counts per backend"
"Monitor health checks passing rate"

Phase 8: Optimize
─────────────────
"Analyze which services need more resources"
"Check for resource bottlenecks"
"Tune resource limits and requests"

Phase 9: Scale Down (After traffic normalizes)
───────────────────────────────────────────────
"Gradually scale deployments back to normal levels"
"Monitor during scale-down for any issues"
"Stop temporary compute resources"
"Document scaling thresholds for automation"
```

---

## Security Compliance

### Scenario: Security Audit and Remediation

**Goal:** Perform security scan and fix vulnerabilities.

**Security Audit:**

```
Phase 1: Code Security
──────────────────────
"Get all SonarQube projects"
"Show projects with security rating below A"
"List all security hotspots across projects"
"Show critical and high severity vulnerabilities"

"For each critical vulnerability:"
"Get vulnerability details and affected files"
"Create Jira ticket for remediation"

Phase 2: Container Security
───────────────────────────
"List all Docker images in use"
"Scan images for vulnerabilities"
"Show images with HIGH or CRITICAL CVEs"

"Pull latest secure base images"
"Rebuild containers with patched dependencies"
"Re-scan to verify fixes"

Phase 3: Infrastructure Security
─────────────────────────────────
AWS Security:
"List EC2 security groups with 0.0.0.0/0 access"
"Show S3 buckets with public read access"
"List IAM users with full admin access"
"Show resources without encryption"

Azure Security:
"List NSGs with overly permissive rules"
"Show storage accounts without firewall"
"List VMs without disk encryption"
"Show Key Vaults without access restrictions"

GCP Security:
"List firewall rules allowing 0.0.0.0/0"
"Show buckets without uniform access"
"List service accounts with owner role"
"Show instances without shielded VM"

Phase 4: Kubernetes Security
────────────────────────────
"List pods running as root user"
"Show pods without security context"
"List deployments without resource limits"
"Show services using default service account"

"Get secrets not encrypted at rest"
"List network policies - ensure egress restrictions"
"Show pod security policies compliance"

Phase 5: Access Control
───────────────────────
"List all IAM users and last access time"
"Show users without MFA enabled"
"List service accounts with unused keys"
"Show overly permissive roles"

Phase 6: Network Security
─────────────────────────
"List all publicly accessible endpoints"
"Show load balancers without SSL"
"List databases with public access"
"Show VPNs or direct connects"

Phase 7: Remediation
────────────────────
"Update security group to remove 0.0.0.0/0"
"Enable encryption on all S3 buckets"
"Rotate old access keys"
"Enable MFA for all users"

"Update Kubernetes pod security policies"
"Add resource limits to all deployments"
"Remove privileged containers"

Phase 8: Verification
─────────────────────
"Re-run security scans"
"Verify all critical issues resolved"
"Generate compliance report"
"Create Datadog event: Security audit completed"
```

---

## Cost Optimization

### Scenario: Reduce Cloud Costs

**Goal:** Identify and eliminate wasteful spending.

**Cost Optimization Plan:**

```
Phase 1: Resource Inventory
───────────────────────────
"List all EC2 instances with uptime > 30 days"
"Show stopped instances still incurring charges"
"List unattached EBS volumes"
"Show unused elastic IPs"

"List all Azure VMs and their sizes"
"Show VMs with < 20% CPU utilization last 7 days"
"List unattached managed disks"

"List all GCE instances"
"Show instances with sustained use discount eligibility"
"List committed use discounts available"

Phase 2: Right-Sizing
─────────────────────
"Analyze instance utilization last 30 days"
"Identify oversized instances"
"Get recommendations for instance type changes"

Examples:
"Show EC2 instances using <10% CPU consistently"
"Recommend smaller instance types"
"Calculate potential savings"

Phase 3: Storage Optimization
──────────────────────────────
"List S3 buckets over 1TB"
"Show objects not accessed in 90 days"
"Recommend moving to cheaper storage class"

"Create lifecycle policies for old data"
"Move infrequent access data to Glacier"
"Delete temporary files older than 30 days"

Phase 4: Database Optimization
───────────────────────────────
"List all RDS instances"
"Show databases with low connection counts"
"Check for oversized database instances"
"Recommend Reserved Instances for production DBs"

Phase 5: Kubernetes Optimization
─────────────────────────────────
"Get resource usage for all pods"
"Show pods with resource requests much higher than usage"
"Identify pods that can be consolidated"
"Check for unnecessary replica counts"

Phase 6: Reserved Instances
───────────────────────────
"List long-running instances suitable for RIs"
"Calculate savings with 1-year reserved instances"
"Purchase RIs for production workloads"

Phase 7: Spot/Preemptible Instances
───────────────────────────────────
"Identify non-critical workloads"
"Move batch jobs to spot instances"
"Configure spot instance bidding"
"Set up auto-scaling with spot instances"

Phase 8: Cleanup
────────────────
"Delete old snapshots (>90 days)"
"Remove unused load balancers"
"Delete old AMIs/images"
"Clean up old container images"

"Stop non-production resources on weekends"
"Schedule shutdowns for dev/test environments"

Phase 9: Monitoring
───────────────────
"Set up cost alerts in CloudWatch"
"Create budget alerts for overspending"
"Track cost per service/team"
"Generate monthly cost reports"

Phase 10: Report
────────────────
"Calculate total monthly costs before optimization"
"Calculate projected savings"
"Create cost optimization summary"
"Document all changes made"
```

---

## Next Steps

For more detailed information, see:
- [TOOL_REFERENCE.md](TOOL_REFERENCE.md) - Complete tool documentation
- [ADVANCED_AUTOMATION.md](ADVANCED_AUTOMATION.md) - Complex workflows
- [QUICK_START_EXAMPLES.md](QUICK_START_EXAMPLES.md) - Quick reference examples

---

**Happy Automating! 🚀**
