"""The Kimi tool loop must re-send the tool list every iteration so tools
recovered by ``search_tools`` mid-turn actually reach the model."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        agent = DevOpsAgent(cfg)
    agent.register_tool(
        name='list_dynamodb_tables', description='List DynamoDB tables',
        input_schema={'type': 'object', 'properties': {}}, handler=lambda **kw: {'success': True, 'tables': []},
    )
    agent.register_tool(
        name='list_ec2_instances', description='List EC2 instances',
        input_schema={'type': 'object', 'properties': {}}, handler=lambda **kw: {'success': True},
    )
    return agent


def _tool_call_response(name, args):
    tc = SimpleNamespace(id='call_1', function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = ''
    msg.reasoning_content = None
    msg.model_dump.return_value = {'role': 'assistant', 'content': '', 'tool_calls': []}
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason='tool_calls')], usage=None)


def _text_response(text):
    msg = SimpleNamespace(tool_calls=None, content=text, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason='stop')], usage=None)


def test_search_tools_result_reaches_kimi_on_next_iteration(monkeypatch):
    from src.agent.conversation import ConversationManager
    monkeypatch.setenv('MOONSHOT_API_KEY', 'test-key')
    agent = _make_agent()
    agent.conversation = ConversationManager()
    agent.conversation.add_user_message('list my dynamodb tables')
    # Progressive loading narrowed the set to EC2 only (plus the search hatch).
    agent._tools_override = [
        td for td in agent.tool_definitions if td['name'] in ('list_ec2_instances', 'search_tools')
    ]

    sent_tool_names = []

    def fake_create(**params):
        sent_tool_names.append({t['function']['name'] for t in params.get('tools', [])})
        if len(sent_tool_names) == 1:
            return _tool_call_response('search_tools', {'query': 'dynamodb tables'})
        return _text_response('done')

    client = MagicMock()
    client.chat.completions.create.side_effect = fake_create
    with patch('openai.OpenAI', return_value=client):
        out = agent._call_kimi_api()

    assert out == 'done'
    assert len(sent_tool_names) == 2
    assert 'list_dynamodb_tables' not in sent_tool_names[0]
    assert 'list_dynamodb_tables' in sent_tool_names[1], (
        "tool recovered by search_tools was not sent to Kimi on the next iteration"
    )
