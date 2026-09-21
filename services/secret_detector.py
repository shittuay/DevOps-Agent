"""
Secret Detection & Redaction Service

Inspired by OpenClaw's detect-secrets integration. Scans text for
accidentally exposed credentials and redacts them before display.
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

REDACT_PLACEHOLDER = '[REDACTED]'

# Each pattern: (name, compiled regex, group_to_redact or None for full match)
SECRET_PATTERNS: List[Tuple[str, re.Pattern, int]] = [
    # AWS Access Key ID (starts with AKIA)
    ('AWS Access Key', re.compile(r'\b(AKIA[0-9A-Z]{16})\b'), 1),

    # AWS Secret Access Key (40-char base64)
    ('AWS Secret Key', re.compile(r'(?:aws_secret_access_key|secret.?key)\s*[=:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?', re.IGNORECASE), 1),

    # Generic API Key patterns
    # 'api[_-]?key' already matches 'apikey' via the optional separator, so a
    # separate '|apikey' alternative never fires.
    ('API Key', re.compile(r'(?:api[_-]?key)\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?', re.IGNORECASE), 1),

    # Anthropic API Key
    ('Anthropic Key', re.compile(r'\b(sk-ant-[A-Za-z0-9_\-]{20,})\b'), 1),

    # OpenAI API Key
    ('OpenAI Key', re.compile(r'\b(sk-[A-Za-z0-9]{20,})\b'), 1),

    # Stripe Secret Key
    ('Stripe Secret', re.compile(r'\b(sk_(?:live|test)_[A-Za-z0-9]{20,})\b'), 1),

    # Stripe Publishable Key
    ('Stripe Publishable', re.compile(r'\b(pk_(?:live|test)_[A-Za-z0-9]{20,})\b'), 1),

    # GitHub Token
    ('GitHub Token', re.compile(r'\b(gh[pousr]_[A-Za-z0-9_]{36,})\b'), 1),

    # Generic Bearer Token
    ('Bearer Token', re.compile(r'Bearer\s+([A-Za-z0-9_\-.]{20,})', re.IGNORECASE), 1),

    # Private Key Block
    ('Private Key', re.compile(r'(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)', re.IGNORECASE), 1),

    # Azure Client Secret (UUID-like followed by secret)
    ('Azure Secret', re.compile(r'(?:client.?secret|azure.?secret)\s*[=:]\s*["\']?([A-Za-z0-9_\-.~]{30,})["\']?', re.IGNORECASE), 1),

    # GCP Service Account Key indicator
    ('GCP Key', re.compile(r'"private_key"\s*:\s*"(-----BEGIN)', re.IGNORECASE), 0),

    # Database connection strings with passwords
    ('DB Password', re.compile(r'(?:postgres|mysql|mongodb)(?:ql)?://[^:]+:([^@\s]{8,})@', re.IGNORECASE), 1),

    # Generic password in key=value
    ('Password', re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']{8,})["\']?', re.IGNORECASE), 1),

    # Slack webhook URL
    ('Slack Webhook', re.compile(r'(https://hooks\.slack\.com/services/[A-Za-z0-9/]+)'), 1),

    # Discord webhook URL
    ('Discord Webhook', re.compile(r'(https://discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+)'), 1),
]


def scan_for_secrets(text: str) -> List[dict]:
    """
    Scan text for potential secrets/credentials.

    Args:
        text: Text to scan

    Returns:
        List of dicts with 'type', 'match', 'start', 'end' for each found secret
    """
    if not text:
        return []

    findings = []
    for name, pattern, group in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({
                'type': name,
                'match': match.group(group),
                'start': match.start(group),
                'end': match.end(group),
            })

    if findings:
        types = set(f['type'] for f in findings)
        logger.warning(f"Secrets detected in text: {', '.join(types)}")

    return findings


def redact_secrets(text: str) -> str:
    """
    Scan text and replace any detected secrets with [REDACTED].

    Args:
        text: Text potentially containing secrets

    Returns:
        Text with secrets redacted
    """
    if not text:
        return ''

    findings = scan_for_secrets(text)
    if not findings:
        return text

    # Sort by position descending so replacements don't shift indices
    findings.sort(key=lambda f: f['start'], reverse=True)

    result = text
    for finding in findings:
        secret = finding['match']
        # Show first 4 chars for identification, redact the rest
        if len(secret) > 8:
            preview = secret[:4] + '...' + REDACT_PLACEHOLDER
        else:
            preview = REDACT_PLACEHOLDER
        result = result[:finding['start']] + preview + result[finding['end']:]

    return result


def contains_secrets(text: str) -> bool:
    """Quick check if text contains any secrets."""
    return len(scan_for_secrets(text)) > 0
