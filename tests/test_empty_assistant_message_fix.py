"""Regression test for a production incident (CLAUDE_RUNBOOK.md, 2026-08-25):

Kimi's API rejected chat requests with:
  "Invalid request: the message at position 3 with role 'assistant' must not
   be empty"

Root cause: a prior turn's assistant response was persisted to ChatMessage.content
as an empty string (e.g. a tool-only reply with no closing text), and reloading
that turn's conversation_history replayed a plain {'role': 'assistant',
'content': ''} message into the Kimi/Claude request — no tool_calls attached,
since history round-trips only ever carry final text, not the tool-call
scaffolding. Kimi rejects a non-tool-call assistant message with empty content.

This test exercises the retroactive-protection half of the fix: an empty
assistant entry already sitting in conversation_history (from before the fix)
must be dropped when rebuilding the in-memory conversation, not replayed.
"""
from unittest.mock import MagicMock, patch


def _make_agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


def _poisoned_history():
    """A conversation_history list containing an empty-content assistant turn,
    the exact shape a pre-fix ChatMessage row round-trips as."""
    return [
        {'role': 'user', 'content': 'list my ec2 instances'},
        {'role': 'assistant', 'content': ''},
        {'role': 'user', 'content': 'now check s3'},
    ]


class TestEmptyAssistantHistoryDropped:
    def test_isolated_skips_empty_assistant_history_entry(self):
        captured = []

        def fake_call_claude(self_inner, *args, **kwargs):
            captured.extend(self_inner.conversation.get_messages_for_api())
            return "mocked response"

        agent = _make_agent()
        with patch.object(type(agent), '_call_claude_api', fake_call_claude), \
             patch.object(type(agent), '_set_cloud_user_context'), \
             patch.object(type(agent), '_clear_cloud_user_context'):
            agent.process_message_isolated(
                user_message='final message',
                conversation_history=_poisoned_history(),
            )

        assistant_msgs = [m for m in captured if m['role'] == 'assistant']
        assert assistant_msgs == [], (
            "empty-content assistant history entry must be dropped, not replayed"
        )

    def test_streaming_skips_empty_assistant_history_entry(self):
        captured = []

        def fake_call_kimi_streaming(self_inner, *args, **kwargs):
            captured.extend(self_inner.conversation.get_messages_for_api())
            yield "mocked chunk"

        agent = _make_agent()
        with patch.object(type(agent), '_call_kimi_api_streaming', fake_call_kimi_streaming), \
             patch.object(type(agent), '_set_cloud_user_context'), \
             patch.object(type(agent), '_clear_cloud_user_context'):
            list(agent.process_message_streaming(
                user_message='final message',
                conversation_history=_poisoned_history(),
                provider='kimi',
            ))

        assistant_msgs = [m for m in captured if m['role'] == 'assistant']
        assert assistant_msgs == [], (
            "empty-content assistant history entry must be dropped, not replayed"
        )

    def test_non_empty_assistant_history_entry_still_included(self):
        """Guard against an overly broad fix that drops legitimate turns too."""
        captured = []

        def fake_call_claude(self_inner, *args, **kwargs):
            captured.extend(self_inner.conversation.get_messages_for_api())
            return "mocked response"

        history = [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi there'},
        ]

        agent = _make_agent()
        with patch.object(type(agent), '_call_claude_api', fake_call_claude), \
             patch.object(type(agent), '_set_cloud_user_context'), \
             patch.object(type(agent), '_clear_cloud_user_context'):
            agent.process_message_isolated(
                user_message='follow up',
                conversation_history=history,
            )

        assistant_msgs = [m for m in captured if m['role'] == 'assistant']
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]['content'] == [{'type': 'text', 'text': 'hi there'}]
