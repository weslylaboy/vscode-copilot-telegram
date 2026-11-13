"""vscode-copilot-telegram MCP server (stdio).

VS Code launches this with the workspace folder as the working directory. Copilot
calls ``run_command`` instead of its built-in terminal tool, and every call waits
for an Approve/Deny tap in Telegram.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Annotated, Any

try:  # mcp >= 2.0
    from mcp.server import MCPServer as _Server  # type: ignore[attr-defined]
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from pydantic import Field

from .broker import Broker
from .config import ConfigError, load_env_files, load_settings, resolve_workspace_root, telegram_credentials
from .bridge import Bridge
from .telegram import TelegramAPI

log = logging.getLogger("vscode_copilot_telegram")

INSTRUCTIONS = (
    "Use run_command for every shell command; the user approves each one from Telegram. "
    "Use ask_user whenever you need a decision or information from the user. "
    "Use notify for short progress updates at milestones."
)

mcp = _Server("vscode-copilot-telegram", instructions=INSTRUCTIONS)

_bridge: Bridge | None = None
_startup_error: str | None = None


def _get_bridge() -> Bridge:
    if _bridge is None:
        raise RuntimeError(f"vscode-copilot-telegram is not configured: {_startup_error}")
    return _bridge


@mcp.tool()
async def ask_user(
    question: Annotated[str, Field(description="The question for the user. Be specific and self-contained.")],
    options: Annotated[list[str] | None, Field(description="Optional choices shown as buttons. "
                                                           "The user may still type a free-text answer.")] = None,
    timeout_s: Annotated[int | None, Field(description="Seconds to wait (default from config, 600).")] = None,
) -> str:
    """Ask the user a question on Telegram and wait for the answer.

    Returns the user's answer text, or the string 'timeout' if they did not answer in time.
    """
    try:
        bridge = _get_bridge()
    except RuntimeError as exc:
        return f"error: {exc}"
    return await bridge.ask_user(question, options, timeout_s)


@mcp.tool()
async def run_command(
    command: Annotated[str, Field(description="The exact shell command to run.")],
    reason: Annotated[str, Field(description="One sentence on why this command is needed.")],
    cwd: Annotated[str | None, Field(description="Working directory, absolute or relative to the "
                                                 "workspace root. Must be inside the workspace.")] = None,
    timeout_s: Annotated[int | None, Field(description="Seconds to wait for approval (default 600). "
                                                       "No answer means denied.")] = None,
) -> dict[str, Any]:
    """Run a shell command in the workspace after the user approves it on Telegram.

    Returns decision (approved, auto-approved, denied, denied-timeout, denied-error, blocked, rejected),
    exit_code (null if not run), and output (combined stdout/stderr, truncated). If denied, the command
    did not run: do not retry it in another form; adjust your plan or ask_user.
    """
    try:
        bridge = _get_bridge()
    except RuntimeError as exc:
        return {"decision": "denied-error", "exit_code": None, "output": f"Not run: {exc}"}
    return await bridge.run_command(command, reason, cwd, timeout_s)


@mcp.tool()
async def notify(
    message: Annotated[str, Field(description="Short status update for the user.")],
) -> str:
    """Send a one-way status message to the user's Telegram (does not wait for a reply)."""
    try:
        bridge = _get_bridge()
    except RuntimeError as exc:
        return f"error: {exc}"
    return await bridge.notify(message)


def build_bridge(workspace: str | None) -> Bridge:
    root = resolve_workspace_root(workspace)
    load_env_files(root)
    settings = load_settings(root)
    creds = telegram_credentials()
    # VSCODE_COPILOT_TELEGRAM_API_BASE is only for tests / self-hosted Bot API servers.
    api = TelegramAPI(creds.token, creds.user_id,
                      base_url=os.environ.get("VSCODE_COPILOT_TELEGRAM_API_BASE", "https://api.telegram.org"))
    broker = Broker(api, creds.user_id, state_dir=settings.state_dir)
    return Bridge(settings, broker)


def main(argv: list[str] | None = None) -> None:
    global _bridge, _startup_error
    parser = argparse.ArgumentParser(prog="vscode-copilot-telegram", description=__doc__)
    parser.add_argument("--workspace", help="Workspace root (default: $WORKSPACE_ROOT or the current directory)")
    parser.add_argument("--test", action="store_true",
                        help="Send a test message to Telegram and exit (does not start the MCP server)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    # stdout belongs to the MCP protocol; log only to stderr.
    logging.basicConfig(level=args.log_level.upper(), stream=sys.stderr,
                        format="%(asctime)s vscode-copilot-telegram %(levelname)s %(message)s", force=True)
    try:
        _bridge = build_bridge(args.workspace)
    except (ConfigError, ValueError) as exc:
        _startup_error = str(exc)
        log.error("configuration error: %s (tools will refuse to run commands)", exc)
        if args.test:
            sys.exit(f"vscode-copilot-telegram: {exc}")

    if args.test:
        assert _bridge is not None
        result = asyncio.run(_bridge.notify("✅ vscode-copilot-telegram test message. Telegram is set up correctly."))
        print(result)
        sys.exit(0 if result == "sent" else 1)

    if _bridge is not None:
        log.info("workspace %s, audit log %s", _bridge.s.workspace_root, _bridge.s.log_path)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
