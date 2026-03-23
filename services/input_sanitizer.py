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
    # System prompt override attempts
    re.compile(r'<\s*system\s*>', re.IGNORECASE),
    re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>', re.IGNORECASE),
    re.compile(r'\bignore\s+(previous|above|all|prior)\s+(instructions?|prompts?|rules?|context)\b', re.IGNORECASE),
    re.compile(r'\bforget\s+(all\s+)?(previous|your|the)\s+(instructions?|rules?|training|context|guidelines?)\b', re.IGNORECASE),
    re.compile(r'\bdisregard\s+(all|previous|prior|your)\s+(instructions?|rules?|guidelines?|context)\b', re.IGNORECASE),
    re.compile(r'\byour\s+(real|true|actual|original)\s+instructions?\s+(are|say|tell|state)\b', re.IGNORECASE),
    re.compile(r'\bnew\s+system\s+prompt\s*:', re.IGNORECASE),
    re.compile(r'\boverride\s+(mode|instructions?|safety|guidelines?)\b', re.IGNORECASE),

    # DAN / jailbreak named patterns
    re.compile(r'\bdo\s+anything\s+now\b', re.IGNORECASE),
    re.compile(r'\bDAN\s+(mode|activated|enabled|is|prompt)\b', re.IGNORECASE),
    re.compile(r'\bjailbreak\s*(mode|activated|prompt|this|the\s+AI)?\b', re.IGNORECASE),
    re.compile(r'\bdeveloper\s+mode\s+(on|activated|enabled|unlocked)\b', re.IGNORECASE),
    re.compile(r'\bunrestricted\s+(mode|AI|assistant|access)\b', re.IGNORECASE),
    re.compile(r'\bno\s+restrictions?\s+(mode|AI|assistant|enabled)\b', re.IGNORECASE),
    re.compile(r'\bunlock\s+(mode|full\s+access|unrestricted|all\s+capabilities)\b', re.IGNORECASE),

    # Persona hijack patterns
    re.compile(r'\byou\s+are\s+now\b.{0,60}\bno\s+(restrictions?|rules?|limits?|guidelines?)\b', re.IGNORECASE),
    re.compile(r'\bact\s+as\s+(if\s+you\s+(are|have|were)|a)\b.{0,60}\bno\s+restrictions?\b', re.IGNORECASE),
    re.compile(r'\bpretend\s+(you\s+(are|have|were)|to\s+be)\b.{0,60}\bno\s+(rules?|restrictions?|limits?)\b', re.IGNORECASE),
    re.compile(r'\bsimulate\s+(being\s+)?(an?\s+AI|a\s+system)\s+(with(out)?|that\s+has\s+no)\b', re.IGNORECASE),
    re.compile(r'\byour\s+true\s+self\b', re.IGNORECASE),

    # Authority / privilege escalation claims
    re.compile(r'\b(I\s+am|this\s+is)\s+(Anthropic|the\s+developer|the\s+platform\s+admin|your\s+(creator|developer|operator))\b', re.IGNORECASE),
    re.compile(r'\banthropix?\s+override\b', re.IGNORECASE),
    re.compile(r'\benter\s+maintenance\s+mode\b', re.IGNORECASE),

    # Newline injection (trying to inject a fake system/assistant turn)
    re.compile(r'\n\s*(system|assistant)\s*:', re.IGNORECASE),
    re.compile(r'\\n\s*(system|assistant)\s*:', re.IGNORECASE),
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
