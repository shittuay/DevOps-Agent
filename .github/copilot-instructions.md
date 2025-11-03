## Purpose

This file gives targeted, actionable guidance for AI coding assistants working on the DevOps Automation Agent repository so they can be productive immediately.

## Quick summary (what to know first)

- Two entry points: CLI (`main.py`) and Web UI (`app.py`). Use `python main.py interactive` for local CLI testing and `python app.py` to run the web UI on http://localhost:5000.
- Configuration is provided via `config/config.yaml` and sensitive values live in `config/.env`. The `ConfigManager` loads both (see `src/config/config_manager.py`) and will raise if `ANTHROPIC_API_KEY` is missing.
- Tools are modular under `src/tools/*.py`. Each module should expose a get_tools() collection (the agent checks `hasattr(module, 'get_tools')`) and tool entries are registered by `DevOpsAgent.register_tools_from_module` (see `src/agent/core.py`).

## Architecture notes (essential cross-file context)

- Core orchestration: `src/agent/core.py` (DevOpsAgent) - creates an Anthropic client, manages conversation flow, registers tools, handles tool_use responses, and enforces safety via `SafetyValidator`.
- Conversation & API format: `src/agent/conversation.py` - ConversationManager converts messages into the block format expected by Claude, and stores tool results back into the conversation.
- Safety: `src/agent/safety.py` - contains pattern lists and `validate_tool_call`/`validate_command` logic. Dangerous patterns are configured in `config/config.yaml`.
- Tool modules: `src/tools/*` (e.g., `aws_tools.py`, `kubernetes_tools.py`, `git_tools.py`) — each should return tool definitions with keys: `name`, `description`, `input_schema`, `handler`.
- Web layer: `app.py` — wraps the same agent for a Flask UI, uses `models.py` (SQLite via Flask-SQLAlchemy) and `templates/` for pages. `app.py` initializes DB automatically on start.

## Important developer workflows & commands

- Setup (Windows PowerShell):
  - python -m venv venv; venv\Scripts\activate; pip install -r requirements.txt
  - Initialize config: `python main.py init` (copies examples to `config/`)
  - Start CLI: `python main.py interactive`
  - Single question: `python main.py ask "List all EC2 instances"`
  - Start web UI: `python app.py` (opens at http://localhost:5000)

- Tests & linters (project includes pytest, black, mypy, pylint):
  - Run tests: `pytest -q`
  - Lint: `pylint src` (project uses `pylint` in requirements)
  - Formatting: `black .`

## Project-specific patterns and conventions

- Tool registration pattern: modules export `get_tools()` returning a list of tool dicts. Agent consumes each entry with `register_tool(name, description, input_schema, handler)` (see `register_tools_from_module` in `src/agent/core.py`). When adding tools, match this shape.
- Tool handlers should be plain callables that accept keyword arguments conforming to the declared `input_schema` and return JSON-serializable results. DevOpsAgent sanitizes and stringifies results before adding them to conversation history.
- Safety-first: heavy emphasis on pattern-based blocking and confirmation. Dangerous commands live in `config/config.yaml` under `safety.dangerous_commands` and are checked by `SafetyValidator`. If a change affects destructive logic, update both `config/config.yaml.example` and `src/agent/safety.py` tests.
- Config lookup: prefer `ConfigManager` properties (e.g., `config.claude_model`, `config.aws_enabled`) rather than reading env vars directly.
- Conversation format: assistant messages are lists of content blocks (see `ConversationManager.add_assistant_message`). Tool results must be added back to the conversation via `conversation.add_tool_result(tool_use_id, result)`.

## Integration & external dependencies

- Anthropic / Claude: created in `DevOpsAgent.__init__` using `anthropic.Anthropic(api_key=config.anthropic_api_key)`; any change to how messages are sent should preserve `messages` and `tools` shapes used in `_call_claude_api`.
- AWS / K8s / Git / CI providers: the code toggles tool registration based on config flags (`aws_enabled`, `k8s_enabled`, `jenkins_enabled`, `github_enabled`) from `ConfigManager`.
- Web UI auth: Flask-Login + SQLite (models in `models.py`). On first run `app.py` will call `db.create_all()`.

## When making edits, prefer low-risk, testable changes

- Add unit tests under `tests/` for: tool registration (module exposes get_tools), safety matching, and ConfigManager get/validation. The repo already lists `pytest` in requirements.
- If you change any default dangerous patterns or behavior in `SafetyValidator`, add or update tests that ensure high-risk patterns still result in `requires_confirmation` or `is_safe=False` as intended.

## Examples to copy-paste (how to register a tool)

See pattern in `DevOpsAgent.register_tool`:

1) Tool definition (module-level):

  def get_tools():
      return [
          {
              'name': 'execute_command',
              'description': 'Run a shell command',
              'input_schema': {'command': {'type': 'string'}},
              'handler': execute_command_handler
          }
      ]

2) Agent registration (already used in `main.py`/`app.py`):
  agent.register_tools_from_module(command_tools)

## Files to check first when debugging feature X

- Agent tool execution / failures: `src/agent/core.py`, `src/agent/safety.py`, `src/agent/conversation.py`
- Config or missing API key issues: `src/config/config_manager.py`, `config/config.yaml`, `config/.env`
- Web UI issues: `app.py`, `templates/` and `models.py` (DB auth)

---
If anything here is unclear or you want extra examples (unit tests, example tool), tell me which area to expand and I'll iterate.
