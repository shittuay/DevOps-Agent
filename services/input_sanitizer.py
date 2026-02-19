"""
Input Sanitization Service

Sanitizes user input before processing to prevent prompt injection,
command injection, and other attacks.

Two distinct functions:
  sanitize_input()   — clean the text (strip dangerous chars, normalize unicode)
  validate_message() — check content policy (length limits, injection patterns)
"""

import re
import unicodedata
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Absolute max length — hard truncation to prevent memory exhaustion
MAX_INPUT_LENGTH = 50000

# Practical message length limit for chat (enforced by validate_message)
MAX_MESSAGE_LENGTH = 10000

# Null and dangerous control characters to strip
DANGEROUS_CHARS = set(range(0x00, 0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x20)) | {0x7F}
# Keep: 0x09 (tab), 0x0A (newline), 0x0D (carriage return)

# Unicode categories to strip (format chars, private use, surrogates)
STRIP_CATEGORIES = {'Cf', 'Co', 'Cs'}

# Patterns that look like prompt injection attempts — BLOCK these
INJECTION_PATTERNS = [
    re.compile(r'<\s*system\s*>', re.IGNORECASE),
    re.compile(r'\bignore\s+(previous|above|all)\s+(instructions|prompts)\b', re.IGNORECASE),
    re.compile(r'\byou\s+are\s+now\b.*\bassistant\b', re.IGNORECASE),
    re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>', re.IGNORECASE),
    re.compile(r'\bdo\s+anything\s+now\b', re.IGNORECASE),                     # DAN-style
    re.compile(r'\bforget\s+(all\s+)?(previous|your)\s+(instructions|rules|training)\b', re.IGNORECASE),
    re.compile(r'\bact\s+as\s+(if\s+you\s+are|a)\b.{0,40}\bno\s+restrictions\b', re.IGNORECASE),
]


def sanitize_input(text: str) -> str:
    """
    Sanitize user input text.

    - Strips null bytes and dangerous control characters
    - Normalizes Unicode to NFC form
    - Strips Unicode format/control characters
    - Hard-truncates to MAX_INPUT_LENGTH

    Does NOT check content policy — call validate_message() for that.

    Args:
        text: Raw user input

    Returns:
        Sanitized text
    """
    if not text:
        return ''

    # Truncate to prevent memory exhaustion
    if len(text) > MAX_INPUT_LENGTH:
        original_len = len(text)
        text = text[:MAX_INPUT_LENGTH]
        logger.warning(f"Input hard-truncated from {original_len} to {MAX_INPUT_LENGTH} chars")

    # Strip null bytes
    text = text.replace('\x00', '')

    # Strip dangerous control characters
    text = ''.join(
        ch for ch in text
        if ord(ch) not in DANGEROUS_CHARS
    )

    # Normalize Unicode to NFC (canonical decomposition + composition)
    text = unicodedata.normalize('NFC', text)

    # Strip Unicode format/control characters (invisible chars that can confuse LLMs)
    text = ''.join(
        ch for ch in text
        if unicodedata.category(ch) not in STRIP_CATEGORIES
    )

    return text.strip()


def validate_message(text: str) -> Tuple[bool, str]:
    """
    Check whether a message passes content policy.

    Checks:
    - Length <= MAX_MESSAGE_LENGTH
    - No prompt injection patterns

    Args:
        text: Already-sanitized user message

    Returns:
        (is_valid, reason) — is_valid=False means the message should be rejected.
    """
    if len(text) > MAX_MESSAGE_LENGTH:
        return False, f"Message too long ({len(text)} chars). Maximum is {MAX_MESSAGE_LENGTH}."

    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(f"Prompt injection pattern blocked: {pattern.pattern!r}")
            return False, "Message blocked: contains prompt injection patterns."

    return True, ""


def sanitize_output(text: str) -> str:
    """
    Sanitize AI output before displaying to user.

    - Strips null bytes
    - Strips dangerous control characters
    - Normalizes Unicode

    Args:
        text: Raw AI output

    Returns:
        Sanitized text
    """
    if not text:
        return ''

    text = text.replace('\x00', '')
    text = ''.join(
        ch for ch in text
        if ord(ch) not in DANGEROUS_CHARS
    )
    text = unicodedata.normalize('NFC', text)

    return text
