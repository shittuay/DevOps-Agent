"""
Live smoke test for the Kimi AI Coach and quiz generation.
Run on the production server:
  cd /home/ubuntu/app/DevOps-Agent
  FLASK_ENV=production python scripts/test_kimi_live.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load secrets the same way the app does
os.environ.setdefault('FLASK_ENV', 'production')
from services.secrets_manager import get_moonshot_api_key

print("=" * 50)
print("1. Checking MOONSHOT_API_KEY...")
key = get_moonshot_api_key()
if not key:
    print("FAIL: MOONSHOT_API_KEY not found in env or Secrets Manager")
    sys.exit(1)
print(f"OK: key starts with {key[:8]}...")

print("\n2. Kimi API smoke test (AI Coach style)...")
try:
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1")
    model = os.environ.get('CURRICULUM_MODEL', 'moonshot-v1-8k')

    resp = client.chat.completions.create(
        model='moonshot-v1-8k',
        max_tokens=60,
        messages=[
            {"role": "system", "content": "You are a DevOps learning coach."},
            {"role": "user", "content": "In one sentence, what is a Dockerfile?"},
        ],
    )
    answer = resp.choices[0].message.content.strip()
    print(f"OK: {answer}")
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n3. Kimi streaming test (AI Coach stream)...")
try:
    stream = client.chat.completions.create(
        model='moonshot-v1-8k',
        max_tokens=40,
        stream=True,
        messages=[
            {"role": "system", "content": "You are a DevOps learning coach."},
            {"role": "user", "content": "Name one Linux command for disk usage."},
        ],
    )
    tokens = []
    for chunk in stream:
        t = chunk.choices[0].delta.content or ''
        tokens.append(t)
    print(f"OK: {''.join(tokens).strip()}")
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n4. Kimi JSON quiz generation test...")
try:
    quiz_prompt = """Generate exactly 2 multiple-choice quiz questions for a DevOps student.
Return ONLY valid JSON array, no markdown.
Format: [{"question":"...","options":["A","B","C","D"],"correct":0,"explanation":"..."}]"""

    resp = client.chat.completions.create(
        model='moonshot-v1-32k',
        max_tokens=512,
        messages=[{"role": "user", "content": quiz_prompt}],
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
    questions = json.loads(raw.strip())
    if not questions:
        raise ValueError("Expected at least 1 question")
    for field in ('question', 'correct'):
        if field not in questions[0]:
            raise ValueError(f"Missing '{field}' field")
    print(f"OK: {len(questions)} questions generated")
    print(f"   Sample: {questions[0]['question'][:60]}...")
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("\n" + "=" * 50)
print("ALL TESTS PASSED — Kimi AI Coach is working correctly")
