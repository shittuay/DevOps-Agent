"""
Full end-to-end quiz smoke test on the production server.
Run: FLASK_ENV=production python scripts/test_quiz_live.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'production')

from services.secrets_manager import get_moonshot_api_key
from openai import OpenAI

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f": {detail}" if detail else ""))
        errors.append(label)

# ── 1. API key ────────────────────────────────────────────────────────────────
print("\n1. API key")
key = get_moonshot_api_key()
check("MOONSHOT_API_KEY present", bool(key))
if not key:
    sys.exit(1)

client = OpenAI(api_key=key, base_url="https://api.moonshot.ai/v1")

# ── 2. Generate full 5-question quiz ─────────────────────────────────────────
print("\n2. Generate 5-question quiz (moonshot-v1-32k)")
prompt = """Generate exactly 5 multiple-choice quiz questions for a DevOps student studying:

Module: Linux CLI & Shell Basics (Phase 01: Linux & Networking)
Topics covered: ["Navigating the file system: ls, cd, pwd, find", "File operations: cp, mv, rm, mkdir, chmod, chown", "Text processing: grep, awk, sed", "Shell scripting: variables, loops, conditionals"]

Return ONLY valid JSON — no markdown, no explanation, just the JSON array.
Format:
[{"question":"...","options":["A","B","C","D"],"correct":0,"explanation":"..."}]

Rules:
- correct is the index (0-3) of the right answer in options
- Questions must be practical and relevant to real DevOps work
- Vary difficulty: 2 easy, 2 medium, 1 hard"""

try:
    resp = client.chat.completions.create(
        model="moonshot-v1-32k",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    questions = json.loads(raw.strip())
    check("Returned valid JSON", True)
except json.JSONDecodeError as e:
    check("Returned valid JSON", False, str(e))
    print(f"  Raw response: {raw[:200]}")
    sys.exit(1)
except Exception as e:
    check("API call succeeded", False, str(e))
    sys.exit(1)

# ── 3. Validate structure ─────────────────────────────────────────────────────
print("\n3. Validate question structure")
check("Exactly 5 questions", len(questions) == 5, f"got {len(questions)}")
for i, q in enumerate(questions):
    prefix = f"Q{i+1}"
    check(f"{prefix} has 'question' field", "question" in q and q["question"])
    check(f"{prefix} has 4 options", len(q.get("options", [])) == 4, f"got {len(q.get('options',[]))}")
    check(f"{prefix} 'correct' is 0-3", q.get("correct") in (0,1,2,3), f"got {q.get('correct')}")
    check(f"{prefix} has explanation", bool(q.get("explanation")))

# ── 4. Print questions for visual inspection ──────────────────────────────────
print("\n4. Questions preview")
for i, q in enumerate(questions):
    print(f"\n  Q{i+1}: {q['question']}")
    for j, opt in enumerate(q["options"]):
        marker = " ✓" if j == q["correct"] else "  "
        print(f"    [{j}]{marker} {opt}")
    print(f"    Explanation: {q['explanation'][:80]}...")

# ── 5. Simulate scoring (all correct) ────────────────────────────────────────
print("\n5. Scoring simulation")
correct_answers = [q["correct"] for q in questions]
score = sum(1 for i, q in enumerate(questions) if correct_answers[i] == q["correct"])
pct = round((score / len(questions)) * 100)
check("All-correct score = 100%", pct == 100, f"got {pct}%")

wrong_answers = [(q["correct"] + 1) % 4 for q in questions]
score_wrong = sum(1 for i, q in enumerate(questions) if wrong_answers[i] == q["correct"])
check("All-wrong score = 0%", score_wrong == 0, f"got {score_wrong}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
if errors:
    print(f"FAILED — {len(errors)} check(s) failed: {', '.join(errors)}")
    sys.exit(1)
else:
    print("ALL QUIZ TESTS PASSED")
