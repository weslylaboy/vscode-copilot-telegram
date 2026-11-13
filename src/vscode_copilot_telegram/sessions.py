"""Find and parse VS Code Copilot chat session files.

Formats handled (all defensively; unknown shapes are skipped, never fatal):

1. ``chatSessions/<id>.json``  (VS Code < 1.109): one JSON object
   ``{"version": 3, "sessionId": ..., "requests": [{"requestId", "message": {"text"}, "response": [parts]}]}``
2. ``chatSessions/<id>.jsonl`` (VS Code >= 1.109): an append-only operation log.
   Each line is ``{"kind": 0, "v": <full session>}`` (snapshot), ``{"kind": 1, "k": [path], "v": value}`` (set),
   ``{"kind": 2, "k": [path], "v": [items], "i": index?}`` (push / splice), or ``{"kind": 3, "k": [path]}`` (delete).
   Replaying the log yields the same object as format 1.
3. ``GitHub.copilot-chat/transcripts/<id>.jsonl`` (newer Copilot Chat builds / Copilot harness):
   a ``type``-discriminated event log (``user.message``, ``assistant.message``, ``tool.execution_start`` ...)
   with the payload under ``data``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

EDITIONS = ("Code", "Code - Insiders", "VSCodium")

# Response part kinds that are UI chrome or private reasoning, never mirrored.
SKIP_KINDS = {"thinking", "progressMessage", "progressTask", "progressTaskSerialized", "warning", "info",
              "systemNotification", "mcpServersStarting", "mcpServersStartingSlow", "voiceProgress",
              "undoStop", "codeblockUri", "prepareToolInvocation", "references", "command", "pullRequest"}


@dataclass(frozen=True)
class Turn:
    key: str        # stable id used for dedupe across restarts
    role: str       # user | assistant | tool
    text: str
    complete: bool = True


# ---------------------------------------------------------------- locating

def user_data_dirs() -> list[Path]:
    """VS Code 'User' folders for every edition on this OS (override: VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS)."""
    override = os.environ.get("VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS")
    if override:
        return [Path(p).expanduser() for p in override.split(os.pathsep) if p]
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    dirs = [base / e / "User" for e in EDITIONS]
    # VS Code Server / Remote (tunnels, SSH, WSL) keeps data here on the remote host
    dirs.append(Path.home() / ".vscode-server" / "data" / "User")
    dirs.append(Path.home() / ".vscode-server-insiders" / "data" / "User")
    return dirs


def file_uri_to_path(uri: str) -> str | None:
    """``file:///c%3A/Users/me/proj`` -> ``c:/Users/me/proj``; ``file:///home/me/p`` -> ``/home/me/p``."""
    if not isinstance(uri, str):
        return None
    parsed = urlparse(uri)
    if parsed.scheme not in ("file", "vscode-remote", "vscode-vfs"):
        return None
    path = unquote(parsed.path)
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":  # /c:/...
        path = path[1:]
    if parsed.scheme == "file" and parsed.netloc and parsed.netloc != "localhost":  # UNC
        path = f"//{parsed.netloc}{path}"
    return path


def normalize_path(p: str | os.PathLike[str]) -> str:
    s = str(p).replace("\\", "/").rstrip("/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].lower() + s[1:]
    if sys.platform in ("win32", "darwin"):  # case-insensitive file systems by default
        s = s.casefold()
    return s


def find_workspace_storage(project: Path, roots: Iterable[Path] | None = None) -> list[Path]:
    """Return every workspaceStorage/<hash> folder whose workspace.json points at ``project``."""
    try:
        target = normalize_path(Path(project).expanduser().resolve())
    except OSError:
        target = normalize_path(project)
    matches: list[Path] = []
    for user_dir in roots if roots is not None else user_data_dirs():
        ws_root = Path(user_dir) / "workspaceStorage"
        if not ws_root.is_dir():
            continue
        for wj in ws_root.glob("*/workspace.json"):
            try:
                data = json.loads(wj.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            folder = file_uri_to_path(data.get("folder", "")) if isinstance(data, dict) else None
            if folder and normalize_path(folder) == target:
                matches.append(wj.parent)
    return sorted(matches, key=lambda p: _mtime(p), reverse=True)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def session_files(storage_dir: Path, source: str = "auto") -> list[Path]:
    """Session files under one workspaceStorage folder.

    source: ``chatsessions``, ``transcripts``, ``both``, or ``auto`` (chatSessions if any exist, else transcripts).
    When ``<id>.json`` and ``<id>.jsonl`` both exist, the ``.jsonl`` wins.
    """
    chat_dir = storage_dir / "chatSessions"
    by_id: dict[str, Path] = {}
    if chat_dir.is_dir():
        for f in sorted(chat_dir.glob("*.json")):
            by_id.setdefault(f.stem, f)
        for f in sorted(chat_dir.glob("*.jsonl")):
            by_id[f.stem] = f
    chats = sorted(by_id.values())
    transcripts: list[Path] = []
    for name in ("GitHub.copilot-chat", "github.copilot-chat"):
        tdir = storage_dir / name / "transcripts"
        if tdir.is_dir():
            transcripts = sorted(tdir.glob("*.jsonl"))
            break
    if source == "chatsessions":
        return chats
    if source == "transcripts":
        return transcripts
    if source == "both":
        return chats + transcripts
    return chats or transcripts


def is_transcript(path: Path) -> bool:
    return path.parent.name == "transcripts"


# ---------------------------------------------------------------- JSONL op-log replay

def _container_get(obj: Any, key: Any) -> Any:
    if isinstance(obj, list):
        return obj[int(key)]
    return obj[key]


def _walk(state: Any, path: list[Any], create: bool) -> Any:
    cur = state
    for i, key in enumerate(path):
        if isinstance(cur, list):
            cur = cur[int(key)]
        elif isinstance(cur, dict):
            if key not in cur or cur[key] is None:
                if not create:
                    raise KeyError(key)
                nxt = path[i + 1] if i + 1 < len(path) else None
                cur[key] = [] if isinstance(nxt, int) else {}
            cur = cur[key]
        else:
            raise KeyError(key)
    return cur


def _set(state: Any, path: list[Any], value: Any) -> Any:
    if not path:
        return value
    parent = _walk(state, path[:-1], create=True)
    last = path[-1]
    if isinstance(parent, list):
        idx = int(last)
        if idx == len(parent):
            parent.append(value)
        else:
            parent[idx] = value
    else:
        parent[last] = value
    return state


def _push(state: Any, path: list[Any], value: Any, index: Any = None) -> Any:
    parent = _walk(state, path[:-1], create=True) if path else None
    if path:
        last = path[-1]
        try:
            target = _container_get(parent, last)
        except (KeyError, IndexError, TypeError):
            target = None
        if not isinstance(target, list):
            target = []
            _set(state, path, target)
    else:
        target = state
    if isinstance(index, int):
        del target[index:]
    if isinstance(value, list):
        target.extend(value)
    else:
        target.append(value)
    return state


def _delete(state: Any, path: list[Any]) -> Any:
    if not path:
        return None
    parent = _walk(state, path[:-1], create=False)
    last = path[-1]
    if isinstance(parent, list):
        del parent[int(last)]
    elif isinstance(parent, dict):
        parent.pop(last, None)
    return state


def replay_oplog(lines: Iterable[str]) -> dict | None:
    state: Any = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            op = json.loads(line)
        except ValueError:
            continue  # a partially written last line, or garbage
        if not isinstance(op, dict):
            continue
        kind = op.get("kind")
        try:
            if kind == 0:
                state = op.get("v")
            elif state is None:
                continue
            elif kind == 1:
                state = _set(state, list(op.get("k") or []), op.get("v"))
            elif kind == 2:
                state = _push(state, list(op.get("k") or []), op.get("v"), op.get("i"))
            elif kind == 3:
                state = _delete(state, list(op.get("k") or []))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return state if isinstance(state, dict) else None


def load_session(path: Path) -> dict | None:
    try:
        raw = Path(path).read_text("utf-8", errors="replace")
    except OSError:
        return None
    if path.suffix == ".jsonl":
        return replay_oplog(raw.splitlines())
    try:
        data = json.loads(raw)
    except ValueError:
        # file mid-write, or actually an op-log with a .json name
        return replay_oplog(raw.splitlines())
    if isinstance(data, dict) and "kind" in data and "v" in data:
        return replay_oplog(raw.splitlines())
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- text extraction

def _str(v: Any) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("value", "text", "content"):
            if isinstance(v.get(k), str):
                return v[k]
    return None


def _uri_basename(u: Any) -> str | None:
    path: Any
    if isinstance(u, str):
        path = file_uri_to_path(u) or u
    elif isinstance(u, dict):
        path = u.get("path") or u.get("fsPath") or u.get("external")
        if not isinstance(path, str):
            inner = u.get("uri") or (u.get("location") or {}).get("uri")
            return _uri_basename(inner) if inner is not None else (u.get("name") if isinstance(u.get("name"), str) else None)
    else:
        return None
    name = PurePosixPath(str(path).replace("\\", "/")).name
    return name or None


def user_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        if isinstance(message.get("text"), str):
            return message["text"]
        parts = message.get("parts")
        if isinstance(parts, list):
            return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))
    return ""


def response_text(parts: Any, include_tools: bool = True) -> str:
    if isinstance(parts, str):
        return parts
    if isinstance(parts, dict):
        parts = parts.get("value") if isinstance(parts.get("value"), list) else [parts]
    if not isinstance(parts, list):
        return ""
    out: list[str] = []
    last_edit: str | None = None

    def line(s: str) -> None:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(s + "\n")

    for p in parts:
        if isinstance(p, str):
            out.append(p)
            continue
        if not isinstance(p, dict):
            continue
        kind = p.get("kind")
        if kind in SKIP_KINDS:
            continue
        if kind in (None, "markdownContent", "markdownVuln"):
            v = _str(p.get("content")) if kind == "markdownContent" and p.get("content") is not None else None
            v = v if v is not None else _str(p.get("value"))
            if v:
                out.append(v)
                last_edit = None
        elif kind == "inlineReference":
            name = p.get("name") if isinstance(p.get("name"), str) else _uri_basename(p.get("inlineReference"))
            if name:
                out.append(f"`{name}`")
        elif kind in ("toolInvocationSerialized", "toolInvocation") and include_tools:
            msg = _str(p.get("pastTenseMessage")) or _str(p.get("invocationMessage"))
            tsd = p.get("toolSpecificData") or {}
            cmd = tsd.get("commandLine") if isinstance(tsd, dict) else None
            if isinstance(cmd, dict):
                cmd = cmd.get("toolEdited") or cmd.get("original")
            if isinstance(cmd, str) and cmd.strip():
                line(f"🔧 $ {cmd.strip()}")
            elif msg:
                line(f"🔧 {msg.strip()}")
        elif kind == "textEditGroup" and include_tools:
            name = _uri_basename(p.get("uri"))
            if name and name != last_edit:
                line(f"✏️ edited {name}")
                last_edit = name
        elif kind == "confirmation":
            title = _str(p.get("title")) or ""
            msg = _str(p.get("message")) or ""
            if title or msg:
                line(f"❔ {title} {msg}".strip())
    return "".join(out).strip()


def _request_complete(req: dict, is_last: bool) -> bool:
    if not is_last:
        return True
    if req.get("result") is not None:
        return True
    if req.get("isComplete") is True:
        return True
    ms = req.get("modelState")
    if isinstance(ms, dict) and (ms.get("completedAt") or ms.get("value") not in (None, 0)):
        return True
    return False


def turns_from_session(session: dict, include_tools: bool = True) -> list[Turn]:
    reqs = session.get("requests") if isinstance(session, dict) else None
    if not isinstance(reqs, list):
        return []
    turns: list[Turn] = []
    for i, req in enumerate(reqs):
        if not isinstance(req, dict):
            continue
        rid = str(req.get("requestId") or req.get("id") or f"idx{i}")
        prompt = user_text(req.get("message")).strip()
        if prompt:
            turns.append(Turn(f"{rid}:u", "user", prompt))
        reply = response_text(req.get("response"), include_tools)
        if reply:
            turns.append(Turn(f"{rid}:a", "assistant", reply, _request_complete(req, i == len(reqs) - 1)))
    return turns


def turns_from_transcript(path: Path, include_tools: bool = True) -> list[Turn]:
    try:
        lines = Path(path).read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    turns: list[Turn] = []
    for n, line in enumerate(lines):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        data = ev.get("data")
        if not isinstance(data, dict):
            data = ev
        key = str(ev.get("id") or data.get("messageId") or f"line{n}")
        if etype == "user.message":
            text = _str(data.get("content")) or _str(data.get("text")) or _str(data.get("message")) or ""
            if text.strip():
                turns.append(Turn(f"{key}:u", "user", text.strip()))
        elif etype == "assistant.message":
            text = _str(data.get("content")) or _str(data.get("text")) or _str(data.get("message")) or ""
            if text.strip():
                turns.append(Turn(f"{key}:a", "assistant", text.strip()))
        elif etype == "tool.execution_start" and include_tools:
            name = data.get("toolName") or data.get("name") or "tool"
            args = data.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            cmd = args.get("command") if isinstance(args, dict) else None
            if isinstance(cmd, str) and cmd.strip():
                turns.append(Turn(f"{key}:t", "tool", f"🔧 $ {cmd.strip()}"))
            else:
                target = None
                if isinstance(args, dict):
                    target = args.get("filePath") or args.get("path")
                label = f"🔧 {name}" + (f" {PurePosixPath(str(target).replace(chr(92), '/')).name}" if target else "")
                turns.append(Turn(f"{key}:t", "tool", label))
    return turns


def turns_for_file(path: Path, include_tools: bool = True) -> list[Turn]:
    if is_transcript(path):
        return turns_from_transcript(path, include_tools)
    session = load_session(path)
    return turns_from_session(session, include_tools) if session else []


def session_title(path: Path) -> str | None:
    if is_transcript(path):
        return None
    s = load_session(path)
    t = s.get("customTitle") if isinstance(s, dict) else None
    return t if isinstance(t, str) and t.strip() else None
