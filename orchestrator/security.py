"""Credential redaction for logs and error messages."""
from __future__ import annotations

import re

# Patterns that should never appear in logs or error output
PATTERNS: list[re.Pattern[str]] = [
    # API keys (sk-ant-..., sk-..., etc.)
    re.compile(r"sk-[A-Za-z0-9\-_]{20,}", re.IGNORECASE),
    # Generic "key = value" with long alphanumeric values
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|auth)[^\S\n]*[=:][^\S\n]*['\"]?([A-Za-z0-9\-_./+]{16,})['\"]?"),
    # Bearer tokens
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_./+]{16,}"),
    # Base64-looking long strings preceded by sensitive keywords
    re.compile(r"(?i)(authorization)[^\S\n]*[=:][^\S\n]*['\"]?([A-Za-z0-9+/=]{32,})['\"]?"),
]

_REDACTED = "[REDACTED]"


def sanitize_text(text: str) -> str:
    """Replace credential patterns in *text* with [REDACTED]."""
    for pattern in PATTERNS:
        # For patterns with capture groups, replace only the sensitive group
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(0).replace(m.group(m.lastindex or 1), _REDACTED), text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text
