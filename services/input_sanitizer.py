"""
Input Sanitization Service

Inspired by OpenClaw's security patterns. Sanitizes user input before
processing to prevent prompt injection, command injection, and other attacks.
"""

import re
import unicodedata
import logging

logger = logging.getLogger(__name__)

# Maximum input length (prevent memory exhaustion)
MAX_INPUT_LENGTH = 50000

# Null and dangerous control characters to strip
DANGEROUS_CHARS = set(range(0x00, 0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x20)) | {0x7F}
# Keep: 0x09 (tab), 0x0A (newline), 0x0D (carriage return)

# Unicode categories to strip (format chars, private use, surrogates)
STRIP_CATEGORIES = {'Cf', 'Co', 'Cs'}

# Patterns that look like prompt injection attempts
INJECTION_PATTERNS = [
    re.compile(r'<\s*system\s*>', re.IGNORECASE),
    re.compile(r'\bignore\s+(previous|above|all)\s+(instructions|prompts)\b', re.IGNORECASE),
    re.compile(r'\byou\s+are\s+now\b.*\bassistant\b', re.IGNORECASE),
    re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>', re.IGNORECASE),
]


def sanitize_input(text: str) -> str:
    """
    Sanitize user input text.

    - Strips null bytes and dangerous control characters
    - Normalizes Unicode to NFC form
    - Strips Unicode format/control characters
    - Truncates to max length
    - Logs potential injection attempts (does not block)

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
        logger.warning(f"Input truncated from {original_len} to {MAX_INPUT_LENGTH} chars")

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

    # Log potential prompt injection attempts (don't block — just alert)
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning(f"Potential prompt injection detected: {pattern.pattern}")
            break

    return text.strip()


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
