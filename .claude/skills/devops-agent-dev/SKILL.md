---
name: devops-agent-dev
description: Development guide for the DevOps Agent Flask application. Use when adding features, modifying tools, updating the UI, or making changes to the DevOps Agent codebase.
---

# DevOps Agent Development Guide

## Overview

This skill provides comprehensive guidance for developing and extending the DevOps Agent Flask application with Claude AI integration.

## Project Architecture

### Directory Structure

```
devops-agent/
├── app.py                    # Main Flask application
├── models.py                 # SQLAlchemy database models
├── main.py                   # CLI entry point (legacy)
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (secrets)
├── src/                      # Source code
│   ├── agent/               # Agent framework
│   │   ├── core.py          # DevOpsAgent class
│   │   ├── conversation.py  # Conversation management
│   │   └── safety.py        # Safety validations
│   ├── config/              # Configuration management
│   │   └── __init__.py      # ConfigManager
│   ├── tools/               # Tool integrations
│   │   ├── aws_tools.py     # AWS integrations
│   │   ├── gcp_tools.py     # GCP integrations
│   │   ├── kubernetes_tools.py  # K8s tools
│   │   ├── git_tools.py     # Git operations
│   │   ├── cicd_tools.py    # CI/CD integrations
│   │   ├── command_tools.py # Shell commands
│   │   └── pentest_tools.py # Security testing
│   └── utils/               # Utilities
│       └── logging.py       # Logging setup
├── services/                 # Business logic services
│   └── demo_mode.py         # Demo mode service
├── templates/               # Jinja2 HTML templates
│   ├── base.html           # Base template
│   ├── index.html          # Home page
│   ├── chat.html           # Chat interface
│   └── ...
├── static/                  # Static assets
│   ├── css/                # Stylesheets
│   ├── js/                 # JavaScript
│   └── img/                # Images
├── tests/                   # Test files
├── config/                  # Config files (legacy)
├── logs/                    # Application logs
└── instance/                # SQLite database

```

### Key Components

**app.py** - Main Flask application with:
- Route definitions
- Authentication (Flask-Login)
- Security (CSRF, rate limiting)
- Stripe integration
- Database initialization

**models.py** - Database models:
- User, ChatMessage, Conversation
- SubscriptionTier, UserSubscription
- CommandTemplate, ResponseFeedback
- InfrastructureResource, CostOptimization, SecurityFinding, Alert

**src/agent/core.py** - DevOpsAgent class:
- Claude API integration
- Tool execution
- Conversation management

**src/tools/** - Tool implementations:
- Each file implements specific tool category
- Tools use Anthropic's tool use format

## Development Workflow

### Phase 1: Setup Development Environment

```bash
# 1. Clone repository
cd devops-agent

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template
cp .env.example .env

# 5. Configure .env with your keys
# Edit .env and add:
# - ANTHROPIC_API_KEY
# - AWS credentials (if needed)
# - Stripe keys (if testing payments)

# 6. Initialize database
python -c "from models import db; from app import app; app.app_context().push(); db.create_all()"

# 7. Run development server
python app.py
```

### Phase 2: Adding New Features

#### Adding a New Tool

**1. Create Tool Function**

Add to appropriate file in `src/tools/` (e.g., `aws_tools.py`):

```python
def new_aws_tool(param1: str, param2: str) -> Dict[str, Any]:
    """
    Description of what this tool does.

    Args:
        param1: Description
        param2: Description

    Returns:
        Dictionary with result data
    """
    try:
        # Implement tool logic
        import boto3
        client = boto3.client('service')
        result = client.some_operation(
            Param1=param1,
            Param2=param2
        )

        return {
            'success': True,
            'data': result,
            'message': 'Operation completed successfully'
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Operation failed'
        }
```

**2. Register Tool**

Add tool definition to the module's `get_tools()` function:

```python
def get_tools():
    """Return list of AWS tools"""
    return [
        {
            'name': 'new_aws_tool',
            'description': 'Clear description for Claude about when to use this tool',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'param1': {
                        'type': 'string',
                        'description': 'Description of param1'
                    },
                    'param2': {
                        'type': 'string',
                        'description': 'Description of param2'
                    }
                },
                'required': ['param1']
            },
            'handler': new_aws_tool
        },
        # ... other tools
    ]
```

**3. Update app.py**

Ensure the tool module is imported and included:

```python
from src.tools import aws_tools

# In the route that uses tools:
tools = []
tools.extend(aws_tools.get_tools())
# Pass tools to Claude
```

**4. Test the Tool**

```bash
# Start the app
python app.py

# In browser:
# - Login
# - Start chat
# - Ask Claude to use your new tool

# Or test directly:
python -c "from src.tools.aws_tools import new_aws_tool; print(new_aws_tool('test', 'value'))"
```

#### Adding a New Database Model

**1. Define Model in models.py**

```python
class NewFeature(db.Model):
    __tablename__ = 'new_features'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship('User', backref='new_features')

    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat()
        }
```

**2. Create Migration Script**

```python
# migrate_add_new_feature.py
from models import db, NewFeature
from app import app

def migrate():
    with app.app_context():
        db.create_all()
        print("✅ Created new_features table")

if __name__ == '__main__':
    migrate()
```

**3. Run Migration**

```bash
python migrate_add_new_feature.py
```

**4. Add Routes in app.py**

```python
@app.route('/api/new-features', methods=['POST'])
@login_required
def create_new_feature():
    data = request.get_json()
    feature = NewFeature(
        name=data['name'],
        description=data.get('description'),
        user_id=current_user.id
    )
    db.session.add(feature)
    db.session.commit()
    return jsonify(feature.to_dict()), 201

@app.route('/api/new-features', methods=['GET'])
@login_required
def list_new_features():
    features = NewFeature.query.filter_by(user_id=current_user.id).all()
    return jsonify([f.to_dict() for f in features])
```

#### Adding a New Page

**1. Create Template**

Create `templates/new_page.html`:

```html
{% extends "base.html" %}

{% block title %}New Page{% endblock %}

{% block content %}
<div class="container mt-5">
    <h1>New Page</h1>
    <p>Content goes here</p>
</div>
{% endblock %}

{% block scripts %}
<script>
    // Page-specific JavaScript
    console.log('New page loaded');
</script>
{% endblock %}
```

**2. Add Route**

In `app.py`:

```python
@app.route('/new-page')
@login_required  # If authentication required
def new_page():
    return render_template('new_page.html')
```

**3. Add Navigation Link**

In `templates/base.html` (if navigation exists):

```html
<a href="{{ url_for('new_page') }}" class="nav-link">New Page</a>
```

### Phase 3: Testing Changes

#### Run Unit Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_agent.py -v

# With coverage
pytest --cov=src tests/
```

#### Manual Testing

```bash
# 1. Start development server
python app.py

# 2. Open browser
# http://localhost:5000

# 3. Test functionality
# - Sign up new user
# - Login
# - Test new feature
# - Check database
```

#### Integration Testing

```bash
# Run integration test suite
python test_integration.py

# Test specific features
python test_new_features.py
python test_team_features.py
```

### Phase 4: Code Quality

#### Linting

```bash
# Install linters
pip install pylint flake8 black

# Run pylint
pylint app.py src/

# Run flake8
flake8 app.py src/

# Format with black
black app.py src/
```

#### Type Checking

```bash
# Install mypy
pip install mypy

# Run type checker
mypy app.py src/
```

## Common Development Tasks

### Update Requirements

```bash
# After installing new package
pip freeze > requirements.txt

# Or manually add to requirements.txt
echo "new-package==1.0.0" >> requirements.txt
```

### Database Operations

```bash
# Create all tables
python -c "from models import db; from app import app; app.app_context().push(); db.create_all()"

# Drop all tables (DANGER!)
python -c "from models import db; from app import app; app.app_context().push(); db.drop_all()"

# Query database
python -c "from models import User; from app import app; app.app_context().push(); print(User.query.all())"

# Create test user
python -c "
from models import db, User
from app import app
app.app_context().push()
user = User(email='test@example.com', username='testuser')
user.set_password('password123')
db.session.add(user)
db.session.commit()
print('User created')
"
```

### View Logs

```bash
# Application logs
tail -f logs/agent.log

# Security logs
tail -f logs/security.log

# Filter for errors
grep ERROR logs/agent.log

# Filter for specific user
grep "user_id=5" logs/agent.log
```

### Environment Management

```bash
# Check environment variables
python -c "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'Not set'))"

# Load .env in Python
from dotenv import load_dotenv
load_dotenv()
```

## Configuration

### Development vs Production

```python
# In app.py
if os.environ.get('FLASK_ENV') == 'production':
    app.config['DEBUG'] = False
    app.config['TESTING'] = False
    # Use PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
else:
    app.config['DEBUG'] = True
    # Use SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/devops.db'
```

### Feature Flags

```python
# In .env
FEATURE_TEAM_COLLABORATION=true
FEATURE_DEMO_MODE=false

# In app.py
TEAM_COLLABORATION_ENABLED = os.environ.get('FEATURE_TEAM_COLLABORATION', 'false').lower() == 'true'

if TEAM_COLLABORATION_ENABLED:
    # Enable team features
    pass
```

## Debugging Tips

### Debug Flask Routes

```python
# Add debug print statements
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    print(f"DEBUG: Received data: {data}")  # Debug
    # ... rest of code
```

### Debug Database Queries

```python
# Enable SQL query logging
app.config['SQLALCHEMY_ECHO'] = True

# This will print all SQL queries to console
```

### Debug Claude API Calls

```python
# In src/agent/core.py
def execute_chat(self, message: str):
    print(f"DEBUG: Sending to Claude: {message}")
    response = self.client.messages.create(...)
    print(f"DEBUG: Claude response: {response}")
    return response
```

### Use Interactive Python Shell

```bash
# Start Python shell with app context
python -i -c "from app import app; from models import *; ctx = app.app_context(); ctx.push()"

# Now you can run queries
>>> User.query.all()
>>> Conversation.query.filter_by(user_id=1).all()
```

## Best Practices

1. **Always use virtual environment** - Keeps dependencies isolated
2. **Never commit .env file** - Contains secrets
3. **Test before deploying** - Run test suite
4. **Use type hints** - Improves code clarity
5. **Write docstrings** - Document functions and classes
6. **Handle errors gracefully** - Use try/except blocks
7. **Log important events** - Use logging module
8. **Validate user input** - Never trust user data
9. **Use database transactions** - Wrap operations in try/except with rollback
10. **Keep tools simple** - Each tool should do one thing well

## Useful Code Snippets

### Get Current User in Route

```python
from flask_login import current_user, login_required

@app.route('/profile')
@login_required
def profile():
    user = current_user
    return render_template('profile.html', user=user)
```

### Execute Tool from Agent

```python
from src.agent import DevOpsAgent

agent = DevOpsAgent(api_key=os.environ['ANTHROPIC_API_KEY'])
response = agent.execute_chat("List my EC2 instances")
print(response)
```

### Query with Pagination

```python
page = request.args.get('page', 1, type=int)
per_page = 20
conversations = Conversation.query.filter_by(user_id=current_user.id)\
    .order_by(Conversation.updated_at.desc())\
    .paginate(page=page, per_page=per_page)
```

### Flash Messages

```python
from flask import flash

flash('Operation successful!', 'success')
flash('Error occurred', 'error')
flash('Warning message', 'warning')
```

## Quick Reference

### File Locations

- Main app: `app.py`
- Models: `models.py`
- AWS tools: `src/tools/aws_tools.py`
- GCP tools: `src/tools/gcp_tools.py`
- K8s tools: `src/tools/kubernetes_tools.py`
- Templates: `templates/`
- Static files: `static/`
- Logs: `logs/`
- Database: `instance/devops.db`

### Important Environment Variables

- `ANTHROPIC_API_KEY` - Claude API key (required)
- `SECRET_KEY` - Flask secret key (required)
- `DATABASE_URL` - Database connection string
- `AWS_ACCESS_KEY_ID` - AWS credentials
- `AWS_SECRET_ACCESS_KEY` - AWS credentials
- `GOOGLE_APPLICATION_CREDENTIALS` - GCP service account
- `STRIPE_SECRET_KEY` - Stripe payments
- `FLASK_ENV` - development or production

### Common Commands

```bash
# Start app
python app.py

# Run tests
pytest tests/ -v

# Create tables
python -c "from models import db; from app import app; app.app_context().push(); db.create_all()"

# Run migration
python migrate_<name>.py

# View logs
tail -f logs/agent.log

# Format code
black app.py src/

# Check code
pylint app.py src/
```
