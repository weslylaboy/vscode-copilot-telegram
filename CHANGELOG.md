# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- The project's own `.env` (`<workspace>/.env`) is no longer loaded by the server or the watcher. Before, a `.env` written by Copilot (file edits aren't gated) or brought by a cloned repository could replace the Telegram credentials or set `VSCODE_COPILOT_TELEGRAM_API_BASE`, and so decide who approves commands. If that file has `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*`, or `LOG_PATH`, both programs now log a warning and ignore them.
- An `allow` list (or `use_default_block = false`) in `vscode-copilot-telegram.toml` is ignored until you accept it with the new `vscode-copilot-telegram --accept-policy` command, which you type in a terminal. Before, Copilot could add `allow = ['.*']` to the file (file edits aren't gated), and after a restart its commands ran with no tap. The accepted copy is saved in `~/.config/vscode-copilot-telegram/accepted-policy.json`; if the list in the file differs from it, the allow list is empty, the built-in block list is on, and every command asks. The default block list now also denies a `run_command` that contains `--accept-policy` or names the accepted file.

### Added

- `vscode-copilot-telegram --accept-policy` (see above), a warning in the server output and in each approval message while an allow list is not accepted, and `tests/test_config.py`.

### Changed

- **Breaking:** if your credentials were in the project `.env`, move them to `~/.config/vscode-copilot-telegram/.env`, or to a file outside the project named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE` (use this for one bot per project). Variables from the project `.env` are also no longer passed to approved commands.
- **Breaking:** an existing `allow` list in `vscode-copilot-telegram.toml` stops working until you run `vscode-copilot-telegram --accept-policy --workspace <project>` once.



## [0.1.0] - 2026-11-12

First release.

### Added

- `vscode-copilot-telegram` MCP server (stdio) with three tools for GitHub Copilot agent mode in VS Code:
  - `run_command`: runs a shell command in the workspace only after you tap **Approve** in Telegram; **Deny** and **Deny with note** send the decision (and your note) back to Copilot.
  - `ask_user`: asks a question with optional answer buttons or a free-text reply.
  - `notify`: one-way status message.
- Fail-closed approvals: deny on timeout (default 600 s), Telegram errors, or configuration errors.
- Built-in block list (destructive `rm`, force pushes, disk wipes, `curl | sh`, fork bomb, power commands) plus user `block` patterns.
- Allow list with whole-command matching; commands with shell chaining are never auto-approved.
- Workspace jail for `cwd`, including symlink escapes.
- Single-use, per-request callback buttons that survive restarts; replies accepted only from `TELEGRAM_USER_ID`; `/pending` command.
- Secret masking for everything sent to Telegram or written to the audit log; bot token stripped from command environments.
- JSONL audit log in `<workspace>/.vscode-copilot-telegram/audit.jsonl`.
- `vscode-copilot-telegram-watch` chat mirror: forwards prompts, replies, and tool/edit summaries from VS Code's `chatSessions` (`.json` and `.jsonl` op-log) and Copilot `transcripts`, with dedupe across restarts, `--list`, `--dry-run`, `--backfill`, and VS Code Server (tunnels/SSH/WSL) paths.
- `vscode-copilot-telegram --test` to check the bot setup.
- Optional `vscode-copilot-telegram.toml` (timeouts, output limits, shell, allow/block lists, log path, project label).
- Examples for `.vscode/mcp.json` (Local harness), `.mcp.json` (Copilot harness), `.env`, and `.github/copilot-instructions.md`.
- Docs: setup for Windows and macOS, configuration, troubleshooting, architecture, development, security.
- GitLab CI running the test suite on Python 3.11 and 3.12.
- 110 automated tests.

[0.1.0]: https://github.com/weslylaboy/vscode-copilot-telegram
