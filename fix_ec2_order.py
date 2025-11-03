"""Update EC2 conversation to be the most recent"""
import sys
import codecs
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

from app import app, db
from models import Conversation

with app.app_context():
    print("="*70)
    print("Fixing EC2 Conversation Order")
    print("="*70)

    # Find EC2 conversation
    ec2_conv = Conversation.query.filter(
        Conversation.title.like('%ec2 instancte%')
    ).first()

    if ec2_conv:
        print(f"\nUpdating EC2 conversation...")
        print(f"Title: {ec2_conv.title}")
        print(f"Old timestamp: {ec2_conv.updated_at}")

        # Update to NOW
        ec2_conv.updated_at = datetime.utcnow()

        print(f"New timestamp: {ec2_conv.updated_at}")
        db.session.commit()

        print("\n✓ EC2 conversation updated to be MOST RECENT")

        # Show final order
        print("\n" + "="*70)
        print("Final Order (Most Recent First):")
        print("="*70)

        convs = Conversation.query.order_by(Conversation.updated_at.desc()).all()
        for i, conv in enumerate(convs, 1):
            print(f"{i}. {conv.title}")

        print("\n" + "="*70)
    else:
        print("\n✗ EC2 conversation not found")
