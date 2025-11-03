# DevOps Agent - CREATE Operations Guide

This guide documents all the CREATE operations added to the DevOps Agent, enabling you to provision and create cloud resources across AWS, Azure, and Google Cloud Platform using natural language.

## Overview

The agent now supports comprehensive CREATE operations for:
- **AWS**: EC2 instances, S3 buckets, RDS databases, Lambda functions, Security Groups
- **Azure**: Resource Groups, Virtual Machines, Storage Accounts, SQL Servers, SQL Databases
- **Google Cloud**: Compute instances, Storage buckets, Cloud SQL instances

---

## AWS CREATE Operations

### 1. Create EC2 Instance

Create a new Amazon EC2 virtual machine instance.

**Natural Language Examples:**
```
"Create an EC2 instance with AMI ami-0c55b159cbfafe1f0 of type t2.micro"
"Launch a t3.small EC2 instance using ami-abc123 with key pair my-key in us-east-1"
"Create an EC2 instance named web-server with t2.medium type"
```

**Parameters:**
- `ami_id` (required): AMI ID to use (e.g., ami-0c55b159cbfafe1f0)
- `instance_type` (required): Instance type (e.g., t2.micro, t3.small, m5.large)
- `key_name` (optional): SSH key pair name
- `security_group_ids` (optional): List of security group IDs
- `subnet_id` (optional): Subnet ID for VPC placement
- `tags` (optional): Tags as key-value pairs
- `user_data` (optional): User data script for initialization
- `region` (optional): AWS region

**Response:**
```json
{
  "success": true,
  "instance_id": "i-0abc123def456",
  "instance_type": "t2.micro",
  "ami_id": "ami-0c55b159cbfafe1f0",
  "state": "pending",
  "private_ip": "10.0.1.50",
  "message": "Successfully created EC2 instance i-0abc123def456",
  "region": "us-east-1"
}
```

---

### 2. Create S3 Bucket

Create a new Amazon S3 storage bucket with security best practices.

**Natural Language Examples:**
```
"Create an S3 bucket named my-app-data"
"Create an S3 bucket my-backups with versioning enabled in us-west-2"
"Create a secure S3 bucket my-files with encryption and public access blocked"
```

**Parameters:**
- `bucket_name` (required): Bucket name (must be globally unique)
- `region` (optional): AWS region
- `versioning_enabled` (optional): Enable versioning (default: false)
- `encryption_enabled` (optional): Enable server-side encryption (default: true)
- `public_access_block` (optional): Block public access (default: true, recommended)

**Response:**
```json
{
  "success": true,
  "bucket_name": "my-app-data",
  "region": "us-east-1",
  "versioning_enabled": false,
  "encryption_enabled": true,
  "public_access_blocked": true,
  "message": "Successfully created S3 bucket my-app-data"
}
```

**Security Notes:**
- Encryption is enabled by default (AES256)
- Public access is blocked by default (best practice)
- Versioning can be enabled for data protection

---

### 3. Create RDS Database Instance

Create a new Amazon RDS managed database instance.

**Natural Language Examples:**
```
"Create a MySQL RDS instance named mydb with class db.t3.micro"
"Create a PostgreSQL RDS database prod-db with db.r5.large instance class"
"Create an RDS instance named app-db using MySQL 8.0 with 100GB storage"
```

**Parameters:**
- `db_instance_identifier` (required): Unique identifier for the database
- `db_instance_class` (required): Instance class (e.g., db.t3.micro, db.r5.large)
- `engine` (required): Database engine (mysql, postgres, mariadb, oracle-ee, sqlserver-ex)
- `master_username` (required): Master username
- `master_password` (required): Master password (must meet complexity requirements)
- `allocated_storage` (optional): Storage size in GB (default: 20)
- `db_name` (optional): Initial database name
- `engine_version` (optional): Specific engine version
- `multi_az` (optional): Enable Multi-AZ for high availability (default: false)
- `publicly_accessible` (optional): Make publicly accessible (default: false)
- `backup_retention_period` (optional): Days to retain backups 0-35 (default: 7)
- `region` (optional): AWS region

**Response:**
```json
{
  "success": true,
  "db_instance_identifier": "mydb",
  "engine": "mysql",
  "status": "creating",
  "message": "Successfully initiated creation of RDS instance mydb"
}
```

**Security Notes:**
- Storage is always encrypted
- Backups are enabled by default (7-day retention)
- Not publicly accessible by default
- Multi-AZ can be enabled for production workloads

---

### 4. Create Security Group

Create a new EC2 security group with custom firewall rules.

**Natural Language Examples:**
```
"Create a security group named web-sg for HTTP traffic"
"Create security group app-sg with SSH and HTTP access"
"Create security group db-sg allowing MySQL from 10.0.0.0/16"
```

**Parameters:**
- `group_name` (required): Security group name
- `description` (required): Description of the security group
- `vpc_id` (optional): VPC ID (uses default VPC if not specified)
- `ingress_rules` (optional): List of ingress rules with protocol, port, and CIDR
- `region` (optional): AWS region

**Ingress Rule Format:**
```json
{
  "protocol": "tcp",
  "port": 80,
  "cidr": "0.0.0.0/0"
}
```

**Response:**
```json
{
  "success": true,
  "group_id": "sg-0abc123",
  "group_name": "web-sg",
  "vpc_id": "vpc-abc123",
  "rules_added": 2,
  "message": "Successfully created security group web-sg with 2 ingress rules"
}
```

---

### 5. Create Lambda Function

Create a new AWS Lambda serverless function.

**Natural Language Examples:**
```
"Create a Lambda function named my-function using Python 3.9"
"Create a Lambda function process-data with Node.js 18.x runtime"
"Create Lambda function api-handler with 512MB memory and 30s timeout"
```

**Parameters:**
- `function_name` (required): Lambda function name
- `runtime` (required): Runtime (python3.9, python3.11, nodejs18.x, nodejs20.x, java17, dotnet6, go1.x, ruby3.2)
- `role_arn` (required): ARN of IAM role for Lambda execution
- `handler` (required): Function handler (e.g., index.handler, lambda_function.lambda_handler)
- `zip_file_path` (required): Path to ZIP file containing function code
- `description` (optional): Function description
- `timeout` (optional): Timeout in seconds 1-900 (default: 3)
- `memory_size` (optional): Memory in MB 128-10240 (default: 128)
- `environment_variables` (optional): Environment variables as key-value pairs
- `region` (optional): AWS region

**Response:**
```json
{
  "success": true,
  "function_name": "my-function",
  "function_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-function",
  "runtime": "python3.9",
  "handler": "lambda_function.lambda_handler",
  "memory_size": 128,
  "timeout": 3,
  "message": "Successfully created Lambda function my-function"
}
```

---

### 6. Delete Operations (AWS)

**Delete EC2 Instance:**
```
"Delete EC2 instance i-0abc123"
"Terminate instance i-0abc123"
```

**Delete S3 Bucket:**
```
"Delete S3 bucket my-old-data"
"Delete S3 bucket my-temp with force to remove all objects"
```

Parameters:
- `force`: If true, deletes all objects and versions first (default: false)

---

## Azure CREATE Operations

### 1. Create Resource Group

Create a new Azure Resource Group to organize resources.

**Natural Language Examples:**
```
"Create an Azure resource group named production-rg in East US"
"Create resource group dev-rg in West Europe"
"Create Azure resource group test-rg in Southeast Asia with tags"
```

**Parameters:**
- `resource_group_name` (required): Resource group name
- `location` (required): Azure region (eastus, westus2, westeurope, southeastasia, etc.)
- `tags` (optional): Tags as key-value pairs

**Response:**
```json
{
  "success": true,
  "resource_group_name": "production-rg",
  "location": "eastus",
  "provisioning_state": "Succeeded",
  "message": "Successfully created resource group production-rg"
}
```

---

### 2. Create Virtual Machine

Create a new Azure Virtual Machine with complete networking setup.

**Natural Language Examples:**
```
"Create an Azure VM named web-vm in East US with Standard_B1s size"
"Create a VM app-server in resource group prod-rg with Ubuntu 18.04"
"Create Azure virtual machine db-server with Standard_D2s_v3 in West Europe"
```

**Parameters:**
- `resource_group` (required): Resource group name (must exist)
- `vm_name` (required): Virtual machine name
- `location` (required): Azure region
- `vm_size` (required): VM size (Standard_B1s, Standard_D2s_v3, Standard_E2s_v3, etc.)
- `admin_username` (required): Administrator username
- `admin_password` (required): Administrator password (12-72 characters)
- `image_publisher` (optional): Image publisher (default: Canonical for Ubuntu)
- `image_offer` (optional): Image offer (default: UbuntuServer)
- `image_sku` (optional): Image SKU (default: 18.04-LTS)
- `os_disk_size_gb` (optional): OS disk size in GB (default: 30)
- `tags` (optional): Tags

**What Gets Created:**
- Virtual Network (VNet)
- Subnet
- Public IP Address
- Network Interface (NIC)
- Virtual Machine

**Response:**
```json
{
  "success": true,
  "vm_name": "web-vm",
  "location": "eastus",
  "vm_size": "Standard_B1s",
  "provisioning_state": "Succeeded",
  "message": "Successfully created VM web-vm. This process may take several minutes to complete."
}
```

---

### 3. Create Storage Account

Create a new Azure Storage Account.

**Natural Language Examples:**
```
"Create Azure storage account mystorageacct in East US"
"Create storage account proddata in resource group prod-rg with Standard_GRS"
"Create Azure storage account backups with Premium_LRS in West US"
```

**Parameters:**
- `resource_group` (required): Resource group name
- `storage_account_name` (required): Storage account name (3-24 lowercase alphanumeric, globally unique)
- `location` (required): Azure region
- `sku_name` (optional): SKU (Standard_LRS, Standard_GRS, Standard_RAGRS, Premium_LRS) (default: Standard_LRS)
- `kind` (optional): Account kind (StorageV2, Storage, BlobStorage) (default: StorageV2)
- `tags` (optional): Tags

**Response:**
```json
{
  "success": true,
  "storage_account_name": "mystorageacct",
  "location": "eastus",
  "sku": "Standard_LRS",
  "kind": "StorageV2",
  "provisioning_state": "Succeeded",
  "primary_endpoints": {
    "blob": "https://mystorageacct.blob.core.windows.net/",
    "file": "https://mystorageacct.file.core.windows.net/",
    "queue": "https://mystorageacct.queue.core.windows.net/",
    "table": "https://mystorageacct.table.core.windows.net/"
  },
  "message": "Successfully created storage account mystorageacct"
}
```

---

### 4. Create SQL Server

Create a new Azure SQL Server.

**Natural Language Examples:**
```
"Create Azure SQL Server myserver in East US"
"Create SQL server prod-sql in resource group prod-rg"
"Create Azure SQL Server dev-sql with admin user sqladmin"
```

**Parameters:**
- `resource_group` (required): Resource group name
- `server_name` (required): SQL server name (must be globally unique)
- `location` (required): Azure region
- `admin_username` (required): Administrator username
- `admin_password` (required): Administrator password (8+ chars, uppercase, lowercase, digit, special char)
- `version` (optional): SQL Server version (default: 12.0)
- `tags` (optional): Tags

**Response:**
```json
{
  "success": true,
  "server_name": "myserver",
  "location": "eastus",
  "version": "12.0",
  "fully_qualified_domain_name": "myserver.database.windows.net",
  "state": "Ready",
  "message": "Successfully created SQL Server myserver"
}
```

---

### 5. Create SQL Database

Create a new Azure SQL Database on an existing SQL Server.

**Natural Language Examples:**
```
"Create Azure SQL database appdb on server myserver"
"Create SQL database proddb on server prod-sql with Standard S1 tier"
"Create database testdb on server dev-sql with 5GB size"
```

**Parameters:**
- `resource_group` (required): Resource group name
- `server_name` (required): SQL server name (must exist)
- `database_name` (required): Database name
- `location` (required): Azure region (must match server location)
- `sku_name` (optional): SKU name (Basic, S0, S1, S2, P1, P2, etc.) (default: Basic)
- `sku_tier` (optional): SKU tier (Basic, Standard, Premium) (default: Basic)
- `max_size_bytes` (optional): Maximum size in bytes (default: 2GB)
- `tags` (optional): Tags

**Response:**
```json
{
  "success": true,
  "database_name": "appdb",
  "server_name": "myserver",
  "location": "eastus",
  "sku": "Basic (Basic)",
  "status": "Online",
  "max_size_bytes": 2147483648,
  "message": "Successfully created database appdb on server myserver"
}
```

---

### 6. Delete Operations (Azure)

**Delete Resource Group (WARNING: Deletes ALL resources!):**
```
"Delete Azure resource group old-rg"
"Delete resource group test-rg with force"
```

**Delete Virtual Machine:**
```
"Delete Azure VM old-vm in resource group prod-rg"
"Delete virtual machine test-vm"
```

---

## Google Cloud CREATE Operations

### 1. Create Compute Engine Instance

Create a new Google Compute Engine virtual machine instance.

**Natural Language Examples:**
```
"Create a GCE instance named web-server in us-central1-a"
"Create Google Compute instance app-vm in zone us-west1-b with n1-standard-1"
"Create GCE instance db-server with e2-medium in europe-west1-b"
```

**Parameters:**
- `instance_name` (required): Instance name
- `zone` (required): Zone (us-central1-a, us-west1-b, europe-west1-b, asia-southeast1-a)
- `machine_type` (optional): Machine type (e2-medium, n1-standard-1, n2-standard-2) (default: e2-medium)
- `image_project` (optional): Image project (default: debian-cloud)
- `image_family` (optional): Image family (default: debian-11)
- `disk_size_gb` (optional): Boot disk size in GB (default: 10)
- `project_id` (optional): GCP project ID

**Response:**
```json
{
  "success": true,
  "instance_name": "web-server",
  "zone": "us-central1-a",
  "machine_type": "e2-medium",
  "project": "my-project-123",
  "operation": "operation-1234567890",
  "message": "Successfully initiated creation of instance web-server. This may take a few minutes."
}
```

---

### 2. Create Cloud Storage Bucket

Create a new Google Cloud Storage bucket.

**Natural Language Examples:**
```
"Create GCS bucket my-app-data"
"Create Google Cloud Storage bucket backups in EU"
"Create GCS bucket archives with COLDLINE storage class"
```

**Parameters:**
- `bucket_name` (required): Bucket name (must be globally unique)
- `location` (optional): Location (US, EU, us-central1, europe-west1) (default: US)
- `storage_class` (optional): Storage class (STANDARD, NEARLINE, COLDLINE, ARCHIVE) (default: STANDARD)
- `project_id` (optional): GCP project ID

**Response:**
```json
{
  "success": true,
  "bucket_name": "my-app-data",
  "location": "US",
  "storage_class": "STANDARD",
  "project": "my-project-123",
  "self_link": "https://www.googleapis.com/storage/v1/b/my-app-data",
  "message": "Successfully created Cloud Storage bucket my-app-data"
}
```

**Storage Classes:**
- `STANDARD`: Frequently accessed data
- `NEARLINE`: Accessed less than once a month
- `COLDLINE`: Accessed less than once a quarter
- `ARCHIVE`: Long-term storage, accessed less than once a year

---

### 3. Create Cloud SQL Instance

Create a new Google Cloud SQL managed database instance.

**Natural Language Examples:**
```
"Create Cloud SQL instance mydb with MySQL 8.0"
"Create GCP SQL instance prod-db with PostgreSQL 14 in us-east1"
"Create Cloud SQL instance app-db with db-n1-standard-1 tier"
```

**Parameters:**
- `instance_name` (required): Instance name
- `database_version` (optional): Version (MYSQL_8_0, POSTGRES_14, SQLSERVER_2019_STANDARD) (default: MYSQL_8_0)
- `tier` (optional): Machine tier (db-f1-micro, db-n1-standard-1, db-n1-standard-2) (default: db-f1-micro)
- `region` (optional): Region (us-central1, us-east1, europe-west1) (default: us-central1)
- `root_password` (optional): Root password (auto-generated if not provided)
- `project_id` (optional): GCP project ID

**Response:**
```json
{
  "success": true,
  "instance_name": "mydb",
  "database_version": "MYSQL_8_0",
  "tier": "db-f1-micro",
  "region": "us-central1",
  "project": "my-project-123",
  "operation": "operation-1234567890",
  "message": "Successfully initiated creation of Cloud SQL instance mydb. This may take several minutes."
}
```

**Security Notes:**
- Backups are enabled by default (03:00 UTC start time)
- IPv4 is enabled for connectivity
- Root password is auto-generated if not provided

---

### 4. Delete Operations (GCP)

**Delete Compute Instance:**
```
"Delete GCE instance old-server in zone us-central1-a"
"Delete Google Compute instance test-vm in us-west1-b"
```

**Delete Storage Bucket:**
```
"Delete GCS bucket old-data"
"Delete Cloud Storage bucket temp-files with force to remove all objects"
```

---

## Complete Usage Examples

### Multi-Cloud Infrastructure Provisioning

**Scenario: Set up a web application across three clouds**

```
# AWS - Create application infrastructure
"Create an EC2 instance for web server with type t3.medium using ami-abc123"
"Create an S3 bucket my-app-assets for static files"
"Create an RDS MySQL database app-db with db.t3.small"

# Azure - Create backup infrastructure
"Create Azure resource group backup-rg in West US"
"Create Azure storage account backupdata in resource group backup-rg"
"Create Azure VM backup-server with Standard_B2s in West US"

# Google Cloud - Create analytics infrastructure
"Create GCE instance analytics-vm with n1-standard-4 in us-central1-a"
"Create GCS bucket analytics-data with NEARLINE storage class"
"Create Cloud SQL instance analytics-db with PostgreSQL 14"
```

### Development Environment Setup

```
# Create dev resources in AWS
"Create an EC2 instance dev-server with t2.micro"
"Create S3 bucket dev-code-artifacts"
"Create security group dev-sg allowing SSH and HTTP"

# Create dev resources in Azure
"Create Azure resource group dev-rg in East US"
"Create Azure VM dev-workstation with Standard_D2s_v3"
"Create Azure storage account devdata"

# Create dev resources in GCP
"Create GCE instance dev-instance with e2-medium in us-west1-a"
"Create GCS bucket dev-builds"
```

### Database Migration Project

```
# Source: Create AWS RDS for migration source
"Create RDS MySQL instance source-db with db.r5.large and 100GB storage"

# Target: Create Azure SQL for migration target
"Create Azure resource group migration-rg in East US"
"Create Azure SQL Server migration-server"
"Create Azure SQL database target-db on server migration-server with Standard S3"

# Backup: Create GCP Cloud SQL for backup
"Create Cloud SQL instance backup-db with MySQL 8.0 in us-central1"
```

---

## Best Practices

### Security

1. **Passwords and Credentials:**
   - Use strong passwords (12+ characters, mixed case, numbers, special chars)
   - Store credentials securely (never in code)
   - Rotate credentials regularly

2. **Network Security:**
   - Use security groups/firewalls to restrict access
   - Don't expose databases publicly unless absolutely necessary
   - Use VPCs and private subnets for sensitive resources

3. **Encryption:**
   - Enable encryption for storage (enabled by default in most cases)
   - Use encrypted connections (SSL/TLS)
   - Enable encryption at rest for databases

4. **Access Control:**
   - Use IAM roles with least privilege
   - Enable MFA for administrative access
   - Use service accounts for applications

### Cost Optimization

1. **Right-Sizing:**
   - Start with smaller instance types and scale up as needed
   - Use burstable instances (t2/t3, B-series, e2) for dev/test
   - Monitor usage and adjust resources accordingly

2. **Storage:**
   - Use appropriate storage classes (Standard, Nearline, Coldline)
   - Enable lifecycle policies to transition old data
   - Delete unused resources and snapshots

3. **Cleanup:**
   - Delete resources when no longer needed
   - Use tags to track resource ownership and purpose
   - Set up alerts for unexpected costs

### Reliability

1. **Backups:**
   - Enable automated backups for databases
   - Store critical data in multiple locations
   - Test restore procedures regularly

2. **High Availability:**
   - Use Multi-AZ deployments for production databases
   - Deploy across multiple availability zones
   - Use load balancers for web applications

3. **Monitoring:**
   - Enable CloudWatch/Azure Monitor/Cloud Monitoring
   - Set up alerts for resource health
   - Monitor resource utilization

---

## Troubleshooting

### Common Issues

**1. "Permission Denied" Errors:**
- Verify IAM permissions for the operation
- Check that credentials are configured correctly
- Ensure service limits haven't been exceeded

**2. "Resource Already Exists" Errors:**
- Use unique names (especially for buckets and servers)
- Check if resource was created in a previous attempt
- Use different names or delete existing resources

**3. "Invalid Parameter" Errors:**
- Verify parameter formats (e.g., AMI IDs, instance types)
- Check region availability for specific resources
- Ensure required parameters are provided

**4. "Quota Exceeded" Errors:**
- Check service quotas in your cloud provider console
- Request quota increases if needed
- Delete unused resources to free up quota

**5. "Operation Timeout" Errors:**
- Large resources may take several minutes to create
- Check cloud provider console for operation status
- Wait and retry if operation is still in progress

### Getting Help

```
# Check what CREATE operations are available
"List all available CREATE operations"
"What can I create with this agent?"

# Get details about a specific operation
"How do I create an EC2 instance?"
"What parameters are needed to create an Azure VM?"

# Check status of created resources
"Show me all my EC2 instances"
"List my Azure virtual machines"
"Get status of GCE instance web-server"
```

---

## Summary

The DevOps Agent now supports **20+ CREATE operations** across AWS, Azure, and Google Cloud Platform:

**AWS (7 operations):**
- EC2 Instances
- S3 Buckets
- RDS Databases
- Lambda Functions
- Security Groups
- Plus delete operations for EC2 and S3

**Azure (7 operations):**
- Resource Groups
- Virtual Machines
- Storage Accounts
- SQL Servers
- SQL Databases
- Plus delete operations for Resource Groups and VMs

**Google Cloud (6 operations):**
- Compute Engine Instances
- Cloud Storage Buckets
- Cloud SQL Instances
- Plus delete operations for instances and buckets

All operations support natural language commands and follow security best practices with encryption, access controls, and secure defaults.

---

**Ready to create cloud resources? Just ask the agent in plain English!**

Example: "Create an EC2 instance named web-server with type t2.micro and an S3 bucket my-data, then create an Azure VM backup-server in East US"
