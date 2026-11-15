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
from typing import Annotated, Any, Literal

try:  # mcp >= 2.0
    from mcp.server import MCPServer as _Server  # type: ignore[attr-defined]
    from mcp.server.mcpserver import Context  # type: ignore[attr-defined,import-not-found]
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context  # type: ignore[no-redef,attr-defined]
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef,attr-defined]

from pydantic import BaseModel, Field, create_model

from .broker import Broker
from .config import (ConfigError, accept_policy, ignored_project_env_names, load_env_files, load_settings,
                     resolve_workspace_root, telegram_credentials)
from .bridge import Bridge, LocalAnswer, LocalPrompt, LocalQuestion
from .telegram import TelegramAPI

log = logging.getLogger("vscode_copilot_telegram")

INSTRUCTIONS = (
    "Use run_command for every shell command; the user approves each one in VS Code or on Telegram. "
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


# ---------------- ask in VS Code first ----------------
# Each question has two forms: a dropdown (mcp 2.x accepts it) and plain text fields (the only thing
# mcp 1.x accepts). The dropdown is tried first.
class _ApprovalForm(BaseModel):
    decision: Literal["approve", "deny"] = Field(description="Approve or deny the command")
    note: str = Field(default="", description="Optional note for Copilot (used when you deny)")


class _ApprovalFormText(BaseModel):
    decision: str = Field(description="Type approve or deny")
    note: str = Field(default="", description="Optional note for Copilot (used when you deny)")


def _question_forms(options: list[str]) -> tuple[type[BaseModel], type[BaseModel]]:
    if not options:
        form = create_model("QuestionForm", answer=(str, Field(description="Your answer")))
        return form, form
    choice: Any = Literal[tuple(options)]  # type: ignore[valid-type]
    dropdown = create_model("QuestionForm", choice=(choice, Field(description="Your answer")))
    text = create_model("QuestionFormText", choice=(str, Field(description="Type one of: " + ", ".join(options))))
    return dropdown, text


def _client_can_elicit(ctx: Any) -> bool:
    """True if the MCP client (VS Code) can show a form to the user."""
    try:
        caps = getattr(ctx, "client_capabilities", None)  # mcp 2.x
        if caps is not None:
            return bool(getattr(caps, "elicitation", None))
        from mcp import types
        session = ctx.request_context.session  # mcp 1.x
        return bool(session.check_client_capability(
            types.ClientCapabilities(elicitation=types.ElicitationCapability())))
    except Exception:  # noqa: BLE001 - not being able to tell means: do not use VS Code
        return False


def _describe_client(ctx: Any) -> str:
    """What the MCP client says about itself, for the log (best effort)."""
    try:
        info = None
        caps = getattr(ctx, "client_capabilities", None)  # mcp 2.x
        if caps is None:
            params = ctx.request_context.session.client_params  # mcp 1.x
            caps, info = params.capabilities, params.clientInfo
        shown = caps.model_dump(exclude_none=True) if caps is not None else "none"
        return f"capabilities {shown}" + (f", client {info.name} {info.version}" if info else "")
    except Exception:  # noqa: BLE001
        return "unknown"


async def _elicit(ctx: Any, message: str, dropdown: type[BaseModel], text: type[BaseModel]) -> Any:
    try:
        return await ctx.elicit(message, dropdown)
    except TypeError:  # mcp 1.x refuses dropdown fields
        return await ctx.elicit(message, text)


def vscode_prompt(ctx: Any) -> LocalPrompt:
    """Build the function that asks the user in VS Code with an MCP elicitation form.

    It waits until the user answers. The caller cancels it (which makes the SDK tell VS Code to
    close the form) when Telegram answers first. It returns None when VS Code cannot ask or the
    user dismisses the form, so the caller falls back to Telegram."""
    async def ask(question: LocalQuestion) -> LocalAnswer | None:
        if not _client_can_elicit(ctx):
            log.info("VS Code cannot show a form: the client did not declare elicitation (%s); using Telegram",
                     _describe_client(ctx))
            return None
        try:
            if question.kind == "approval":
                result = await _elicit(ctx, question.message, _ApprovalForm, _ApprovalFormText)
            else:
                result = await _elicit(ctx, question.message, *_question_forms(question.options))
        except Exception as exc:  # noqa: BLE001 - e.g. no back-channel on this connection
            log.info("VS Code did not take the question (%s); using Telegram", exc)
            return None
        if result.action == "decline" and question.kind == "approval":
            return LocalAnswer("deny")
        if result.action != "accept":
            return None
        data = result.data
        if question.kind == "approval":
            if str(data.decision).strip().lower() != "approve":  # only an exact "approve" approves
                return LocalAnswer("deny", (data.note or "").strip() or None)
            return LocalAnswer("approve")
        if question.options:
            return LocalAnswer("option", str(data.choice))
        return LocalAnswer("text", data.answer)
    return ask


@mcp.tool()
async def ask_user(
    ctx: Context,
    question: Annotated[str, Field(description="The question for the user. Be specific and self-contained.")],
    options: Annotated[list[str] | None, Field(description="Optional choices shown as buttons. "
                                                           "The user may still type a free-text answer.")] = None,
    timeout_s: Annotated[int | None, Field(description="Seconds to wait (default from config, 600).")] = None,
) -> str:
    """Ask the user a question, first in VS Code and then on Telegram, and wait for the answer.

    Returns the user's answer text, or the string 'timeout' if they did not answer in time.
    """
    try:
        bridge = _get_bridge()
    except RuntimeError as exc:
        return f"error: {exc}"
    return await bridge.ask_user(question, options, timeout_s, local_prompt=vscode_prompt(ctx))


@mcp.tool()
async def run_command(
    ctx: Context,
    command: Annotated[str, Field(description="The exact shell command to run.")],
    reason: Annotated[str, Field(description="One sentence on why this command is needed.")],
    cwd: Annotated[str | None, Field(description="Working directory, absolute or relative to the "
                                                 "workspace root. Must be inside the workspace.")] = None,
    timeout_s: Annotated[int | None, Field(description="Seconds to wait for approval on Telegram "
                                                       "(default 600). No answer means denied.")] = None,
) -> dict[str, Any]:
    """Run a shell command in the workspace after the user approves it in VS Code or on Telegram.

    Returns decision (approved, auto-approved, denied, denied-timeout, denied-error, blocked, rejected),
    exit_code (null if not run), and output (combined stdout/stderr, truncated). If denied, the command
    did not run: do not retry it in another form; adjust your plan or ask_user.
    """
    try:
        bridge = _get_bridge()
    except RuntimeError as exc:
        return {"decision": "denied-error", "exit_code": None, "output": f"Not run: {exc}"}
    return await bridge.run_command(command, reason, cwd, timeout_s, local_prompt=vscode_prompt(ctx))


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


# ---------------- speak the older MCP protocol only ----------------
# mcp 2.x also speaks the 2026-07-28 protocol. A client that tries it first (Copilot's runtime sends
# `server/discover`) gets it, and in that protocol a server cannot ask the user while a call is running:
# `ctx.elicit` fails with "no back-channel". The form in VS Code needs the older `initialize` protocol.
# So this server answers `server/discover` with "method not found", and the client falls back to `initialize`.
class _LegacyOnlyRead:
    """Wraps the SDK's input stream and refuses `server/discover` (see above). mcp 2.x only."""

    def __init__(self, inner: Any, write: Any, refuse: Any) -> None:
        self._inner = inner
        self._write = write
        self._refuse = refuse  # builds the reply for a refused request

    async def _skip(self, item: Any) -> bool:
        request: Any = getattr(item, "message", None)
        if getattr(request, "method", None) == "server/discover" and getattr(request, "id", None) is not None:
            log.info("answering server/discover with 'method not found', so the client uses the initialize protocol")
            await self._write.send(self._refuse(request.id))
            return True
        return False

    async def receive(self) -> Any:
        while True:
            item = await self._inner.receive()
            if not await self._skip(item):
                return item

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __aiter__(self) -> "_LegacyOnlyRead":
        return self

    async def __anext__(self) -> Any:
        while True:
            item = await self._inner.__anext__()  # raises StopAsyncIteration at the end
            if not await self._skip(item):
                return item

    async def __aenter__(self) -> "_LegacyOnlyRead":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    @property
    def last_context(self) -> Any:  # the SDK reads the sender's context from here
        return getattr(self._inner, "last_context", None)


def _run_stdio_legacy_only() -> bool:
    """Serve over stdio with the older protocol only. Returns False (nothing was started) if this mcp
    version does not have the pieces, for example mcp 1.x, which only speaks the older protocol anyway."""
    try:
        import anyio
        import mcp_types  # type: ignore[import-not-found]
        from mcp.server.stdio import stdio_server
        from mcp.shared.message import SessionMessage
        lowlevel = mcp._lowlevel_server  # type: ignore[attr-defined]
        init_options = lowlevel.create_initialization_options()
    except Exception:  # noqa: BLE001 - ImportError or AttributeError on other mcp versions
        return False

    def refuse(request_id: Any) -> Any:
        error = mcp_types.ErrorData(code=mcp_types.METHOD_NOT_FOUND, message="Method not found: server/discover")
        return SessionMessage(mcp_types.JSONRPCError(jsonrpc="2.0", id=request_id, error=error))

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await lowlevel.run(_LegacyOnlyRead(read, write, refuse), write, init_options)

    anyio.run(serve)
    return True


def build_bridge(workspace: str | None) -> Bridge:
    root = resolve_workspace_root(workspace)
    load_env_files()
    ignored = ignored_project_env_names(root)
    if ignored:
        log.warning("%s sets %s, but the project .env is never read. Put these in "
                    "~/.config/vscode-copilot-telegram/.env or in the file named by "
                    "VSCODE_COPILOT_TELEGRAM_ENV_FILE.", root / ".env", ", ".join(ignored))
    settings = load_settings(root)
    for warning in settings.startup_warnings:
        log.warning("%s", warning)
    if settings.policy_warning:
        log.warning("%s", settings.policy_warning)
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
    parser.add_argument("--accept-policy", action="store_true",
                        help="Review and accept the allow list in vscode-copilot-telegram.toml (type it yourself "
                             "in a terminal; does not start the MCP server)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    if args.accept_policy:
        sys.exit(accept_policy(resolve_workspace_root(args.workspace)))

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
    if not _run_stdio_legacy_only():
        mcp.run("stdio")


if __name__ == "__main__":
    main()
