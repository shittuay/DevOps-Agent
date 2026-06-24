"""Conversation manager for DevOps Agent."""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

# Cached tiktoken encoder (loaded lazily, once). Falls back to a char heuristic
# if tiktoken is unavailable. We only need an *over-estimate* for budgeting, so a
# cross-provider approximation is fine — never an HTTP round-trip in the hot path.
_TIKTOKEN_ENCODER = None
_TIKTOKEN_TRIED = False


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a string.

    Uses a cached tiktoken cl100k encoder when available; otherwise falls back to
    a len/4 heuristic. Designed to be cheap and to lean slightly high so token
    budgets stay safely under the model context window.
    """
    if not text:
        return 0
    global _TIKTOKEN_ENCODER, _TIKTOKEN_TRIED
    if not _TIKTOKEN_TRIED:
        _TIKTOKEN_TRIED = True
        try:
            import tiktoken
            _TIKTOKEN_ENCODER = tiktoken.get_encoding('cl100k_base')
        except Exception:
            _TIKTOKEN_ENCODER = None
    if _TIKTOKEN_ENCODER is not None:
        try:
            return len(_TIKTOKEN_ENCODER.encode(text))
        except Exception:
            pass
    return len(text) // 4 + 1


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

    def __init__(self, max_history: int = 20, token_budget: Optional[int] = None,
                 recency_keep: int = 8):
        """
        Initialize conversation manager.

        Args:
            max_history: Maximum number of messages to keep in history (hard cap).
            token_budget: Optional token budget. When set and exceeded, oldest
                tool_result bodies are compacted (not dropped) until under budget.
                When None, behavior is the legacy count-only sliding window.
            recency_keep: Number of most-recent messages never compacted.
        """
        self.messages: List[Message] = []
        self.max_history = max_history
        self.token_budget = token_budget
        self.recency_keep = recency_keep
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
        """
        Trim conversation history to max_history length.
        Ensures tool_use and tool_result blocks stay together.
        Then compacts old tool_result bodies if a token budget is configured.
        """
        # Token-aware compaction runs regardless of message count so a few huge
        # tool_results can't blow the budget even when under the count cap.
        if self.token_budget is not None:
            self._compact_old_tool_results()

        if len(self.messages) <= self.max_history:
            return

        # Start from the cutoff point
        cutoff_index = len(self.messages) - self.max_history

        # Check if we're cutting in the middle of a tool use/result pair
        # Look backwards from cutoff to find a safe place to cut
        safe_cutoff = cutoff_index
        for i in range(cutoff_index, min(cutoff_index + 5, len(self.messages))):
            msg = self.messages[i]
            # If this is a user message with tool_result, we need to keep the previous assistant message
            if msg.role == 'user' and any(
                (block.get('type') if isinstance(block, dict) else getattr(block, 'type', None)) == 'tool_result'
                for block in msg.content
            ):
                # Find the previous assistant message with tool_use
                for j in range(i - 1, max(0, i - 10), -1):
                    if self.messages[j].role == 'assistant':
                        # Check if it has tool_use
                        has_tool_use = any(
                            (block.get('type') if isinstance(block, dict) else getattr(block, 'type', None)) == 'tool_use'
                            for block in self.messages[j].content
                        )
                        if has_tool_use:
                            safe_cutoff = j
                            break
                break
            # If this is a safe boundary (user text message), we can cut here
            elif msg.role == 'user' and all(
                (block.get('type') if isinstance(block, dict) else getattr(block, 'type', None)) == 'text'
                for block in msg.content
            ):
                safe_cutoff = i
                break

        self.messages = self.messages[safe_cutoff:]

    @staticmethod
    def _block_text(block: Any) -> str:
        """Best-effort text extraction from a content block for token counting."""
        if isinstance(block, dict):
            if isinstance(block.get('text'), str):
                return block['text']
            if isinstance(block.get('content'), str):
                return block['content']
            return str(block)
        return str(block)

    def estimated_tokens(self) -> int:
        """Estimate total tokens across all messages in history."""
        total = 0
        for msg in self.messages:
            for block in msg.content:
                total += estimate_tokens(self._block_text(block))
        return total

    def _compact_old_tool_results(self) -> None:
        """
        Shrink the bodies of old tool_result blocks in place until the history
        fits within ``token_budget``. Compacting (rather than dropping) keeps every
        tool_use/tool_result pair intact and preserves resource IDs/ARNs, which
        live at the head of cloud-API JSON.
        """
        if self.token_budget is None:
            return
        if self.estimated_tokens() <= self.token_budget:
            return

        compactable = max(0, len(self.messages) - self.recency_keep)
        head_chars, tail_chars, threshold = 400, 120, 600

        for i in range(compactable):
            msg = self.messages[i]
            changed = False
            for block in msg.content:
                if not isinstance(block, dict):
                    continue
                if block.get('type') != 'tool_result':
                    continue
                content = block.get('content')
                if not isinstance(content, str) or len(content) <= threshold:
                    continue
                if '[compacted' in content:
                    continue  # already compacted
                elided = len(content) - head_chars - tail_chars
                block['content'] = (
                    content[:head_chars]
                    + f"\n…[compacted {elided} chars]…\n"
                    + content[-tail_chars:]
                )
                changed = True
            if changed and self.estimated_tokens() <= self.token_budget:
                return

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
