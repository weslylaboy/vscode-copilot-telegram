"""Allow/block decisions for commands before anyone is asked."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# Denied without asking. Users can add more in vscode-copilot-telegram.toml ``block``.
DEFAULT_BLOCK: list[str] = [
    # rm -rf on /, /*, ~, $HOME, or with --no-preserve-root
    r"\brm\s+(?:-[^\s]*\s+)*-[^\s]*[rR][^\s]*\s+(?:-[^\s]*\s+)*(?:/|/\*|~|~/|~/\*|\$HOME|\$\{HOME\})(?=$|[\s;&|])",
    r"\brm\b.*--no-preserve-root",
    # force pushes (--force, -f, --force-with-lease, +refspec)
    r"\bgit\s+push\b.*(?:\s--force(?:-with-lease)?\b|\s-[a-zA-Z]*f[a-zA-Z]*\b|\s\+\S)",
    # filesystem destruction
    r"\bmkfs(?:\.\w+)?\b",
    r"\bdd\b.*\bof=/dev/",
    r">\s*/dev/(?:sd|nvme|disk|hd)\w*",
    r"\bchmod\s+(?:-\w+\s+)*-R\s+0?777\s+/(?=$|\s)",
    # piping downloads straight into a shell
    r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:ba|z|k|da|fi)?sh\b",
    r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?python[0-9.]*\b",
    r"\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b.*\|\s*(?:iex|Invoke-Expression)\b",
    # fork bomb
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # Windows disk wipes
    r"\bformat\s+[a-zA-Z]:",
    r"\b(?:rd|rmdir)\s+/s\b.*\b[a-zA-Z]:\\?(?=$|\s)",
    r"\bRemove-Item\b.*-Recurse\b.*\s[a-zA-Z]:\\?\*?(?=$|\s)",
    # power state
    r"^\s*(?:sudo\s+)?(?:shutdown|reboot|halt|poweroff)\b",
]

# Shell metacharacters that chain or substitute commands. An allow-list match is
# only trusted when none of these appear, so "npm test && rm -rf src" is never
# auto-approved just because it starts with "npm test".
_CHAINING = re.compile(r"(;|&&|\|\||\||`|\$\(|\n|\r|>|<|&\s*$)")


class Verdict(str, Enum):
    BLOCK = "block"
    ALLOW = "allow"
    ASK = "ask"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    pattern: str | None = None


def compile_patterns(patterns: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for p in patterns:
        try:
            out.append((p, re.compile(p, re.IGNORECASE)))
        except re.error as exc:
            raise ValueError(f"invalid regex {p!r}: {exc}") from exc
    return out


class CommandPolicy:
    """Block list wins over allow list. Allow patterns must match the whole command."""

    def __init__(self, allow: list[str] | None = None, block: list[str] | None = None,
                 use_default_block: bool = True) -> None:
        block_list = (DEFAULT_BLOCK if use_default_block else []) + list(block or [])
        self._block = compile_patterns(block_list)
        self._allow = compile_patterns(list(allow or []))

    def evaluate(self, command: str) -> Decision:
        cmd = command.strip()
        if not cmd:
            return Decision(Verdict.BLOCK, "<empty command>")
        for raw, rx in self._block:
            if rx.search(cmd):
                return Decision(Verdict.BLOCK, raw)
        if not _CHAINING.search(cmd):
            for raw, rx in self._allow:
                if rx.fullmatch(cmd):
                    return Decision(Verdict.ALLOW, raw)
        return Decision(Verdict.ASK)
