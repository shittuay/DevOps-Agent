"""Configuration manager for DevOps Agent."""
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv


class ConfigManager:
    """Manages configuration from environment variables and YAML files."""

    def __init__(self, config_path: Optional[str] = None, env_path: Optional[str] = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to YAML configuration file
            env_path: Path to .env file
        """
        self.config: Dict[str, Any] = {}
        self.config_path = config_path
        self.env_path = env_path

        # Load configurations
        self._load_env()
        self._load_yaml()
        self._validate_config()

    def _load_env(self) -> None:
        """Load environment variables from .env file."""
        if self.env_path and os.path.exists(self.env_path):
            load_dotenv(self.env_path)
        else:
            # Try to load from default locations
            env_locations = [
                Path.cwd() / '.env',
                Path.cwd() / 'config' / '.env',
                Path(__file__).parent.parent.parent / 'config' / '.env'
            ]
            for env_file in env_locations:
                if env_file.exists():
                    load_dotenv(env_file)
                    break

    def _load_yaml(self) -> None:
        """Load configuration from YAML file."""
        config_locations = []

        if self.config_path:
            config_locations.append(Path(self.config_path))

        # Default locations to check
        config_locations.extend([
            Path.cwd() / 'config.yaml',
            Path.cwd() / 'config' / 'config.yaml',
            Path(__file__).parent.parent.parent / 'config' / 'config.yaml'
        ])

        for config_file in config_locations:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f) or {}
                break

        # If no YAML found, use defaults
        if not self.config:
            self.config = self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'agent': {
                'name': 'DevOps Agent',
                'version': '1.0.0',
                'log_level': 'INFO'
            },
            'claude': {
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 4096,
                'temperature': 0.7
            },
            'aws': {
                'default_region': 'us-east-1',
                'profile': 'default',
                'enabled': True
            },
            'azure': {
                'enabled': True,
                'subscription_id': None,
                'default_location': 'eastus'
            },
            'gcp': {
                'enabled': True,
                'project_id': None,
                'default_region': 'us-central1',
                'default_zone': 'us-central1-a'
            },
            'kubernetes': {
                'default_context': 'default',
                'default_namespace': 'default',
                'kubeconfig': '~/.kube/config',
                'enabled': True
            },
            'github': {
                'enabled': True
            },
            'gitlab': {
                'url': 'https://gitlab.com',
                'enabled': False
            },
            'jenkins': {
                'enabled': False
            },
            'safety': {
                'require_confirmation': True,
                'dangerous_commands': [
                    'rm -rf /',
                    'rm -rf *',
                    'drop database',
                    'delete all',
                    'mkfs',
                    'dd if='
                ],
                'dry_run_default': False,
                'command_timeout_seconds': 1800  # 30 minutes for long-running operations
            },
            'logging': {
                'file': 'logs/agent.log',
                'format': 'json',
                'max_size_mb': 100,
                'backup_count': 5,
                'console_output': True
            }
        }

    def _validate_config(self) -> None:
        """Validate required configuration."""
        # Check for required environment variables
        required_env_vars = ['ANTHROPIC_API_KEY']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}\n"
                f"Please set them in your .env file or environment."
            )

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.

        Args:
            key: Configuration key in dot notation (e.g., 'claude.model')
            default: Default value if key not found

        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get environment variable value.

        Args:
            key: Environment variable name
            default: Default value if not found

        Returns:
            Environment variable value
        """
        return os.getenv(key, default)

    @property
    def anthropic_api_key(self) -> str:
        """Get Anthropic API key."""
        return self.get_env('ANTHROPIC_API_KEY', '')

    @property
    def claude_model(self) -> str:
        """Get Claude model name."""
        return self.get('claude.model', 'claude-sonnet-4-20250514')

    @property
    def claude_max_tokens(self) -> int:
        """Get Claude max tokens."""
        return self.get('claude.max_tokens', 4096)

    @property
    def claude_temperature(self) -> float:
        """Get Claude temperature."""
        return self.get('claude.temperature', 0.7)

    @property
    def aws_region(self) -> str:
        """Get AWS default region."""
        return self.get_env('AWS_DEFAULT_REGION') or self.get('aws.default_region', 'us-east-1')

    @property
    def aws_profile(self) -> str:
        """Get AWS profile."""
        return self.get_env('AWS_PROFILE') or self.get('aws.profile', 'default')

    @property
    def aws_enabled(self) -> bool:
        """Check if AWS integration is enabled."""
        return self.get('aws.enabled', True)

    @property
    def azure_enabled(self) -> bool:
        """Check if Azure integration is enabled."""
        return self.get('azure.enabled', True)

    @property
    def azure_subscription_id(self) -> Optional[str]:
        """Get Azure subscription ID."""
        return self.get_env('AZURE_SUBSCRIPTION_ID') or self.get('azure.subscription_id')

    @property
    def azure_default_location(self) -> str:
        """Get Azure default location."""
        return self.get('azure.default_location', 'eastus')

    @property
    def gcp_enabled(self) -> bool:
        """Check if GCP integration is enabled."""
        return self.get('gcp.enabled', True)

    @property
    def gcp_project_id(self) -> Optional[str]:
        """Get GCP project ID."""
        return self.get_env('GCP_PROJECT_ID') or self.get('gcp.project_id')

    @property
    def gcp_default_region(self) -> str:
        """Get GCP default region."""
        return self.get('gcp.default_region', 'us-central1')

    @property
    def gcp_default_zone(self) -> str:
        """Get GCP default zone."""
        return self.get('gcp.default_zone', 'us-central1-a')

    @property
    def k8s_enabled(self) -> bool:
        """Check if Kubernetes integration is enabled."""
        return self.get('kubernetes.enabled', True)

    @property
    def k8s_default_context(self) -> str:
        """Get Kubernetes default context."""
        return self.get('kubernetes.default_context', 'default')

    @property
    def k8s_default_namespace(self) -> str:
        """Get Kubernetes default namespace."""
        return self.get('kubernetes.default_namespace', 'default')

    @property
    def k8s_kubeconfig(self) -> str:
        """Get Kubernetes kubeconfig path."""
        kubeconfig = self.get_env('KUBECONFIG') or self.get('kubernetes.kubeconfig', '~/.kube/config')
        return os.path.expanduser(kubeconfig)

    @property
    def github_token(self) -> Optional[str]:
        """Get GitHub token."""
        return self.get_env('GITHUB_TOKEN')

    @property
    def github_enabled(self) -> bool:
        """Check if GitHub integration is enabled."""
        return self.get('github.enabled', True) and bool(self.github_token)

    @property
    def gitlab_token(self) -> Optional[str]:
        """Get GitLab token."""
        return self.get_env('GITLAB_TOKEN')

    @property
    def gitlab_url(self) -> str:
        """Get GitLab URL."""
        return self.get_env('GITLAB_URL') or self.get('gitlab.url', 'https://gitlab.com')

    @property
    def gitlab_enabled(self) -> bool:
        """Check if GitLab integration is enabled."""
        return self.get('gitlab.enabled', False) and bool(self.gitlab_token)

    @property
    def jenkins_url(self) -> Optional[str]:
        """Get Jenkins URL."""
        return self.get_env('JENKINS_URL') or self.get('jenkins.url')

    @property
    def jenkins_username(self) -> Optional[str]:
        """Get Jenkins username."""
        return self.get_env('JENKINS_USERNAME')

    @property
    def jenkins_token(self) -> Optional[str]:
        """Get Jenkins token."""
        return self.get_env('JENKINS_TOKEN')

    @property
    def jenkins_enabled(self) -> bool:
        """Check if Jenkins integration is enabled."""
        return (
            self.get('jenkins.enabled', False)
            and bool(self.jenkins_url)
            and bool(self.jenkins_username)
            and bool(self.jenkins_token)
        )

    @property
    def log_level(self) -> str:
        """Get log level."""
        return self.get_env('AGENT_LOG_LEVEL') or self.get('agent.log_level', 'INFO')

    @property
    def log_file(self) -> str:
        """Get log file path."""
        return self.get('logging.file', 'logs/agent.log')

    @property
    def require_confirmation(self) -> bool:
        """Check if confirmation is required for dangerous operations."""
        env_value = self.get_env('AGENT_REQUIRE_CONFIRMATION')
        if env_value is not None:
            return env_value.lower() in ('true', '1', 'yes')
        return self.get('safety.require_confirmation', True)

    @property
    def dangerous_commands(self) -> list:
        """Get list of dangerous commands."""
        return self.get('safety.dangerous_commands', [])

    @property
    def command_timeout(self) -> int:
        """Get command timeout in seconds."""
        return self.get('safety.command_timeout_seconds', 300)

    def __repr__(self) -> str:
        """String representation of config."""
        return f"ConfigManager(config_path={self.config_path})"
