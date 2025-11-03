"""Update duplicate 'hi' conversation titles to be more descriptive"""
import sys
import codecs

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation, ChatMessage

with app.app_context():
    print("="*70)
    print("Updating 'hi' Conversation Titles")
    print("="*70)

    # Find all conversations titled "hi"
    hi_convs = Conversation.query.filter_by(title='hi').order_by(
        Conversation.updated_at.desc()
    ).all()

    print(f"\nFound {len(hi_convs)} conversation(s) titled 'hi'\n")

    for i, conv in enumerate(hi_convs, 1):
        messages = ChatMessage.query.filter_by(
            conversation_id=conv.id,
            role='user'
        ).order_by(ChatMessage.timestamp).all()

        print(f"{i}. Conversation {conv.id[:8]}...")
        print(f"   Current title: {conv.title}")
        print(f"   Messages: {len(messages)}")

        if messages:
            print(f"   Message history:")
            for j, msg in enumerate(messages, 1):
                preview = msg.content[:60] + "..." if len(msg.content) > 60 else msg.content
                print(f"     {j}. {preview}")

            # Find a better title from the conversation
            # Look for the second user message (after "hi")
            better_title = None
            if len(messages) > 1:
                second_msg = messages[1]
                better_title = second_msg.content.strip()
            elif len(messages) == 1:
                # Only one message which is "hi" - use first assistant response topic
                assistant_msgs = ChatMessage.query.filter_by(
                    conversation_id=conv.id,
                    role='assistant'
                ).order_by(ChatMessage.timestamp).first()

                if assistant_msgs:
                    # Extract key topic from assistant response
                    if 'EKS' in assistant_msgs.content or 'Kubernetes' in assistant_msgs.content:
                        better_title = "EKS Cluster Setup"
                    elif 'Jenkins' in assistant_msgs.content:
                        better_title = "Jenkins Setup"
                    else:
                        better_title = "General DevOps Help"

            if better_title:
                if len(better_title) > 50:
                    better_title = better_title[:47] + '...'

                print(f"   New title: {better_title}")
                conv.title = better_title
            else:
                print(f"   Keeping title: {conv.title}")

        print()

    db.session.commit()

    print("="*70)
    print("Update Complete!")
    print("="*70)

    # Show final state
    print("\nFinal Conversation List:")
    print("-"*70)

    convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
    for i, conv in enumerate(convs, 1):
        msg_count = ChatMessage.query.filter_by(conversation_id=conv.id).count()
        print(f"{i}. {conv.title} ({msg_count} messages)")

    print("\n" + "="*70)
