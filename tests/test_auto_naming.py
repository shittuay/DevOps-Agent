"""Test auto-naming feature.

Run directly: python tests/test_auto_naming.py
"""
import sys
sys.path.insert(0, '.')


def main():
    from app import app, db
    from models import Conversation, ChatMessage, User

    with app.app_context():
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

            messages = ChatMessage.query.filter_by(
                conversation_id=latest_conv.id
            ).order_by(ChatMessage.timestamp).all()

            print(f"\n  Message Count: {len(messages)}")
            if messages:
                first_msg = messages[0]
                print(f"\n  First Message:")
                print(f"    Role: {first_msg.role}")
                print(f"    Content: {first_msg.content[:100]}...")
                print(f"\n  Expected Title: {first_msg.content[:50]}")
                print(f"  Actual Title: {latest_conv.title}")

                if latest_conv.title == first_msg.content[:50] or latest_conv.title == first_msg.content:
                    print("\n  Auto-naming is working!")
                elif latest_conv.title == "New Chat":
                    print("\n  Title not updated - still 'New Chat'")
                else:
                    print(f"\n  Title is: {latest_conv.title}")
        else:
            print("\nNo conversations found in database")

        print("\n" + "="*60)
        print("All Conversations:")
        print("="*60)
        all_convs = Conversation.query.order_by(Conversation.updated_at.desc()).limit(5).all()
        for conv in all_convs:
            msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
            print(f"\n  {conv.id[:8]}... - '{conv.title}' ({msg_count} messages)")

        print("\n" + "="*60)


if __name__ == '__main__':
    main()
