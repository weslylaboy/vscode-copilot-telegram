"""Start the real MCP server over stdio and talk to it with the MCP SDK client.

Telegram is pointed at a closed local port, so nothing leaves the machine and every
call that needs Telegram must fail closed.
"""

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _params(workspace, **env):
    base = {k: v for k, v in os.environ.items() if k not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID")}
    base.update({"TELEGRAM_BOT_TOKEN": "123456:FAKE-TOKEN-FOR-TESTS", "TELEGRAM_USER_ID": "4242",
                 "VSCODE_COPILOT_TELEGRAM_API_BASE": "http://127.0.0.1:9",
                 "LOG_PATH": str(workspace / ".vscode-copilot-telegram" / "audit.jsonl"), **env})
    return StdioServerParameters(command=sys.executable, args=["-m", "vscode_copilot_telegram", "--log-level", "WARNING"],
                                 env=base, cwd=str(workspace))


def _schema(tool):  # mcp 2.x: input_schema, mcp 1.x: inputSchema
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")


def _payload(result):
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    text = result.content[0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


async def test_server_lists_tools_and_fails_closed(workspace):
    marker = workspace / "should-not-exist"
    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            assert set(tools) == {"ask_user", "run_command", "notify"}
            props = _schema(tools["run_command"])["properties"]
            assert {"command", "reason", "cwd", "timeout_s"} <= set(props)
            assert set(_schema(tools["run_command"])["required"]) == {"command", "reason"}
            assert {"question", "options", "timeout_s"} <= set(_schema(tools["ask_user"])["properties"])

            r = _payload(await session.call_tool("run_command", {"command": "ls", "reason": "x", "cwd": "/"}))
            assert r["decision"] == "rejected"

            cmd = f'"{sys.executable}" -c "open(r\'{marker}\', \'w\').close()"'
            r = _payload(await session.call_tool("run_command", {"command": cmd, "reason": "x"}))
            assert r["decision"] == "denied-error" and r["exit_code"] is None
            assert not marker.exists()

            r = _payload(await session.call_tool("ask_user", {"question": "hi?"}))
            assert str(r).startswith("error:")
            r = _payload(await session.call_tool("notify", {"message": "hello"}))
            assert str(r).startswith("error:")
    audit = (workspace / ".vscode-copilot-telegram" / "audit.jsonl").read_text().splitlines()
    assert [json.loads(x)["decision"] for x in audit][:2] == ["rejected", "denied-error"]


async def test_server_without_credentials_refuses(workspace):
    params = _params(workspace)
    params.env.pop("TELEGRAM_BOT_TOKEN")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = _payload(await session.call_tool("run_command", {"command": "echo hi", "reason": "x"}))
            assert r["decision"] == "denied-error" and "TELEGRAM_BOT_TOKEN" in r["output"]


# ---- VS Code first: the server asks with an MCP elicitation form ----

def _form(action="accept", **content):
    from mcp import types
    return types.ElicitResult(action=action, content=content or None)


def _python_cmd(code):
    return f'"{sys.executable}" -c "{code}"'


async def test_vscode_form_approves_and_runs_without_telegram(workspace):
    marker = workspace / "ran-after-vscode-approval"
    asked = []

    async def form(context, params):
        asked.append(params.message)
        return _form(decision="approve")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            cmd = _python_cmd(f"open(r'{marker}', 'w').close()")
            r = _payload(await session.call_tool("run_command", {"command": cmd, "reason": "test"}))
    assert r["decision"] == "approved" and r["exit_code"] == 0
    assert marker.exists()
    assert len(asked) == 1 and "test" in asked[0]
    record = json.loads((workspace / ".vscode-copilot-telegram" / "audit.jsonl").read_text().splitlines()[-1])
    assert record["decision"] == "approved" and record["via"] == "vscode"


async def test_vscode_form_deny_returns_the_note_and_does_not_run(workspace):
    marker = workspace / "must-not-exist"

    async def form(context, params):
        return _form(decision="deny", note="use the other script")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            cmd = _python_cmd(f"open(r'{marker}', 'w').close()")
            r = _payload(await session.call_tool("run_command", {"command": cmd, "reason": "test"}))
    assert r["decision"] == "denied" and r["note"] == "use the other script" and r["exit_code"] is None
    assert not marker.exists()


async def test_ask_user_is_answered_in_vscode(workspace):
    async def form(context, params):
        return _form(choice="SQLite")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            r = _payload(await session.call_tool(
                "ask_user", {"question": "Which database?", "options": ["Postgres", "SQLite"]}))
    assert r == "SQLite"


async def test_dismissed_form_goes_to_telegram_and_fails_closed(workspace):
    marker = workspace / "must-not-exist"

    async def form(context, params):
        return _form(action="cancel")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            cmd = _python_cmd(f"open(r'{marker}', 'w').close()")
            r = _payload(await session.call_tool("run_command", {"command": cmd, "reason": "test"}))
    assert r["decision"] == "denied-error" and r["exit_code"] is None  # Telegram is a closed port
    assert not marker.exists()


async def test_late_vscode_answer_still_counts_when_telegram_is_down(workspace):
    """No answer for 1 s, so the server tries Telegram (down). The VS Code form stays open and a later
    answer still approves."""
    import asyncio
    (workspace / "vscode-copilot-telegram.toml").write_text("vscode_wait_s = 1\n")
    marker = workspace / "ran-after-late-approval"

    async def form(context, params):
        await asyncio.sleep(2)
        return _form(decision="approve")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            cmd = _python_cmd(f"open(r'{marker}', 'w').close()")
            r = _payload(await session.call_tool("run_command", {"command": cmd, "reason": "test", "timeout_s": 30}))
    assert r["decision"] == "approved" and marker.exists()


def _mcp_major() -> int:
    from importlib.metadata import version
    return int(version("mcp").split(".")[0])


@pytest.mark.skipif(_mcp_major() < 2, reason="mcp 1.x does not send notifications/cancelled, so the form stays open")
async def test_unanswered_form_is_cancelled_when_the_server_gives_up(workspace):
    import asyncio
    (workspace / "vscode-copilot-telegram.toml").write_text("vscode_wait_s = 1\n")
    cancelled = asyncio.Event()

    async def form(context, params):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _form(action="cancel")

    async with stdio_client(_params(workspace)) as (read, write):
        async with ClientSession(read, write, elicitation_callback=form) as session:
            await session.initialize()
            r = _payload(await session.call_tool("run_command", {"command": "echo hi", "reason": "x", "timeout_s": 1}))
            await asyncio.wait_for(cancelled.wait(), 5)
    assert r["decision"] == "denied-error" and r["exit_code"] is None
