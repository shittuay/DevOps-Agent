# AWS Services Expansion - Complete Guide

## Overview

The DevOps Agent now supports **20+ AWS services** with comprehensive resource listing and management capabilities. This massive expansion enables you to inventory and manage your entire AWS infrastructure from a single interface.

---

## New Services Added

### Networking & Content Delivery

#### 1. **VPC (Virtual Private Cloud)**
- List all VPCs with CIDR blocks, state, and tags
- List subnets with availability zones and available IPs
- List security groups with ingress/egress rule counts

**Commands:**
```
"List all VPCs"
"Show subnets in VPC vpc-12345"
"List security groups"
```

#### 2. **CloudFront**
- List CDN distributions with domain names
- View enabled/disabled status
- See aliases and origins count

**Commands:**
```
"List CloudFront distributions"
"Show all CDN distributions"
```

#### 3. **Route 53**
- List DNS hosted zones (public and private)
- View record set counts
- See zone comments and configurations

**Commands:**
```
"List Route 53 hosted zones"
"Show all DNS zones"
```

#### 4. **API Gateway**
- List REST APIs (API Gateway V1)
- List HTTP/WebSocket APIs (API Gateway V2)
- View endpoint configurations

**Commands:**
```
"List API Gateways"
"Show all API Gateway APIs"
"List API Gateway V2 APIs"
```

---

### Compute & Containers

#### 5. **ECS (Elastic Container Service)**
- List ECS clusters with task/service counts
- List services within clusters
- View running, pending, and registered instances

**Commands:**
```
"List ECS clusters"
"Show ECS services in cluster my-cluster"
"List container services"
```

#### 6. **Elastic Beanstalk**
- List applications with version counts
- List environments with health status
- View platform details and URLs

**Commands:**
```
"List Elastic Beanstalk applications"
"Show Beanstalk environments"
"List all EB environments"
```

#### 7. **Lambda Functions** (Enhanced)
- Now includes runtime, handler, memory, timeout
- Code size and last modified date
- Function descriptions

**Commands:**
```
"List all Lambda functions"
"Show Lambda functions with runtime info"
```

---

### Databases & Storage

#### 8. **DynamoDB**
- List all tables with item counts
- View table size in bytes
- See billing mode (provisioned/on-demand)
- Key schema information

**Commands:**
```
"List DynamoDB tables"
"Show all DynamoDB tables"
"List NoSQL databases"
```

#### 9. **RDS (Relational Database Service)** (Enhanced)
- List database instances with complete details
- Engine type, version, endpoint, port
- Multi-AZ status, storage info
- Public accessibility status

**Commands:**
```
"List RDS instances"
"Show all databases"
"List RDS with endpoints"
```

#### 10. **ElastiCache**
- List Redis and Memcached clusters
- View engine version and node type
- Number of nodes and status

**Commands:**
```
"List ElastiCache clusters"
"Show Redis clusters"
"List cache clusters"
```

---

## Comprehensive Resource Inventory

### **NEW: One-Command Full AWS Audit**

The most powerful new feature is the comprehensive resource inventory tool that scans **ALL** AWS services in a single command.

**Command:**
```
"List all my AWS resources"
"Scan my entire AWS environment"
"Audit my AWS infrastructure"
"Show me everything in my AWS account"
```

**What It Does:**
1. Scans 14 AWS services simultaneously
2. Returns organized inventory by service category
3. Counts total resources across all services
4. Provides detailed information for each resource

**Services Scanned:**
- EC2 instances
- S3 buckets
- RDS databases
- DynamoDB tables
- Lambda functions
- EKS clusters
- ECS clusters
- ElastiCache clusters
- Elastic Beanstalk environments
- VPCs, subnets, security groups
- CloudFront distributions
- Route 53 hosted zones
- API Gateways
- IAM users and roles

**Sample Output:**
```json
{
  "success": true,
  "region": "us-east-1",
  "total_resources": 47,
  "scan_time": "2025-11-22T12:00:00",
  "services": {
    "ec2": {
      "count": 5,
      "instances": [...]
    },
    "s3": {
      "count": 12,
      "buckets": [...]
    },
    "rds": {
      "count": 3,
      "instances": [...]
    },
    "dynamodb": {
      "count": 8,
      "tables": [...]
    },
    ...
  }
}
```

---

## Complete Service Summary

| Service | List Command | Details |
|---------|-------------|---------|
| **EC2** | `get_ec2_instances` | Instances with full details (7 sections) |
| **S3** | `list_s3_buckets` | Buckets with creation dates |
| **RDS** | `list_rds_instances` | Databases with endpoints |
| **DynamoDB** | `list_dynamodb_tables` | Tables with item counts |
| **Lambda** | `list_lambda_functions` | Functions with runtime info |
| **EKS** | `get_eks_clusters` | Kubernetes clusters |
| **ECS** | `list_ecs_clusters` | Container clusters |
| **ElastiCache** | `list_elasticache_clusters` | Cache clusters |
| **Beanstalk** | `list_beanstalk_environments` | PaaS environments |
| **VPC** | `list_vpcs` | Virtual networks |
| **Subnets** | `list_subnets` | Network subnets |
| **Security Groups** | `list_security_groups` | Firewall rules |
| **CloudFront** | `list_cloudfront_distributions` | CDN distributions |
| **Route 53** | `list_route53_zones` | DNS zones |
| **API Gateway** | `list_api_gateways` | REST APIs |
| **API Gateway V2** | `list_api_gateway_v2` | HTTP/WebSocket APIs |
| **IAM Users** | `list_iam_users` | User accounts |
| **IAM Roles** | `list_iam_roles` | Service roles |
| **CloudWatch** | `get_cloudwatch_logs` | Log streams |

---

## Usage Examples

### Network Infrastructure Audit
```
User: "Show me all my VPCs and subnets"

Agent: I'll list your VPCs and subnets.

VPCs (3):
1. vpc-abc123 (10.0.0.0/16) - Production VPC
   State: available
   Default: No

2. vpc-def456 (172.16.0.0/16) - Development VPC
   State: available
   Default: No

3. vpc-ghi789 (192.168.0.0/16) - Default VPC
   State: available
   Default: Yes

Subnets (8):
1. subnet-111 in vpc-abc123
   CIDR: 10.0.1.0/24
   AZ: us-east-1a
   Available IPs: 251

2. subnet-222 in vpc-abc123
   CIDR: 10.0.2.0/24
   AZ: us-east-1b
   Available IPs: 248

...
```

### Container Services Overview
```
User: "List all my container services"

Agent: I'll list ECS and EKS resources.

ECS Clusters (2):
1. production-cluster
   Running tasks: 15
   Pending tasks: 2
   Active services: 8
   Registered instances: 5

2. staging-cluster
   Running tasks: 6
   Pending tasks: 0
   Active services: 3
   Registered instances: 2

EKS Clusters (1):
1. kubernetes-prod
   Version: 1.28
   Status: ACTIVE
   Endpoint: https://...
```

### Database Inventory
```
User: "Show me all my databases"

Agent: I'll list RDS and DynamoDB resources.

RDS Instances (3):
1. prod-postgres
   Engine: postgres 15.4
   Class: db.r5.large
   Status: available
   Endpoint: prod-postgres.abc.us-east-1.rds.amazonaws.com:5432
   Multi-AZ: Yes
   Storage: 100 GB

2. staging-mysql
   Engine: mysql 8.0
   Class: db.t3.medium
   Status: available
   Endpoint: staging-mysql.xyz.us-east-1.rds.amazonaws.com:3306
   Multi-AZ: No
   Storage: 50 GB

DynamoDB Tables (8):
1. Users
   Status: ACTIVE
   Items: 1,245,892
   Size: 3.2 GB
   Billing: ON_DEMAND

2. Orders
   Status: ACTIVE
   Items: 458,234
   Size: 1.8 GB
   Billing: PROVISIONED

...
```

### CDN and DNS Configuration
```
User: "List CloudFront and Route 53 resources"

Agent: I'll show CDN distributions and DNS zones.

CloudFront Distributions (3):
1. E2ABCDEFG123
   Domain: d111111abcdef8.cloudfront.net
   Aliases: www.example.com, example.com
   Status: Deployed
   Enabled: Yes
   Origins: 2

Route 53 Hosted Zones (4):
1. example.com
   Type: Public
   Records: 25
   Zone ID: Z1234567890ABC

2. internal.corp
   Type: Private
   Records: 12
   Zone ID: Z0987654321XYZ

...
```

### Complete Infrastructure Audit
```
User: "Scan my entire AWS environment"

Agent: I'll perform a comprehensive scan of all AWS services.

[Scanning...]

AWS Resource Inventory
Region: us-east-1
Scan Time: 2025-11-22 12:00:00 UTC

Total Resources: 127

Service Breakdown:
├─ EC2: 12 instances
│  └─ Running: 8, Stopped: 4
├─ S3: 24 buckets
│  └─ Total: 24
├─ RDS: 6 databases
│  └─ Available: 5, Backing up: 1
├─ DynamoDB: 18 tables
│  └─ Active: 18
├─ Lambda: 35 functions
│  └─ Python: 20, Node.js: 12, Java: 3
├─ EKS: 2 clusters
│  └─ Active: 2
├─ ECS: 4 clusters
│  └─ Running tasks: 32
├─ ElastiCache: 3 clusters
│  └─ Redis: 2, Memcached: 1
├─ Beanstalk: 5 environments
│  └─ Healthy: 4, Warning: 1
├─ VPC: 5 VPCs
│  └─ With 15 subnets, 23 security groups
├─ CloudFront: 4 distributions
│  └─ Enabled: 4
├─ Route 53: 6 hosted zones
│  └─ Public: 4, Private: 2
├─ API Gateway: 8 APIs
│  └─ REST: 5, HTTP: 2, WebSocket: 1
└─ IAM: 42 users, 85 roles
```

---

## Advanced Filtering

### By Region
```
"List EC2 instances in us-west-2"
"Show RDS databases in eu-west-1"
"List DynamoDB tables in ap-southeast-1"
```

### By VPC
```
"List subnets in VPC vpc-12345"
"Show security groups in VPC vpc-67890"
```

### By Cluster
```
"List ECS services in cluster production"
"Show tasks in ECS cluster staging"
```

### By Application
```
"List Beanstalk environments for app MyApp"
```

### Selective Service Scan
```
"Scan only EC2, S3, and RDS resources"
"List resources for compute services only"
```

**Tool Call:**
```python
get_aws_resource_inventory(
    services=['ec2', 's3', 'rds'],
    region='us-east-1'
)
```

---

## Performance Considerations

### Scan Times

| Scope | Estimated Time | Services Scanned |
|-------|---------------|------------------|
| Single service | 2-5 seconds | 1 service |
| Compute only | 10-15 seconds | EC2, Lambda, ECS, EKS, Beanstalk |
| Networking only | 8-12 seconds | VPC, CloudFront, Route 53, API Gateway |
| Databases only | 10-15 seconds | RDS, DynamoDB, ElastiCache |
| Full scan (all) | 30-60 seconds | All 14 services |

### Optimization Tips

1. **Specify Region**: Scanning a specific region is faster than default
   ```
   "List all resources in us-east-1"
   ```

2. **Selective Services**: Only scan what you need
   ```
   "List EC2, RDS, and S3 resources"
   ```

3. **Filter Results**: Use filters to reduce data
   ```
   "Show only running EC2 instances"
   ```

4. **VPC Filtering**: Narrow down networking scans
   ```
   "List resources in VPC vpc-12345"
   ```

---

## Common Use Cases

### 1. Infrastructure Audit
**Scenario**: Monthly review of all resources
```
"Scan my entire AWS environment"
```

### 2. Cost Analysis Preparation
**Scenario**: Identify all billable resources
```
"List all EC2 instances, RDS databases, and S3 buckets"
```

### 3. Security Review
**Scenario**: Check security groups and IAM
```
"List all security groups and IAM users"
```

### 4. Application Inventory
**Scenario**: Document application components
```
"List all resources for application MyApp"
"Show ECS services, RDS databases, and S3 buckets"
```

### 5. Network Topology
**Scenario**: Map network infrastructure
```
"List VPCs, subnets, and security groups"
"Show CloudFront distributions and Route 53 zones"
```

### 6. Serverless Stack
**Scenario**: Review serverless architecture
```
"List Lambda functions, API Gateways, and DynamoDB tables"
```

### 7. Container Platform
**Scenario**: Review container infrastructure
```
"List ECS clusters, EKS clusters, and ECR repositories"
"Show all ECS services and tasks"
```

### 8. Multi-Region Audit
**Scenario**: Check resources across regions
```
"List EC2 instances in us-east-1"
[Review results]
"List EC2 instances in us-west-2"
[Review results]
"List EC2 instances in eu-west-1"
```

---

## Integration with Existing Features

### Works with Pentest Tools
```
"Run AWS security audit"
[Scans for security issues in S3, security groups, IAM, etc.]

"List all resources then audit security"
[First gets inventory, then runs security checks]
```

### Works with Resource Management
```
"List all EC2 instances"
[Reviews instances]
"Stop instance i-12345"
"Terminate instance i-67890"
```

### Works with CloudWatch
```
"List Lambda functions"
[Reviews functions]
"Get logs for Lambda function my-function"
```

---

## Configuration

### Enable All AWS Services

In `config/config.yaml`:
```yaml
aws:
  enabled: true
  default_region: "us-east-1"
  profile: "default"

  # Service-specific settings
  scan_timeout_seconds: 300  # 5 minutes for full scans
  max_results_per_service: 1000

  # Services to enable
  services:
    ec2: true
    s3: true
    rds: true
    dynamodb: true
    lambda: true
    eks: true
    ecs: true
    elasticache: true
    beanstalk: true
    vpc: true
    cloudfront: true
    route53: true
    apigateway: true
    iam: true
```

### AWS Credentials

The agent uses standard AWS credentials:

1. **Environment variables**:
   ```bash
   export AWS_ACCESS_KEY_ID=your_key
   export AWS_SECRET_ACCESS_KEY=your_secret
   export AWS_DEFAULT_REGION=us-east-1
   ```

2. **AWS CLI configuration**:
   ```bash
   aws configure
   ```

3. **IAM role** (when running on EC2):
   Automatically detected

### Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "s3:List*",
        "s3:Get*",
        "rds:Describe*",
        "dynamodb:List*",
        "dynamodb:Describe*",
        "lambda:List*",
        "lambda:Get*",
        "eks:Describe*",
        "eks:List*",
        "ecs:Describe*",
        "ecs:List*",
        "elasticache:Describe*",
        "elasticbeanstalk:Describe*",
        "cloudfront:List*",
        "cloudfront:Get*",
        "route53:List*",
        "route53:Get*",
        "apigateway:GET",
        "iam:List*",
        "iam:Get*",
        "logs:Describe*",
        "logs:Get*",
        "logs:Filter*"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Troubleshooting

### "Access Denied" Error
**Problem**: Missing IAM permissions
**Solution**: Add required permissions from IAM policy above

### "Region not found" Error
**Problem**: Invalid region specified
**Solution**: Use valid AWS region (e.g., us-east-1, eu-west-1)

### Timeout on Full Scan
**Problem**: Too many resources to scan in time limit
**Solution**:
- Scan specific services only
- Increase timeout in config
- Scan by region

### Empty Results
**Problem**: No resources found
**Solution**:
- Check you're scanning the correct region
- Verify AWS credentials are correct
- Ensure resources exist in your account

### Rate Limiting
**Problem**: AWS API throttling
**Solution**:
- Wait a moment and retry
- Scan fewer services at once
- Request AWS API limit increase

---

## Summary

### What's New
✅ **14 AWS services** added (VPC, DynamoDB, ECS, ElastiCache, Beanstalk, CloudFront, Route 53, API Gateway, enhanced Lambda/RDS)

✅ **Comprehensive inventory tool** for one-command full AWS audit

✅ **20+ total AWS services** now supported

✅ **Detailed resource information** matching AWS Console output

✅ **Advanced filtering** by region, VPC, cluster, etc.

✅ **Performance optimizations** for fast scanning

### Quick Start
1. Configure AWS credentials (`aws configure`)
2. Enable AWS tools in config
3. Ask: `"List all my AWS resources"`
4. Review comprehensive inventory
5. Use service-specific commands for details

### Most Useful Commands
- `"List all my AWS resources"` - Full audit
- `"List EC2 instances"` - Compute resources
- `"Show all databases"` - RDS + DynamoDB
- `"List VPCs and subnets"` - Network topology
- `"Show Lambda functions"` - Serverless inventory
- `"List container services"` - ECS + EKS

### Support
- Check logs: `tail -f logs/agent.log`
- View AWS status: `aws sts get-caller-identity`
- Test connection: `aws ec2 describe-instances --max-items 1`

---

**Your DevOps Agent can now manage your entire AWS infrastructure!** 🚀
