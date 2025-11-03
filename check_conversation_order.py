"""Check conversation sorting order"""
import sys
import codecs

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage
from datetime import datetime

with app.app_context():
    print("="*70)
    print("Conversation Order (Most Recent First)")
    print("="*70)

    # Get conversations sorted by updated_at DESC (most recent first)
    convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()

    print(f"\nTotal Conversations: {len(convs)}\n")

    for i, conv in enumerate(convs, 1):
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()

        # Calculate time ago
        now = datetime.utcnow()
        time_diff = now - conv.updated_at

        if time_diff.days > 0:
            time_ago = f"{time_diff.days}d ago"
        elif time_diff.seconds // 3600 > 0:
            time_ago = f"{time_diff.seconds // 3600}h ago"
        elif time_diff.seconds // 60 > 0:
            time_ago = f"{time_diff.seconds // 60}m ago"
        else:
            time_ago = "Just now"

        print(f"{i}. {conv.title}")
        print(f"   ID: {conv.id[:16]}...")
        print(f"   Updated: {conv.updated_at} ({time_ago})")
        print(f"   Messages: {msg_count}")
        print()

    print("="*70)
    print("✓ This is the order that should appear in the sidebar")
    print("  (Most recently updated conversation at the top)")
    print("="*70)
