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
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://",
)

# Security audit logger
os.makedirs('logs', exist_ok=True)
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
_security_handler = RotatingFileHandler('logs/security.log', maxBytes=50 * 1024 * 1024, backupCount=5)
_security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
if not security_logger.handlers:
    security_logger.addHandler(_security_handler)
