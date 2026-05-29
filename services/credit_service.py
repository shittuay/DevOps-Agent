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
