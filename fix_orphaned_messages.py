"""Fix orphaned messages by creating missing conversations"""
import sys
import codecs

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage
from datetime import datetime

with app.app_context():
    print("="*70)
    print("Fixing Orphaned Messages")
    print("="*70)

    # Find all messages
    all_messages = ChatMessage.query.all()

    # Group messages by conversation_id
    conv_ids = set(msg.conversation_id for msg in all_messages)

    print(f"\nTotal unique conversation IDs in messages: {len(conv_ids)}")

    # Check which conversations exist
    orphaned_convs = []
    for conv_id in conv_ids:
        conv = Conversation.query.get(conv_id)
        if not conv:
            orphaned_convs.append(conv_id)
            print(f"  ✗ Missing conversation: {conv_id[:16]}...")

    if orphaned_convs:
        print(f"\n{'='*70}")
        print(f"Found {len(orphaned_convs)} orphaned conversation(s)")
        print("="*70)

        for conv_id in orphaned_convs:
            # Get messages for this conversation
            messages = ChatMessage.query.filter_by(conversation_id=conv_id).order_by(ChatMessage.timestamp).all()

            if messages:
                first_user_msg = next((msg for msg in messages if msg.role == 'user'), None)

                if first_user_msg:
                    # Create title from first message
                    title = first_user_msg.content.strip()
                    if len(title) > 50:
                        title = title[:47] + '...'
                else:
                    title = "Recovered Chat"

                # Get timestamps
                created_at = messages[0].timestamp
                updated_at = messages[-1].timestamp

                # Get user_id from first message
                user_id = messages[0].user_id

                print(f"\nCreating conversation for: {conv_id[:16]}...")
                print(f"  Title: {title}")
                print(f"  Messages: {len(messages)}")
                print(f"  Created: {created_at}")
                print(f"  Updated: {updated_at}")

                # Create the conversation
                new_conv = Conversation(
                    id=conv_id,
                    user_id=user_id,
                    title=title,
                    created_at=created_at,
                    updated_at=updated_at
                )
                db.session.add(new_conv)

        # Commit all changes
        db.session.commit()

        print(f"\n{'='*70}")
        print(f"✓ Created {len(orphaned_convs)} missing conversation(s)")
        print("="*70)

    else:
        print("\n✓ No orphaned messages found - all conversations exist!")

    # Summary
    print(f"\nSummary:")
    print(f"  Total conversations: {Conversation.query.count()}")
    print(f"  Total messages: {ChatMessage.query.count()}")
    print("="*70)
