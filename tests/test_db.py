"""Test database connectivity and check tables"""
from app import app, db
from models import User, Conversation, SubscriptionTier, ChatMessage, UserSubscription

with app.app_context():
    print("="*60)
    print("Database Connectivity Test")
    print("="*60)

    # Check tables
    print("\nTables in database:")
    for table in db.metadata.tables:
        print(f"  - {table}")

    # Check counts
    print("\nRecord counts:")
    try:
        user_count = User.query.count()
        print(f"  Users: {user_count}")
    except Exception as e:
        print(f"  Users: ERROR - {str(e)}")

    try:
        conv_count = Conversation.query.count()
        print(f"  Conversations: {conv_count}")
    except Exception as e:
        print(f"  Conversations: ERROR - {str(e)}")

    try:
        tier_count = SubscriptionTier.query.count()
        print(f"  Subscription Tiers: {tier_count}")
    except Exception as e:
        print(f"  Subscription Tiers: ERROR - {str(e)}")

    try:
        msg_count = ChatMessage.query.count()
        print(f"  Chat Messages: {msg_count}")
    except Exception as e:
        print(f"  Chat Messages: ERROR - {str(e)}")

    try:
        sub_count = UserSubscription.query.count()
        print(f"  User Subscriptions: {sub_count}")
    except Exception as e:
        print(f"  User Subscriptions: ERROR - {str(e)}")

    # Check if security fields exist
    print("\nChecking security fields in User table:")
    if user_count > 0:
        user = User.query.first()
        print(f"  - failed_login_attempts: {hasattr(user, 'failed_login_attempts')}")
        print(f"  - locked_until: {hasattr(user, 'locked_until')}")
        print(f"  - last_login_ip: {hasattr(user, 'last_login_ip')}")
    else:
        print("  No users in database to check")

    print("\n" + "="*60)
    print("Database test completed successfully!")
    print("="*60)
