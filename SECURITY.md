# Security

vscode-copilot-telegram puts a human approval step between GitHub Copilot and your shell, and sends parts of your development session to Telegram. This page says what it protects, what it doesn't, and how to keep the token safe.

## Threat model

**Assets:** your machine and workspace (what commands can do), your secrets (bot token, project credentials), and your code and chat content (what gets sent to Telegram).

| Threat | Mitigation | Residual risk |
| --- | --- | --- |
| Copilot runs a harmful command (model mistake or prompt injection from code, docs, web pages, or tool output) | Every command needs your **Approve** tap; built-in block list; workspace jail for `cwd`; timeout = deny | You approve something harmful without reading it. The block list is pattern-based and can be evaded; it's a safety net, not a sandbox. |
| Copilot bypasses the gate via its built-in terminal | You turn off Run in Terminal; fallback settings force VS Code's own prompt | If the built-in tool is left on and auto-approved, commands never reach Telegram. See [SETUP §7](docs/SETUP.md#7-copilot-harness-and-the-built-in-terminal). |
| A command escapes the workspace | `cwd` must resolve (after symlinks) inside the workspace | `cwd` only sets the starting folder. An approved command can still `cd ..` or touch absolute paths. Read what you approve. |
| Someone else answers your approvals | Only updates from `TELEGRAM_USER_ID` in that chat are accepted | Anyone with access to your unlocked phone or Telegram session can tap Approve. Use Telegram's passcode lock and review active sessions. |
| Replay of an old approval | Random per-request ids, single-use, persisted across restarts; timeouts are marked answered | — |
| Allow list abused through chaining (`npm test && curl … \| sh`) | Allow patterns must match the whole command, and any `;`, `&&`, `\|\|`, `\|`, backticks, `$(`, `>`, `<`, newline, or trailing `&` disables auto-approval | Overly broad allow patterns (e.g. `npm .*`) can still auto-approve things like `npm install <malicious>`. Keep patterns narrow. |
| Secrets leak to Telegram | `mask_secrets` on everything sent and logged; bot token stripped from child environments and redacted from error messages | Masking is best-effort. Unusual secret formats, or secrets split across lines, can slip through. Telegram stores chat history on its servers. |
| Bot token theft | Token only in env vars / an untracked `.env` outside the repo; the server refuses a token in `vscode-copilot-telegram.toml` | Anyone who reads your `.env` or process environment can impersonate the bot (send you messages). They still can't approve commands, which requires *your* user id. |
| A misconfigured or crashed server runs commands | Fail closed: config errors, Telegram errors, and timeouts all mean "not run" | — |
| A file inside the project changes the gate: what is auto-approved, who receives the approvals, or the address the server talks to. Copilot can write such a file (file edits aren't gated), and a cloned repository can bring one | The project `.env` is never read, so it can't change the credentials, the Bot API address, or the audit log path. An allow list (or `use_default_block = false`) in the project TOML is ignored until you accept it yourself, outside the project (see [Accepting the allow list](#accepting-the-allow-list)). The audit log is outside the project | The MCP config in the project is read by VS Code, not by this tool, so it is still trusted. You can still accept a bad allow list. The accepted copy is out of reach of VS Code's built-in edit tools, but not of a terminal command you allow. |

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

## Project files that can change the gate

Files inside the project can decide how the gate works. Copilot can create or edit them without approval, because file edits aren't gated, and a repository you clone can bring its own.

| File | What it can change | Protected by the code? |
| --- | --- | --- |
| `.env` in the project root | Nothing. Before, it could replace the Telegram credentials (so another person received and approved the requests) and the Bot API address (so another server received the bot token and answered the approvals). | **Yes.** The file is never read. If it has `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*`, or `LOG_PATH`, the server and the watcher log a warning and ignore them. |
| `vscode-copilot-telegram.toml` | `allow` decides what runs with no tap. A pattern that matches everything auto-approves every command that has no chaining characters. `use_default_block = false` turns off the built-in block list. | **Partly.** `allow` and `use_default_block = false` are ignored until you accept them yourself with `--accept-policy` (see below). The other keys (timeouts, `shell`, `block`, `project_name`) can't make a command run without your tap, so they are trusted as written. `log_path` is ignored (with a warning). |
| `.mcp.json` | Which program VS Code starts as the server, with which `--workspace` and which environment. | **No.** VS Code reads this, not this tool. |

A change to the MCP config takes effect the next time VS Code starts the server.

### Accepting the allow list

An `allow` list, or `use_default_block = false`, in `vscode-copilot-telegram.toml` is **ignored until you accept it**. You accept it by typing `vscode-copilot-telegram --accept-policy --workspace <project>` in your own terminal, reading the patterns, and typing `accept`. The accepted copy is saved outside the project, in `~/.config/vscode-copilot-telegram/accepted-policy.json`.

- If Copilot (or a cloned repository) adds, removes, or changes anything in the allow list or `use_default_block`, it no longer matches what you accepted. The allow list is then empty, the built-in block list stays on, and every command asks in Telegram. The server output and each approval message say so.
- The accept command refuses to run without a terminal, so it can't be run through `run_command` (no input) or a script. The built-in block list also denies any `run_command` that contains it, or names the accepted file.
- It checks the list when you accept it. It **refuses** a pattern that approves (almost) every command, such as `.*` or `\S+`. For every other pattern it **warns** under the pattern if it also approves risky commands, for example `git diff --output=/tmp/out.txt` (writes a file anywhere), `npm install some-package`, `python script.py`, or `pytest ../other-project`. A test runner or build tool in the list runs any code in the project, including code Copilot just wrote. The check can't judge your list, so read the patterns.
- It does **not** stop you from accepting a bad list. See the allow-list row in the threat table above for what a broad pattern allows.
- VS Code says its built-in agent tools can only read and write files inside the current workspace folder ([VS Code security page](https://code.visualstudio.com/docs/agents/run/security)). The accepted copy is in your home folder, so those tools can't change it. It can still be changed by a terminal command (the built-in Run in Terminal tool, if it is on), by another MCP server or extension, or by a `run_command` you approve (the built-in block list denies one that names the file). If the built-in terminal is on, an agent can also type `accept` itself, but then the gate is already open.
- If you open your home folder as the workspace, the accepted copy would be inside the workspace. The server then ignores it (fail closed) and `--accept-policy` refuses to save: open a project folder instead.
- Agent sandboxing in VS Code (see its security page) limits what terminal commands can touch.

What you can do:

- Before you start the server in a repository you cloned, look for the TOML and the MCP config and read them.
- Keep both in git, and check `git status` and `git diff` before you restart the server or reload the VS Code window.
- Ask VS Code to confirm edits to the files that control the gate. In your **User** settings (Preferences: Open User Settings (JSON)):

  ```jsonc
  "chat.tools.edits.autoApprove": {
    "**/.mcp.json": false,
    "**/vscode-copilot-telegram.toml": false,
    "**/.env": false
  }
  ```

  This is the setting VS Code recommends for sensitive files ([VS Code security page](https://code.visualstudio.com/docs/agents/run/security), step 4). An edit then waits for your click, so you see it before the server restarts. Servers in `.mcp.json` inherit Workspace Trust, so VS Code doesn't ask again when their `command` changes; this setting is how you get a chance to look.
- Keep the file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE` outside the project. If it points to a file inside the project, that file has the same problem the project `.env` had.
- If a warning says the allow list is not accepted and you didn't change it, find out who did (`git diff`) before you accept it again.

Not tested yet: registering the server in your **user-level** MCP configuration (outside the project) instead of the project files, so a project can't change its `command`. It is on the [to-do list](README.md#to-do).

## Token storage

- Store `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` in `~/.config/vscode-copilot-telegram/.env` (Windows: `C:\Users\YOU\.config\vscode-copilot-telegram\.env`). On macOS/Linux, `chmod 600` it.
- Never commit a token. The repo's `.gitignore` excludes `.env`, `.env.*`, and `.vscode-copilot-telegram/`. Add `.env` and `.vscode-copilot-telegram/` to each project's `.gitignore` too.
- Don't put literal tokens in `.mcp.json`; that file is often committed.
- If a token leaks: in @BotFather, `/mybots` → your bot → **API Token → Revoke current token**, then update the `.env` file and restart the server and watcher.

## Data sent to Telegram

To your private chat with your own bot: project name, commands, Copilot's reasons, working folders, a tail of command output, questions and answers, status notes, and, if you run the watcher, your prompts and Copilot's replies with one-line tool and file-edit summaries. All of it is masked first. It's stored by Telegram like any other chat (bot chats aren't end-to-end encrypted). If that isn't acceptable for a codebase, run without the watcher, use `--no-tools`, or don't use vscode-copilot-telegram on that project.

The audit log stays on your machine, outside the project (`~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl`; the start-up line in the server output shows the exact path), and is masked the same way. It is outside the project on purpose: it records what Copilot asked to run, and VS Code's built-in edit tools can't reach it there. Output returned to **Copilot** is not masked, since Copilot already works with the workspace contents.

## Environment of approved commands

Approved commands inherit the MCP server's environment, minus `TELEGRAM_BOT_TOKEN`. That includes anything VS Code passes to MCP servers and any variables loaded from `~/.config/vscode-copilot-telegram/.env` or the file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE`. The project's own `.env` is not loaded, so a command that needs it has to read it itself. Keep unrelated secrets out of that environment where you can.

## Reporting a vulnerability

This is a personal project. Report security problems privately to the project owner through GitHub (**Security → Report a vulnerability** on the repository), not in a public issue, and include steps to reproduce.
