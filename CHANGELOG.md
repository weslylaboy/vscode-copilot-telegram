# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased

First release. Replace "unreleased" with the date when you tag it.

### Added

- `vscode-copilot-telegram` MCP server (stdio) with three tools for GitHub Copilot agent mode in VS Code:
  - `run_command`: runs a shell command in the workspace only after you approve it, first in VS Code and then, if you do not answer in time, on Telegram with **Approve**; **Deny** and **Deny with note** send the decision (and your note) back to Copilot.
  - `ask_user`: asks a question with optional answer buttons or a free-text reply, first in VS Code and then on Telegram.
  - `notify`: one-way status message.
- Ask in VS Code first: `run_command` and `ask_user` show an MCP elicitation form in VS Code. If you do not answer within `vscode_wait_s` seconds (default 180), the same question also goes to Telegram, the form stays open, and the first answer wins. If VS Code cannot show forms, the question goes to Telegram at once (`vscode_wait_s = 0` keeps the old Telegram-only way). The audit log records where the answer came from (`via`).
- Fail-closed approvals: deny on timeout (default 600 s), Telegram errors, or configuration errors.
- Built-in block list (destructive `rm`, force pushes, disk wipes, `curl | sh`, fork bomb, power commands) plus user `block` patterns.
- Allow list with whole-command matching; commands with shell chaining are never auto-approved. An allow list only works after you accept it (see **Security**).
- `vscode-copilot-telegram --accept-policy`: you type it in a terminal to review and accept the allow list. It refuses patterns that approve (almost) every command and warns when a pattern also approves risky commands. While an allow list is not accepted, the server output and each approval message say so.
- Workspace jail for `cwd`, including symlink escapes.
- Single-use, per-request callback buttons that survive restarts; replies accepted only from `TELEGRAM_USER_ID`; `/pending` command.
- Secret masking for everything sent to Telegram or written to the audit log; bot token stripped from command environments.
- JSONL audit log, written outside the project (`~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl`; `LOG_PATH` moves it).
- `vscode-copilot-telegram-watch` chat mirror: forwards prompts, replies, and tool/edit summaries from VS Code's `chatSessions` (`.json` and `.jsonl` op-log) and Copilot `transcripts`, with dedupe across restarts, `--list`, `--dry-run`, `--backfill`, and VS Code Server (tunnels/SSH/WSL) paths.
- `vscode-copilot-telegram --test` to check the bot setup.
- Optional `vscode-copilot-telegram.toml` (timeouts, output limits, shell, allow/block lists, project label).
- Failures that don't stop a request (a failed answer to a button tap, a failed short message, an error while closing the poller) are written to the server log as warnings.
- Examples for `.mcp.json` (Copilot harness), `.env`, and `.github/copilot-instructions.md`, and a `.env.example` that documents every variable.
- Docs: setup for Windows, macOS, and Linux (systemd), the Copilot harness (the Local harness is deprecated by VS Code and not supported), configuration, troubleshooting, architecture, development, and security (including the VS Code setting that asks for a click before Copilot edits the files that control the gate).
- Instructions for coding agents that work on this repository (`AGENTS.md`, `.github/copilot-instructions.md`, `CLAUDE.md`).
- GitHub Actions runs the tests on Linux, macOS, and Windows (Python 3.11 and 3.12) and a `mypy` type check; the code type-checks clean. The number of automated tests is in `docs/DEVELOPMENT.md`.

### Security

- The project's own `.env` (`<workspace>/.env`) is never loaded. Copilot can edit project files without approval and a cloned repository can bring its own, so that file must not decide who approves commands. If it has `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*`, or `LOG_PATH`, both programs log a warning and ignore them. Credentials are read from `~/.config/vscode-copilot-telegram/.env` or from the file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE`.
- An `allow` list (or `use_default_block = false`) in `vscode-copilot-telegram.toml` is ignored until you accept it with `--accept-policy`. The accepted copy is saved outside the project, in `~/.config/vscode-copilot-telegram/accepted-policy.json`; if the list in the file differs from it, the allow list is empty, the built-in block list is on, and every command asks. The default block list also denies a `run_command` that contains `--accept-policy` or names the accepted file, and the server ignores the accepted copy if it would be inside the workspace.
- The audit log is outside the project, so Copilot's file edits can't change or delete it. A `log_path` in the project TOML is ignored with a warning that says where the log is now and names an older log file if one is still there.
- On Windows, the command killer calls `taskkill` by its full path. Before, a `taskkill.exe` placed in the project could run when a command hit its run timeout.
- The watcher uses SHA-256 instead of SHA-1 for its state file name and its reply check. This is not a security fix (nothing depended on it), but it removes a weak hash from the code.

### Notes for anyone who ran an early version from `main`

- If your credentials were in the project `.env`, move them to `~/.config/vscode-copilot-telegram/.env`, or to a file outside the project named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE` (use this for one bot per project). The project `.env` is also no longer passed to approved commands.
- An `allow` list stops working until you run `vscode-copilot-telegram --accept-policy --workspace <project>` once.
- The audit log moved out of the project. An older `.vscode-copilot-telegram/audit.jsonl` stays where it is; move or delete it.
- The watcher's state file has a new name, so each watcher starts once as a first run: old history is not sent again. You can delete the old `~/.vscode-copilot-telegram/watch-*.json` files.

[0.1.0]: https://github.com/weslylaboy/vscode-copilot-telegram
