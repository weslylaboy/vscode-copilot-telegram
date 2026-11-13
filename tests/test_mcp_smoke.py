"""Start the real MCP server over stdio and talk to it with the MCP SDK client.

Telegram is pointed at a closed local port, so nothing leaves the machine and every
call that needs Telegram must fail closed.
"""

import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _params(workspace, **env):
    base = {k: v for k, v in os.environ.items() if k not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID")}
    base.update({"TELEGRAM_BOT_TOKEN": "123456:FAKE-TOKEN-FOR-TESTS", "TELEGRAM_USER_ID": "4242",
                 "VSCODE_COPILOT_TELEGRAM_API_BASE": "http://127.0.0.1:9", **env})
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
