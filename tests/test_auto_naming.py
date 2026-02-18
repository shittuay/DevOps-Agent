"""Test auto-naming feature"""
from app import app, db
from models import Conversation, ChatMessage, User
from datetime import datetime

with app.app_context():
    # Find the latest conversation
    latest_conv = Conversation.query.order_by(Conversation.updated_at.desc()).first()

    print("="*60)
    print("Auto-Naming Feature Test")
    print("="*60)

    if latest_conv:
        print(f"\nLatest Conversation:")
        print(f"  ID: {latest_conv.id}")
        print(f"  Title: {latest_conv.title}")
        print(f"  Created: {latest_conv.created_at}")
        print(f"  Updated: {latest_conv.updated_at}")

        # Get messages for this conversation
        messages = ChatMessage.query.filter_by(
            conversation_id=latest_conv.id
        ).order_by(ChatMessage.timestamp).all()

        print(f"\n  Message Count: {len(messages)}")
        if messages:
            print(f"\n  First Message:")
            first_msg = messages[0]
            print(f"    Role: {first_msg.role}")
            print(f"    Content: {first_msg.content[:100]}...")

            print(f"\n  Expected Title: {first_msg.content[:50]}")
            print(f"  Actual Title: {latest_conv.title}")

            if latest_conv.title == first_msg.content[:50] or latest_conv.title == first_msg.content:
                print("\n  ✓ Auto-naming is working!")
            elif latest_conv.title == "New Chat":
                print("\n  ✗ Title not updated - still 'New Chat'")
            else:
                print(f"\n  ? Title is: {latest_conv.title}")
    else:
        print("\nNo conversations found in database")

    # Check all conversations
    print("\n" + "="*60)
    print("All Conversations:")
    print("="*60)
    all_convs = Conversation.query.order_by(Conversation.updated_at.desc()).limit(5).all()
    for conv in all_convs:
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
        print(f"\n  {conv.id[:8]}... - '{conv.title}' ({msg_count} messages)")

    print("\n" + "="*60)
