"""Requesting-user context and credential lookup for integration tools.

Set and cleared by DevOpsAgent._set_cloud_user_context / _clear_cloud_user_context,
alongside the AWS/Azure/GCP contexts.
"""
import threading
from typing import Dict, Optional

_context = threading.local()


def set_user_context(user_id: Optional[int]) -> None:
    _context.user_id = user_id


def clear_user_context() -> None:
    _context.user_id = None


def get_user_id() -> Optional[int]:
    return getattr(_context, 'user_id', None)


def credentials(provider: str, caller_url: Optional[str] = None, **explicit: Optional[str]) -> Dict[str, str]:
    """Resolve credentials for the requesting user; raises IntegrationNotConnected."""
    from services.integration_credentials import resolve
    return resolve(provider, get_user_id(), explicit=explicit, caller_url=caller_url)
