# GitHub Copilot instructions (this repository)

These instructions are for GitHub Copilot (and similar assistants) when **developing vscode-copilot-telegram itself**.

They are not the end-user template. End users who want Copilot, in *their* projects, to use this tool's `run_command` / `ask_user` / `notify` MCP tools should copy [`examples/copilot-instructions.md`](../examples/copilot-instructions.md). Do not merge that template into this file, and do not replace that template with this file.

Read [`AGENTS.md`](../AGENTS.md) and follow it. The points below are the rules that must not be skipped.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

- MCP server bot check (needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID`; does not start the server): `vscode-copilot-telegram --test --workspace <dir>`
- Watcher, no token needed: `vscode-copilot-telegram-watch --list --workspace <project>` and `vscode-copilot-telegram-watch --dry-run --once --workspace <project>`

Python 3.11+ (CI: 3.11 and 3.12). No test should call the real Telegram API.

## Conventions

- Only `server.py` imports MCP. Keep `bridge.py` MCP-free.
- Log the server to stderr only; stdout is the MCP protocol.
- Dependencies: `mcp`, `httpx`, `python-dotenv`, plus the stdlib. Match existing typing (`from __future__ import annotations`, `str | None`).
- Update `CHANGELOG.md` for user-visible changes. Bump `pyproject.toml` and `__init__.py` together when releasing.
- This repo is on GitHub; open pull requests there.

## Security invariants

- Approvals fail closed: only `approved` / `auto-approved` run a command. Timeouts, Telegram errors, and bad config deny.
- Only `TELEGRAM_USER_ID` can answer. Callback buttons are single-use (persisted across restarts).
- `mask_secrets` on everything sent to Telegram or written to the audit log. Never commit `.env` or put a token in TOML.
- Only the MCP server long-polls Telegram (`getUpdates`). The watcher is send-only. Do not add a second poller.
- Do not weaken default block/allow policy without documentation and tests.

When a change affects behavior, security, CLI, or module boundaries, update the docs listed in `AGENTS.md` (README, `docs/*`, `SECURITY.md`, `CHANGELOG.md` as appropriate).
