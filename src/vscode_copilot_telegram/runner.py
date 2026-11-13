"""Run an approved command with a timeout and capture combined output."""

from __future__ import annotations

import asyncio
import contextlib
import ntpath
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Never hand our own secrets to commands Copilot runs.
_SCRUB_ENV = ("TELEGRAM_BOT_TOKEN",)


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    timed_out: bool = False


def truncate(text: str, limit: int) -> str:
    """Keep the start and (mostly) the end, where errors usually are."""
    if len(text) <= limit:
        return text
    marker = f"\n… [{len(text) - limit} characters truncated] …\n"
    keep = max(limit - len(marker), 0)
    head = keep // 4
    tail = keep - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    for k in _SCRUB_ENV:
        env.pop(k, None)
    return env


async def _spawn(command: str, cwd: Path, shell: str) -> asyncio.subprocess.Process:
    common: dict[str, Any] = {"cwd": str(cwd), "stdin": asyncio.subprocess.DEVNULL,
                              "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT,
                              "env": _child_env()}
    if sys.platform == "win32":
        common["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        common["start_new_session"] = True
    if shell in ("powershell", "pwsh"):
        exe = "powershell" if shell == "powershell" else "pwsh"
        return await asyncio.create_subprocess_exec(exe, "-NoProfile", "-NonInteractive", "-Command",
                                                    command, **common)
    if shell in ("bash", "sh"):
        return await asyncio.create_subprocess_exec(shell, "-c", command, **common)
    if shell == "cmd":
        return await asyncio.create_subprocess_exec("cmd.exe", "/d", "/s", "/c", command, **common)
    return await asyncio.create_subprocess_shell(command, **common)


def _taskkill_exe() -> str:
    # Full path on purpose: for a bare name Windows looks in the server's current
    # folder (often the workspace) before System32, so a taskkill.exe placed in the
    # project would run instead of the real one.
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return ntpath.join(root, "System32", "taskkill.exe")


def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    try:
        if sys.platform == "win32":
            # Fixed program and arguments; the only variable part is our own child's pid.
            subprocess.run([_taskkill_exe(), "/T", "/F", "/PID", str(proc.pid)],  # noqa: S603
                           capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):  # already gone
            proc.kill()


async def run_command(command: str, cwd: Path, timeout_s: float, shell: str = "default") -> RunResult:
    proc = await _spawn(command, cwd, shell)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return RunResult(exit_code=proc.returncode, output=out.decode("utf-8", errors="replace"))
    except asyncio.TimeoutError:
        _kill_tree(proc)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            out = b""
        text = (out or b"").decode("utf-8", errors="replace")
        return RunResult(exit_code=None, output=text + f"\n[killed after {timeout_s:.0f}s run timeout]",
                         timed_out=True)
