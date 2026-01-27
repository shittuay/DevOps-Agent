# DevOps Agent - Claude Context

> This file provides persistent context for Claude Code sessions.

## Project Overview

**DevOps Agent** is a Flask-based web application that provides an AI-powered DevOps automation assistant. Users interact via chat to manage cloud infrastructure (AWS, Azure, GCP), Kubernetes clusters, and CI/CD pipelines.

## Tech Stack

- **Backend:** Flask + SQLAlchemy (SQLite)
- **Frontend:** Jinja2 templates + vanilla JavaScript
- **AI:** Anthropic Claude API
- **Auth:** Flask-Login with bcrypt password hashing
- **Cloud:** boto3 (AWS), azure-sdk, google-cloud

## Key Architecture

```
app.py              # Flask application entry point
models.py           # SQLAlchemy models (User, Conversation, ChatMessage, etc.)
src/
  agent/
    core.py         # DevOpsAgent - main AI orchestration
    safety.py       # SafetyValidator - command validation
    conversation.py # ConversationManager - message handling
  tools/
    aws_tools.py    # AWS operations (EC2, S3, RDS, etc.)
    kubernetes_tools.py
    git_tools.py
  config/
    config_manager.py
services/
  infrastructure_sync.py  # Per-user cloud resource sync
  credential_encryption.py # Fernet encryption for credentials
templates/
  chat.html, settings.html, etc.
```

## Critical Security Patterns

### User Isolation (NEVER bypass)
- ALL database queries MUST filter by `user_id=current_user.id`
- Conversations, messages, credentials are per-user
- Cloud operations use per-user encrypted credentials

### Credential Storage
- `UserCloudCredential` model stores encrypted credentials
- Uses Fernet (AES-128) encryption via `credential_encryption.py`
- Key derived from `CREDENTIAL_ENCRYPTION_KEY` or `SECRET_KEY`

### Authentication
- `@login_required` decorator on all API routes
- Email verification required for new accounts
- Account lockout after 5 failed attempts

## Common Tasks

### Adding a New Tool
1. Create handler in `src/tools/`
2. Export via `get_tools()` function
3. Register in agent: `agent.register_tools_from_module(module)`

### Adding a New Model
1. Define in `models.py`
2. Run migration: `python migrate_*.py`
3. Add API routes in `app.py`

### Running the App
```bash
python app.py  # Web UI at http://localhost:5000
python main.py interactive  # CLI mode
```

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Claude API key
- `SECRET_KEY` - Flask session secret

Optional:
- `CREDENTIAL_ENCRYPTION_KEY` - For credential encryption
- `DATABASE_URL` - Database connection string

## Current User Context

Each user has isolated:
- Chat conversations and history
- Cloud credentials (AWS/Azure/GCP)
- Infrastructure resources
- Cost optimizations and alerts
- Subscriptions and credits

## Testing

```bash
pytest -q                    # Run all tests
python -m pytest tests/ -v   # Verbose
```

## Skills Available

Use `/skill-name` or mention the skill:
- `/flask-test` - Run tests
- `/db-migrate` - Database migrations
- `/deploy-verify` - Deployment verification
- `/cloud-debug` - Cloud troubleshooting
- `/devops-agent-dev` - Development guide
- `/secrets-mgmt` - Secrets management

## Code Style

- No emojis unless requested
- Minimal comments (self-documenting code)
- Type hints for function signatures
- SQLAlchemy for all database operations
