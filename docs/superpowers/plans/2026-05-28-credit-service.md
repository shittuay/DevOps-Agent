# CreditService Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract a `CreditService` class so all credit reads/writes go through a single choke point instead of 40 scattered direct accesses to `UserSubscription.credits_remaining`.

**Architecture:** `services/credit_service.py` — three static methods (`balance`, `deduct`, `grant`) that each fetch `UserSubscription` by `user_id` and delegate to existing model methods (`use_credit`, `add_credits`). `deduct` accepts `commit=False` so it can participate in larger transactions. Hard-reset assignments (subscription creation, tier upgrades, monthly renewal) stay as direct assignments — they are not increments/decrements.

**Tech Stack:** Flask-SQLAlchemy, existing `UserSubscription` model methods (`use_credit`, `add_credits`, `has_credits`), pytest with SQLite in-memory fixtures.

---

### Task 1: Create `CreditService` with tests

**Files:**
- Create: `services/credit_service.py`
- Create: `tests/test_credit_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_credit_service.py
import pytest


@pytest.fixture
def user_with_sub(test_user, db_session):
    from models import db, SubscriptionTier, UserSubscription
    from datetime import datetime
    tier = SubscriptionTier.query.filter_by(name='free').first()
    if not tier:
        tier = SubscriptionTier(name='free', monthly_credits=20, max_tools=10)
        db.session.add(tier)
        db.session.commit()
    sub = UserSubscription(
        user_id=test_user.id,
        tier_id=tier.id,
        credits_remaining=10,
        current_period_start=datetime.utcnow(),
        current_period_end=datetime.utcnow(),
    )
    db.session.add(sub)
    db.session.commit()
    yield test_user, sub


def test_balance_returns_credits(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    assert CreditService.balance(user.id) == 10


def test_balance_returns_zero_for_no_subscription(test_user):
    from services.credit_service import CreditService
    assert CreditService.balance(test_user.id) == 0


def test_deduct_reduces_by_one(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    remaining = CreditService.deduct(user.id)
    assert remaining == 9
    assert CreditService.balance(user.id) == 9


def test_deduct_floors_at_zero(user_with_sub, db_session):
    from models import UserSubscription
    from services.credit_service import CreditService
    user, sub = user_with_sub
    sub.credits_remaining = 0
    db_session.commit()
    remaining = CreditService.deduct(user.id)
    assert remaining == 0
    assert CreditService.balance(user.id) == 0


def test_deduct_commit_false_does_not_persist_without_commit(user_with_sub, db_session):
    from models import UserSubscription, db
    from services.credit_service import CreditService
    user, sub = user_with_sub
    CreditService.deduct(user.id, commit=False)
    db_session.rollback()
    assert CreditService.balance(user.id) == 10


def test_grant_increases_balance(user_with_sub):
    from services.credit_service import CreditService
    user, sub = user_with_sub
    new_bal = CreditService.grant(user.id, 5)
    assert new_bal == 15
    assert CreditService.balance(user.id) == 15


def test_grant_returns_zero_for_no_subscription(test_user):
    from services.credit_service import CreditService
    result = CreditService.grant(test_user.id, 5)
    assert result == 0
```

- [ ] **Step 2: Run tests — expect failure**

```bash
pytest tests/test_credit_service.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'services.credit_service'`

- [ ] **Step 3: Create `services/credit_service.py`**

```python
from __future__ import annotations


class CreditService:
    """Single choke point for all credit reads and writes.

    Delegates to UserSubscription.use_credit() and add_credits() — those
    methods handle the credits_used_this_month / total_credits_used bookkeeping.
    """

    @staticmethod
    def balance(user_id: int) -> int:
        """Return current credits_remaining, or 0 if no subscription exists."""
        from models import UserSubscription
        sub = UserSubscription.query.filter_by(user_id=user_id).first()
        return sub.credits_remaining if sub else 0

    @staticmethod
    def deduct(user_id: int, amount: int = 1, commit: bool = True) -> int:
        """Deduct *amount* credits (default 1). Floor at 0.

        Pass commit=False when deducting inside a larger transaction — the
        caller is responsible for db.session.commit().

        Returns the new balance (or 0 if no subscription).
        """
        from models import UserSubscription
        sub = UserSubscription.query.filter_by(user_id=user_id).first()
        if not sub:
            return 0
        for _ in range(amount):
            if not sub.use_credit(commit=False):
                break  # already at 0
        if commit:
            from models import db
            db.session.commit()
        return sub.credits_remaining

    @staticmethod
    def grant(user_id: int, amount: int) -> int:
        """Add *amount* credits. Commits immediately.

        Returns the new balance (or 0 if no subscription).
        """
        from models import UserSubscription
        sub = UserSubscription.query.filter_by(user_id=user_id).first()
        if not sub:
            return 0
        sub.add_credits(amount)   # add_credits() commits internally
        return sub.credits_remaining
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_credit_service.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/credit_service.py tests/test_credit_service.py
git commit -m "feat: add CreditService with balance/deduct/grant"
```

---

### Task 2: Export from `services/__init__.py`

**Files:**
- Modify: `services/__init__.py`

- [ ] **Step 1: Add export**

Open `services/__init__.py`. Add this line after the existing `from services.cache_service import ...` line:

```python
from services.credit_service import CreditService
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from services import CreditService; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add services/__init__.py
git commit -m "chore: export CreditService from services package"
```

---

### Task 3: Migrate `app.py` — admin grant + balance reads

**Files:**
- Modify: `app.py`

These are the non-chat usages: the admin credit-grant endpoint (~line 2641) and the `credits_remaining` balance read in the non-streaming `/api/chat` response (~line 3092).

- [ ] **Step 1: Add import at the top of `app.py`**

Find the block of service imports near the top of `app.py` (search for `from services.`). Add:

```python
from services.credit_service import CreditService
```

- [ ] **Step 2: Replace admin grant (around line 2641)**

Find:
```python
    old = sub.credits_remaining
    sub.credits_remaining = old + amount
    db.session.commit()
    return jsonify({
        'success': True,
        'email': target_email,
        'credits_before': old,
        'credits_after': sub.credits_remaining,
        'tier': sub.tier.name if sub.tier else 'unknown'
    })
```

Replace with:
```python
    old = CreditService.balance(target.id)
    new_bal = CreditService.grant(target.id, amount)
    return jsonify({
        'success': True,
        'email': target_email,
        'credits_before': old,
        'credits_after': new_bal,
        'tier': sub.tier.name if sub.tier else 'unknown'
    })
```

- [ ] **Step 3: Replace balance read in non-streaming `/api/chat` response (around line 3092)**

Find:
```python
            'credits_remaining': subscription.credits_remaining,
```

Replace with:
```python
            'credits_remaining': CreditService.balance(current_user.id),
```

- [ ] **Step 4: Replace balance reads in non-streaming trial context (around lines 2895 and 3052)**

Find (first occurrence, in the non-streaming `/api/chat`):
```python
            credits_left = subscription.credits_remaining
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
```

Replace with:
```python
            credits_left = CreditService.balance(current_user.id)
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
```

- [ ] **Step 5: Replace non-streaming deduct + low-credit check (around lines 3041–3057)**

Find:
```python
        # Deduct credit AFTER successful response (not before)
        if success:
            subscription.use_credit(commit=False)

        db.session.commit()

        # Fire low-credit warning email at exactly 5 credits remaining (once per threshold)
        if success and subscription.credits_remaining == 5 and current_user.email:
            try:
                import threading
                from services.email_service import email_service as _es
                _u = current_user._get_current_object()
                _r = subscription.credits_remaining
```

Replace with:
```python
        # Deduct credit AFTER successful response (not before)
        new_bal = None
        if success:
            new_bal = CreditService.deduct(current_user.id, commit=False)

        db.session.commit()

        # Fire low-credit warning email at exactly 5 credits remaining (once per threshold)
        if success and new_bal == 5 and current_user.email:
            try:
                import threading
                from services.email_service import email_service as _es
                _u = current_user._get_current_object()
                _r = new_bal
```

- [ ] **Step 6: Verify app starts and tests pass**

```bash
python -m py_compile app.py && echo "syntax ok"
pytest tests/test_credit_service.py tests/test_billing.py tests/test_payment_credits.py -q
```

Expected: syntax ok, tests pass.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "refactor: migrate app.py admin grant and non-streaming balance reads to CreditService"
```

---

### Task 4: Migrate `app.py` — streaming path

**Files:**
- Modify: `app.py`

The streaming `/api/chat/stream` path (the `generate()` inner function). Two sets of changes:
(a) trial context balance read, (b) approval-pending SSE events, (c) post-response deduct + balance read.

- [ ] **Step 1: Replace streaming trial context (around line 3414)**

Find (second occurrence of this block, inside the streaming path):
```python
            credits_left = subscription.credits_remaining
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
```

Replace with:
```python
            credits_left = CreditService.balance(uid)
            trial_context = (
                f"TRIAL CONTEXT: This user is on a free trial with {credits_left} credits remaining out of 20. "
```

- [ ] **Step 2: Replace approval-pending SSE `credits_remaining` reads (lines 3549 and 3580)**

Find (first occurrence):
```python
                            yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': sub.credits_remaining, 'approval_pending': True})}\n\n"
                            return
```

Replace with:
```python
                            yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': CreditService.balance(uid), 'approval_pending': True})}\n\n"
                            return
```

Find (second occurrence):
```python
                        yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': sub.credits_remaining, 'approval_pending': True})}\n\n"
                        return
```

Replace with:
```python
                        yield f"data: {_json.dumps({'type': 'done', 'credits_remaining': CreditService.balance(uid), 'approval_pending': True})}\n\n"
                        return
```

- [ ] **Step 3: Replace streaming deduct + remaining read (around lines 3661–3668)**

Find:
```python
                    # Deduct credit AFTER successful response (not before)
                    fresh_sub = UserSubscription.query.filter_by(user_id=uid).first()
                    if fresh_sub:
                        fresh_sub.use_credit(commit=False)

                    db.session.commit()

                    # Read remaining credits after commit
                    remaining = fresh_sub.credits_remaining if fresh_sub else 0

                    # Fire low-credit warning email at exactly 5 credits remaining
                    if fresh_sub and remaining == 5:
```

Replace with:
```python
                    # Deduct credit AFTER successful response (not before)
                    remaining = CreditService.deduct(uid, commit=False)

                    db.session.commit()

                    # Fire low-credit warning email at exactly 5 credits remaining
                    if remaining == 5:
```

- [ ] **Step 4: Verify syntax and tests**

```bash
python -m py_compile app.py && echo "syntax ok"
pytest tests/test_credit_service.py tests/test_billing.py -q
```

Expected: syntax ok, tests pass.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "refactor: migrate app.py streaming path to CreditService"
```

---

### Task 5: Migrate `routes/api_gateway.py`

**Files:**
- Modify: `routes/api_gateway.py`

Three patterns: direct tool call response, streaming agent done event, non-streaming agent response.

- [ ] **Step 1: Add import**

Near the top of `routes/api_gateway.py`, find existing service imports and add:

```python
from services.credit_service import CreditService
```

- [ ] **Step 2: Replace direct tool call deduct + response (around line 625)**

Find:
```python
    sub.use_credit(commit=False)
    db.session.commit()

    return jsonify({
        'result': result,
        'tool': tool_name,
        'credits_remaining': sub.credits_remaining,
    })
```

Replace with:
```python
    remaining = CreditService.deduct(user_id, commit=False)
    db.session.commit()

    return jsonify({
        'result': result,
        'tool': tool_name,
        'credits_remaining': remaining,
    })
```

- [ ] **Step 3: Replace streaming agent deduct + done event (around lines 739–741)**

Find:
```python
                _sub.use_credit(commit=False)
                db.session.commit()
                credits_left = _sub.credits_remaining
```

Replace with:
```python
                credits_left = CreditService.deduct(user_id, commit=False)
                db.session.commit()
```

- [ ] **Step 4: Replace non-streaming agent deduct + response (around lines 888–894)**

Find:
```python
    sub.use_credit(commit=False)
    db.session.commit()

    return jsonify({
        'response': response_text,
        'tools_used': tools_used,
        'credits_remaining': sub.credits_remaining,
        'conversation_id': conversation_id,
    })
```

Replace with:
```python
    remaining = CreditService.deduct(user_id, commit=False)
    db.session.commit()

    return jsonify({
        'response': response_text,
        'tools_used': tools_used,
        'credits_remaining': remaining,
        'conversation_id': conversation_id,
    })
```

- [ ] **Step 5: Verify syntax and tests**

```bash
python -m py_compile routes/api_gateway.py && echo "syntax ok"
pytest tests/test_credit_service.py tests/test_api.py -q
```

Expected: syntax ok, tests pass.

- [ ] **Step 6: Commit**

```bash
git add routes/api_gateway.py
git commit -m "refactor: migrate api_gateway.py to CreditService"
```

---

### Task 6: Migrate `routes/billing.py` and `services/drip_email_service.py`

**Files:**
- Modify: `routes/billing.py`
- Modify: `services/drip_email_service.py`

Only the balance read in the billing status endpoint is migrated. Hard-reset assignments (`subscription.credits_remaining = tier.monthly_credits` and constructor kwargs) stay as-is — they are full resets, not deltas.

- [ ] **Step 1: Add import to `routes/billing.py`**

Near the top of `routes/billing.py`, add:

```python
from services.credit_service import CreditService
```

- [ ] **Step 2: Replace balance read in billing status response (around line 533)**

Find:
```python
            'credits_remaining': subscription.credits_remaining,
```

Replace with:
```python
            'credits_remaining': CreditService.balance(current_user.id),
```

- [ ] **Step 3: Add import to `services/drip_email_service.py`**

Near the top of `services/drip_email_service.py`, add:

```python
from services.credit_service import CreditService
```

- [ ] **Step 4: Replace balance read in drip email (around lines 115–119)**

Find:
```python
            # Check if user is on a paid tier
            is_paid = False
            credits_remaining = 20
            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            if sub and sub.tier:
                is_paid = sub.tier.name in ('starter', 'professional', 'business')
                credits_remaining = sub.credits_remaining or 0
```

Replace with:
```python
            # Check if user is on a paid tier
            is_paid = False
            credits_remaining = CreditService.balance(user.id)
            sub = UserSubscription.query.filter_by(user_id=user.id).first()
            if sub and sub.tier:
                is_paid = sub.tier.name in ('starter', 'professional', 'business')
```

- [ ] **Step 5: Verify syntax and tests**

```bash
python -m py_compile routes/billing.py services/drip_email_service.py && echo "syntax ok"
pytest tests/test_billing.py tests/test_payment_credits.py tests/test_credit_service.py -q
```

Expected: syntax ok, tests pass.

- [ ] **Step 6: Commit**

```bash
git add routes/billing.py services/drip_email_service.py
git commit -m "refactor: migrate billing.py and drip_email_service.py to CreditService"
```

---

### Task 7: Full test suite + TODOS.md

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Run the full test suite**

```bash
pytest -q 2>&1 | tail -20
```

Expected: all tests pass (pre-existing fixture failures in conftest are unrelated — focus on any new failures).

- [ ] **Step 2: Confirm no stray `credits_remaining` writes remain**

```bash
grep -rn "\.credits_remaining\s*=" app.py routes/ services/ | grep -v "credit_service.py\|models.py\|credits_remaining=\|#"
```

Expected output — only these lines should remain (legitimate hard resets):
- `routes/billing.py`: `subscription.credits_remaining = tier.monthly_credits` (tier upgrade reset)
- `routes/billing.py`: `user_subscription.credits_remaining = tier_credits` (renewal reset)
- `routes/billing.py`: `user_subscription.credits_remaining = free_tier.monthly_credits` (renewal reset)

- [ ] **Step 3: Mark TODOS.md done**

In `TODOS.md`, find:
```
### [ ] Extract CreditService
```

Replace with:
```
### [x] Extract CreditService — DONE
`services/credit_service.py`: `balance(user_id)`, `deduct(user_id, amount=1, commit=True)`, `grant(user_id, amount)`. Migrated 40 usages across app.py, routes/billing.py, routes/api_gateway.py, services/drip_email_service.py. Hard resets (tier upgrades, monthly renewal) remain as direct assignment.
```

- [ ] **Step 4: Final commit**

```bash
git add TODOS.md
git commit -m "chore: mark Extract CreditService complete in TODOS.md"
```
