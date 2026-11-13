# Security

vscode-copilot-telegram puts a human approval step between GitHub Copilot and your shell, and sends parts of your development session to Telegram. This page says what it protects, what it doesn't, and how to keep the token safe.

## Threat model

**Assets:** your machine and workspace (what commands can do), your secrets (bot token, project credentials), and your code and chat content (what gets sent to Telegram).

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Copilot runs a harmful command (model mistake or prompt injection from code, docs, web pages, or tool output) | Every command needs your **Approve** tap; built-in block list; workspace jail for `cwd`; timeout = deny | You approve something harmful without reading it. The block list is pattern-based and can be evaded; it's a safety net, not a sandbox. |
| Copilot bypasses the gate via its built-in terminal | You turn off Run in Terminal; fallback settings force VS Code's own prompt | If the built-in tool is left on and auto-approved, commands never reach Telegram. See [SETUP §7](docs/SETUP.md#7-local-vs-copilot-harness-sessions). |
| A command escapes the workspace | `cwd` must resolve (after symlinks) inside the workspace | `cwd` only sets the starting folder. An approved command can still `cd ..` or touch absolute paths. Read what you approve. |
| Someone else answers your approvals | Only updates from `TELEGRAM_USER_ID` in that chat are accepted | Anyone with access to your unlocked phone or Telegram session can tap Approve. Use Telegram's passcode lock and review active sessions. |
| Replay of an old approval | Random per-request ids, single-use, persisted across restarts; timeouts are marked answered | — |
| Allow list abused through chaining (`npm test && curl … \| sh`) | Allow patterns must match the whole command, and any `;`, `&&`, `\|\|`, `\|`, backticks, `$(`, `>`, `<`, newline, or trailing `&` disables auto-approval | Overly broad allow patterns (e.g. `npm .*`) can still auto-approve things like `npm install <malicious>`. Keep patterns narrow. |
| Secrets leak to Telegram | `mask_secrets` on everything sent and logged; bot token stripped from child environments and redacted from error messages | Masking is best-effort. Unusual secret formats, or secrets split across lines, can slip through. Telegram stores chat history on its servers. |
| Bot token theft | Token only in env vars / an untracked `.env` outside the repo; the server refuses a token in `vscode-copilot-telegram.toml` | Anyone who reads your `.env` or process environment can impersonate the bot (send you messages). They still can't approve commands, which requires *your* user id. |
| A misconfigured or crashed server runs commands | Fail closed: config errors, Telegram errors, and timeouts all mean "not run" | — |

**Out of scope:** a compromised local machine or VS Code extension, a compromised Telegram account, and malicious code you approve.

## What is and isn't gated

| Action by Copilot | Gated by vscode-copilot-telegram? |
| --- | --- |
| Shell commands via `run_command` | **Yes.** Telegram approval, block list, allow list, jail, audit. |
| Questions via `ask_user` | Answered by you on Telegram. |
| Shell commands via the built-in **Run in Terminal** | **No.** Turn the tool off, or apply the fallback so VS Code asks. |
| File creation and edits (built-in edit tools) | **No.** Review with VS Code's Keep/Undo and `git diff`; consider `chat.tools.edits.autoApprove` rules for sensitive files. |
| Tasks, notebooks, other MCP servers or extensions | **No.** |
| Web fetches | **No** (VS Code's own URL approvals apply). |

## Token storage

- Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` in `~/.config/vscode-copilot-telegram/.env` (Windows: `C:\Users\YOU\.config\vscode-copilot-telegram\.env`). On macOS/Linux, `chmod 600` it.
- Or let VS Code prompt for it and keep it in its secret storage ([`examples/mcp.json`](examples/mcp.json)).
- Never commit a token. The repo's `.gitignore` excludes `.env`, `.env.*`, and `.vscode-copilot-telegram/`. Add `.env` and `.vscode-copilot-telegram/` to each project's `.gitignore` too.
- Don't put literal tokens in `.vscode/mcp.json` or `.mcp.json`; those files are often committed.
- If a token leaks: in @BotFather, `/mybots` → your bot → **API Token → Revoke current token**, then update the `.env` file and restart the server and watcher.

## Data sent to Telegram

To your private chat with your own bot: project name, commands, Copilot's reasons, working folders, a tail of command output, questions and answers, status notes, and, if you run the watcher, your prompts and Copilot's replies with one-line tool and file-edit summaries. All of it is masked first. It's stored by Telegram like any other chat (bot chats aren't end-to-end encrypted). If that isn't acceptable for a codebase, run without the watcher, use `--no-tools`, or don't use vscode-copilot-telegram on that project.

The audit log (`<workspace>/.vscode-copilot-telegram/audit.jsonl`) stays on your machine and is masked the same way. Output returned to **Copilot** is not masked, since Copilot already works with the workspace contents.

## Environment of approved commands

Approved commands inherit the MCP server's environment, minus `TELEGRAM_BOT_TOKEN`. That includes anything VS Code passes to MCP servers and any variables loaded from `<workspace>/.env`. Keep unrelated secrets out of that environment where you can.

## Reporting a vulnerability

This is a personal project. Report security problems privately to the project owner through GitHub (**Security → Report a vulnerability** on the repository), not in a public issue, and include steps to reproduce.
