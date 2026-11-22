"""Permission to send a user's messages to the AI providers, asked in the iPhone app.

Apple's App Review Guideline 5.1.2(i) asks apps to say when personal data goes to a third-party
AI and get the user's permission first. The app shows a one-time screen
(static/js/ai_consent.js) before the first message; this module is the server side of it:
the stored answer (User.ai_consent_at) and a backstop that refuses AI requests from the app
until the user has said yes, so a skipped or broken screen can never send data anyway.

On the website the policy is shown at sign-up and nothing is gated.
"""
from flask import has_request_context, jsonify, request
from flask_login import current_user

from services.app_client import is_ios_app

# Every endpoint whose request is sent to an AI provider.
AI_ENDPOINTS = (
    '/api/chat',
    '/api/chat/stream',
    '/curriculum/api/ai-guide',
    '/curriculum/api/quiz/generate',
    '/api/learning/session-summary',  # sends the chat transcript to Anthropic (Haiku)
)

# Who receives the data; shown on the consent screen and in Settings. Keep in step with the
# privacy policy's section 3.
AI_PROVIDERS = (
    ('Anthropic', 'checks every message for abuse, and answers on plans that use Claude'),
    ('Moonshot AI', 'answers on plans that use Kimi'),
    ('Groq', 'answers only when the main model is unavailable'),
)

CONSENT_REQUIRED_MESSAGE = (
    "DevOps Agent needs your permission before it sends your messages to its AI providers. "
    "Send your message again to see what is shared, or allow it in Settings > Profile."
)


def is_ai_endpoint(path: str) -> bool:
    return path.rstrip('/') in AI_ENDPOINTS


def has_consented(user) -> bool:
    return bool(getattr(user, 'ai_consent_at', None))


def consent_required_response():
    """A 403 for an app request to an AI endpoint from a user who hasn't said yes; else None."""
    if not has_request_context() or request.method != 'POST':
        return None
    if not is_ai_endpoint(request.path) or not is_ios_app():
        return None
    if not current_user.is_authenticated or has_consented(current_user):
        return None
    return jsonify({'error': CONSENT_REQUIRED_MESSAGE, 'code': 'ai_consent_required'}), 403
