# DevOps Agent - Complete User Guide

Welcome to the DevOps Agent! This guide will help you get started with using natural language to automate your entire DevOps infrastructure.

## Table of Contents

1. [Introduction](#introduction)
2. [Installation](#installation)
3. [First-Time Setup](#first-time-setup)
4. [Using the Agent](#using-the-agent)
5. [Natural Language Tips](#natural-language-tips)
6. [Common Workflows](#common-workflows)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

---

## Introduction

### What is DevOps Agent?

DevOps Agent is an AI-powered automation tool that lets you manage your entire infrastructure using natural language. Instead of remembering complex commands and syntax, simply describe what you want to do in plain English.

### What Can It Do?

- **Multi-Cloud Management**: AWS, Azure, Google Cloud
- **Container Orchestration**: Kubernetes, Docker
- **Infrastructure as Code**: Terraform operations
- **CI/CD Pipelines**: Jenkins, GitHub Actions
- **Code Quality**: SonarQube analysis
- **Monitoring**: Prometheus, Datadog, Grafana
- **Version Control**: Git, GitHub operations

### Key Features

✅ **Natural Language Interface** - No complex syntax to remember
✅ **Safety Validations** - Prevents destructive operations
✅ **Multi-Cloud Support** - Unified interface for AWS, Azure, GCP
✅ **Audit Logging** - Complete operation history
✅ **Web & CLI Interfaces** - Use what works best for you

---

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Git (optional, for repository operations)

### Step 1: Install Python Dependencies

```bash
# Clone or navigate to the devops-agent directory
cd devops-agent

# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Verify Installation

```bash
python main.py --version
```

You should see the version information if installation was successful.

---

## First-Time Setup

### 1. Initialize Configuration

```bash
python main.py init
```

This creates:
- `config/.env` - Environment variables and secrets
- `config/config.yaml` - Agent configuration
- `logs/` directory - For audit logs

### 2. Configure API Key (Required)

The agent requires an Anthropic API key to function.

**Option A: Using Web Interface**
```bash
python app.py
```
Then navigate to http://localhost:5000 and follow the setup wizard.

**Option B: Manual Configuration**

Edit `config/.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-your-actual-api-key-here
```

Get your API key from: https://console.anthropic.com/

### 3. Configure Cloud Providers (Optional)

See [AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md) for detailed setup instructions for:
- AWS
- Azure
- Google Cloud Platform
- Kubernetes
- GitHub/Jenkins
- Monitoring tools

---

## Using the Agent

### Interface Options

The DevOps Agent offers two interfaces:

#### Option 1: Command Line Interface (CLI)

**Interactive Mode** (Recommended for exploratory work)
```bash
python main.py interactive
```

Features:
- Conversational interface
- Command history
- Rich formatting
- Special commands: `help`, `tools`, `clear`, `stats`, `exit`

**Single Command Mode** (Great for scripts)
```bash
python main.py ask "List all EC2 instances in us-east-1"
```

**List Available Tools**
```bash
python main.py tools
```

#### Option 2: Web Interface

**Start the Web Server**
```bash
python app.py
```

Then open http://localhost:5000 in your browser.

Features:
- Beautiful Claude-style UI
- User authentication
- Session persistence
- Settings management
- Real-time responses

---

## Natural Language Tips

### How to Phrase Requests

The agent understands natural language, so speak naturally! Here are some tips:

### ✅ Good Examples

```
"List all EC2 instances"
"Show me pods in the production namespace"
"Get logs from the nginx pod"
"What's the status of my Jenkins job?"
"Scale the frontend deployment to 5 replicas"
"Show me all Docker containers that are running"
```

### ❌ Avoid Being Too Vague

```
"Check everything"  # Too vague
"Fix it"  # What needs fixing?
"Get stuff"  # What stuff?
```

### 💡 Be Specific When Needed

```
# Instead of: "Start the server"
✅ "Start EC2 instance i-0abc123"

# Instead of: "Get logs"
✅ "Get logs from pod nginx-abc123 in namespace production"

# Instead of: "Deploy"
✅ "Run terraform apply in /path/to/terraform with auto-approve"
```

### Using Filters and Parameters

The agent understands context and parameters:

```
"List EC2 instances with tag Environment=production"
"Show me pods in namespace staging with status Running"
"Get CloudWatch logs from /aws/lambda/my-function for the last 2 hours"
"Scale deployment web-app to 3 replicas in namespace prod"
```

### Chaining Operations

You can describe multi-step processes:

```
"Check the health of all pods in production, then show me logs from any unhealthy ones"

"List all Azure VMs, then show me detailed info for the one named web-server-01"

"Run terraform plan in ./infrastructure, and if it looks good, apply it"
```

---

## Common Workflows

### Cloud Infrastructure Management

**AWS Examples:**
```
"List all EC2 instances"
"Show me S3 buckets in us-west-2"
"Get details for instance i-0abc123"
"Stop EC2 instance i-0abc123"
"Show me EKS clusters"
"Get CloudWatch logs from /aws/lambda/my-function for the last hour"
```

**Azure Examples:**
```
"List all Azure virtual machines"
"Show me VMs in resource group production-rg"
"Start VM named web-server in resource group prod-rg"
"List all storage accounts"
"Get Azure Monitor metrics for resource ID /subscriptions/..."
```

**Google Cloud Examples:**
```
"List all GCE instances in project my-project"
"Show me compute instances in zone us-central1-a"
"Stop instance web-server-1 in zone us-central1-a"
"List Cloud Storage buckets"
"Show me GKE clusters"
```

### Kubernetes Operations

```
"Show all pods in namespace production"
"Get logs from pod nginx-abc123"
"Describe pod nginx-abc123 in namespace default"
"Scale deployment web-app to 5 replicas"
"Restart deployment api-server"
"List all services in namespace prod"
"Show me all nodes in the cluster"
```

### Docker Operations

```
"List all running containers"
"Show me all Docker containers including stopped ones"
"Get logs from container nginx-001"
"Show me resource usage for container web-app"
"Stop container nginx-001"
"Pull image nginx:latest"
"List all Docker images"
"Show me Docker networks"
```

### Terraform Workflows

```
"Initialize terraform in /path/to/terraform"
"Run terraform plan in ./infrastructure"
"Apply terraform in ./infra with auto-approve"
"Show terraform state"
"List terraform workspaces"
"Switch to workspace production"
"Validate terraform configuration in ./infra"
"Format terraform files in ./infra"
```

### Git Operations

```
"Show status of repository /path/to/repo"
"List branches in /path/to/repo"
"Get commit history for the last 10 commits"
"Show diff between commit abc123 and def456"
"List pull requests for owner/repo"
"Get details for pull request #42 in owner/repo"
```

### CI/CD Pipeline Management

```
"Trigger Jenkins job deploy-production"
"Show status of Jenkins job build-app build number 42"
"Get logs from Jenkins job deploy-app build 100"
"Trigger GitHub workflow deploy in owner/repo on branch main"
"Show GitHub workflow runs for owner/repo"
```

### Code Quality & SonarQube

```
"List all SonarQube projects"
"Show quality gate status for project my-app"
"Get code coverage for project my-app"
"Show me all bugs in project my-app"
"List critical vulnerabilities in project my-app"
"Show security hotspots for project my-app"
```

### Monitoring & Observability

**Prometheus:**
```
"Query prometheus for cpu usage"
"Show prometheus targets"
"Get prometheus alerts"
```

**Datadog:**
```
"Show all Datadog monitors"
"Get Datadog hosts"
"Query Datadog metrics for system.cpu.user"
"Create Datadog event titled 'Deployment' with message 'Deployed v1.2'"
```

**Grafana:**
```
"List Grafana dashboards"
"Show Grafana datasources"
"Get Grafana alerts"
```

---

## Troubleshooting

### Common Issues

#### 1. "Agent not initialized" Error

**Problem:** Missing or invalid API key

**Solution:**
```bash
# Check if .env file exists
ls config/.env

# Verify API key is set
cat config/.env | grep ANTHROPIC_API_KEY

# Re-run initialization
python main.py init
```

#### 2. "AWS credentials not found"

**Problem:** AWS credentials not configured

**Solution:**
```bash
# Option 1: Use environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_DEFAULT_REGION=us-east-1

# Option 2: Configure in .env file
echo "AWS_ACCESS_KEY_ID=your_key" >> config/.env
echo "AWS_SECRET_ACCESS_KEY=your_secret" >> config/.env
echo "AWS_DEFAULT_REGION=us-east-1" >> config/.env

# Option 3: Use AWS CLI
aws configure
```

#### 3. "Kubernetes config not found"

**Problem:** kubectl config not found or misconfigured

**Solution:**
```bash
# Check if kubeconfig exists
ls ~/.kube/config

# Set KUBECONFIG if in different location
export KUBECONFIG=/path/to/kubeconfig

# Verify kubectl works
kubectl get pods
```

#### 4. "Docker daemon not running"

**Problem:** Docker is not installed or not running

**Solution:**
```bash
# Check Docker status
docker ps

# Start Docker (varies by OS)
# On Windows: Start Docker Desktop
# On Linux: sudo systemctl start docker
# On macOS: Start Docker Desktop
```

#### 5. "Tool execution failed with timeout"

**Problem:** Command took too long to execute

**Solution:**
```bash
# Increase timeout in config/config.yaml
safety:
  command_timeout_seconds: 600  # Increase from 300

# Or specify timeout in request:
"Execute terraform apply with timeout of 10 minutes"
```

### Getting Help

1. **View available tools:**
   ```bash
   python main.py tools
   ```

2. **Check agent status:**
   ```bash
   python main.py ask "Show me session statistics"
   ```

3. **View logs:**
   ```bash
   tail -f logs/agent.log
   ```

4. **Interactive help:**
   ```bash
   python main.py interactive
   # Then type: help
   ```

---

## Best Practices

### Security

1. **Store credentials securely**
   - Use environment variables in `config/.env`
   - Never commit `.env` to version control
   - Rotate credentials regularly

2. **Use read-only credentials for exploration**
   - Start with limited IAM permissions
   - Use separate credentials for read vs write operations

3. **Enable safety confirmations**
   ```yaml
   # config/config.yaml
   safety:
     require_confirmation: true
   ```

4. **Review audit logs**
   ```bash
   tail -f logs/agent.log
   ```

### Performance

1. **Use specific queries**
   - "List EC2 instances in us-east-1" (specific)
   - vs "List all AWS resources" (too broad)

2. **Limit result sets**
   - "Show me the last 50 lines of logs"
   - vs "Show me all logs" (could be huge)

3. **Use filters**
   - "List pods with status Running"
   - vs "List all pods" (then filter manually)

### Workflow Efficiency

1. **Use web interface for exploration**
   - Better for learning and testing
   - Session persistence
   - Easy to review history

2. **Use CLI for automation**
   - Single-command mode for scripts
   - Easy to integrate with other tools
   - Better for CI/CD pipelines

3. **Chain related operations**
   - "Check pod status, then get logs if unhealthy"
   - More efficient than separate requests

### Safety

1. **Always review before destructive operations**
   - The agent will ask for confirmation on high-risk operations
   - Read the summary carefully before confirming

2. **Test in non-production first**
   - Use dev/staging environments for testing
   - Verify commands work as expected

3. **Use dry-run when available**
   - "Run terraform plan" before "apply"
   - "Execute command with dry-run enabled"

---

## Next Steps

Now that you understand the basics, explore:

1. **[AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md)** - Set up all cloud providers
2. **[AUTOMATION_COOKBOOK.md](AUTOMATION_COOKBOOK.md)** - Real-world automation scenarios
3. **[TOOL_REFERENCE.md](TOOL_REFERENCE.md)** - Complete tool catalog
4. **[ADVANCED_AUTOMATION.md](ADVANCED_AUTOMATION.md)** - Power user features
5. **[QUICK_START_EXAMPLES.md](QUICK_START_EXAMPLES.md)** - 50+ ready-to-use examples

---

## Support

- **Documentation:** See `docs/` directory
- **Issues:** https://github.com/your-repo/devops-agent/issues
- **Examples:** See `examples/` directory

---

**Happy Automating! 🚀**
