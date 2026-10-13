"""AI Coach and quiz generation on the learning pages.

Both used to hardcode moonshot-v1-8k / moonshot-v1-32k, which are not in Moonshot's current
model list, so every request failed and the raw provider error was printed on the page. These
tests pin: the app-wide default model is used, an unavailable model falls back, provider
errors become a readable message (never the raw text), a reply with no answer text is reported
instead of rendering a blank box, and quiz JSON wrapped in prose or code fences still parses.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from routes import curriculum
from services.model_router import DEFAULT_KIMI_MODEL

MODULE_ID = 'linux-cli'
GOOD_QUIZ = [{'question': f'Q{i}?', 'options': ['a', 'b', 'c', 'd'], 'correct': i % 4,
              'explanation': 'because'} for i in range(5)]


def _status_error(cls, status, message='boom'):
    request = httpx.Request('POST', 'https://api.moonshot.ai/v1/chat/completions')
    return cls(message, response=httpx.Response(status, request=request), body=None)


def _chunk(content=None, reasoning=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


@pytest.fixture
def no_env_override(monkeypatch):
    monkeypatch.delenv('CURRICULUM_MODEL', raising=False)
    monkeypatch.delenv('KIMI_MODEL', raising=False)


@pytest.fixture
def coach(authenticated_client, no_env_override):
    """Patches the API key, the guardrail screen and the OpenAI client; yields the fake client."""
    from src.agent.guardrails import GuardrailResult

    fake = MagicMock()
    with patch.object(curriculum, 'get_moonshot_api_key', return_value='test-key'), \
         patch('src.agent.guardrails.screen_message',
               return_value=GuardrailResult(blocked=False, reason='', category='')), \
         patch('openai.OpenAI', return_value=fake):
        yield authenticated_client, fake


def _ask(client):
    resp = client.post('/curriculum/api/ai-guide',
                       json={'module_id': MODULE_ID, 'question': 'How do I list files by size?'})
    events = [json.loads(line[6:]) for line in resp.get_data(as_text=True).splitlines()
              if line.startswith('data: ') and line != 'data: [DONE]']
    return resp, events


def test_default_model_is_the_app_wide_kimi_model_not_moonshot_v1(no_env_override):
    assert curriculum._curriculum_models() == [DEFAULT_KIMI_MODEL]
    assert not any(m.startswith('moonshot-v1') for m in curriculum._curriculum_models())


def test_override_is_tried_first_then_the_default(monkeypatch):
    monkeypatch.setenv('CURRICULUM_MODEL', 'some-other-model')
    assert curriculum._curriculum_models() == ['some-other-model', DEFAULT_KIMI_MODEL]


def test_coach_streams_only_the_answer_text(coach):
    client, fake = coach
    fake.chat.completions.create.return_value = iter([
        _chunk(reasoning='thinking...'), _chunk(content='Use '), _chunk(content='ls -lS'),
        SimpleNamespace(choices=[]),
    ])
    resp, events = _ask(client)
    assert resp.status_code == 200
    assert ''.join(e.get('text', '') for e in events) == 'Use ls -lS'
    assert not any('error' in e for e in events)
    kwargs = fake.chat.completions.create.call_args.kwargs
    assert kwargs['model'] == DEFAULT_KIMI_MODEL
    assert kwargs['max_tokens'] >= 4096  # room for a reasoning model's thinking tokens


def test_coach_reports_an_empty_answer_instead_of_a_blank_box(coach):
    client, fake = coach
    fake.chat.completions.create.return_value = iter([_chunk(reasoning='only thinking')])
    _, events = _ask(client)
    assert any('did not return an answer' in e.get('error', '') for e in events)


def test_unavailable_model_falls_back_to_the_default(coach, monkeypatch):
    client, fake = coach
    monkeypatch.setenv('CURRICULUM_MODEL', 'retired-model')
    fake.chat.completions.create.side_effect = [
        _status_error(openai.NotFoundError, 404, 'model not found'),
        iter([_chunk(content='ok')]),
    ]
    _, events = _ask(client)
    assert [e.get('text') for e in events] == ['ok']
    tried = [c.kwargs['model'] for c in fake.chat.completions.create.call_args_list]
    assert tried == ['retired-model', DEFAULT_KIMI_MODEL]


@pytest.mark.parametrize('error, expected', [
    (lambda: _status_error(openai.AuthenticationError, 401, 'Invalid Authentication sk-SECRET'), 'API key'),
    (lambda: _status_error(openai.RateLimitError, 429, 'exceeded_current_quota org-123'), 'busy or out of quota'),
    (lambda: RuntimeError('internal detail /var/www/x.py line 9'), 'Something went wrong'),
])
def test_provider_errors_become_readable_and_never_leak_raw_text(coach, error, expected):
    client, fake = coach
    exc = error()
    fake.chat.completions.create.side_effect = exc
    _, events = _ask(client)
    messages = [e['error'] for e in events if 'error' in e]
    assert messages and expected in messages[0]
    assert str(exc) not in messages[0]


def test_non_model_errors_do_not_trigger_fallback(coach, monkeypatch):
    client, fake = coach
    monkeypatch.setenv('CURRICULUM_MODEL', 'some-model')
    fake.chat.completions.create.side_effect = _status_error(openai.RateLimitError, 429)
    _ask(client)
    assert fake.chat.completions.create.call_count == 1


def _quiz_reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.mark.parametrize('text', [
    json.dumps(GOOD_QUIZ),
    '```json\n' + json.dumps(GOOD_QUIZ) + '\n```',
    'Here are your questions:\n' + json.dumps(GOOD_QUIZ) + '\nGood luck!',
])
def test_quiz_parses_json_however_the_model_wraps_it(coach, text):
    client, fake = coach
    curriculum._quiz_cache.pop(MODULE_ID, None)
    fake.chat.completions.create.return_value = _quiz_reply(text)
    resp = client.post('/curriculum/api/quiz/generate', json={'module_id': MODULE_ID})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(resp.get_json()['questions']) == 5
    assert fake.chat.completions.create.call_args.kwargs['model'] == DEFAULT_KIMI_MODEL
    curriculum._quiz_cache.pop(MODULE_ID, None)


@pytest.mark.parametrize('text', [
    '', 'no json here',
    json.dumps([{'question': 'Q?', 'options': ['a', 'b'], 'correct': 0}]),
    json.dumps([{'question': 'Q?', 'options': ['a', 'b', 'c', 'd'], 'correct': 7}]),
])
def test_quiz_rejects_unusable_replies(coach, text):
    client, fake = coach
    curriculum._quiz_cache.pop(MODULE_ID, None)
    fake.chat.completions.create.return_value = _quiz_reply(text)
    resp = client.post('/curriculum/api/quiz/generate', json={'module_id': MODULE_ID})
    assert resp.status_code == 500
    assert 'Failed to parse quiz questions' in resp.get_json()['error']


def test_quiz_provider_error_is_readable(coach):
    client, fake = coach
    curriculum._quiz_cache.pop(MODULE_ID, None)
    fake.chat.completions.create.side_effect = _status_error(openai.AuthenticationError, 401, 'bad key sk-SECRET')
    resp = client.post('/curriculum/api/quiz/generate', json={'module_id': MODULE_ID})
    assert resp.status_code == 502
    assert 'sk-SECRET' not in resp.get_json()['error']
