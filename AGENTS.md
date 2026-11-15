# AGENTS.md

Canonical instructions for any coding agent working **on this repository**.

This file is for people and tools that change vscode-copilot-telegram itself. It is not the template end users add to their own projects so Copilot will use this tool's MCP server. That template is [`examples/copilot-instructions.md`](examples/copilot-instructions.md). GitHub Copilot should follow [`.github/copilot-instructions.md`](.github/copilot-instructions.md) (which points here). Claude Code should follow [`CLAUDE.md`](CLAUDE.md).

For deeper design and setup, read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md), [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md), and [`SECURITY.md`](SECURITY.md).

## Purpose

vscode-copilot-telegram lets a developer follow GitHub Copilot Chat (inside VS Code) from Telegram and approve the shell commands Copilot wants to run, without enabling Copilot's official remote features.

It is two programs that share one bot and one config loader:

- `vscode-copilot-telegram` — an MCP server over stdio, started by VS Code. It exposes `run_command` (gated by an Approve/Deny answer, asked in VS Code first and on Telegram after `vscode_wait_s`), `ask_user`, and `notify`. It is the only process that long-polls Telegram.
- `vscode-copilot-telegram-watch` — a file watcher the user starts. It reads Copilot chat session files from disk and **only sends** messages to Telegram.

This project is unrelated to [michael-schwartzman/copilot-telegram](https://github.com/michael-schwartzman/copilot-telegram), which wraps the Copilot CLI.

## Architecture map

All runtime code lives in `src/vscode_copilot_telegram/`. The module table (what each module owns and what it depends on) is in [`docs/ARCHITECTURE.md` → Module map](docs/ARCHITECTURE.md#module-map). Read it before you move code between modules, and update it there when a module's job changes.

Tests are in `tests/` (one file per area, plus `tests/test_mcp_smoke.py` and fixtures under `tests/fixtures/`). `tests/conftest.py` provides `FakeTelegram` and `make_bridge`.

## Setup and commands

Python 3.11 is the minimum (`tomllib`, `Path.is_relative_to`, `str | None` typing). CI runs 3.11 and 3.12.

```bash
python3 -m venv .venv && source .venv/bin/activate
# Windows: py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
mypy
```

`pytest -q` is the full suite (the current test count is in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md#run-the-tests)). Narrow with `pytest -q tests/test_bridge.py` or `pytest -q -k timeout`. Options are in `pyproject.toml` (`asyncio_mode = "auto"`). `mypy` type-checks `src/` (settings under `[tool.mypy]` in `pyproject.toml`).

Check the bot setup (needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID`, typically in `~/.config/vscode-copilot-telegram/.env`). Sends one test message and exits; it does not start the MCP server. Without credentials it prints `vscode-copilot-telegram: TELEGRAM_BOT_TOKEN is not set` (or the matching user-id error) to stderr and exits non-zero:

```bash
vscode-copilot-telegram --test --workspace /tmp/scratch
```

Watcher inspection does **not** need a token:

```bash
vscode-copilot-telegram-watch --list --workspace <project>
vscode-copilot-telegram-watch --dry-run --once --workspace <project>
vscode-copilot-telegram-watch --dry-run --backfill 3 --workspace <project>
```

`--list` prints matched `workspaceStorage` folders and session files, then exits. `--dry-run` prints messages instead of sending. `--once` checks once and exits (otherwise the watcher loops until Ctrl+C).

Manual MCP Inspector and end-to-end steps are in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Code conventions

- Python 3.11+, `from __future__ import annotations`, builtin generics (`list[str]`, `dict[str, Any]`), union with `|`. Public functions and methods are typed. Structured data uses dataclasses.
- Runtime dependencies are only `mcp` (>=1.2), `httpx`, and `python-dotenv`. Everything else is the stdlib (`tomllib`, `asyncio`, `pathlib`, `re`, …). Dev extras: `pytest`, `pytest-asyncio`, `mypy`. Do not add a dependency unless there is a clear need.
- There is no repo formatter or linter config. Match the surrounding style: module docstrings, `logging.getLogger("vscode_copilot_telegram.<module>")`, relatively few comments.
- `mypy` must report no errors on `src/`. The `type: ignore` comments on the `mcp` imports in `server.py` are needed because the code supports `mcp` 1.x and 2.x; run `mypy` and `pytest` against both (for example in two virtual environments, one with `"mcp<2"`) when you touch them or the elicitation code. The test that checks the VS Code form is cancelled is skipped on `mcp` 1.x, which does not send the cancel.
- `bridge.py` must stay free of MCP imports. `server.py` is the only MCP-aware module.
- The server's stdout belongs to the MCP protocol. Log only to stderr.
- Errors use small domain exceptions (`ConfigError`, `CwdError`, `TelegramError`). On the approval path, every failure must become a deny (or `blocked` / `rejected`) with `exit_code: null` — never an uncaught exception that could be read as success. Add a test for every new failure path.
- Everything sent to Telegram goes through `mask_secrets`. Everything written to the audit log goes through `AuditLog` (which masks string fields). Output returned to Copilot is not masked, because Copilot already sees the workspace.
- Bump `version` in `pyproject.toml` and `__init__.py` together, and add a `CHANGELOG.md` entry, when you release.

## Testing rules

- No test talks to the real Telegram API or needs a real token.
- Unit tests use `FakeTelegram` from `tests/conftest.py` (in-memory stand-in for `TelegramAPI`: records sent/edited messages, tests push `callback_query` and `message` updates).
- The MCP smoke test starts the real server with `python -m vscode_copilot_telegram` over stdio and sets `VSCODE_COPILOT_TELEGRAM_API_BASE` to a closed local port so calls fail closed without hitting `api.telegram.org`. That env var is also how a self-hosted Bot API base would be configured; do not use it to reach the public API in tests.
- Session parsing tests use hand-made fixtures in `tests/fixtures/`. If a real VS Code/Copilot format changes, copy a small **scrubbed** sample into that folder, add a test in `tests/test_sessions.py`, then fix the parser.
- Do not change watcher dedupe key shapes (`<requestId>:u` / `:a`, transcript `<event id>:u` / `:a` / `:t`) without a migration plan: a change makes every existing watcher resend history.
- The automated tests have not been run against live Telegram or live VS Code session files. Treat the first real run of a new path as an integration test, and add a regression fixture if something breaks.

## Security invariants

Do not weaken or bypass these:

1. **Approvals fail closed.** A command runs only after a positive decision (`approved` or `auto-approved`). Deny, timeout (`denied-timeout`), no way to ask (Telegram send failure and no VS Code answer, `denied-error`), missing/bad config (`denied-error`), cwd outside the workspace (`rejected`), and block-list / empty command (`blocked`) must not run the command. The one exception is an allow-list full match (an allow list you accepted) with no chaining characters; even then a notice is sent, and if the notice cannot be sent the allow-listed command still runs. If VS Code and Telegram answer at the same moment with different decisions, the denial wins.
2. **Only you can answer.** On Telegram only `TELEGRAM_USER_ID`, in that chat, can answer; updates from anyone else are ignored. In VS Code the answer comes from the MCP elicitation form that VS Code shows to the user (`bridge._decide`, `server.vscode_prompt`). The bridge asks in VS Code first, and asks on Telegram only after `vscode_wait_s` (0 = Telegram only). Never auto-answer the form, and only an exact `approve` in the form approves.
3. **Buttons are single-use.** Each request has a random id in callback data. Answered ids are persisted in `.vscode-copilot-telegram/broker-state.json` and survive restarts. A second tap is acknowledged as already answered and does nothing. When VS Code answers after the Telegram message was sent, the Telegram request is withdrawn (its id is marked answered) and the VS Code form is cancelled when Telegram answers first.
4. **Secret masking.** `mask_secrets` on every outbound Telegram message and every audit field. `TELEGRAM_BOT_TOKEN` is stripped from the child command environment and redacted from API error text. Never accept a token in `vscode-copilot-telegram.toml`.
5. **Audit log.** Every request and decision is appended to an audit log outside the workspace, `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` (masked, append-only). Keep it out of the project: Copilot's file edits can only reach the workspace. A `log_path` in the TOML is ignored (the server warns and names an older log file if one is left); only `LOG_PATH` in the environment can move it.
6. **Single poller.** Only the MCP server calls `getUpdates`, and only while a request is pending. The watcher must stay send-only (`TelegramSender` has no `getUpdates`). A second poller gets Telegram `409 Conflict`. One bot per VS Code window.
7. **The project `.env` is never loaded.** `load_env_files` reads only the file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE` and `~/.config/vscode-copilot-telegram/.env`. Anything that can write to the workspace (Copilot's file edits, a cloned repository) must not be able to set the Telegram credentials, the Bot API address, or any other setting through `<workspace>/.env`. A filter of "dangerous names" is not enough, because proxy and certificate variables would pass.
8. **An allow list in the project TOML needs your acceptance.** `load_settings` ignores `allow` and `use_default_block = false` (empty allow list, block list on, `Settings.policy_warning` set) unless they equal what `--accept-policy` saved in `~/.config/vscode-copilot-telegram/accepted-policy.json`. `accept_policy` must keep refusing without a terminal and without typing `accept`, refusing patterns that approve everything, and refusing when the accepted copy is inside the workspace (`load_settings` then ignores it too). The default block list must keep denying commands that contain `--accept-policy` or name the accepted file. Do not store the accepted copy inside the workspace.

Also keep the built-in default block list as a safety net. Allow-list patterns must match the **whole** command; shell chaining (`;`, `&&`, `||`, `|`, backticks, `$(`, `>`, `<`, newline, trailing `&`) disables auto-approval.

File edits, the built-in "Run in Terminal" tool, and other MCP servers are not gated by this project. Do not claim otherwise in docs or tool descriptions.

## Docs to update

| Change | Also update |
| --- | --- |
| User-facing behavior, setup, or CLI flags | [`README.md`](README.md) if it is a headline feature, plus the relevant file under [`docs/`](docs/) (`SETUP.md`, `WATCHER.md`, `CONFIGURATION.md`, `TROUBLESHOOTING.md`, `DEVELOPMENT.md`, `ARCHITECTURE.md`). Follow [`docs/STYLE.md`](docs/STYLE.md) when you write docs. |
| Security properties, token handling, or threat model | [`SECURITY.md`](SECURITY.md) |
| Module boundaries or request flow | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (the module map lives there), and this file if a rule here changes |
| Agent/contributor workflow | this file, and a short pointer in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) if needed |
| Any user-visible change | [`CHANGELOG.md`](CHANGELOG.md) (`Unreleased` until the next version is tagged) |
| Version bump | `pyproject.toml`, `src/vscode_copilot_telegram/__init__.py`, `CHANGELOG.md` |

Keep examples in `examples/` in sync when you change MCP config shape, env vars, or the end-user instructions template.

## Commits and pull requests

This project lives on GitHub (`https://github.com/weslylaboy/vscode-copilot-telegram`). Open pull requests there.

- Prefer a focused commit (or a short, coherent series) with an imperative subject, like the existing "Add …" / "Initial commit: …" style.
- Every change that can break behavior needs a test. Docs-only and instruction-file changes do not.
- `pytest -q` and `mypy` must pass locally. CI runs the same commands on Python 3.11 and 3.12 for every branch push and pull request (`.github/workflows/ci.yml`).
- Do not include `.env` files, tokens, personal bot ids, or unsanitized real chat transcripts.
- Do not rewrite published `main` history.

## What not to do

- Do not commit secrets, `.env`, `.env.*`, or `.vscode-copilot-telegram/` state (all are gitignored). Never put a bot token in TOML, examples, or MCP JSON that people commit.
- Do not add a second Telegram poller, and do not give the watcher a `getUpdates` call.
- Do not weaken policy defaults (built-in block list, whole-command allow matching, chaining check, fail-closed paths) without an explicit docs and changelog update, and do not remove tests that lock those defaults in.
- Do not import MCP from `bridge.py` or log MCP traffic to stdout.
- Do not treat "the tests passed" as proof the tool works against live VS Code or live Telegram.
