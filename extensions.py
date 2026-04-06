"""
Shared Flask extension instances.

Import these into app.py (for init_app) and into blueprints (for decorators/logging).
Having them here breaks the circular import between app.py and routes/*.py.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Rate limiter — app.init_app() is called in app.py
# Redis backend persists limits across restarts; falls back to memory if Redis is unavailable.
import os as _os
_redis_url = _os.environ.get('REDIS_URL', 'redis://localhost:6379')
try:
    import redis as _redis_check
    _redis_check.from_url(_redis_url).ping()
    _limiter_storage = _redis_url
except Exception:
    _limiter_storage = 'memory://'

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri=_limiter_storage,
)

# Security audit logger — use absolute path so it works regardless of working directory
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(_log_dir, exist_ok=True)
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
security_logger.propagate = False  # don't bubble up to root logger
_security_handler = RotatingFileHandler(os.path.join(_log_dir, 'security.log'), maxBytes=50 * 1024 * 1024, backupCount=5)
_security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
if not security_logger.handlers:
    security_logger.addHandler(_security_handler)
