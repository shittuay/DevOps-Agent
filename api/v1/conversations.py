"""
Conversations API Endpoints

Provides conversation and chat management endpoints.
"""

from flask import jsonify, request, g
from datetime import datetime
import uuid
from api.v1 import api_v1_bp
from services.api_key_service import require_api_key


@api_v1_bp.route('/conversations', methods=['GET'])
@require_api_key(scope='read')
def list_conversations():
    """
    List user's conversations.

    Requires: API key with 'read' scope

    Query Parameters:
        limit (int): Number of conversations to return (default: 20, max: 100)
        offset (int): Offset for pagination (default: 0)
    """
    from models import Conversation

    user_id = g.api_user.id
    limit = min(request.args.get('limit', 20, type=int), 100)
    offset = request.args.get('offset', 0, type=int)

    conversations = Conversation.query.filter_by(user_id=user_id)\
        .order_by(Conversation.updated_at.desc())\
        .limit(limit)\
        .offset(offset)\
        .all()

    total = Conversation.query.filter_by(user_id=user_id).count()

    return jsonify({
        'conversations': [c.to_dict() for c in conversations],
        'pagination': {
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + limit < total
        }
    })


@api_v1_bp.route('/conversations/<conversation_id>', methods=['GET'])
@require_api_key(scope='read')
def get_conversation(conversation_id):
    """
    Get a specific conversation with messages.

    Requires: API key with 'read' scope

    Query Parameters:
        include_messages (bool): Include messages in response (default: true)
        message_limit (int): Number of messages to include (default: 50)
    """
    from models import Conversation, ChatMessage

    user_id = g.api_user.id
    include_messages = request.args.get('include_messages', 'true').lower() == 'true'
    message_limit = min(request.args.get('message_limit', 50, type=int), 200)

    conversation = Conversation.query.filter_by(
        id=conversation_id,
        user_id=user_id
    ).first()

    if not conversation:
        return jsonify({
            'error': 'Not found',
            'message': 'Conversation not found'
        }), 404

    result = conversation.to_dict()

    if include_messages:
        messages = ChatMessage.query.filter_by(
            conversation_id=conversation_id,
            user_id=user_id
        ).order_by(ChatMessage.timestamp.asc())\
         .limit(message_limit)\
         .all()

        result['messages'] = [m.to_dict() for m in messages]

    return jsonify(result)


@api_v1_bp.route('/conversations', methods=['POST'])
@require_api_key(scope='write')
def create_conversation():
    """
    Create a new conversation.

    Requires: API key with 'write' scope

    Body:
        title (string, optional): Conversation title
    """
    from models import db, Conversation

    user_id = g.api_user.id
    data = request.get_json() or {}

    conversation = Conversation(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=data.get('title', 'New Chat')
    )

    db.session.add(conversation)
    db.session.commit()

    return jsonify({
        'message': 'Conversation created',
        'conversation': conversation.to_dict()
    }), 201


@api_v1_bp.route('/conversations/<conversation_id>', methods=['DELETE'])
@require_api_key(scope='write')
def delete_conversation(conversation_id):
    """
    Delete a conversation.

    Requires: API key with 'write' scope
    """
    from models import db, Conversation, ChatMessage

    user_id = g.api_user.id

    conversation = Conversation.query.filter_by(
        id=conversation_id,
        user_id=user_id
    ).first()

    if not conversation:
        return jsonify({
            'error': 'Not found',
            'message': 'Conversation not found'
        }), 404

    # Delete messages first
    ChatMessage.query.filter_by(
        conversation_id=conversation_id,
        user_id=user_id
    ).delete()

    db.session.delete(conversation)
    db.session.commit()

    return jsonify({
        'message': 'Conversation deleted'
    })


@api_v1_bp.route('/conversations/<conversation_id>/messages', methods=['POST'])
@require_api_key(scope='write')
def send_message(conversation_id):
    """
    Send a message to a conversation and get AI response.

    Requires: API key with 'write' scope

    Body:
        content (string, required): Message content
    """
    from models import db, Conversation, ChatMessage, UserSubscription

    user_id = g.api_user.id
    data = request.get_json() or {}

    if not data.get('content'):
        return jsonify({
            'error': 'Bad request',
            'message': 'Message content is required'
        }), 400

    # Verify conversation exists and belongs to user
    conversation = Conversation.query.filter_by(
        id=conversation_id,
        user_id=user_id
    ).first()

    if not conversation:
        return jsonify({
            'error': 'Not found',
            'message': 'Conversation not found'
        }), 404

    # Check credits
    subscription = UserSubscription.query.filter_by(user_id=user_id).first()
    if subscription and not subscription.has_credits():
        return jsonify({
            'error': 'Insufficient credits',
            'message': 'You have no credits remaining'
        }), 402

    # Save user message
    user_message = ChatMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        role='user',
        content=data['content']
    )
    db.session.add(user_message)

    # TODO: Call Claude API to get response
    # For now, return a placeholder
    assistant_response = "This is a placeholder response. The Claude API integration would generate the actual response."

    # Save assistant message
    assistant_message = ChatMessage(
        user_id=user_id,
        conversation_id=conversation_id,
        role='assistant',
        content=assistant_response
    )
    db.session.add(assistant_message)

    # Update conversation timestamp
    conversation.updated_at = datetime.utcnow()

    # Deduct credit
    if subscription:
        subscription.use_credit()

    db.session.commit()

    return jsonify({
        'user_message': user_message.to_dict(),
        'assistant_message': assistant_message.to_dict()
    }), 201
