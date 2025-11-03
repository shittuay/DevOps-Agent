"""Check for messages sent today"""
import sys
import codecs
from datetime import datetime, timedelta

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    print("="*70)
    print("Recent Messages (Today)")
    print("="*70)

    # Get today's date
    today = datetime.now().date()

    # Find all messages from today
    all_messages = ChatMessage.query.order_by(ChatMessage.timestamp.desc()).all()

    print(f"\nTotal messages in database: {len(all_messages)}")

    # Filter messages from today
    today_messages = [msg for msg in all_messages if msg.timestamp and msg.timestamp.date() >= today]

    if today_messages:
        print(f"\nMessages from today ({today}): {len(today_messages)}\n")

        for msg in today_messages:
            conv = Conversation.query.get(msg.conversation_id)
            conv_title = conv.title if conv else "Unknown"
            content_preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content

            print(f"Time: {msg.timestamp}")
            print(f"Conversation: {msg.conversation_id[:8]}... ({conv_title})")
            print(f"Role: {msg.role}")
            print(f"Content: {content_preview}")
            print("-" * 70)
    else:
        print(f"\nNo messages from today")

    # Show last 5 messages
    print(f"\n{'='*70}")
    print("Last 5 Messages (Any Date)")
    print("="*70)

    for msg in all_messages[:5]:
        conv = Conversation.query.get(msg.conversation_id)
        conv_title = conv.title if conv else "Unknown"
        content_preview = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content

        print(f"\nTime: {msg.timestamp}")
        print(f"Conversation: {conv_title}")
        print(f"[{msg.role}] {content_preview}")

    print("\n" + "="*70)
