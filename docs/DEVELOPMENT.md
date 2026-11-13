# Development

Everything you need to change vscode-copilot-telegram safely. Read [ARCHITECTURE.md](ARCHITECTURE.md) first for the module map and design decisions.

## Agent instructions

Instruction files for coding agents that work on **this** repository (not for end-user projects that use the tool):

- [`AGENTS.md`](../AGENTS.md) — canonical guide (architecture, commands, conventions, tests, security invariants).
- [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) — GitHub Copilot. This is not [`examples/copilot-instructions.md`](../examples/copilot-instructions.md), which is the template end users copy into their own projects so Copilot will call this tool's MCP server.
- [`CLAUDE.md`](../CLAUDE.md) — Claude Code; imports `AGENTS.md`.

## Set up a dev environment

```bash
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Python 3.11 is the minimum (`tomllib`, `Path.is_relative_to`, modern typing). CI runs 3.11 and 3.12; it was also run locally on 3.13.

## Run the tests

```bash
pytest -q                          # whole suite (110 tests, ~7 s)
pytest -q tests/test_bridge.py     # one module
pytest -q -k timeout               # by name
```

pytest options live in `pyproject.toml` under `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`).

| File | Covers |
| --- | --- |
| `tests/test_bridge.py` | Approve once and ignore second taps, answered ids surviving a restart, deny, deny with note, timeout fails closed, Telegram send failure fails closed, unauthorized users ignored, several pending at once, block list, allow list notice, cwd jail, masking in Telegram, audit log, `ask_user` options / text / timeout / reply routing, `notify` |
| `tests/test_policy.py` | Built-in block list, allow list full-match, chaining never auto-approved |
| `tests/test_masking.py` | Each masking pattern |
| `tests/test_runner.py` | Combined output capture, run timeout kills, token stripped from the child environment, head-and-tail truncation |
| `tests/test_workspace.py` | cwd resolution, `..` / absolute / sibling-prefix / symlink escapes, missing folders |
| `tests/test_sessions.py` | The three chat formats (fixtures in `tests/fixtures/`), op-log replay, file URI decoding, workspaceStorage matching, message splitting and formatting, and the watcher: dedupe across restarts, settle time, no history flood, backfill, retry after send failure |
| `tests/test_mcp_smoke.py` | Starts the real server with `python -m vscode_copilot_telegram` over stdio, lists tools, and checks that calls fail closed with Telegram pointed at a closed local port, and without credentials |

`tests/conftest.py` provides `FakeTelegram` (an in-memory stand-in for `TelegramAPI`: records sent and edited messages, lets tests push `callback_query` and `message` updates) and the `make_bridge` fixture.

No test talks to the real Telegram API or needs a token. `VSCODE_COPILOT_TELEGRAM_API_BASE` lets the smoke test point the server at a dead local port.

## CI

`.github/workflows/ci.yml` (GitHub Actions) runs `pip install -e ".[dev]"` and `pytest -q` on Python 3.11 and 3.12, for every branch push and pull request. Results are in the **Actions** tab of the repository.

## Manual testing against real Telegram

1. Create a throwaway bot with @BotFather and put its token in `~/.config/vscode-copilot-telegram/.env`.
2. `vscode-copilot-telegram --test --workspace /tmp/scratch` → you get the ✅ message.
3. Drive the MCP server without VS Code using the MCP Inspector:
   ```bash
   npx @modelcontextprotocol/inspector .venv/bin/vscode-copilot-telegram --workspace /tmp/scratch
   ```
   Call `run_command` with `{"command": "echo hi", "reason": "test"}` and approve on your phone.
4. Watcher: `vscode-copilot-telegram-watch --workspace <a folder you've chatted in> --dry-run --backfill 3`.
5. Then run the [end-to-end checklist](SETUP.md#12-end-to-end-verification-checklist) in VS Code.

## What is not tested yet

The automated tests use a fake Telegram and hand-made session fixtures. As of 0.1.0, none of the following has been exercised:

- **Real Telegram Bot API**: actual long polling, `409 Conflict` handling, rate limits (`retry_after`), HTML rendering of messages, `force_reply` for notes, message edits on old messages.
- **Real VS Code + Copilot**: that Copilot agent mode reliably picks `run_command` once Run in Terminal is off; tool approval interplay; the Copilot harness reading `.mcp.json`; how `${workspaceFolder}` and `envFile` resolve on each OS.
- **Real chat session files** from current VS Code / Copilot Chat builds on Windows and macOS (the fixtures model the formats described below), including VS Code Server paths for tunnels.
- **Windows specifics**: `cmd.exe` / PowerShell quoting through `run_command`, `taskkill /T` process-tree kill, Task Scheduler with `pythonw.exe`.
- **macOS launchd** agent and privacy (TCC) prompts.
- **Linux systemd** user service for the watcher.

Treat the first real run as the integration test, and please add regression tests or fixtures for anything that breaks.

## chatSessions format assumptions

These are undocumented VS Code internals, so `sessions.py` parses defensively: unknown kinds and missing fields are skipped, never fatal.

**Locating a project's storage.** Each `…/User/workspaceStorage/<hash>/workspace.json` has `"folder": "<uri>"` (`file:///…`, `vscode-remote://…`, `vscode-vfs://…`). The URI is decoded (`%3A` → `:`, drive letters lower-cased, UNC kept), compared after resolving symlinks, case-insensitively on Windows and macOS. Multi-root workspaces (`"workspace": …`) aren't matched; use `--storage`.

**Format 1, `chatSessions/<id>.json`:**
`{"version": 3, "sessionId", "customTitle"?, "requests": [{"requestId", "message": {"text" | "parts": [{"text"}]}, "response": [parts], "result"?, "isComplete"?, "modelState"?}]}`

**Format 2, `chatSessions/<id>.jsonl` (VS Code ≥ 1.109):** one op per line, replayed in order:
`{"kind": 0, "v": <full session>}` snapshot · `{"kind": 1, "k": [path], "v": value}` set · `{"kind": 2, "k": [path], "v": [items], "i"?: index}` push/splice · `{"kind": 3, "k": [path]}` delete. The replayed object is format 1.

**Response parts used** (`kind`): `markdownContent` / `markdownVuln` / no kind (`content` or `value` text), `inlineReference` (file name), `toolInvocation` / `toolInvocationSerialized` (`pastTenseMessage` / `invocationMessage`, and `toolSpecificData.commandLine` for terminal commands), `textEditGroup` (edited file name), `confirmation` (`title` / `message`). Skipped on purpose: `thinking`, progress, warnings, references, code-block URIs, undo stops, and other UI chrome (`SKIP_KINDS`).

**Completion.** A reply is complete when its request has `result`, `isComplete: true`, or a `modelState` with `completedAt` / non-zero `value`, or when it isn't the last request. Incomplete replies are sent once unchanged for `--settle` seconds.

**Format 3, `GitHub.copilot-chat/transcripts/<id>.jsonl`:** events `{"type", "id"?, "data": {…}}` with `user.message` / `assistant.message` (`content` | `text` | `message`) and `tool.execution_start` (`toolName`, `arguments` with `command` or `filePath` / `path`).

**Dedupe keys.** `<requestId>:u` / `:a` for chat sessions, `<event id>:u` / `:a` / `:t` for transcripts. Changing these keys makes every watcher resend history, so don't.

When a format changes: copy a small, **scrubbed** sample into `tests/fixtures/`, add a test in `tests/test_sessions.py`, then fix the parser.

## Conventions

- Keep `bridge.py` free of MCP imports; `server.py` is the only MCP-aware module.
- Everything that leaves the machine for Telegram goes through `mask_secrets`, and every audit field through `AuditLog`.
- Anything that can fail on the approval path must end in a deny. Add a test for every new failure path.
- stdout belongs to the MCP protocol in the server: log to stderr only.
- Bump `version` in `pyproject.toml` and `__init__.py` together, and add a `CHANGELOG.md` entry.

## Known limitations

See [ARCHITECTURE.md → Known limitations](ARCHITECTURE.md#known-limitations). The list lives only there.

## Roadmap

1. **`preToolUse` hook to block the built-in shell.** Use Copilot's agent hooks (`.github/hooks/*.json`, `preToolUse`) to deny the built-in terminal tool and point the model at `run_command`. This closes the Copilot-harness gap where Run in Terminal can't be unticked. Needs testing against the current hook schema in VS Code and the Copilot harness.
2. **Slack and Discord.** Factor the `Api` protocol in `broker.py` into a transport interface (send, edit, buttons, poll or socket), then add Slack (Socket Mode, Block Kit buttons) and Discord (gateway, components) backends selected by config.
3. **File-edit approval.** Options: a `write_file` / `apply_patch` MCP tool that shows a diff in Telegram, combined with `chat.tools.edits.autoApprove` rules so built-in edits to sensitive paths still need a click; or a git-based "approve the diff before commit" flow.
4. **Better multi-window support.** One poller shared across windows (a small local daemon), removing the one-bot-per-window rule.
5. **Packaging.** Publish to PyPI so setup is `pipx install vscode-copilot-telegram`.
6. **Real-world fixtures** for chat formats on Windows, macOS, and VS Code Server.
