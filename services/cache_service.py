"""
Redis Cache Service for DevOps Agent

Provides caching layer for frequently accessed data:
- User sessions and preferences
- Cloud resource lists
- API responses
- Rate limiting data
"""

import os
import json
import hashlib
import logging
from functools import wraps
from typing import Any, Callable, Optional, Union
from datetime import timedelta

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CacheService:
    """
    Redis-based caching service with fallback to in-memory cache.

    Features:
    - Automatic serialization/deserialization
    - TTL support
    - Key prefixing for namespace isolation
    - Decorator for function result caching
    - Fallback to in-memory dict when Redis unavailable
    """

    def __init__(self, app=None):
        self.redis_client = None
        self.memory_cache = {}  # Fallback cache
        self.default_ttl = 300  # 5 minutes default
        self.key_prefix = "devops:"
        self.enabled = False

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize cache with Flask app configuration."""
        redis_url = app.config.get('REDIS_URL') or os.environ.get('REDIS_URL')

        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True
                )
                # Test connection
                self.redis_client.ping()
                self.enabled = True
                logger.info("Redis cache initialized successfully")
            except redis.ConnectionError as e:
                logger.warning(f"Redis connection failed, using memory cache: {e}")
                self.redis_client = None
                self.enabled = True  # Still enabled with memory fallback
            except Exception as e:
                logger.warning(f"Redis initialization failed: {e}")
                self.redis_client = None
                self.enabled = True
        else:
            if not REDIS_AVAILABLE:
                logger.info("Redis package not installed, using memory cache")
            else:
                logger.info("REDIS_URL not configured, using memory cache")
            self.enabled = True

        # Store in app extensions
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['cache'] = self

        # Configuration
        self.default_ttl = app.config.get('CACHE_DEFAULT_TTL', 300)
        self.key_prefix = app.config.get('CACHE_KEY_PREFIX', 'devops:')

    def _make_key(self, key: str) -> str:
        """Create a prefixed cache key."""
        return f"{self.key_prefix}{key}"

    def _serialize(self, value: Any) -> str:
        """Serialize value to JSON string."""
        return json.dumps(value, default=str)

    def _deserialize(self, value: str) -> Any:
        """Deserialize JSON string to value."""
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                value = self.redis_client.get(full_key)
                return self._deserialize(value)
            except redis.RedisError as e:
                logger.error(f"Redis get error: {e}")
                # Fallback to memory
                return self.memory_cache.get(full_key)
        else:
            cached = self.memory_cache.get(full_key)
            if cached:
                # Check TTL for memory cache
                if cached.get('expires') and cached['expires'] < self._now():
                    del self.memory_cache[full_key]
                    return None
                return cached.get('value')
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set a value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (default: 300)
        """
        full_key = self._make_key(key)
        ttl = ttl or self.default_ttl

        if self.redis_client:
            try:
                self.redis_client.setex(full_key, ttl, self._serialize(value))
                return
            except redis.RedisError as e:
                logger.error(f"Redis set error: {e}")
                # Fall through to the in-memory cache

        self.memory_cache[full_key] = {
            'value': value,
            'expires': self._now() + ttl
        }

    def delete(self, key: str) -> None:
        """
        Delete a value from cache.

        Args:
            key: Cache key
        """
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                self.redis_client.delete(full_key)
            except redis.RedisError as e:
                logger.error(f"Redis delete error: {e}")

        # Always drop the in-memory copy too. A value written here while Redis
        # was down would otherwise outlive its own delete.
        self.memory_cache.pop(full_key, None)

    def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Key pattern (e.g., "user:123:*")

        Returns:
            Number of keys deleted
        """
        full_pattern = self._make_key(pattern)
        deleted = 0

        if self.redis_client:
            try:
                cursor = 0
                while True:
                    cursor, keys = self.redis_client.scan(cursor, match=full_pattern)
                    if keys:
                        deleted += self.redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except redis.RedisError as e:
                logger.error(f"Redis delete_pattern error: {e}")

        # Also clean memory cache
        keys_to_delete = [k for k in self.memory_cache if k.startswith(full_pattern.replace('*', ''))]
        for k in keys_to_delete:
            del self.memory_cache[k]
            deleted += 1

        return deleted

    def exists(self, key: str) -> bool:
        """Check if a key exists in cache."""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return bool(self.redis_client.exists(full_key))
            except redis.RedisError:
                pass

        return full_key in self.memory_cache

    def increment(self, key: str, amount: int = 1) -> int:
        """Increment a counter in cache."""
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return self.redis_client.incrby(full_key, amount)
            except redis.RedisError as e:
                logger.error(f"Redis increment error: {e}")

        # Memory fallback
        if full_key not in self.memory_cache:
            self.memory_cache[full_key] = {'value': 0, 'expires': None}
        self.memory_cache[full_key]['value'] += amount
        return self.memory_cache[full_key]['value']

    def get_or_set(self, key: str, factory: Callable, ttl: Optional[int] = None) -> Any:
        """
        Get value from cache or compute and cache it.

        Args:
            key: Cache key
            factory: Function to call if cache miss
            ttl: Time-to-live in seconds

        Returns:
            Cached or computed value
        """
        value = self.get(key)
        if value is None:
            value = factory()
            self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        """Clear all cached data (use with caution)."""
        # delete_pattern() covers both Redis and the in-memory fallback, and
        # handles RedisError itself - so there was never anything for a
        # try/except here to catch.
        self.delete_pattern("*")
        self.memory_cache.clear()

    def _now(self) -> int:
        """Get current timestamp."""
        import time
        return int(time.time())

    # ==========================================
    # Decorator for caching function results
    # ==========================================

    def cached(self, ttl: Optional[int] = None, key_prefix: str = ""):
        """
        Decorator to cache function results.

        Usage:
            @cache.cached(ttl=300, key_prefix="user_data")
            def get_user_data(user_id):
                return expensive_database_query(user_id)

        Args:
            ttl: Cache TTL in seconds
            key_prefix: Prefix for cache key
        """
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Build cache key from function name and arguments
                key_parts = [key_prefix or func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)
                cache_key = hashlib.md5(cache_key.encode(), usedforsecurity=False).hexdigest()

                # Try to get from cache
                cached_value = self.get(cache_key)
                if cached_value is not None:
                    logger.debug(f"Cache hit for {func.__name__}")
                    return cached_value

                # Compute and cache
                logger.debug(f"Cache miss for {func.__name__}")
                result = func(*args, **kwargs)
                self.set(cache_key, result, ttl)
                return result

            # Add method to invalidate this function's cache
            wrapper.invalidate = lambda *args, **kwargs: self.delete(
                hashlib.md5(":".join([key_prefix or func.__name__] +
                    [str(a) for a in args] +
                    [f"{k}={v}" for k, v in sorted(kwargs.items())]
                ).encode(), usedforsecurity=False).hexdigest()
            )

            return wrapper
        return decorator

    # ==========================================
    # Specific cache helpers
    # ==========================================

    def cache_user_data(self, user_id: int, data: dict, ttl: int = 600):
        """Cache user-specific data."""
        return self.set(f"user:{user_id}:data", data, ttl)

    def get_user_data(self, user_id: int) -> Optional[dict]:
        """Get cached user data."""
        return self.get(f"user:{user_id}:data")

    def invalidate_user_cache(self, user_id: int):
        """Invalidate all cache for a user."""
        return self.delete_pattern(f"user:{user_id}:*")

    def cache_cloud_resources(self, user_id: int, provider: str, resource_type: str,
                              resources: list, ttl: int = 120):
        """Cache cloud resources for a user."""
        key = f"user:{user_id}:cloud:{provider}:{resource_type}"
        return self.set(key, resources, ttl)

    def get_cloud_resources(self, user_id: int, provider: str, resource_type: str) -> Optional[list]:
        """Get cached cloud resources."""
        key = f"user:{user_id}:cloud:{provider}:{resource_type}"
        return self.get(key)

    def cache_api_response(self, endpoint: str, params: dict, response: Any, ttl: int = 60):
        """Cache API response."""
        params_hash = hashlib.md5(json.dumps(params, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
        key = f"api:{endpoint}:{params_hash}"
        return self.set(key, response, ttl)

    def get_api_response(self, endpoint: str, params: dict) -> Optional[Any]:
        """Get cached API response."""
        params_hash = hashlib.md5(json.dumps(params, sort_keys=True).encode(), usedforsecurity=False).hexdigest()
        key = f"api:{endpoint}:{params_hash}"
        return self.get(key)

    def get_stats(self) -> dict:
        """Get cache statistics."""
        stats = {
            'backend': 'redis' if self.redis_client else 'memory',
            'enabled': self.enabled,
            'memory_cache_size': len(self.memory_cache)
        }

        if self.redis_client:
            try:
                info = self.redis_client.info('memory')
                stats['redis_memory_used'] = info.get('used_memory_human', 'N/A')
                stats['redis_connected_clients'] = self.redis_client.info('clients').get('connected_clients', 0)
            except redis.RedisError:
                stats['redis_status'] = 'error'

        return stats


# Global cache instance
cache = CacheService()


def init_cache(app):
    """Initialize cache with Flask app."""
    cache.init_app(app)
    return cache
