"""
DevOps Automation Agent - Main CLI Entry Point
"""
import os
import sys
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table


# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.agent import DevOpsAgent
from src.utils import setup_logging, get_logger
from src.tools import (
    command_tools,
    aws_tools,
    azure_tools,
    gcp_tools,
    kubernetes_tools,
    git_tools,
    cicd_tools,
    pentest_tools
)


console = Console(force_terminal=True, legacy_windows=False)


def print_banner():
    """Print welcome banner."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║         DevOps Automation Agent                              ║
║         Powered by Claude AI                                 ║
║         Version 1.0.0                                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")


def initialize_agent(config_path=None, env_path=None):
    """
    Initialize the DevOps Agent with configuration and tools.

    Args:
        config_path: Path to config YAML file
        env_path: Path to .env file

    Returns:
        Configured DevOpsAgent instance
    """
    try:
        # Load configuration
        config = ConfigManager(config_path=config_path, env_path=env_path)

        # Setup logging
        setup_logging(
            log_file=config.log_file,
            log_level=config.log_level,
            console_output=config.get('logging.console_output', True),
            json_format=config.get('logging.format') == 'json'
        )

        logger = get_logger(__name__)
        logger.info("Initializing DevOps Agent")

        # Create agent
        agent = DevOpsAgent(config)

        # Register command tools (always enabled)
        agent.register_tools_from_module(command_tools)
        console.print("[green][OK][/green] Command execution tools loaded")

        # Register AWS tools if enabled
        if config.aws_enabled:
            agent.register_tools_from_module(aws_tools)
            console.print("[green][OK][/green] AWS tools loaded")

        # Register Azure tools if enabled
        if config.azure_enabled:
            agent.register_tools_from_module(azure_tools)
            console.print("[green][OK][/green] Azure tools loaded")

        # Register GCP tools if enabled
        if config.gcp_enabled:
            agent.register_tools_from_module(gcp_tools)
            console.print("[green][OK][/green] GCP tools loaded")

        # Register Kubernetes tools if enabled
        if config.k8s_enabled:
            agent.register_tools_from_module(kubernetes_tools)
            console.print("[green][OK][/green] Kubernetes tools loaded")

        # Register Git tools
        agent.register_tools_from_module(git_tools)
        console.print("[green][OK][/green] Git tools loaded")

        # Register CI/CD tools if enabled
        if config.jenkins_enabled or config.github_enabled:
            agent.register_tools_from_module(cicd_tools)
            console.print("[green][OK][/green] CI/CD tools loaded")

        # Register Penetration Testing tools if enabled
        if config.get('pentest.enabled', False):
            agent.register_tools_from_module(pentest_tools)
            console.print("[green][OK][/green] Penetration testing tools loaded")
            console.print("[yellow][!][/yellow]  Ensure you have authorization before scanning targets")

        logger.info(f"Agent initialized with {len(agent.list_available_tools())} tools")

        return agent

    except ValueError as e:
        console.print(f"[red]Configuration error:[/red] {str(e)}")
        console.print("\n[yellow]Please check your configuration:[/yellow]")
        console.print("1. Ensure .env file exists with ANTHROPIC_API_KEY")
        console.print("2. Copy config/config.yaml.example to config/config.yaml")
        console.print("3. Update configuration with your credentials")
        sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error initializing agent:[/red] {str(e)}")
        sys.exit(1)


@click.group()
@click.version_option(version='1.0.0')
def cli():
    """
    DevOps Automation Agent - AI-powered DevOps assistant

    Automate your DevOps workflows with natural language commands.
    """
    pass


@cli.command()
@click.option('--config', '-c', help='Path to config YAML file')
@click.option('--env', '-e', help='Path to .env file')
def interactive(config, env):
    """
    Start interactive chat session with the agent.

    Use natural language to perform DevOps tasks.
    Type 'exit' or 'quit' to end the session.
    """
    print_banner()
    console.print("\n[cyan]Initializing agent...[/cyan]\n")

    # Initialize agent
    agent = initialize_agent(config_path=config, env_path=env)

    console.print(f"\n[green]Agent ready![/green] Connected to {agent.config.claude_model}")
    console.print(f"[dim]Tools available: {len(agent.list_available_tools())}[/dim]\n")

    console.print("[yellow]Type your DevOps commands in natural language.[/yellow]")
    console.print("[dim]Examples:[/dim]")
    console.print("  • List all EC2 instances in us-east-1")
    console.print("  • Show me GCP compute instances")
    console.print("  • List Azure virtual machines")
    console.print("  • Show me pods in the default namespace")
    console.print("  • Get the last 50 lines of logs from pod nginx-123")
    console.print("  • What's the status of my Jenkins job 'deploy-prod'?")
    console.print("\n[dim]Type 'help' for more commands, 'exit' to quit[/dim]\n")

    # Interactive loop
    while True:
        try:
            # Get user input
            user_input = console.input("[bold cyan]You:[/bold cyan] ").strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() in ['exit', 'quit', 'q']:
                console.print("\n[yellow]Goodbye! 👋[/yellow]\n")
                break

            if user_input.lower() == 'help':
                show_help()
                continue

            if user_input.lower() == 'tools':
                show_tools(agent)
                continue

            if user_input.lower() == 'clear':
                agent.clear_conversation()
                console.print("[green]Conversation history cleared[/green]\n")
                continue

            if user_input.lower() == 'stats':
                show_stats(agent)
                continue

            # Process with agent
            console.print("\n[dim]Processing...[/dim]\n")

            response = agent.process_message(user_input)

            # Display response
            console.print(Panel(
                Markdown(response),
                title="[bold green]Agent Response[/bold green]",
                border_style="green"
            ))
            console.print()

        except KeyboardInterrupt:
            console.print("\n\n[yellow]Session interrupted. Type 'exit' to quit.[/yellow]\n")
            continue

        except Exception as e:
            console.print(f"\n[red]Error:[/red] {str(e)}\n")
            continue


@cli.command()
@click.argument('message')
@click.option('--config', '-c', help='Path to config YAML file')
@click.option('--env', '-e', help='Path to .env file')
def ask(message, config, env):
    """
    Ask a single question to the agent.

    Example: devops-agent ask "List all EC2 instances"
    """
    # Initialize agent
    agent = initialize_agent(config_path=config, env_path=env)

    console.print(f"\n[cyan]Question:[/cyan] {message}\n")

    # Process message
    response = agent.process_message(message)

    # Display response
    console.print(Panel(
        Markdown(response),
        title="[bold green]Agent Response[/bold green]",
        border_style="green"
    ))
    console.print()


@cli.command()
@click.option('--config', '-c', help='Path to config YAML file')
@click.option('--env', '-e', help='Path to .env file')
def tools(config, env):
    """List all available tools."""
    agent = initialize_agent(config_path=config, env_path=env)
    show_tools(agent)


@cli.command()
def init():
    """Initialize configuration files."""
    console.print("\n[cyan]Initializing DevOps Agent configuration...[/cyan]\n")

    # Check if files already exist
    config_file = 'config/config.yaml'
    env_file = 'config/.env'

    if os.path.exists(config_file):
        console.print(f"[yellow]Warning:[/yellow] {config_file} already exists")
    else:
        # Copy example files
        example_config = 'config/config.yaml.example'
        if os.path.exists(example_config):
            import shutil
            shutil.copy(example_config, config_file)
            console.print(f"[green]✓[/green] Created {config_file}")

    if os.path.exists(env_file):
        console.print(f"[yellow]Warning:[/yellow] {env_file} already exists")
    else:
        example_env = 'config/.env.example'
        if os.path.exists(example_env):
            import shutil
            shutil.copy(example_env, env_file)
            console.print(f"[green]✓[/green] Created {env_file}")

    console.print("\n[yellow]Next steps:[/yellow]")
    console.print("1. Edit config/.env and add your ANTHROPIC_API_KEY")
    console.print("2. Edit config/config.yaml with your cloud credentials")
    console.print("3. Run 'python main.py interactive' to start the agent\n")


def show_help():
    """Show help information."""
    help_text = """
## Available Commands

**Interactive Mode Commands:**
- `help` - Show this help message
- `tools` - List all available tools
- `clear` - Clear conversation history
- `stats` - Show session statistics
- `exit/quit` - Exit the session

**Example Queries:**

**AWS:**
- List all EC2 instances
- Show me S3 buckets
- Get CloudWatch logs from /aws/lambda/my-function

**Azure:**
- List all Azure virtual machines
- Show me Azure storage accounts
- Get details of VM named myvm in resource group myrg

**GCP:**
- List all GCP compute instances
- Show me Cloud Storage buckets
- List GKE clusters
- Show Cloud SQL instances

**Kubernetes:**
- Show pods in namespace default
- Get logs from pod nginx-abc123
- Scale deployment my-app to 3 replicas
- Restart deployment api-server

**Git:**
- Show status of repository /path/to/repo
- List pull requests for owner/repo
- Get commit history for /path/to/repo

**CI/CD:**
- Trigger Jenkins job deploy-prod
- Show GitHub workflow runs for owner/repo

**General:**
- Execute command: ls -la
- Run script: /path/to/script.sh
    """
    console.print(Panel(
        Markdown(help_text),
        title="[bold cyan]Help[/bold cyan]",
        border_style="cyan"
    ))


def show_tools(agent):
    """Show available tools."""
    table = Table(title="Available Tools", show_header=True, header_style="bold cyan")
    table.add_column("Tool Name", style="green")
    table.add_column("Category", style="yellow")

    tools_list = agent.list_available_tools()

    # Categorize tools
    categories = {
        'AWS': [t for t in tools_list if t.startswith(('get_ec2', 'list_s3', 'get_eks', 'get_cloudwatch', 'list_iam', 'manage_ec2', 'create_ec2', 'delete_ec2'))],
        'Azure': [t for t in tools_list if 'azure' in t.lower() or t.startswith(('list_virtual_machines', 'get_vm', 'manage_vm', 'list_storage_accounts'))],
        'GCP': [t for t in tools_list if t.startswith(('list_compute_instances', 'manage_compute', 'create_compute', 'delete_compute', 'list_storage_buckets', 'create_storage', 'delete_storage', 'list_gke', 'list_cloud_sql', 'create_cloud_sql', 'list_cloud_functions', 'get_gcp'))],
        'Kubernetes': [t for t in tools_list if t.startswith(('get_pods', 'get_deployments', 'scale_', 'restart_', 'get_services', 'get_nodes', 'describe_pod'))],
        'Git': [t for t in tools_list if 'repository' in t or 'pull_request' in t or 'commit' in t or 'branch' in t or 'diff' in t],
        'CI/CD': [t for t in tools_list if 'jenkins' in t or 'github_workflow' in t or 'gitlab' in t],
        'Command': [t for t in tools_list if 'execute' in t or 'command' in t]
    }

    for category, tools in categories.items():
        for tool in tools:
            table.add_row(tool, category)

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total tools: {len(tools_list)}[/dim]\n")


def show_stats(agent):
    """Show session statistics."""
    stats = agent.get_conversation_summary()

    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Messages", str(stats['total_messages']))
    table.add_row("User Messages", str(stats['user_messages']))
    table.add_row("Agent Messages", str(stats['assistant_messages']))
    table.add_row("Session Duration", f"{stats['session_duration_seconds']:.1f}s")
    table.add_row("Available Tools", str(len(agent.list_available_tools())))

    console.print()
    console.print(Panel(table, title="[bold cyan]Session Statistics[/bold cyan]", border_style="cyan"))
    console.print()


if __name__ == '__main__':
    cli()
