"""
Flask Web Interface for DevOps Agent with API Key Configuration
"""
import os
import sys
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
import secrets

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import ConfigManager
from src.agent import DevOpsAgent
from src.utils import setup_logging, get_logger
from src.tools import (
    command_tools,
    aws_tools,
    kubernetes_tools,
    git_tools,
    cicd_tools
)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Global agent instance
agent = None
config_manager = None

def check_api_key_configured():
    """Check if API key is configured in .env file."""
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return False

    with open(env_path, 'r') as f:
        content = f.read()
        return 'ANTHROPIC_API_KEY=' in content and 'your_anthropic_api_key_here' not in content

def save_api_key(api_key):
    """Save API key to .env file."""
    env_path = os.path.join('config', '.env')

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add ANTHROPIC_API_KEY
    found = False
    for i, line in enumerate(lines):
        if line.startswith('ANTHROPIC_API_KEY='):
            lines[i] = f'ANTHROPIC_API_KEY={api_key}\n'
            found = True
            break

    if not found:
        lines.insert(0, f'ANTHROPIC_API_KEY={api_key}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def save_aws_credentials(access_key, secret_key, region='us-east-1'):
    """Save AWS credentials to .env file."""
    env_path = os.path.join('config', '.env')

    # Read existing content
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add AWS credentials
    credentials = {
        'AWS_ACCESS_KEY_ID': access_key,
        'AWS_SECRET_ACCESS_KEY': secret_key,
        'AWS_DEFAULT_REGION': region
    }

    for key, value in credentials.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break

        if not found:
            lines.append(f'{key}={value}\n')

    # Write back
    with open(env_path, 'w') as f:
        f.writelines(lines)

def get_aws_config_status():
    """Check if AWS credentials are configured."""
    env_path = os.path.join('config', '.env')
    if not os.path.exists(env_path):
        return {
            'configured': False,
            'access_key': None,
            'region': None
        }

    with open(env_path, 'r') as f:
        content = f.read()

    # Check if AWS credentials exist and are not placeholder values
    has_access_key = 'AWS_ACCESS_KEY_ID=' in content and 'your_aws_access_key' not in content

    # Extract region if available
    region = None
    for line in content.split('\n'):
        if line.startswith('AWS_DEFAULT_REGION='):
            region = line.split('=', 1)[1].strip()
            break

    # Extract masked access key for display
    access_key_masked = None
    if has_access_key:
        for line in content.split('\n'):
            if line.startswith('AWS_ACCESS_KEY_ID='):
                key = line.split('=', 1)[1].strip()
                if key and len(key) > 8:
                    access_key_masked = key[:4] + '****' + key[-4:]
                break

    return {
        'configured': has_access_key,
        'access_key': access_key_masked,
        'region': region or 'us-east-1'
    }

def initialize_agent():
    """Initialize the DevOps Agent."""
    global agent, config_manager

    try:
        # Load configuration
        config_manager = ConfigManager()

        # Setup logging
        setup_logging(
            log_file=config_manager.log_file,
            log_level=config_manager.log_level,
            console_output=False,  # Disable console output for web
            json_format=config_manager.get('logging.format') == 'json'
        )

        logger = get_logger(__name__)
        logger.info("Initializing DevOps Agent for web interface")

        # Create agent
        agent = DevOpsAgent(config_manager)

        # Register tools
        agent.register_tools_from_module(command_tools)
        if config_manager.aws_enabled:
            agent.register_tools_from_module(aws_tools)
        if config_manager.k8s_enabled:
            agent.register_tools_from_module(kubernetes_tools)
        agent.register_tools_from_module(git_tools)
        if config_manager.jenkins_enabled or config_manager.github_enabled:
            agent.register_tools_from_module(cicd_tools)

        logger.info(f"Agent initialized with {len(agent.list_available_tools())} tools")

        return True, None

    except Exception as e:
        return False, str(e)


@app.route('/')
def index():
    """Render the main chat interface or setup page."""
    # Check if API key is configured
    if not check_api_key_configured():
        return render_template('setup.html')

    # Initialize session if needed
    if 'conversation_id' not in session:
        session['conversation_id'] = secrets.token_hex(8)

    return render_template('index.html')


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """Setup page for API key configuration."""
    if request.method == 'POST':
        data = request.get_json()
        api_key = data.get('api_key', '').strip()

        if not api_key:
            return jsonify({'error': 'API key is required'}), 400

        if not api_key.startswith('sk-ant-'):
            return jsonify({'error': 'Invalid Anthropic API key format'}), 400

        try:
            # Save API key
            save_api_key(api_key)

            # Try to initialize agent
            success, error = initialize_agent()

            if not success:
                return jsonify({'error': f'Failed to initialize agent: {error}'}), 500

            return jsonify({'success': True, 'message': 'API key configured successfully'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return render_template('setup.html')


@app.route('/settings')
def settings():
    """Settings page for AWS and other configurations."""
    return render_template('settings.html')


@app.route('/api/aws-config', methods=['GET', 'POST'])
def aws_config():
    """Handle AWS configuration."""
    if request.method == 'GET':
        return jsonify(get_aws_config_status())

    # POST - Save AWS credentials
    try:
        data = request.get_json()
        access_key = data.get('access_key', '').strip()
        secret_key = data.get('secret_key', '').strip()
        region = data.get('region', 'us-east-1').strip()

        if not access_key or not secret_key:
            return jsonify({'error': 'AWS Access Key and Secret Key are required'}), 400

        # Basic validation
        if not access_key.startswith('AKIA'):
            return jsonify({'error': 'Invalid AWS Access Key format (should start with AKIA)'}), 400

        # Save credentials
        save_aws_credentials(access_key, secret_key, region)

        # Reload agent to use new credentials
        global agent, config_manager
        if agent is not None:
            success, error = initialize_agent()
            if not success:
                return jsonify({'error': f'Credentials saved but agent reload failed: {error}'}), 500

        return jsonify({
            'success': True,
            'message': 'AWS credentials configured successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat', methods=['POST'])
def chat():
    """Handle chat messages."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized. Please configure API key.'}), 503

    try:
        data = request.get_json()
        message = data.get('message', '').strip()

        if not message:
            return jsonify({'error': 'Empty message'}), 400

        # Process message with agent
        response = agent.process_message(message)

        return jsonify({
            'response': response,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger = get_logger(__name__)
        logger.error(f"Error processing chat message: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/tools', methods=['GET'])
def get_tools():
    """Get list of available tools."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        tools = agent.list_available_tools()

        # Categorize tools
        categorized = {
            'Command Execution': [],
            'AWS': [],
            'Kubernetes': [],
            'Git': [],
            'CI/CD': []
        }

        for tool in tools:
            if tool.startswith(('execute_command', 'execute_script')):
                categorized['Command Execution'].append(tool)
            elif tool.startswith(('get_ec2', 'list_s3', 'get_eks', 'get_cloudwatch', 'list_iam', 'manage_ec2')):
                categorized['AWS'].append(tool)
            elif tool.startswith(('get_pods', 'get_deployments', 'scale_', 'restart_', 'get_services', 'get_nodes', 'describe_pod')):
                categorized['Kubernetes'].append(tool)
            elif 'repository' in tool or 'pull_request' in tool or 'commit' in tool or 'branch' in tool or 'diff' in tool:
                categorized['Git'].append(tool)
            elif 'jenkins' in tool or 'github_workflow' in tool:
                categorized['CI/CD'].append(tool)

        return jsonify({
            'total': len(tools),
            'categories': categorized
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/clear', methods=['POST'])
def clear_conversation():
    """Clear conversation history."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        agent.clear_conversation()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get conversation statistics."""
    if agent is None:
        return jsonify({'error': 'Agent not initialized'}), 503

    try:
        stats = agent.get_conversation_summary()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'agent_initialized': agent is not None,
        'api_key_configured': check_api_key_configured(),
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    print("=" * 60)
    print("DevOps Automation Agent - Web Interface")
    print("=" * 60)

    # Check if API key is already configured
    if check_api_key_configured():
        print("\nInitializing agent...")
        success, error = initialize_agent()

        if success:
            print(f"\nAgent initialized with {len(agent.list_available_tools())} tools")
        else:
            print(f"\nWarning: Failed to initialize agent: {error}")
            print("You can configure the API key through the web interface")
    else:
        print("\nAPI key not configured yet.")
        print("Access the web interface to set up your Anthropic API key.")

    print("\n" + "=" * 60)
    print("Starting web server...")
    print("=" * 60)
    print("\nAccess the agent at:")
    print("  http://localhost:5000")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
