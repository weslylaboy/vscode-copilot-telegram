import sys
from types import SimpleNamespace

import pytest

from vscode_copilot_telegram import runner
from vscode_copilot_telegram.runner import run_command, truncate


async def test_runs_and_captures_combined_output(tmp_path):
    cmd = f'"{sys.executable}" -c "import sys; print(\'out\'); print(\'err\', file=sys.stderr); sys.exit(3)"'
    r = await run_command(cmd, tmp_path, 30)
    assert r.exit_code == 3 and "out" in r.output and "err" in r.output


async def test_token_not_passed_to_child(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    cmd = f'"{sys.executable}" -c "import os; print(os.environ.get(\'TELEGRAM_BOT_TOKEN\', \'missing\'))"'
    r = await run_command(cmd, tmp_path, 30)
    assert r.output.strip() == "missing"


@pytest.mark.skipif(sys.platform == "win32", reason="posix sleep")
async def test_run_timeout_kills(tmp_path):
    r = await run_command("sleep 10", tmp_path, 0.5)
    assert r.timed_out and r.exit_code is None


def test_windows_kill_calls_taskkill_by_full_path(monkeypatch):
    # A bare "taskkill" could resolve to a taskkill.exe placed in the workspace.
    calls = []
    monkeypatch.setattr(runner.sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setattr(runner.subprocess, "run", lambda args, **kw: calls.append(args))
    runner._kill_tree(SimpleNamespace(pid=4242))
    assert calls == [[r"C:\Windows\System32\taskkill.exe", "/T", "/F", "/PID", "4242"]]


def test_truncate_keeps_head_and_tail():
    text = "A" * 1000 + "B" * 1000
    out = truncate(text, 500)
    assert len(out) <= 500 and out.startswith("A") and out.endswith("B") and "truncated" in out
    assert truncate("short", 500) == "short"
