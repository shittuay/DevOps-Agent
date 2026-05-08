"""List available Moonshot models and find the right one to use."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'production')

from services.secrets_manager import get_moonshot_api_key
from openai import OpenAI

key = get_moonshot_api_key()
if not key:
    print("FAIL: no key")
    sys.exit(1)

client = OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1")

print("Available models:")
for m in client.models.list().data:
    print(" -", m.id)

# Try a quick call with each candidate
candidates = ['kimi-k2', 'kimi-k2-0605', 'moonshot-v1-8k', 'moonshot-v1-32k', 'kimi-k2.5', 'kimi-k2.6']
print("\nTesting candidates:")
for model in candidates:
    try:
        r = client.chat.completions.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": "Say: ok"}]
        )
        content = r.choices[0].message.content or ''
        print(f"  {model}: '{content.strip()}'")
    except Exception as e:
        print(f"  {model}: ERROR - {e}")
