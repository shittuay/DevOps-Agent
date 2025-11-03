"""Update existing conversations that have messages but still titled 'New Chat'"""
import sys
import codecs

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    print("="*70)
    print("Updating Existing Conversations")
    print("="*70)

    # Find all conversations with "New Chat" title that have messages
    new_chat_convs = Conversation.query.filter_by(title='New Chat').all()

    updated_count = 0
    for conv in new_chat_convs:
        # Get first message
        first_msg = ChatMessage.query.filter_by(
            conversation_id=conv.id,
            role='user'
        ).order_by(ChatMessage.timestamp).first()

        if first_msg:
            # Update title based on first message
            title = first_msg.content.strip()
            if len(title) > 50:
                title = title[:47] + '...'

            conv.title = title
            updated_count += 1
            print(f"\n✓ Updated: {conv.id[:8]}... → '{title}'")

    if updated_count > 0:
        db.session.commit()
        print(f"\n{'='*70}")
        print(f"✓ Updated {updated_count} conversation(s)")
        print(f"{'='*70}")
    else:
        print("\nNo conversations to update")

    # Show all conversations
    print("\nAll Conversations:")
    print("-"*70)
    all_convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    for conv in all_convs:
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
        print(f"  {conv.id[:8]}... - '{conv.title}' ({msg_count} messages)")

    print("\n" + "="*70)
