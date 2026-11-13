"""Append-only JSONL audit log."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .masking import mask_secrets


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, *, request_id: str, type: str, decision: str, command: str | None = None,
              exit_code: int | None = None, **extra: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request_id": request_id,
            "type": type,
            "command": mask_secrets(command) if command is not None else None,
            "decision": decision,
            "exit_code": exit_code,
        }
        for k, v in extra.items():
            record[k] = mask_secrets(v) if isinstance(v, str) else v
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
