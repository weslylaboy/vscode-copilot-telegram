"""Mask secrets before any text leaves the machine for Telegram."""

from __future__ import annotations

import re

MASK = "***"

# Order matters: multi-line blocks first, then specific tokens, then generic patterns.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks (RSA, EC, OPENSSH, PGP, plain).
    (
        re.compile(
            r"-----BEGIN ([A-Z0-9 ]*)PRIVATE KEY( BLOCK)?-----.*?-----END \1PRIVATE KEY( BLOCK)?-----",
            re.DOTALL,
        ),
        "-----PRIVATE KEY " + MASK + "-----",
    ),
    # A BEGIN without an END (truncated output) still hides the rest.
    (re.compile(r"-----BEGIN ([A-Z0-9 ]*)PRIVATE KEY( BLOCK)?-----.*", re.DOTALL), "-----PRIVATE KEY " + MASK + "-----"),
    # GitHub tokens: classic/OAuth/user/server/refresh and fine-grained PATs.
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github_pat_" + MASK),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "gh*_" + MASK),
    # AWS access key ids.
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "AKIA" + MASK),
    # Slack, OpenAI/Anthropic-style, Google API keys, Telegram bot tokens.
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "xox-" + MASK),
    (re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"), "sk-" + MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "AIza" + MASK),
    (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b"), "<telegram-token " + MASK + ">"),
    # Authorization headers / bearer tokens.
    (re.compile(r"(?i)\b(Bearer|Basic|token)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 " + MASK),
    # URLs with credentials: scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@"), r"\1" + MASK + "@"),
    # .env-style assignments whose name looks sensitive: KEY=value, export KEY="value", KEY: value
    (
        re.compile(
            r"(?im)^(\s*(?:export\s+|set\s+|\$env:)?"
            r"[A-Z0-9_.-]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIALS?|AUTH|_KEY)[A-Z0-9_.-]*"
            r"\s*[=:]\s*)(['\"]?)[^\s'\"]+\2"
        ),
        r"\1\2" + MASK + r"\2",
    ),
]


def mask_secrets(text: str) -> str:
    """Return ``text`` with likely secrets replaced by ``***``."""
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
