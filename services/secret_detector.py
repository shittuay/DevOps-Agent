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

    # AWS Secret Access Key (40-char base64). `["\']?` after the label lets the
    # JSON form ("SecretAccessKey": "...") match too; tool results are JSON.
    ('AWS Secret Key', re.compile(r'(?:aws_secret_access_key|secret_?access_?key|secret.?key)["\']?\s*[=:]\s*["\']?([A-Za-z0-9/+=]{40})["\']?', re.IGNORECASE), 1),

    # Generic API Key patterns
    # 'api[_-]?key' already matches 'apikey' via the optional separator, so a
    # separate '|apikey' alternative never fires.
    ('API Key', re.compile(r'(?:api[_-]?key)["\']?\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?', re.IGNORECASE), 1),

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

    # Private Key Block: the whole block, body included (matching only the
    # BEGIN line left the key itself in the text). An unterminated block,
    # e.g. a truncated result, is redacted to the end of the text.
    ('Private Key', re.compile(
        r'(-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'
        r'[\s\S]*?(?:-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|\Z))',
        re.IGNORECASE), 1),

    # Azure Client Secret (UUID-like followed by secret)
    ('Azure Secret', re.compile(r'(?:client.?secret|azure.?secret)["\']?\s*[=:]\s*["\']?([A-Za-z0-9_\-.~]{30,})["\']?', re.IGNORECASE), 1),

    # Database connection strings with passwords
    ('DB Password', re.compile(r'(?:postgres|mysql|mongodb)(?:ql)?://[^:]+:([^@\s]{8,})@', re.IGNORECASE), 1),

    # Generic password in key=value
    ('Password', re.compile(r'(?:password|passwd|pwd)["\']?\s*[=:]\s*["\']?([^\s"\']{8,})["\']?', re.IGNORECASE), 1),

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

    # Two patterns can match overlapping text (a "password=..." inside a DB URL,
    # or anything inside a key block). Keep the earliest, longest match and drop
    # any that overlap it, or the second replacement would splice into the first.
    findings.sort(key=lambda f: (f['start'], -(f['end'] - f['start'])))
    kept = []
    for finding in findings:
        if kept and finding['start'] < kept[-1]['end']:
            continue
        kept.append(finding)

    result = text
    for finding in reversed(kept):
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


# Tools whose purpose is to hand back a live secret value. Their results are
# never stored as-is (see approval_service); the requester downloads them once.
SECRET_DISCLOSING_TOOLS = frozenset({
    'get_secret_value', 'create_ec2_keypair', 'create_iam_access_key',
    'generate_s3_presigned_url', 'list_storage_account_keys', 'regenerate_storage_key',
    'terraform_state_pull', 'terraform_output', 'terraform_state_show',
})

# Field names (lowercased, separators removed) whose value is a credential.
# Matched on the whole name or as a suffix, so "SecretAccessKey" and
# "db_password" match but "secret_name", "SecretArn" and "NextToken" don't.
_SECRET_FIELD_SUFFIXES = (
    'password', 'passwd', 'secretaccesskey', 'secretkey', 'secretvalue', 'secretstring',
    'clientsecret', 'privatekey', 'keymaterial', 'apikey', 'accesstoken', 'refreshtoken',
    'authtoken', 'sessiontoken', 'bearertoken', 'authorization', 'connectionstring',
)


def _is_secret_field(name) -> bool:
    key = re.sub(r'[^a-z0-9]', '', str(name).lower())
    return key in ('secret', 'token') or key.endswith(_SECRET_FIELD_SUFFIXES)


def redact_structure(value):
    """Deep copy of a tool result/input with credentials masked.

    Masks credential-named fields outright and runs every other string through
    redact_secrets(), for anything persisted or shown to someone other than
    the caller (approval rows, the chat copy, reviewers' pages).
    """
    if isinstance(value, dict):
        return {k: (REDACT_PLACEHOLDER if _is_secret_field(k) and v not in (None, '')
                    else redact_structure(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_structure(v) for v in value]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


class StreamingRedactor:
    """Buffers streamed text so a secret split across small SSE chunks still gets redacted.

    `redact_secrets()` only sees whatever text is in the string it's given, but
    Anthropic's raw `content_block_delta` events are often just a handful of
    characters — most of SECRET_PATTERNS's 20+ char tokens land split across
    two or more chunks and match nothing when redacted one chunk at a time,
    even though the assembled response is redacted correctly before being
    saved to the DB. That gap let a secret the model echoed into its response
    text (e.g. from a `get_secret_value`/`create_ec2_keypair` tool result)
    reach the browser over the wire unredacted on the Claude streaming path.

    `feed()` holds back a trailing window of unredacted text on every call —
    long enough to contain any single pattern match — and only returns the
    portion that's safe to emit (no pending match can still extend into it).
    Call `flush()` once at the end of the stream to redact and return
    whatever text remains buffered.
    """

    # Longer than any SECRET_PATTERNS match is expected to realistically span
    # within one streamed chunk boundary. Not a hard guarantee against an
    # arbitrarily long secret spread across many tiny chunks (several patterns
    # use an unbounded `{20,}` capture), but closes the gap for every
    # real-world key/token format in SECRET_PATTERNS.
    TAIL_WINDOW = 120

    def __init__(self):
        self._buffer = ''

    def feed(self, chunk: str) -> str:
        """Add a streamed chunk; return the portion now safe to emit (already redacted)."""
        if not chunk:
            return ''
        self._buffer += chunk
        if len(self._buffer) <= self.TAIL_WINDOW:
            return ''

        cutoff = len(self._buffer) - self.TAIL_WINDOW
        findings = scan_for_secrets(self._buffer)
        # Never cut through the middle of a match still forming in the tail window.
        spanning_starts = [f['start'] for f in findings if f['start'] < cutoff < f['end']]
        if spanning_starts:
            cutoff = min(spanning_starts)

        to_emit, self._buffer = self._buffer[:cutoff], self._buffer[cutoff:]
        return redact_secrets(to_emit) if to_emit else ''

    def flush(self) -> str:
        """Redact and return any text still buffered at end of stream."""
        remaining, self._buffer = self._buffer, ''
        return redact_secrets(remaining) if remaining else ''
