# DevOps Agent - Tools & Capabilities

Hello! I'm your DevOps agent, ready to help you manage **multi-cloud infrastructure**, automate workflows, and streamline your development operations across **AWS, Azure, and Google Cloud Platform**.

---

## 🛠️ Available Tools & Services

### ☁️ AWS Services

#### Compute & Storage:
- **EC2**: Create, manage, list, start/stop/restart instances, delete instances
- **Lambda**: Create serverless functions from ZIP files, manage configurations
- **S3**: Create buckets with encryption, delete buckets (with force option), list buckets, retrieve bucket information
- **EKS**: List and manage Kubernetes clusters

#### Database:
- **RDS**: Create database instances (MySQL, PostgreSQL, MariaDB, Oracle, SQL Server), manage and monitor

#### Security & Networking:
- **IAM**: List users, roles, and manage permissions
- **Security Groups**: Create security groups with custom ingress rules, configure firewall rules
- **CloudWatch**: Retrieve logs and monitoring data, query metrics

#### CREATE Operations:
- ✅ Create EC2 instances with custom AMI, instance type, security groups, tags
- ✅ Create S3 buckets with versioning, encryption (enabled by default), public access blocking
- ✅ Create RDS database instances with Multi-AZ, backup retention, encryption
- ✅ Create Lambda functions with environment variables, custom runtime, memory/timeout settings
- ✅ Create Security Groups with multiple ingress rules
- ✅ Delete EC2 instances and S3 buckets (with force delete option)

---

### 🔷 Azure Services

#### Compute:
- **Virtual Machines**: Create VMs with complete networking setup (VNet, Subnet, Public IP, NIC), manage (start/stop/restart/deallocate), delete
- **VM Sizes**: Support for all Azure VM sizes (B-series, D-series, E-series, etc.)

#### Storage:
- **Storage Accounts**: Create storage accounts with SKU options (Standard_LRS, Standard_GRS, Premium_LRS), list and manage
- **Blob, File, Queue, Table**: Access all storage endpoints

#### Database:
- **Azure SQL**: Create SQL Servers and Databases, manage tiers (Basic, Standard, Premium), configure sizes

#### Resource Management:
- **Resource Groups**: Create, list, and delete resource groups (WARNING: deletes ALL resources inside)

#### Monitoring:
- **Azure Monitor**: Query metrics for any resource, track performance and health

#### CREATE Operations:
- ✅ Create Resource Groups in any Azure region
- ✅ Create Virtual Machines with Ubuntu/Windows images, custom sizes, networking
- ✅ Create Storage Accounts with redundancy options
- ✅ Create SQL Servers with admin credentials
- ✅ Create SQL Databases on existing servers with tier selection
- ✅ Delete Resource Groups and Virtual Machines

---

### 🌐 Google Cloud Platform (GCP)

#### Compute:
- **Compute Engine**: Create instances with custom machine types, manage (start/stop/reset), delete
- **Machine Types**: Support for all GCE machine types (e2, n1, n2, c2, m1, etc.)

#### Storage:
- **Cloud Storage**: Create buckets with storage classes (STANDARD, NEARLINE, COLDLINE, ARCHIVE), delete with force option
- **Multi-regional**: Support for US, EU, and regional locations

#### Database:
- **Cloud SQL**: Create MySQL, PostgreSQL, or SQL Server instances, configure tiers and regions

#### Container & Serverless:
- **GKE**: List and manage Kubernetes Engine clusters
- **Cloud Functions**: List serverless functions

#### Monitoring:
- **Cloud Monitoring**: Query metrics for compute, storage, and other resources

#### CREATE Operations:
- ✅ Create Compute Engine instances with Debian/Ubuntu images, custom disk sizes
- ✅ Create Cloud Storage buckets with storage class selection
- ✅ Create Cloud SQL instances with backup configuration
- ✅ Delete Compute instances and Storage buckets

---

### ⚓ Kubernetes

#### Resource Management:
- **Workloads**: Pods, Deployments, ReplicaSets, StatefulSets, DaemonSets
- **Services**: ClusterIP, NodePort, LoadBalancer, Ingress
- **Configuration**: ConfigMaps, Secrets
- **Storage**: PersistentVolumes, PersistentVolumeClaims
- **Cluster**: Nodes, Namespaces

#### Operations:
- Scale deployments up/down dynamically
- Restart and roll deployments with zero downtime
- View real-time logs from pods
- Describe resources for detailed information
- Check cluster health and resource utilization
- Delete pods and resources

---

### 🔄 Git & Version Control

#### Repository Operations:
- Check repository status and history
- View commit logs and diffs
- List and manage branches
- View pull request details
- Compare commits

#### GitHub Integration:
- List and create pull requests
- View PR status and reviews
- Manage workflow runs

---

### 🚀 CI/CD & Pipeline Automation

#### Jenkins:
- Manage jobs and builds
- Trigger builds with parameters
- View build status and logs
- Monitor pipeline health

#### GitHub Actions:
- Trigger workflows
- View workflow runs and status
- Check action logs

#### GitLab CI/CD:
- Pipeline management
- Job monitoring

---

### 🐳 Docker & Containers

#### Container Management:
- List running and stopped containers
- Start, stop, restart, pause containers
- View container logs (tail, follow)
- Monitor resource usage (CPU%, memory, network)
- Remove containers

#### Image Operations:
- List Docker images
- Pull images from registries
- Remove unused images
- Inspect image details

#### Docker Compose:
- Run docker-compose up/down
- Manage multi-container applications

#### Networking & Volumes:
- List Docker networks
- List Docker volumes
- Inspect network and volume details

---

### 🏗️ Infrastructure as Code

#### Terraform:
- **Initialization**: terraform init with backend configuration
- **Planning**: terraform plan with variable files
- **Deployment**: terraform apply with auto-approve option
- **Destruction**: terraform destroy
- **Validation**: terraform validate and fmt
- **State**: terraform show, output, state list
- **Workspaces**: List and select workspaces

---

### 📊 Code Quality & Analysis

#### SonarQube:
- **Projects**: List all projects and quality gates
- **Metrics**: Get code coverage, duplications, complexity
- **Issues**: List bugs, vulnerabilities, code smells by severity
- **Security**: Track security hotspots and ratings
- **Analysis**: Trigger scans and view results

---

### 📈 Monitoring & Observability

#### Prometheus:
- Execute PromQL queries
- Query metrics over time ranges
- List scrape targets and health
- View active alerts

#### Datadog:
- Query system and custom metrics
- List monitors and their status
- Get host inventory
- Create and retrieve events
- Filter by tags

#### Grafana:
- List dashboards
- View datasources
- Retrieve alerts
- Manage dashboard operations

---

### 🖥️ System Operations

#### Command Execution:
- Execute shell commands safely
- Run scripts from files
- Set environment variables
- Command timeout protection

---

## 💡 How to Interact With Me

### AWS Examples:
```
"Create an EC2 instance with type t2.micro using ami-0c55b159cbfafe1f0"
"Create an S3 bucket named my-app-data with encryption enabled"
"Create a MySQL RDS database named prod-db with db.t3.small"
"Create a Lambda function named api-handler with Python 3.9"
"Create a security group named web-sg allowing HTTP and HTTPS"
"List all running EC2 instances in us-east-1"
"Delete EC2 instance i-abc123"
```

### Azure Examples:
```
"Create an Azure resource group named prod-rg in East US"
"Create an Azure VM named web-server with Standard_B1s in East US"
"Create Azure storage account mystorageacct in West Europe"
"Create Azure SQL Server named myserver in East US"
"Create database appdb on SQL server myserver"
"List all Azure virtual machines"
"Delete Azure VM old-server in resource group prod-rg"
```

### Google Cloud Examples:
```
"Create a GCE instance named web-server in us-central1-a"
"Create a GCS bucket named my-app-data"
"Create a Cloud SQL instance named mydb with MySQL 8.0"
"List all Compute Engine instances"
"Delete GCE instance old-server in zone us-central1-a"
```

### Kubernetes Examples:
```
"Scale the production deployment to 5 replicas"
"List all pods in namespace production"
"Get logs from pod nginx-abc123"
"Restart the api-service deployment"
"Describe pod web-app-12345 in namespace staging"
```

### Multi-Cloud Operations:
```
"Create an EC2 instance in AWS, an Azure VM in East US, and a GCE instance in us-central1-a"
"List all virtual machines across AWS, Azure, and GCP"
"Create storage buckets in S3, Azure Storage, and GCS"
```

### Docker Examples:
```
"List all running containers"
"Show me resource usage for container nginx-001"
"Get logs from container web-app"
"Stop container old-app"
```

### Terraform Examples:
```
"Run terraform plan in ./infrastructure"
"Apply terraform in ./infra with auto-approve"
"List terraform workspaces"
"Show terraform state"
```

### SonarQube Examples:
```
"Show quality gate status for project my-app"
"List all bugs in project backend-api"
"Get code coverage for project frontend"
```

### Monitoring Examples:
```
"Query Prometheus for CPU usage over the last hour"
"Show all Datadog monitors with status alert"
"List Grafana dashboards"
```

---

## 🎯 Best Practices

### Cloud Operations:
- **Specify regions** for AWS/Azure/GCP operations (e.g., us-east-1, eastus, us-central1-a)
- **Use unique names** for globally-scoped resources (S3 buckets, Azure storage accounts, GCS buckets)
- **Check costs** before creating expensive resources (large VMs, Multi-AZ databases)
- **Tag resources** for easier management and cost tracking

### Kubernetes:
- **Include namespaces** for Kubernetes commands (production, staging, development)
- **Verify pod names** before scaling or deleting
- **Use labels** for resource organization

### Security:
- **Use strong passwords** for database and VM creation (12+ chars, mixed case, numbers, special)
- **Enable encryption** by default (already enabled for S3, RDS, Azure Storage)
- **Block public access** unless explicitly needed (already blocked by default for S3)
- **Review security groups** before opening ports to 0.0.0.0/0

### Infrastructure as Code:
- **Run terraform plan** before apply
- **Use workspaces** for environment separation
- **Validate configurations** before deployment

---

## ⚠️ Safety Features

### Built-in Protections:
- ✅ Confirmations required for destructive operations
- ✅ Production environment safeguards
- ✅ Detailed operation logging and audit trails
- ✅ Rollback capabilities where available
- ✅ Command timeout protection (default: 5 minutes)

### Security Best Practices:
- ✅ Encryption enabled by default (S3, RDS, Azure Storage)
- ✅ Public access blocked by default (S3 buckets)
- ✅ Backup retention enabled (RDS: 7 days, Cloud SQL: daily)
- ✅ Storage encryption always enabled (RDS, Cloud SQL)
- ✅ Secure password requirements enforced

### Delete Operations:
- ⚠️ **DELETE operations are DESTRUCTIVE and cannot be undone**
- ⚠️ Deleting Azure Resource Groups removes ALL resources inside
- ⚠️ Use `force` parameter carefully when deleting S3/GCS buckets with contents
- ⚠️ Always verify resource names before deletion

---

## 📊 Total Capabilities

### Cloud Platforms:
- ✅ **AWS**: 15+ services, 20+ operations
- ✅ **Azure**: 5+ services, 15+ operations
- ✅ **GCP**: 5+ services, 12+ operations

### DevOps Tools:
- ✅ **Kubernetes**: 20+ resource types
- ✅ **Docker**: 15+ operations
- ✅ **Terraform**: 10+ commands
- ✅ **Git/GitHub**: 10+ operations
- ✅ **CI/CD**: Jenkins, GitHub Actions, GitLab

### Quality & Monitoring:
- ✅ **SonarQube**: Quality gates, metrics, issues
- ✅ **Prometheus**: PromQL queries, targets, alerts
- ✅ **Datadog**: Metrics, monitors, events
- ✅ **Grafana**: Dashboards, datasources, alerts

### Total Tools: **36 Professional DevOps Tools** 🚀

---

## 🔗 Additional Resources

- **Complete Documentation**: See `docs/USER_GUIDE.md`
- **CREATE Operations Guide**: See `docs/CREATE_OPERATIONS_GUIDE.md`
- **Automation Examples**: See `docs/AUTOMATION_COOKBOOK.md`
- **Tool Reference**: See `docs/TOOL_REFERENCE.md`
- **Authentication Setup**: See `docs/AUTHENTICATION_GUIDE.md`

---

## 🎓 Getting Started

1. **Configure API Key**: Set up your Anthropic API key in setup
2. **Configure Cloud Credentials**:
   - AWS: Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
   - Azure: Set AZURE_SUBSCRIPTION_ID, AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
   - GCP: Set GCP_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS
3. **Start Exploring**: Try simple commands first (list operations)
4. **Create Resources**: Use CREATE operations with appropriate parameters
5. **Automate Workflows**: Combine operations for complex tasks

---

**Ready to automate your infrastructure! Ask me anything about AWS, Azure, GCP, Kubernetes, Docker, CI/CD, and more!** 🚀
