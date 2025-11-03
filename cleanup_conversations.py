"""Clean up duplicate and empty conversations"""
import sys
import codecs
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    print("="*70)
    print("Conversation Cleanup")
    print("="*70)

    # 1. Update EC2 conversation to be most recent
    ec2_conv = Conversation.query.filter(
        Conversation.title.like('%ec2 instancte%')
    ).first()

    if ec2_conv:
        print(f"\n1. Updating EC2 conversation timestamp...")
        print(f"   Title: {ec2_conv.title}")
        print(f"   Old timestamp: {ec2_conv.updated_at}")
        ec2_conv.updated_at = datetime.utcnow()
        print(f"   New timestamp: {ec2_conv.updated_at}")
        print("   ✓ EC2 conversation will now appear FIRST")

    # 2. Find duplicate "hi" conversations
    hi_convs = Conversation.query.filter_by(title='hi').order_by(
        Conversation.updated_at.desc()
    ).all()

    if len(hi_convs) > 1:
        print(f"\n2. Found {len(hi_convs)} conversations titled 'hi'")

        # Keep the most recent one with most messages
        keep_conv = None
        max_messages = 0

        for conv in hi_convs:
            msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
            print(f"   - {conv.id[:8]}... : {msg_count} messages (updated: {conv.updated_at})")

            if msg_count > max_messages:
                max_messages = msg_count
                keep_conv = conv

        if keep_conv:
            print(f"\n   Keeping: {keep_conv.id[:8]}... ({max_messages} messages)")

            # Delete the others
            for conv in hi_convs:
                if conv.id != keep_conv.id:
                    # Check if it has messages - if so, keep it separate
                    msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
                    if msg_count == 0 or msg_count < 3:  # Delete if empty or very short
                        print(f"   Deleting: {conv.id[:8]}... ({msg_count} messages)")
                        # Delete associated messages first
                        ChatMessage.query.filter_by(conversation_id=conv.id).delete()
                        db.session.delete(conv)
                    else:
                        print(f"   Keeping: {conv.id[:8]}... (has {msg_count} unique messages)")

    # 3. Delete empty "New Chat" conversations
    empty_convs = Conversation.query.filter_by(title='New Chat').all()

    if empty_convs:
        print(f"\n3. Found {len(empty_convs)} empty 'New Chat' conversation(s)")

        for conv in empty_convs:
            msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
            if msg_count == 0:
                print(f"   Deleting: {conv.id[:8]}...")
                db.session.delete(conv)
            else:
                print(f"   Keeping: {conv.id[:8]}... (has {msg_count} messages)")

    # Commit all changes
    db.session.commit()

    print("\n" + "="*70)
    print("Cleanup Complete!")
    print("="*70)

    # Show final state
    print("\nFinal Conversation List (in order they'll appear):")
    print("-"*70)

    convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    for i, conv in enumerate(convs, 1):
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
        time_diff = datetime.utcnow() - conv.updated_at

        if time_diff.days > 0:
            time_ago = f"{time_diff.days}d ago"
        elif time_diff.seconds // 3600 > 0:
            time_ago = f"{time_diff.seconds // 3600}h ago"
        elif time_diff.seconds // 60 > 0:
            time_ago = f"{time_diff.seconds // 60}m ago"
        else:
            time_ago = "Just now"

        print(f"{i}. {conv.title} ({msg_count} messages, {time_ago})")

    print("\n" + "="*70)
    print(f"Total conversations: {len(convs)}")
    print("="*70)
