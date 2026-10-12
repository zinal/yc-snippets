"""Маскирование секретов в тексте, который скрипт сохраняет на диск."""

from __future__ import annotations

import re

_PEM_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)
_TOKEN_RE = re.compile(r"\bt1\.[A-Za-z0-9._=-]+")
_OAUTH_RE = re.compile(r"\by[0-3]_[A-Za-z0-9_-]+")
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|iam_token|oauth_token|secret|password|private_key)\b(\s*[:=]\s*)(\S+)"
)


def redact(text: str) -> str:
    if not text:
        return ""
    cleaned = _PEM_RE.sub("[REDACTED PRIVATE KEY]", text)
    cleaned = _TOKEN_RE.sub("[REDACTED IAM TOKEN]", cleaned)
    cleaned = _OAUTH_RE.sub("[REDACTED OAUTH TOKEN]", cleaned)
    cleaned = _ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", cleaned)
    return cleaned
