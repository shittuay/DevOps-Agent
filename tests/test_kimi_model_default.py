"""Free/Starter run on Kimi K3.1 Pro (released 2026-10-23), with kimi-k3 as a safety net.

If Moonshot refuses the new id for our key (not found, or not enabled), chat must
keep working on kimi-k3 instead of failing for every free and starter user.
"""
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from services import model_router as mr

ROOT = Path(__file__).resolve().parent.parent


def test_default_is_k3_1_pro_everywhere():
    assert mr.DEFAULT_KIMI_MODEL == 'kimi-k3.1-pro'
    assert mr.KIMI_FALLBACK_MODEL == 'kimi-k3'
    assert mr.KIMI_MODEL_CONFIG.model == mr.DEFAULT_KIMI_MODEL
    for tier in ('free', 'starter'):
        cfg = mr.DEFAULT_TIER_MODELS[tier]
        assert cfg.provider == 'kimi' and cfg.model == mr.DEFAULT_KIMI_MODEL
        assert 'K3.1 Pro' in cfg.display_name


def test_only_one_hardcoded_old_id():
    src = (ROOT / 'services' / 'model_router.py').read_text()
    assert src.count("'kimi-k3'") == 1, 'kimi-k3 should appear only as the fallback'


def _err(cls, status, msg):
    req = httpx.Request('POST', 'https://api.moonshot.ai/v1/chat/completions')
    return cls(msg, response=httpx.Response(status, request=req), body=None)


class _Client:
    def __init__(self, fail_with=None):
        self.calls = []
        self.fail_with = fail_with
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.calls.append(params['model'])
        if self.fail_with is not None and params['model'] != mr.KIMI_FALLBACK_MODEL:
            raise self.fail_with
        return 'ok'


def test_refused_model_falls_back_to_k3():
    c = _Client(_err(openai.NotFoundError, 404, 'Not found the model kimi-k3.1-pro'))
    params = {'model': mr.DEFAULT_KIMI_MODEL, 'messages': []}
    assert mr.kimi_create_with_fallback(c, params) == 'ok'
    assert c.calls == ['kimi-k3.1-pro', 'kimi-k3']
    assert params['model'] == 'kimi-k3', 'caller keeps using the model that worked'


def test_bad_request_about_model_falls_back():
    c = _Client(_err(openai.BadRequestError, 400, 'model kimi-k3.1-pro is not enabled'))
    assert mr.kimi_create_with_fallback(c, {'model': mr.DEFAULT_KIMI_MODEL}) == 'ok'


def test_other_errors_are_not_hidden():
    c = _Client(_err(openai.RateLimitError, 429, 'rate limited'))
    with pytest.raises(openai.RateLimitError):
        mr.kimi_create_with_fallback(c, {'model': mr.DEFAULT_KIMI_MODEL})
    assert c.calls == ['kimi-k3.1-pro']


def test_no_loop_when_fallback_itself_is_refused():
    err = _err(openai.NotFoundError, 404, 'no model')
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **p: (_ for _ in ()).throw(err))))
    with pytest.raises(openai.NotFoundError):
        mr.kimi_create_with_fallback(client, {'model': mr.KIMI_FALLBACK_MODEL})


def test_every_kimi_call_site_uses_the_fallback():
    core = (ROOT / 'src' / 'agent' / 'core.py').read_text()
    assert core.count('kimi_create_with_fallback(client, params)') >= 2
    failover = (ROOT / 'services' / 'model_failover.py').read_text()
    kimi = failover[failover.index('class KimiProvider'):failover.index('def chat_with_failover')]
    assert 'client.chat.completions.create' not in kimi
    from routes import curriculum
    assert curriculum._curriculum_models()[-1] == 'kimi-k3'
