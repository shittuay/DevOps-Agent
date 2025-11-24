# AWS Resource Listing Guide

## Issue: Database Locked Error

You received this error:
```
Error: (sqlite3.OperationalError) database is locked
```

This happens when multiple requests try to write to the SQLite database simultaneously.

---

## ✅ Fix #1: Apply Database Optimizations

### Option A: Automatic Fix (Run Script)

```bash
cd devops-agent
python fix_database.py
```

This script will:
- Enable WAL (Write-Ahead Logging) mode for better concurrency
- Set busy timeout to 30 seconds
- Optimize synchronous mode

### Option B: Restart Application (Already Fixed)

The application code has been updated with:
- SQLite WAL mode enabled automatically
- 30-second timeout for database locks
- Proper session cleanup and error handling
- Connection pooling

**Just restart your Flask application:**

```bash
# Stop current application (Ctrl+C)
# Then restart:
python app.py
# or
gunicorn app:app
```

The fixes will apply automatically on next startup.

---

## ✅ Fix #2: Use PostgreSQL (Recommended for Production)

If you continue having issues, migrate to PostgreSQL:

### Install PostgreSQL

```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql
brew services start postgresql

# Windows
# Download from: https://www.postgresql.org/download/windows/
```

### Create Database

```bash
sudo -u postgres psql
CREATE DATABASE devops_agent;
CREATE USER devops_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE devops_agent TO devops_user;
\q
```

### Configure Application

Set environment variable:

```bash
export DATABASE_URL="postgresql://devops_user:your_secure_password@localhost/devops_agent"
```

Or add to `.env`:
```
DATABASE_URL=postgresql://devops_user:your_secure_password@localhost/devops_agent
```

Restart the application - it will automatically use PostgreSQL.

---

## AWS Resource Listing

### Prerequisites

1. **Configure AWS Credentials**

```bash
# Option 1: AWS CLI
aws configure
# Enter your AWS Access Key ID and Secret Access Key

# Option 2: Environment variables in .env
echo "AWS_ACCESS_KEY_ID=your_access_key" >> config/.env
echo "AWS_SECRET_ACCESS_KEY=your_secret_key" >> config/.env
echo "AWS_DEFAULT_REGION=us-east-1" >> config/.env
```

2. **Enable AWS Tools**

Edit `config/config.yaml`:
```yaml
aws:
  default_region: "us-east-1"
  profile: "default"
  enabled: true
```

3. **Verify Credentials**

```bash
# Test AWS connection
aws sts get-caller-identity
```

---

## List AWS Resources

### Using CLI

```bash
python main.py ask "List all my EC2 instances"
```

### Using Web Interface

Navigate to: `http://localhost:5000`

In the chat:
```
List all my AWS resources
```

---

## Available AWS Commands

### EC2 Instances

```
"List all EC2 instances"
"Show running EC2 instances"
"List EC2 instances in us-west-2"
"Show EC2 instances tagged Environment=production"
```

### S3 Buckets

```
"List all S3 buckets"
"Show S3 bucket contents for bucket-name"
"Get S3 bucket info"
```

### RDS Databases

```
"List all RDS instances"
"Show RDS database status"
```

### EKS Clusters

```
"List EKS clusters"
"Show EKS cluster details for my-cluster"
```

### Lambda Functions

```
"List all Lambda functions"
"Show Lambda function details"
```

### CloudWatch Logs

```
"Get CloudWatch logs for log-group-name"
"Show recent CloudWatch logs"
```

### Comprehensive Resource Listing

```
"List all my AWS resources across all services"
"Show me an overview of my AWS infrastructure"
"Audit my AWS environment"
```

---

## Example Conversation

```
User: List all my EC2 instances

Agent: I'll fetch your EC2 instances across all regions.

[Retrieves instances...]

Found 5 EC2 instances:

Region: us-east-1 (3 instances)
1. web-server-1 (i-0abc123def456)
   Type: t3.medium
   State: running
   IP: 54.123.45.67
   Tags: Environment=production, Role=webserver

2. api-server-1 (i-0def456abc789)
   Type: t3.small
   State: running
   IP: 54.123.45.68
   Tags: Environment=production, Role=api

3. test-instance (i-0ghi789jkl012)
   Type: t2.micro
   State: stopped
   Tags: Environment=dev

Region: us-west-2 (2 instances)
1. backup-server (i-0mno345pqr678)
   Type: t3.small
   State: running
   IP: 52.123.45.69
   Tags: Environment=production, Role=backup

2. staging-web (i-0stu901vwx234)
   Type: t2.small
   State: running
   IP: 52.123.45.70
   Tags: Environment=staging
```

---

## Filtering Resources

### By State

```
"Show only running EC2 instances"
"List stopped EC2 instances"
```

### By Tags

```
"List EC2 instances tagged Environment=production"
"Show instances with tag Role=webserver"
```

### By Region

```
"List EC2 instances in us-west-2"
"Show resources in eu-west-1"
```

---

## Security Audit

You can also use the pentest tools to audit AWS security:

```
"Run AWS security audit"
"Audit AWS security posture"
"Check my AWS environment for security issues"
```

This will check for:
- S3 buckets with public access
- Unencrypted S3 buckets
- Security groups allowing 0.0.0.0/0
- IAM users with old access keys
- Missing encryption
- Compliance issues

Enable pentest first:
```yaml
# config/config.yaml
pentest:
  enabled: true
  cloud_audit:
    aws:
      enabled: true
```

---

## Available AWS Tools

The following AWS tools are available:

### EC2 Management
- `get_ec2_instances` - List EC2 instances
- `create_ec2_instance` - Create new EC2 instance
- `manage_ec2_instance` - Start/stop/reboot instance
- `delete_ec2_instance` - Terminate instance

### S3 Storage
- `list_s3_buckets` - List all S3 buckets
- `get_s3_bucket_info` - Get bucket details
- `manage_s3_object` - Upload/download files
- `create_s3_bucket` - Create new bucket
- `delete_s3_bucket` - Delete bucket

### RDS Databases
- `get_rds_instances` - List RDS instances
- `create_rds_instance` - Create new RDS instance
- `manage_rds_instance` - Start/stop/modify
- `delete_rds_instance` - Delete database

### EKS Clusters
- `get_eks_clusters` - List EKS clusters
- `get_eks_cluster_info` - Get cluster details
- `update_eks_kubeconfig` - Update kubectl config

### Lambda Functions
- `list_lambda_functions` - List all Lambda functions
- `invoke_lambda_function` - Invoke a function
- `get_lambda_logs` - Get function logs

### CloudWatch
- `get_cloudwatch_logs` - Get log streams
- `get_cloudwatch_metrics` - Get metrics

### Security Auditing
- `aws_security_audit` - Comprehensive security audit

---

## Troubleshooting

### "AWS credentials not found"

**Fix:**
```bash
# Set credentials in .env file
echo "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE" >> config/.env
echo "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" >> config/.env
```

Or use AWS CLI:
```bash
aws configure
```

### "Access Denied" errors

**Fix:** Ensure your AWS user/role has appropriate IAM permissions:

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
        "eks:Describe*",
        "eks:List*",
        "lambda:List*",
        "lambda:Get*",
        "logs:Describe*",
        "logs:Get*",
        "iam:List*",
        "iam:Get*"
      ],
      "Resource": "*"
    }
  ]
}
```

### "Database is locked" error

**Fix:** Run the database fix script:
```bash
python fix_database.py
```

Then restart the application.

### Timeout when listing resources

**Fix:**
1. Limit to specific region:
   ```
   "List EC2 instances in us-east-1 only"
   ```

2. Filter by state:
   ```
   "Show only running EC2 instances"
   ```

3. Increase timeout in config:
   ```yaml
   safety:
     command_timeout_seconds: 1800  # 30 minutes
   ```

---

## Performance Tips

1. **Specify regions** instead of scanning all regions:
   ```
   "List EC2 instances in us-east-1"
   ```

2. **Filter results** to reduce data:
   ```
   "Show only running instances"
   ```

3. **Use specific commands** instead of "all resources":
   ```
   "List EC2 instances"  # Fast
   vs
   "List all AWS resources"  # Slower
   ```

4. **Cache results** by asking follow-up questions:
   ```
   "List EC2 instances"
   [Results returned]
   "Show me only the production instances from that list"
   ```

---

## Quick Start Checklist

- [ ] Fix database lock (run `python fix_database.py`)
- [ ] Configure AWS credentials (`aws configure`)
- [ ] Enable AWS tools in `config/config.yaml`
- [ ] Restart application
- [ ] Test with: `python main.py ask "List all EC2 instances"`

---

## Summary

**Database Issue Fixed:**
- SQLite optimizations applied automatically
- WAL mode enabled
- 30-second timeout set
- Proper error handling added

**AWS Resource Listing:**
- Use natural language: `"List all my EC2 instances"`
- Filter by region, state, or tags
- Security audit available via pentest tools
- Multiple AWS services supported (EC2, S3, RDS, EKS, Lambda, etc.)

**Need Help?**
- Check logs: `tail -f logs/agent.log`
- View database status: `python fix_database.py`
- Test AWS: `aws sts get-caller-identity`

---

Good luck! 🚀
