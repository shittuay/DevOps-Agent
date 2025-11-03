"""Conversation manager for DevOps Agent."""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    """Represents a message in the conversation."""

    role: str  # 'user' or 'assistant'
    content: List[Dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary format for Claude API."""
        return {
            'role': self.role,
            'content': self.content
        }


class ConversationManager:
    """Manages conversation history and context for Claude interactions."""

    def __init__(self, max_history: int = 20):
        """
        Initialize conversation manager.

        Args:
            max_history: Maximum number of messages to keep in history
        """
        self.messages: List[Message] = []
        self.max_history = max_history
        self.session_start = datetime.utcnow()

    def add_user_message(self, content: str) -> None:
        """
        Add a user message to the conversation.

        Args:
            content: User message content
        """
        message = Message(
            role='user',
            content=[{
                'type': 'text',
                'text': content
            }]
        )
        self.messages.append(message)
        self._trim_history()

    def add_assistant_message(self, content: List[Dict[str, Any]]) -> None:
        """
        Add an assistant message to the conversation.

        Args:
            content: Assistant message content (text and tool uses)
        """
        message = Message(
            role='assistant',
            content=content
        )
        self.messages.append(message)
        self._trim_history()

    def add_tool_result(self, tool_use_id: str, tool_result: Any) -> None:
        """
        Add a tool result message to the conversation.

        Args:
            tool_use_id: ID of the tool use
            tool_result: Result from the tool execution
        """
        # Tool results are added as user messages
        message = Message(
            role='user',
            content=[{
                'type': 'tool_result',
                'tool_use_id': tool_use_id,
                'content': str(tool_result)
            }]
        )
        self.messages.append(message)
        self._trim_history()

    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        """
        Get messages in format required by Claude API.

        Returns:
            List of message dictionaries
        """
        return [msg.to_dict() for msg in self.messages]

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.messages = []
        self.session_start = datetime.utcnow()

    def _trim_history(self) -> None:
        """Trim conversation history to max_history length."""
        if len(self.messages) > self.max_history:
            # Keep the most recent messages
            self.messages = self.messages[-self.max_history:]

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of conversation.

        Returns:
            Dictionary with conversation statistics
        """
        user_messages = sum(1 for msg in self.messages if msg.role == 'user')
        assistant_messages = sum(1 for msg in self.messages if msg.role == 'assistant')
        duration = (datetime.utcnow() - self.session_start).total_seconds()

        return {
            'total_messages': len(self.messages),
            'user_messages': user_messages,
            'assistant_messages': assistant_messages,
            'session_duration_seconds': duration,
            'session_start': self.session_start.isoformat()
        }

    def export_conversation(self) -> List[Dict[str, Any]]:
        """
        Export conversation for debugging or analysis.

        Returns:
            List of all messages with timestamps
        """
        return [
            {
                'timestamp': msg.timestamp.isoformat(),
                'role': msg.role,
                'content': msg.content
            }
            for msg in self.messages
        ]

    def __len__(self) -> int:
        """Get number of messages in conversation."""
        return len(self.messages)

    def __repr__(self) -> str:
        """String representation of conversation."""
        summary = self.get_summary()
        return (
            f"ConversationManager("
            f"messages={summary['total_messages']}, "
            f"duration={summary['session_duration_seconds']:.1f}s)"
        )
