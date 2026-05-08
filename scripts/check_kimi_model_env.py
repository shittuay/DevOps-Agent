import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'production')
from services.secrets_manager import get_all_secrets
s = get_all_secrets()
print('KIMI_MODEL in secrets:', s.get('KIMI_MODEL', 'NOT SET'))
print('KIMI_MODEL env:', os.environ.get('KIMI_MODEL', 'NOT SET'))
