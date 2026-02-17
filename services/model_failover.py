"""
Multi-Model Failover Service

Provides automatic failover to alternative LLM providers (OpenAI, Google Gemini)
when the primary Anthropic Claude API is unavailable or rate-limited.
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional, Generator

logger = logging.getLogger(__name__)

# Provider status tracking
_provider_status = {
    'anthropic': {'healthy': True, 'last_failure': 0, 'failures': 0},
    'openai': {'healthy': True, 'last_failure': 0, 'failures': 0},
    'google': {'healthy': True, 'last_failure': 0, 'failures': 0},
    'groq': {'healthy': True, 'last_failure': 0, 'failures': 0},
}

# Backoff: mark provider unhealthy after 3 failures, retry after 60s
MAX_FAILURES = 3
RETRY_AFTER_SECONDS = 60


class ModelProvider:
    """Base class for LLM provider adapters."""

    def __init__(self, name: str):
        self.name = name

    def is_available(self) -> bool:
        status = _provider_status.get(self.name, {})
        if not status.get('healthy', True):
            if time.time() - status.get('last_failure', 0) > RETRY_AFTER_SECONDS:
                status['healthy'] = True
                status['failures'] = 0
                return True
            return False
        return True

    def mark_failure(self):
        status = _provider_status[self.name]
        status['failures'] += 1
        status['last_failure'] = time.time()
        if status['failures'] >= MAX_FAILURES:
            status['healthy'] = False
            logger.warning(f"Provider {self.name} marked unhealthy after {MAX_FAILURES} failures")

    def mark_success(self):
        status = _provider_status[self.name]
        status['healthy'] = True
        status['failures'] = 0

    def chat(self, messages: List[Dict], system: str = None, **kwargs) -> str:
        raise NotImplementedError

    def chat_stream(self, messages: List[Dict], system: str = None, **kwargs) -> Generator[str, None, None]:
        raise NotImplementedError


class AnthropicProvider(ModelProvider):
    """Anthropic Claude adapter (primary)."""

    def __init__(self):
        super().__init__('anthropic')

    @property
    def api_key(self):
        return os.environ.get('ANTHROPIC_API_KEY', '')

    @property
    def model(self):
        return os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')

    def is_available(self) -> bool:
        return bool(self.api_key) and super().is_available()

    def chat(self, messages: List[Dict], system: str = None, **kwargs) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        params = {
            'model': self.model,
            'max_tokens': kwargs.get('max_tokens', 4096),
            'messages': messages,
        }
        if system:
            params['system'] = system
        try:
            response = client.messages.create(**params)
            self.mark_success()
            return response.content[0].text
        except Exception as e:
            self.mark_failure()
            raise

    def chat_stream(self, messages: List[Dict], system: str = None, **kwargs) -> Generator[str, None, None]:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        params = {
            'model': self.model,
            'max_tokens': kwargs.get('max_tokens', 4096),
            'messages': messages,
        }
        if system:
            params['system'] = system
        try:
            with client.messages.stream(**params) as stream:
                for text in stream.text_stream:
                    yield text
            self.mark_success()
        except Exception as e:
            self.mark_failure()
            raise


class OpenAIProvider(ModelProvider):
    """OpenAI GPT adapter (first fallback)."""

    def __init__(self):
        super().__init__('openai')

    @property
    def api_key(self):
        return os.environ.get('OPENAI_API_KEY', '')

    @property
    def model(self):
        return os.environ.get('OPENAI_MODEL', 'gpt-4o')

    def is_available(self) -> bool:
        return bool(self.api_key) and super().is_available()

    def chat(self, messages: List[Dict], system: str = None, **kwargs) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            logger.debug("openai package not installed")
            return ""

        client = OpenAI(api_key=self.api_key)
        oai_messages = []
        if system:
            oai_messages.append({'role': 'system', 'content': system})
        for msg in messages:
            oai_messages.append({'role': msg['role'], 'content': msg['content']})

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                max_tokens=kwargs.get('max_tokens', 4096),
            )
            self.mark_success()
            return response.choices[0].message.content
        except Exception as e:
            self.mark_failure()
            raise

    def chat_stream(self, messages: List[Dict], system: str = None, **kwargs) -> Generator[str, None, None]:
        try:
            from openai import OpenAI
        except ImportError:
            return

        client = OpenAI(api_key=self.api_key)
        oai_messages = []
        if system:
            oai_messages.append({'role': 'system', 'content': system})
        for msg in messages:
            oai_messages.append({'role': msg['role'], 'content': msg['content']})

        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=oai_messages,
                max_tokens=kwargs.get('max_tokens', 4096),
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            self.mark_success()
        except Exception as e:
            self.mark_failure()
            raise


class GoogleProvider(ModelProvider):
    """Google Gemini adapter (second fallback)."""

    def __init__(self):
        super().__init__('google')

    @property
    def api_key(self):
        return os.environ.get('GOOGLE_AI_API_KEY', '')

    @property
    def model(self):
        return os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')

    def is_available(self) -> bool:
        return bool(self.api_key) and super().is_available()

    def chat(self, messages: List[Dict], system: str = None, **kwargs) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            logger.debug("google-generativeai package not installed")
            return ""

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(
            self.model,
            system_instruction=system if system else None,
        )

        # Convert messages to Gemini format
        history = []
        for msg in messages[:-1]:
            role = 'user' if msg['role'] == 'user' else 'model'
            history.append({'role': role, 'parts': [msg['content']]})

        try:
            chat = model.start_chat(history=history)
            last_msg = messages[-1]['content'] if messages else ''
            response = chat.send_message(last_msg)
            self.mark_success()
            return response.text
        except Exception as e:
            self.mark_failure()
            raise

    def chat_stream(self, messages: List[Dict], system: str = None, **kwargs) -> Generator[str, None, None]:
        try:
            import google.generativeai as genai
        except ImportError:
            return

        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(
            self.model,
            system_instruction=system if system else None,
        )

        history = []
        for msg in messages[:-1]:
            role = 'user' if msg['role'] == 'user' else 'model'
            history.append({'role': role, 'parts': [msg['content']]})

        try:
            chat = model.start_chat(history=history)
            last_msg = messages[-1]['content'] if messages else ''
            response = chat.send_message(last_msg, stream=True)
            for chunk in response:
                if chunk.text:
                    yield chunk.text
            self.mark_success()
        except Exception as e:
            self.mark_failure()
            raise


class GroqProvider(ModelProvider):
    """Groq adapter for free-tier users (Llama models via OpenAI-compatible API)."""

    def __init__(self):
        super().__init__('groq')

    @property
    def api_key(self):
        return os.environ.get('GROQ_API_KEY', '')

    @property
    def model(self):
        return os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')

    def is_available(self) -> bool:
        return bool(self.api_key) and super().is_available()

    def chat(self, messages: List[Dict], system: str = None, **kwargs) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            logger.debug("openai package not installed")
            return ""

        client = OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
        oai_messages = []
        if system:
            oai_messages.append({'role': 'system', 'content': system})
        for msg in messages:
            oai_messages.append({'role': msg['role'], 'content': msg['content']})

        try:
            response = client.chat.completions.create(
                model=kwargs.get('model', self.model),
                messages=oai_messages,
                max_tokens=kwargs.get('max_tokens', 4096),
            )
            self.mark_success()
            return response.choices[0].message.content
        except Exception as e:
            self.mark_failure()
            raise

    def chat_stream(self, messages: List[Dict], system: str = None, **kwargs) -> Generator[str, None, None]:
        try:
            from openai import OpenAI
        except ImportError:
            return

        client = OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
        oai_messages = []
        if system:
            oai_messages.append({'role': 'system', 'content': system})
        for msg in messages:
            oai_messages.append({'role': msg['role'], 'content': msg['content']})

        try:
            stream = client.chat.completions.create(
                model=kwargs.get('model', self.model),
                messages=oai_messages,
                max_tokens=kwargs.get('max_tokens', 4096),
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            self.mark_success()
        except Exception as e:
            self.mark_failure()
            raise


# Ordered provider chain
_providers = [
    AnthropicProvider(),
    OpenAIProvider(),
    GoogleProvider(),
    GroqProvider(),
]


def chat_with_failover(
    messages: List[Dict], system: str = None, stream: bool = False, **kwargs
):
    """
    Send chat request with automatic failover across providers.

    Args:
        messages: List of {'role': 'user'|'assistant', 'content': str}
        system: System prompt
        stream: If True, returns a generator of text chunks
        **kwargs: Additional params (max_tokens, etc.)

    Returns:
        str or Generator[str] depending on stream parameter

    Raises:
        RuntimeError: If all providers fail
    """
    errors = []

    for provider in _providers:
        if not provider.is_available():
            logger.debug(f"Skipping unavailable provider: {provider.name}")
            continue

        try:
            logger.info(f"Trying provider: {provider.name}")
            if stream:
                return provider.chat_stream(messages, system, **kwargs)
            else:
                return provider.chat(messages, system, **kwargs)
        except Exception as e:
            errors.append(f"{provider.name}: {str(e)}")
            logger.warning(f"Provider {provider.name} failed: {e}")
            continue

    raise RuntimeError(
        f"All LLM providers failed. Errors: {'; '.join(errors)}"
    )


def get_provider_status() -> Dict[str, Any]:
    """Get health status of all providers."""
    provider_map = {p.name: p for p in _providers}
    return {
        name: {
            'healthy': status['healthy'],
            'failures': status['failures'],
            'available': provider_map[name].is_available() if name in provider_map else False,
            'configured': bool(provider_map[name].api_key) if name in provider_map and hasattr(provider_map[name], 'api_key') else False,
        }
        for name, status in _provider_status.items()
    }


def get_groq_provider() -> GroqProvider:
    """Get the Groq provider instance."""
    for p in _providers:
        if isinstance(p, GroqProvider):
            return p
    return GroqProvider()
