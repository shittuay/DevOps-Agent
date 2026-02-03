# DevOps Automation Agent

🤖 An intelligent DevOps automation agent powered by Claude AI that helps you manage cloud infrastructure, Kubernetes clusters, CI/CD pipelines, and more using natural language commands.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Claude](https://img.shields.io/badge/powered%20by-Claude%20AI-purple.svg)](https://anthropic.com)

## Features

### 🎯 Core Capabilities

- **Natural Language Interface**: Interact with your infrastructure using plain English
- **Multi-Cloud Support**: AWS integration (EC2, S3, EKS, CloudWatch, IAM)
- **Kubernetes Management**: Pod, deployment, service, and node operations
- **Git Operations**: Repository status, branches, commits, and pull requests
- **CI/CD Integration**: Jenkins and GitHub Actions support
- **Safe Execution**: Built-in safety validation and confirmation for destructive operations
- **Audit Trail**: Complete logging of all operations with structured logs

### 🏢 Enterprise Features (Phase 5)

- **Organizations & Multi-tenancy**: Create organizations, manage teams, invite members, SSO integration
- **AI Infrastructure**: Infrastructure templates, one-click provisioning, AI-powered recommendations
- **Analytics Dashboards**: Custom dashboards, widgets, real-time metrics visualization
- **API Gateway**: API key management, webhook endpoints, rate limiting, usage analytics
- **Compliance Framework**: Policy management, compliance reports, audit logging, framework support (SOC2, HIPAA, PCI-DSS)

### 🛠️ Available Tools

**AWS Tools:**
- List and manage EC2 instances
- S3 bucket operations
- EKS cluster information
- CloudWatch logs retrieval
- IAM users and roles inspection

**Kubernetes Tools:**
- Pod management (list, logs, describe)
- Deployment operations (scale, restart, status)
- Service discovery
- Node status and resources
- Events monitoring

**Git Tools:**
- Repository status and history
- Branch management
- Commit history and diffs
- Pull request information (GitHub)

**CI/CD Tools:**
- Jenkins job triggering and monitoring
- GitHub Actions workflow execution
- Build logs retrieval

**Command Tools:**
- Safe shell command execution
- Script execution with timeout protection

## Quick Start

### Prerequisites

- Python 3.10 or higher
- Anthropic API key (get one at [console.anthropic.com](https://console.anthropic.com))
- AWS credentials (if using AWS tools)
- kubectl configured (if using Kubernetes tools)
- Git installed (if using Git tools)

### Installation

1. **Clone or extract the repository:**

```bash
cd devops-agent
```

2. **Create a virtual environment:**

```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies:**

```bash
pip install -r requirements.txt
```

4. **Initialize configuration:**

```bash
python main.py init
```

This will create:
- `config/config.yaml` - Main configuration file
- `config/.env` - Environment variables for secrets

5. **Configure your credentials:**

Edit `config/.env` and add your credentials:

```bash
# Required
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Optional - AWS
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
AWS_DEFAULT_REGION=us-east-1

# Optional - GitHub
GITHUB_TOKEN=your_github_token_here

# Optional - Jenkins
JENKINS_URL=https://jenkins.example.com
JENKINS_USERNAME=your_username
JENKINS_TOKEN=your_jenkins_token
```

6. **Start the agent:**

```bash
python main.py interactive
```

## Usage

### Interactive Mode

Start an interactive chat session with the agent:

```bash
python main.py interactive
```

Example interactions:

```
You: List all EC2 instances in us-east-1

Agent: I'll list the EC2 instances in us-east-1 for you.

Found 3 EC2 instances:
1. web-server-1 (i-0abc123)
   - State: running
   - Type: t3.medium
   - IP: 10.0.1.50

2. database-server (i-0def456)
   - State: running
   - Type: t3.large
   - IP: 10.0.2.100

...
```

```
You: Show me pods in the default namespace that are not running

Agent: I'll check for pods in the default namespace with issues.

Found 2 pods with problems:
1. nginx-abc123 - Status: CrashLoopBackOff
   - Container: nginx (restart count: 5)
   - Last restart: 2 minutes ago

2. api-xyz789 - Status: Pending
   - Reason: Insufficient CPU
   - Node: Not scheduled yet

Would you like me to get logs from any of these pods?
```

### Single Command Mode

Ask a single question without entering interactive mode:

```bash
python main.py ask "What's the status of my Jenkins job deploy-prod?"
```

### List Available Tools

See all available tools the agent can use:

```bash
python main.py tools
```

### Interactive Commands

While in interactive mode, you can use these special commands:

- `help` - Show help information
- `tools` - List all available tools
- `clear` - Clear conversation history
- `stats` - Show session statistics
- `exit` or `quit` - Exit the session

## Example Queries

### AWS

```
- List all EC2 instances
- Show me EC2 instances with tag Environment=production
- Stop instance i-0abc123
- List all S3 buckets
- Get information about bucket my-data-bucket
- Show EKS clusters in us-west-2
- Get CloudWatch logs from /aws/lambda/my-function for the last 2 hours
- List IAM users
```

### Kubernetes

```
- Show all pods in namespace production
- Get logs from pod nginx-abc123
- Show me the last 50 lines of logs from pod api-server container app
- Describe pod my-app-xyz789
- List all deployments in default namespace
- Scale deployment web-app to 5 replicas
- Restart deployment api-server
- Show all services in namespace production
- List all nodes in the cluster
```

### Git

```
- Show status of repository /path/to/repo
- List branches in /path/to/my-project
- Get commit history from /path/to/repo
- Show diff for commit abc123 in /path/to/repo
- List pull requests for octocat/Hello-World
- Get details for pull request #42 in owner/repo
```

### CI/CD

```
- Trigger Jenkins job deploy-production
- Get status of Jenkins job build-app build #123
- Show Jenkins build logs for job deploy-prod build 45
- Trigger GitHub workflow deploy.yml in owner/repo
- Show GitHub workflow runs for owner/repo
```

### Commands

```
- Execute command: ls -la /var/log
- Run command: docker ps
- Execute script /path/to/deployment-script.sh
- Run command with 60 second timeout: ping -c 100 example.com
```

## Configuration

### Main Configuration File

Edit `config/config.yaml` to customize the agent:

```yaml
agent:
  name: "DevOps Agent"
  log_level: "INFO"

claude:
  model: "claude-sonnet-4-20250514"
  max_tokens: 4096
  temperature: 0.7

aws:
  default_region: "us-east-1"
  enabled: true

kubernetes:
  default_namespace: "default"
  enabled: true

safety:
  require_confirmation: true
  dangerous_commands:
    - "rm -rf /"
    - "drop database"
  command_timeout_seconds: 300

logging:
  file: "logs/agent.log"
  format: "json"
  max_size_mb: 100
```

### Environment Variables

All sensitive credentials should be in `config/.env`:

```bash
# Required
ANTHROPIC_API_KEY=your_key_here

# Optional based on features you use
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
GITHUB_TOKEN=your_token
JENKINS_URL=https://jenkins.example.com
JENKINS_USERNAME=admin
JENKINS_TOKEN=your_jenkins_token
```

## Security

### Safety Features

The agent includes several safety mechanisms:

1. **Command Validation**: Dangerous commands are blocked automatically
2. **Confirmation Prompts**: High-risk operations require confirmation
3. **Audit Logging**: All operations are logged with timestamps
4. **Timeout Protection**: Commands have timeout limits
5. **Output Sanitization**: Sensitive data is masked in outputs

### Dangerous Command Patterns

The following patterns are blocked by default:

- `rm -rf /` and variations
- `drop database`
- `mkfs` (filesystem formatting)
- `dd if=` (disk operations)
- Production deletions without confirmation

You can customize these in `config/config.yaml`.

### Best Practices

1. **Use least privilege**: Configure AWS/cloud credentials with minimum required permissions
2. **Enable confirmation**: Keep `require_confirmation: true` in config
3. **Review logs**: Regularly check `logs/agent.log` for audit trail
4. **Rotate credentials**: Regularly rotate API keys and tokens
5. **Test in dev first**: Try commands in development before production

## Logging

### Log Location

Logs are stored in `logs/agent.log` with automatic rotation.

### Log Format

Logs are structured JSON for easy parsing:

```json
{
  "timestamp": "2025-10-28T10:30:45.123Z",
  "level": "INFO",
  "correlation_id": "req-123abc",
  "user": "john.doe",
  "action": "execute_command",
  "command": "kubectl get pods",
  "result": "success",
  "execution_time_ms": 234
}
```

### Log Levels

- `DEBUG`: Detailed information for debugging
- `INFO`: General informational messages
- `WARNING`: Warning messages for potential issues
- `ERROR`: Error messages for failures

Configure log level in `config/config.yaml` or via `AGENT_LOG_LEVEL` environment variable.

## Troubleshooting

### Common Issues

**1. "AWS credentials not found"**

- Solution: Configure AWS credentials via environment variables or `~/.aws/credentials`
- Check: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in `.env`

**2. "Kubernetes config not found"**

- Solution: Ensure `~/.kube/config` exists and is valid
- Test: Run `kubectl get pods` to verify kubectl works

**3. "GitHub token not provided"**

- Solution: Add `GITHUB_TOKEN` to `config/.env`
- Get token: GitHub Settings → Developer settings → Personal access tokens

**4. "Command timed out"**

- Solution: Increase `command_timeout_seconds` in config
- Default is 300 seconds (5 minutes)

**5. "Module not found" errors**

- Solution: Ensure virtual environment is activated
- Run: `pip install -r requirements.txt`

### Debug Mode

Enable debug logging for more detailed information:

```bash
# In config/.env
AGENT_LOG_LEVEL=DEBUG
```

Or in `config/config.yaml`:

```yaml
agent:
  log_level: "DEBUG"
```

## Development

### Project Structure

```
devops-agent/
├── src/
│   ├── agent/          # Core agent framework
│   │   ├── core.py     # Main agent class
│   │   ├── conversation.py
│   │   └── safety.py
│   ├── config/         # Configuration management
│   ├── tools/          # Tool integrations
│   │   ├── aws_tools.py
│   │   ├── kubernetes_tools.py
│   │   ├── git_tools.py
│   │   ├── cicd_tools.py
│   │   └── command_tools.py
│   └── utils/          # Utilities
│       └── logging.py
├── config/             # Configuration files
├── tests/              # Unit tests
├── logs/               # Log files
├── main.py             # CLI entry point
└── requirements.txt    # Dependencies
```

### Adding New Tools

To add a new tool:

1. Create a function in appropriate tools module:

```python
def my_new_tool(param1: str, param2: int) -> Dict[str, Any]:
    """
    Description of what the tool does.

    Args:
        param1: Description
        param2: Description

    Returns:
        Dictionary with results
    """
    # Implementation
    return {'success': True, 'data': result}
```

2. Add tool definition to `get_tools()`:

```python
{
    'name': 'my_new_tool',
    'description': 'Clear description for Claude',
    'input_schema': {
        'type': 'object',
        'properties': {
            'param1': {'type': 'string', 'description': '...'},
            'param2': {'type': 'integer', 'description': '...'}
        },
        'required': ['param1']
    },
    'handler': my_new_tool
}
```

3. Register the module in `main.py` if it's a new category.

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_agent.py
```

## Roadmap

### Phase 2 (Complete)

- [x] Azure and GCP integration
- [x] Terraform and CloudFormation support
- [x] Ansible playbook execution
- [x] Prometheus and Grafana integration
- [x] Datadog integration
- [x] PagerDuty/OpsGenie alerting
- [x] Cost optimization recommendations

### Phase 3 (Complete)

- [x] Web-based UI
- [x] Multi-user support with RBAC
- [x] Automated incident response (6 built-in playbooks)
- [x] Proactive monitoring and alerts (8 default rules)
- [x] Performance optimization suggestions
- [x] Slack/Teams bot integration

### Phase 4 (Complete)

- [x] AI-powered root cause analysis
- [x] Predictive scaling recommendations
- [x] Custom playbook builder UI
- [x] Webhook integrations (GitHub, GitLab, Bitbucket)
- [x] ChatOps commands for Slack/Teams
- [x] Infrastructure drift detection

### Phase 5 (Complete)

- [x] Organizations & Multi-tenancy (teams, members, SSO)
- [x] AI Infrastructure Management (templates, provisioning, recommendations)
- [x] Analytics Dashboards (custom widgets, metrics visualization)
- [x] API Gateway (keys, webhooks, rate limiting, usage tracking)
- [x] Compliance Framework (policies, reports, audit logs, frameworks)

### Phase 6 (Planned)

- [ ] Two-factor authentication (2FA/MFA)
- [ ] Mobile app with push notifications
- [ ] Advanced RBAC with custom roles
- [ ] Automated database backups with cloud storage
- [ ] GraphQL API support
- [ ] Terraform Cloud integration

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

For issues, questions, or feedback:

- **Live Application**: [https://devopsagent.io](https://devopsagent.io)
- **GitHub Issues**: [Create an issue](https://github.com/shittuay/DevOps-Agent/issues)
- **Documentation**: [Full docs](docs/)

## Acknowledgments

- Powered by [Claude AI](https://anthropic.com) from Anthropic
- Built with Python and the amazing open-source community
- Special thanks to all contributors

---

**⚠️ Important Notes:**

- This agent has access to your infrastructure - use with caution
- Always test in development environments first
- Keep your API keys and credentials secure
- Review the audit logs regularly
- The agent will ask for confirmation before destructive operations

**Happy automating! 🚀**
