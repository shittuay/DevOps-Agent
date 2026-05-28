# CreditService Design — 2026-05-28

## Problem

`credits_remaining` is read and written in 40 places across `app.py`, `routes/`, and `services/`. There is no single choke point, no floor guard against going negative, and no place to add per-tool pricing or team credit pools without touching dozens of files.

## Solution

Extract a `CreditService` class with three static methods in `services/credit_service.py`. All callers stop touching `UserSubscription.credits_remaining` directly.

## Interface

```python
class CreditService:
    @staticmethod
    def balance(user_id: int) -> int:
        """Return current credits_remaining, or 0 if no subscription."""

    @staticmethod
    def deduct(user_id: int, amount: int = 1) -> int:
        """Subtract amount from credits_remaining (floor 0). Commit. Return new balance."""

    @staticmethod
    def grant(user_id: int, amount: int) -> int:
        """Add amount to credits_remaining. Commit. Return new balance."""
```

All three methods fetch `UserSubscription.query.filter_by(user_id=user_id).first()` internally. Callers never import `UserSubscription` for credit operations.

## Call-site migration

| Pattern in existing code | Replacement |
|---|---|
| `subscription.credits_remaining` (read) | `CreditService.balance(user_id)` |
| `sub.credits_remaining -= 1` + commit | `CreditService.deduct(user_id, 1)` |
| `sub.credits_remaining += N` + commit | `CreditService.grant(user_id, N)` |
| `sub.credits_remaining = tier.monthly_credits` (reset) | `CreditService.grant` is not appropriate here — direct assignment for resets remains, since it's a hard set not an increment |

## Out of scope

- Audit logging (future work)
- Per-tool pricing (future work — enabled by this refactor)
- Team credit pools (future work)

## Files changed

- `services/credit_service.py` — new file
- `app.py` — replace ~25 usages
- `routes/billing.py` — replace ~8 usages
- `routes/api_gateway.py` — replace ~4 usages
- `services/drip_email_service.py` — replace ~2 usages
- `services/__init__.py` — export `CreditService`
