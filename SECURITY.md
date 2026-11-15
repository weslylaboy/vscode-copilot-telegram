# Security

This tool puts a human step between GitHub Copilot and your shell. It also sends parts of your work to Telegram. This page says what it protects, what it does not, and how to keep the token safe.

## What is gated

| What Copilot does | Gated? |
| --- | --- |
| Shell commands with `run_command` | Yes. Approval in VS Code or on Telegram, block list, allow list, folder jail, audit log. |
| Questions with `ask_user` | You answer in VS Code or on Telegram. |
| Shell commands with the built-in Run in Terminal | No. Turn it off (see [SETUP.md](docs/SETUP.md#7-turn-off-the-built-in-terminal)). |
| File creation and edits (built-in edit tools) | No. Check with Keep/Undo in VS Code and with `git diff`. |
| Tasks, notebooks, other MCP servers, extensions | No. |
| Web fetches | No. The URL approvals of VS Code apply. |

## Threats

Things to protect: your computer and project, your secrets (bot token, project credentials), and your code and chat (what goes to Telegram).

| Threat | What the tool does | What stays open |
| --- | --- | --- |
| Copilot runs a harmful command (a mistake, or a prompt injection from code, docs, web pages or tool output) | Every command needs your Approve. Built-in block list. `cwd` must be inside the project. Timeout means deny. | You approve without reading. The block list is patterns, and it can be avoided. It is a safety net, not a sandbox. |
| Copilot uses the built-in terminal and skips the gate | You turn it off. The settings in SETUP make VS Code ask. | If it stays on and auto-approved, commands do not reach Telegram. |
| A command leaves the project folder | `cwd` must resolve inside the project, after symlinks. | `cwd` is only the start folder. An approved command can run `cd ..` or use absolute paths. Read what you approve. |
| Someone else answers | On Telegram, only `TELEGRAM_USER_ID`, in that chat, is accepted. In VS Code, the form is shown to the person who uses VS Code on the computer. | Anyone with your unlocked phone or Telegram session can tap Approve. Use the passcode of Telegram and check your active sessions. Anyone at your unlocked computer can answer the form. |
| A client answers the VS Code form by itself, so a command is approved without a person | The form is shown by VS Code to you (the VS Code docs call it host-rendered input). VS Code cancels forms in Autopilot, so the question goes to Telegram. | This depends on VS Code. If your client answers forms on its own, set `vscode_wait_s = 0`. Then every approval needs a Telegram tap. |
| An old approval is used again | Random id for each request, single-use, saved across restarts. A timeout also marks the request as answered. | |
| Allow list abused with chaining (`npm test && curl ... \| sh`) | A pattern must match the whole command. `;`, `&&`, `\|\|`, `\|`, backticks, `$(`, `>`, `<`, a new line, or `&` at the end turn off auto-approval. | A broad pattern like `npm .*` still approves `npm install <bad package>`. Keep patterns narrow. |
| Secrets go to Telegram | `mask_secrets` on everything sent and logged. The bot token is removed from the environment of commands and from error texts. | Masking is a best effort. An unusual format, or a secret split in two lines, can pass. Telegram keeps the chat on its servers. |
| Someone steals the bot token | The token lives only in environment variables or an untracked `.env` outside the repo. The server refuses a token in the TOML file. | With the token, a person can send you messages as your bot. They cannot approve commands, because that needs your user id. |
| A crash or a bad config runs commands | Fail closed. Config errors, Telegram errors and timeouts all mean not run. | |
| A file in the project changes the gate | See the next section. | See the next section. |

Out of scope: a hacked computer, a hacked VS Code extension, a hacked Telegram account, and malicious code that you approve.

## Files in the project that can change the gate

Copilot can create and edit files in the project without asking. A repository you clone can also bring its own files.

| File | What it could change | Protected? |
| --- | --- | --- |
| `.env` in the project | Before: the token and user id (so another person could approve), and the Bot API address (so another server could get your token). | Yes. It is never read. If it has `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*` or `LOG_PATH`, both programs write a warning and ignore them. |
| `vscode-copilot-telegram.toml` | `allow` decides what runs without a tap. `use_default_block = false` removes the built-in block list. | Partly. `allow` and `use_default_block = false` are ignored until you accept them. The other keys (timeouts, `shell`, `block`, `project_name`) cannot run a command without your tap. `log_path` is ignored. |
| `.mcp.json` | Which program VS Code starts as the server, and with which arguments and environment. | No. VS Code reads it, not this tool. |

A change in the MCP config works the next time VS Code starts the server.

### Accepting the allow list

You accept an allow list by typing `vscode-copilot-telegram --accept-policy --workspace <project>` in your own terminal, reading the patterns, and typing `accept`. The accepted copy is saved in `~/.config/vscode-copilot-telegram/accepted-policy.json`, outside the project. More in [CONFIGURATION.md](docs/CONFIGURATION.md#accept-the-allow-list).

- If anything in `allow` or `use_default_block` changes, it does not match what you accepted. The allow list becomes empty, the block list stays on, and every command asks in Telegram. The server output and each approval message say so.
- The command refuses to run without a terminal, so `run_command` and scripts cannot run it. The built-in block list also denies a `run_command` that contains it or names the accepted file.
- It refuses a pattern that approves almost everything (`.*`, `\S+`). For other patterns it prints a warning if the pattern also approves risky commands. It cannot judge your list, so read the patterns.
- It does not stop you from accepting a bad list.
- The built-in edit tools of VS Code work only inside the project folder ([VS Code security page](https://code.visualstudio.com/docs/agents/run/security)). The accepted copy is in your home folder, so they cannot change it. A terminal command can: the built-in terminal (if it is on), another MCP server or extension, or a `run_command` that you approve. If the built-in terminal is on, an agent can type `accept` itself, but then the gate is already open.
- If you open your home folder as the project, the accepted copy would be inside the project. The server ignores it and `--accept-policy` refuses to save. Open a project folder.

What you can do:

- Before you start the server in a cloned repository, read its TOML and MCP config.
- Keep both in git. Check `git status` and `git diff` before you restart the server or reload VS Code.
- Ask VS Code to confirm edits to these files. In your user settings:

  ```jsonc
  "chat.tools.edits.autoApprove": {
    "**/.mcp.json": false,
    "**/vscode-copilot-telegram.toml": false,
    "**/.env": false
  }
  ```

  VS Code recommends this setting for sensitive files. Servers in `.mcp.json` have the trust of the workspace, so VS Code does not ask again when their `command` changes. This setting gives you a click to look at it.
- Keep the file in `VSCODE_COPILOT_TELEGRAM_ENV_FILE` outside the project. In the project, it has the same problem as the project `.env`.
- If a warning says the allow list is not accepted and you did not change it, find who did (`git diff`) before you accept it again.

Another option is to register the server in your user-level MCP config, outside the project, so a project cannot change its `command`.

## The token

- Save `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID` in `~/.config/vscode-copilot-telegram/.env`. On macOS and Linux, run `chmod 600` on it.
- Never commit a token. The `.gitignore` of this repo ignores `.env`, `.env.*` and `.vscode-copilot-telegram/`. Do the same in your projects.
- Do not write the token in `.mcp.json`. That file is often committed.
- If the token leaks: in @BotFather, `/mybots`, your bot, **API Token**, **Revoke current token**. Then update the `.env` and restart the server and the watcher.

## What goes to Telegram

To your private chat with your own bot: the project name, commands, the reasons of Copilot, folders, the end of the output of commands, questions and answers, status notes. With the watcher also your prompts, the answers of Copilot, and one-line summaries of tool calls and file edits. Everything is masked first.

Telegram stores it like any other chat. Bot chats are not end-to-end encrypted. If this is not acceptable for a codebase, do not run the watcher, use `--no-tools`, or do not use this tool in that project.

The audit log stays on your computer, outside the project, and it is masked in the same way. It is outside the project because it records what Copilot asked to run, and the edit tools of VS Code cannot reach it there.

The output that goes back to Copilot is not masked. Copilot already works with your files.

## Environment of approved commands

An approved command gets the environment of the server, without `TELEGRAM_BOT_TOKEN`. That includes what VS Code passes to MCP servers and the variables from `~/.config/vscode-copilot-telegram/.env` or the file in `VSCODE_COPILOT_TELEGRAM_ENV_FILE`. The `.env` of the project is not loaded, so a command that needs it must read it. Keep unrelated secrets out of that environment.

## Report a vulnerability

This is a personal project. Report security problems in private, in GitHub: **Security**, **Report a vulnerability**, in the repository. Do not use a public issue. Add the steps to reproduce it.
