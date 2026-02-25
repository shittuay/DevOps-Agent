"""
Currency detection for DevOps Agent billing.
Determines whether to show NGN or USD pricing based on user preferences,
IP geolocation, and Accept-Language headers.
"""
import logging
import time
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Simple in-memory cache for IP geolocation results
_geo_cache = {}  # ip -> (country_code, timestamp)
_GEO_CACHE_TTL = 86400  # 24 hours

# Nigerian language codes
NIGERIAN_LOCALES = {'en-ng', 'yo', 'ig', 'ha', 'pcm'}

# Countries that use NGN
NGN_COUNTRIES = {'NG'}


def detect_user_currency(request, user_preferences=None) -> str:
    """
    Detect the appropriate currency for the user.

    Resolution order:
    1. User's saved preferred_currency in UserPreferences
    2. IP geolocation (Nigeria -> NGN)
    3. Accept-Language header (Nigerian languages -> NGN)
    4. Default: USD

    Args:
        request: Flask request object
        user_preferences: UserPreferences model instance (optional)

    Returns:
        'NGN' or 'USD'
    """
    # 1. Check saved preference
    if user_preferences and getattr(user_preferences, 'preferred_currency', None):
        return user_preferences.preferred_currency

    # 2. IP geolocation
    ip_currency = _detect_from_ip(request)
    if ip_currency:
        return ip_currency

    # 3. Accept-Language header
    lang_currency = _detect_from_language(request)
    if lang_currency:
        return lang_currency

    # 4. Default
    return 'USD'


def _detect_from_ip(request) -> Optional[str]:
    """Detect currency from IP geolocation."""
    ip = _get_client_ip(request)
    if not ip or ip in ('127.0.0.1', '::1', 'localhost'):
        return None

    # Check cache
    cached = _geo_cache.get(ip)
    if cached:
        country_code, ts = cached
        if time.time() - ts < _GEO_CACHE_TTL:
            return 'NGN' if country_code in NGN_COUNTRIES else None
        else:
            del _geo_cache[ip]

    # Query free geolocation API
    try:
        resp = requests.get(
            f'http://ip-api.com/json/{ip}',
            params={'fields': 'countryCode'},
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            country_code = data.get('countryCode', '')
            _geo_cache[ip] = (country_code, time.time())

            # Trim cache to prevent unbounded growth
            if len(_geo_cache) > 10000:
                cutoff = time.time() - _GEO_CACHE_TTL
                expired = [k for k, (_, ts) in _geo_cache.items() if ts < cutoff]
                for k in expired:
                    del _geo_cache[k]

            return 'NGN' if country_code in NGN_COUNTRIES else None
    except Exception as e:
        logger.debug(f"IP geolocation failed for {ip}: {e}")
        return None


def _detect_from_language(request) -> Optional[str]:
    """Detect currency from Accept-Language header."""
    accept_lang = request.headers.get('Accept-Language', '').lower()
    if not accept_lang:
        return None

    for locale in NIGERIAN_LOCALES:
        if locale in accept_lang:
            return 'NGN'

    return None


def _get_client_ip(request) -> Optional[str]:
    """Get client IP, respecting X-Forwarded-For for proxied requests."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr
