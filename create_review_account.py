"""
Create a test account for the Anthropic MCP Connector review team.
Run once: python create_review_account.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DATABASE_URL', 'sqlite:///devops_agent.db')

from app import create_app
from models import db, User
from services.api_gateway import APIGatewayService

REVIEW_EMAIL    = '***REDACTED***'
REVIEW_USERNAME = 'anthropic-reviewer'
REVIEW_PASSWORD = '***REDACTED***'

app = create_app() if callable(getattr(sys.modules.get('app'), 'create_app', None)) else None

def run():
    from flask import Flask
    from models import db as _db

    # Use the existing app context
    import app as app_module
    flask_app = getattr(app_module, 'app', None)
    if flask_app is None:
        print("ERROR: Could not find Flask app instance")
        sys.exit(1)

    with flask_app.app_context():
        # Check if account already exists
        existing = User.query.filter_by(email=REVIEW_EMAIL).first()
        if existing:
            print(f"Account already exists: {REVIEW_EMAIL} (id={existing.id})")
            user = existing
        else:
            user = User(
                email=REVIEW_EMAIL,
                username=REVIEW_USERNAME,
                full_name='Anthropic MCP Reviewer',
                email_verified=True,
                role='user',
            )
            user.set_password(REVIEW_PASSWORD)
            _db.session.add(user)
            _db.session.commit()
            print(f"Created account: {REVIEW_EMAIL} (id={user.id})")

        # Ensure user has a subscription with credits
        from models import UserSubscription, SubscriptionTier
        sub = UserSubscription.query.filter_by(user_id=user.id).first()
        if not sub:
            # Give them starter-tier credits
            tier = SubscriptionTier.query.filter_by(name='starter').first()
            if tier:
                sub = UserSubscription(user_id=user.id, tier_id=tier.id, credits_remaining=100)
                _db.session.add(sub)
                _db.session.commit()
                print(f"Created subscription: starter tier, 100 credits")
        else:
            if sub.credits_remaining < 50:
                sub.credits_remaining = 100
                _db.session.commit()
            print(f"Existing subscription: {sub.credits_remaining} credits")

        # Create an API key for MCP access
        svc = APIGatewayService()
        keys = svc.get_user_api_keys(user.id)
        mcp_key = next((k for k in keys if 'review' in (k.name or '').lower()), None)

        if mcp_key and not mcp_key.is_revoked:
            print(f"API key already exists: {mcp_key.name} (prefix: {mcp_key.key_prefix}...)")
        else:
            key_model, plain_key = svc.create_api_key(
                user_id=user.id,
                name='MCP Connector Review',
                scopes=['mcp:read', 'mcp:execute'],
                expires_in_days=90,
            )
            print(f"\nAPI Key (save this — shown only once):")
            print(f"  {plain_key}")

        print(f"\n--- Review Account Summary ---")
        print(f"Email:    {REVIEW_EMAIL}")
        print(f"Username: {REVIEW_USERNAME}")
        print(f"Password: {REVIEW_PASSWORD}")
        print(f"OAuth:    https://devopsagent.io/mcp/oauth/authorize")
        print(f"SSE:      https://devopsagent.io/mcp/sse")
        print(f"HTTP:     https://devopsagent.io/mcp/")

if __name__ == '__main__':
    run()
