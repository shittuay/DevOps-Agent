"""Check all conversations with detailed info"""
import sys
import codecs

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    print("="*70)
    print("All Conversations - Detailed View")
    print("="*70)

    convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()

    for i, conv in enumerate(convs, 1):
        messages = ChatMessage.query.filter_by(conversation_id=conv.id).order_by(ChatMessage.timestamp).all()

        print(f"\n{i}. Conversation: {conv.id}")
        print(f"   Title: {conv.title}")
        print(f"   Created: {conv.created_at}")
        print(f"   Updated: {conv.updated_at}")
        print(f"   Messages: {len(messages)}")

        if messages:
            print(f"\n   Message History:")
            for j, msg in enumerate(messages, 1):
                content_preview = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content
                print(f"     {j}. [{msg.role}] {content_preview}")
                print(f"        Time: {msg.timestamp}")
        else:
            print("   (No messages)")

    print("\n" + "="*70)
    print(f"Total Conversations: {len(convs)}")
    print(f"With Messages: {sum(1 for c in convs if ChatMessage.query.filter_by(conversation_id=c.id).count() > 0)}")
    print(f"Empty: {sum(1 for c in convs if ChatMessage.query.filter_by(conversation_id=c.id).count() == 0)}")
    print("="*70)
