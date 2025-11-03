"""Check for duplicate conversations"""
import sys
import codecs

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    print("Current Conversations:")
    print("="*70)
    for i, conv in enumerate(convs, 1):
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
        print(f"{i}. {conv.title} ({msg_count} messages)")
        print(f"   ID: {conv.id}")
    print(f"\nTotal: {len(convs)} conversations")
