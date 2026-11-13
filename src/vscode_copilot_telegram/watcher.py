"""vscode-copilot-telegram-watch: mirror a project's Copilot chat sessions to Telegram.

Send-only: this process never calls getUpdates, so it can run next to the MCP server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .config import ConfigError, load_env_files, resolve_workspace_root, telegram_credentials
from .masking import mask_secrets
from .sessions import Turn, find_workspace_storage, session_files, session_title, turns_for_file
from .telegram import TelegramError, TelegramSender, split_message

log = logging.getLogger("vscode_copilot_telegram.watch")

ROLE_LABEL = {"user": "🧑 You", "assistant": "🤖 Copilot", "tool": "🔧 Copilot"}
MAX_SENT_KEYS = 5000


@dataclass
class FileState:
    mtime: float = 0.0
    size: int = -1
    sent: list[str] = field(default_factory=list)
    # key -> [text hash, first time this exact text was seen]; for replies still streaming
    pending: dict[str, list] = field(default_factory=dict)


class WatchState:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.files: dict[str, FileState] = {}
        self.loaded = False
        if path and path.is_file():
            try:
                raw = json.loads(path.read_text("utf-8"))
                for k, v in (raw.get("files") or {}).items():
                    self.files[k] = FileState(v.get("mtime", 0.0), v.get("size", -1), list(v.get("sent", [])),
                                              dict(v.get("pending", {})))
                self.loaded = True
            except (OSError, ValueError, AttributeError):
                log.warning("state file %s unreadable; starting fresh", path)

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"files": {k: {"mtime": v.mtime, "size": v.size, "sent": v.sent[-MAX_SENT_KEYS:],
                              "pending": v.pending} for k, v in self.files.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        tmp.replace(self.path)


def default_state_path(project: Path) -> Path:
    digest = hashlib.sha256(str(project).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".vscode-copilot-telegram" / f"watch-{project.name}-{digest}.json"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def format_messages(project: str, turns: list[Turn], title: str | None = None) -> list[str]:
    """Group consecutive turns by role and render Telegram-sized plain-text messages."""
    groups: list[tuple[str, list[str]]] = []
    for t in turns:
        role = "assistant" if t.role == "tool" else t.role
        if groups and groups[-1][0] == role:
            groups[-1][1].append(t.text)
        else:
            groups.append((role, [t.text]))
    tag = f"[{project}" + (f" · {title}" if title else "") + "]"
    out: list[str] = []
    for role, texts in groups:
        body = mask_secrets("\n\n".join(texts))
        out.extend(split_message(body, prefix=f"{tag} {ROLE_LABEL.get(role, role)}:\n"))
    return out


class Watcher:
    def __init__(self, project: Path, send: Callable[[str], Any], state: WatchState,
                 storage_dirs: list[Path] | None = None, source: str = "auto", settle_s: float = 8.0,
                 include_tools: bool = True, backfill: int = 0, clock: Callable[[], float] = time.time) -> None:
        self.project = project
        self.name = project.name
        self.send = send
        self.state = state
        self.fixed_storage = storage_dirs
        self.source = source
        self.settle_s = settle_s
        self.include_tools = include_tools
        self.backfill = backfill
        self.clock = clock
        self.started_at = clock()

    def storage_dirs(self) -> list[Path]:
        return self.fixed_storage if self.fixed_storage is not None else find_workspace_storage(self.project)

    def files(self) -> list[Path]:
        out: list[Path] = []
        for d in self.storage_dirs():
            out.extend(session_files(d, self.source))
        return out

    def poll_once(self) -> int:
        """Check every session file once; return the number of Telegram messages sent."""
        sent = 0
        for f in self.files():
            try:
                st = f.stat()
            except OSError:
                continue
            key = str(f)
            fs = self.state.files.get(key)
            if fs is None:
                fs = FileState()
                self.state.files[key] = fs
                if st.st_mtime < self.started_at - 1:
                    # existed before we started: don't flood the chat with history
                    self._baseline(f, fs, keep_last=self.backfill)
                    fs.mtime, fs.size = st.st_mtime, st.st_size
                    self.state.save()
                    continue
            changed = (st.st_mtime != fs.mtime or st.st_size != fs.size)
            if not changed and not fs.pending:
                continue
            sent += self._process(f, fs)
            fs.mtime, fs.size = st.st_mtime, st.st_size
            self.state.save()
        return sent

    def _baseline(self, f: Path, fs: FileState, keep_last: int) -> None:
        turns = [t for t in turns_for_file(f, self.include_tools) if t.complete]
        cut = len(turns) - keep_last if keep_last > 0 else len(turns)
        fs.sent.extend(t.key for t in turns[:max(cut, 0)])

    def _process(self, f: Path, fs: FileState) -> int:
        turns = turns_for_file(f, self.include_tools)
        seen = set(fs.sent)
        now = self.clock()
        ready: list[Turn] = []
        for t in turns:
            if t.key in seen:
                continue
            if not t.complete:
                h = _hash(t.text)
                prev = fs.pending.get(t.key)
                if prev is None or prev[0] != h:
                    fs.pending[t.key] = [h, now]
                    break  # keep order: nothing after a still-streaming reply
                if now - float(prev[1]) < self.settle_s:
                    break
            ready.append(t)
        if not ready:
            return 0
        title = session_title(f)
        messages = format_messages(self.name, ready, title)
        count = 0
        for m in messages:
            self.send(m)  # raises on failure -> nothing marked as sent, retried next poll
            count += 1
        for t in ready:
            fs.sent.append(t.key)
            fs.pending.pop(t.key, None)
        return count


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="vscode-copilot-telegram-watch", description=__doc__)
    ap.add_argument("--workspace", help="Project folder (default: $WORKSPACE_ROOT or the current directory)")
    ap.add_argument("--storage", action="append",
                    help="Explicit workspaceStorage/<hash> folder(s); skips auto-detection")
    ap.add_argument("--interval", type=float, default=2.0, help="Seconds between checks (default 2)")
    ap.add_argument("--settle", type=float, default=8.0,
                    help="Send a reply that has no completion marker after it stops changing for N seconds")
    ap.add_argument("--source", choices=["auto", "chatsessions", "transcripts", "both"], default="auto")
    ap.add_argument("--backfill", type=int, default=0,
                    help="On first sight of an existing session, also send its last N messages")
    ap.add_argument("--no-tools", action="store_true", help="Leave out tool-call / file-edit lines")
    ap.add_argument("--state-file", help="Where to remember what was sent (default ~/.vscode-copilot-telegram/)")
    ap.add_argument("--dry-run", action="store_true", help="Print messages instead of sending (no token needed)")
    ap.add_argument("--list", action="store_true", help="Show matched storage folders and session files, then exit")
    ap.add_argument("--once", action="store_true", help="Check once and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, stream=sys.stderr,
                        format="%(asctime)s vscode-copilot-telegram-watch %(levelname)s %(message)s")

    project = resolve_workspace_root(args.workspace)
    load_env_files(project)
    storage = [Path(s).expanduser() for s in args.storage] if args.storage else None

    if args.list:
        dirs = storage if storage is not None else find_workspace_storage(project)
        print(f"project: {project}")
        if not dirs:
            print("no matching workspaceStorage folder found. Open the folder in VS Code and send one chat "
                  "message, or pass --storage.")
            sys.exit(1)
        for d in dirs:
            print(f"storage: {d}")
            files = session_files(d, args.source)
            if not files:
                print("  (no session files yet)")
            for f in files:
                turns = turns_for_file(f, not args.no_tools)
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
                print(f"  {f}  [{when}, {len(turns)} messages]")
        return

    send: Callable[[str], Any]
    if args.dry_run:
        def print_message(text: str) -> None:
            print(text + "\n" + "-" * 40, flush=True)
        send = print_message
        state = WatchState(None)
    else:
        try:
            creds = telegram_credentials()
        except ConfigError as exc:
            sys.exit(f"vscode-copilot-telegram-watch: {exc}")
        sender = TelegramSender(creds.token, creds.user_id)
        send = sender.send_message
        state = WatchState(Path(args.state_file).expanduser() if args.state_file else default_state_path(project))

    w = Watcher(project, send, state, storage_dirs=storage, source=args.source, settle_s=args.settle,
                include_tools=not args.no_tools, backfill=args.backfill)
    if not state.loaded:
        # First run for this project: treat everything already on disk as history.
        w.started_at = time.time()
    log.info("watching %s (every %.1fs). Ctrl+C to stop.", project, args.interval)
    warned = False
    while True:
        try:
            if not w.storage_dirs():
                if not warned:
                    log.warning("no VS Code workspaceStorage for %s yet; waiting…", project)
                    warned = True
            else:
                warned = False
                n = w.poll_once()
                if n:
                    log.info("sent %d message(s)", n)
        except TelegramError as exc:
            log.warning("Telegram send failed (will retry): %s", exc)
        except KeyboardInterrupt:
            break
        except Exception:  # noqa: BLE001 - never die on a weird file
            log.exception("watch loop error")
        if args.once:
            break
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
