# Troubleshooting

Start with the logs:

- **MCP server:** Command Palette → **MCP: List Servers** → **vscode-copilot-telegram** → **Show Output**. Every line starts with `vscode-copilot-telegram`. Restart the server with `--log-level DEBUG` in `args` for more detail.
- **Watcher:** the terminal you started it in, `~/Library/Logs/vscode-copilot-telegram-watch.log` with the launchd setup, or `journalctl --user -u vscode-copilot-telegram-watch-your-project.service` with the systemd setup. Add `-v` for debug output.
- **Audit log:** `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` records every request and decision (the exact path is in the server output at start-up).

Contents: [The allow list does nothing](#the-allow-list-does-nothing) · [log_path is ignored](#the-server-says-log_path-is-ignored) · [No messages at all](#no-telegram-messages-at-all) · [Buttons don't respond](#buttons-dont-respond-or-say-expired) · [Several VS Code windows (409 Conflict)](#several-vs-code-windows-409-conflict) · [Watcher finds no sessions](#the-watcher-finds-no-sessions) · [Watcher sends nothing](#the-watcher-runs-but-sends-nothing) · [Copilot still uses the built-in terminal](#copilot-still-uses-the-built-in-terminal) · [Server doesn't appear](#the-server-doesnt-show-up-in-copilot) · [Wrong Copilot account](#copilot-uses-the-wrong-github-account) · [Blocked tunnels](#remote-tunnels-are-blocked-by-your-company) · [Commands fail on Windows](#commands-fail-on-windows-with-syntax-errors)

---

## The allow list does nothing

Commands that match your `allow` list still ask in Telegram, and the approval message says *The allow list in the project file is not accepted, so it is ignored.* The server output (MCP: List Servers → Show Output) has a warning that starts with `vscode-copilot-telegram.toml sets an allow list …`.

An allow list (or `use_default_block = false`) only works after you accept it, and it must be exactly what you accepted. Open the file and read the patterns, then run this yourself in a terminal (not through Copilot):

```bash
vscode-copilot-telegram --accept-policy --workspace /path/to/your/project     # full path to the venv executable
```

Type `accept`, then restart the MCP server (MCP: List Servers → Restart). It refuses to run without a terminal ("must be run by you"). If the warning appears and you did not change the file, check `git diff` first: something edited the list.

It also refuses a pattern that approves (almost) every command, such as `.*`; replace it with patterns for the exact commands you trust. If it says the accepted file "is inside" the workspace, you opened your home folder as the workspace: open a project folder instead.

## The server says `log_path` is ignored

Nothing is stopped. The server output (MCP: List Servers → Show Output) has a warning like `vscode-copilot-telegram.toml sets log_path, which is no longer read`. The audit log is outside the project now (`~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl`, the warning shows the exact path). If an older audit log is still in the project, the warning names it: move it or delete it. Remove the `log_path` line from `vscode-copilot-telegram.toml` to stop the warning. To put the log somewhere else, set `LOG_PATH` in the server's environment (VS Code's `env`, or `~/.config/vscode-copilot-telegram/.env`).

## No Telegram messages at all

Run the test from a terminal:

```bash
vscode-copilot-telegram --test --workspace /path/to/project     # full path to the venv executable
```

| Output | Cause | Fix |
| --- | --- | --- |
| `vscode-copilot-telegram: TELEGRAM_BOT_TOKEN is not set` (or `TELEGRAM_USER_ID`) | No `.env` found, or the credentials are only in the project's own `.env`, which is never read (the output then also shows `the project .env is never read`) | Create `~/.config/vscode-copilot-telegram/.env` ([SETUP §5](SETUP.md#5-save-the-token-and-user-id)). On Windows, check the file isn't saved as `.env.txt` (`dir -Force $HOME\.config\vscode-copilot-telegram`) and has no BOM. |
| `TELEGRAM_USER_ID must be a number` | You used your @username | Use the numeric id from @userinfobot. |
| `error: could not send to Telegram (Telegram error 401: Unauthorized)` | Wrong or revoked token | Copy the token again from @BotFather (`/mybots` → your bot → API Token). |
| `… (Telegram error 400: Bad Request: chat not found)` | You never pressed **Start** in the bot's chat, or the user id is wrong | Open your bot, tap **Start**, and check the id. |
| `… (Telegram error 403: Forbidden: bot was blocked by the user)` | You blocked the bot | Unblock it in Telegram. |
| `… (sendMessage failed: …)`, e.g. a connect error or timeout | No route to `api.telegram.org` (proxy, firewall, corporate network) | Try from another network. If you need an HTTPS proxy, set `HTTPS_PROXY` in the server's environment (httpx honours it). |

If `--test` works but nothing arrives from Copilot:

- The server may have a configuration error. Its output shows `configuration error: … (tools will refuse to run commands)`. The test runs in your terminal's environment; VS Code may start the server with a different environment or working directory. Check the `command` and `--workspace` in your MCP config.
- Copilot may not be calling the tools at all (it's using its built-in terminal). See [Copilot still uses the built-in terminal](#copilot-still-uses-the-built-in-terminal).

## Buttons don't respond, or say "expired"

The server only polls Telegram **while a request is waiting**, and stops when nothing is pending.

| What you see | Meaning |
| --- | --- |
| Spinner on the button, then nothing | The server isn't polling: it crashed, was restarted, or another process is polling the same bot (next section). Check the server output. |
| *This request has expired.* | The request is no longer waiting: the server restarted, or Copilot's call was cancelled. Ask Copilot to try again. |
| *Already answered.* | That request was already approved, denied, or timed out. Buttons are single-use on purpose. |
| *Waiting for your note. Reply with text.* | You tapped **Deny with note**; type the note (swipe-reply to the prompt if several are waiting). |
| *Several requests are waiting. Swipe-reply to the one you mean.* | Two questions are open; reply to the specific message. |
| *Nothing is waiting for a typed answer right now.* | You typed text but no question or note is open. Approvals only take button taps. |

Also check that you're tapping as the account whose id is `TELEGRAM_USER_ID`. Taps from any other account are ignored and logged as `ignored button press from unauthorized user`.

## Several VS Code windows (409 Conflict)

Telegram allows **one** `getUpdates` poller per bot. If two VS Code windows each run vscode-copilot-telegram with the same bot, they steal each other's taps, and the output shows:

```
another process is polling this bot (409 Conflict). Use one bot per open VS Code window, and never poll from the watcher.
```

Fix: create one bot per window or project with @BotFather, and give each project its own token. Keep each project's token in its own file outside the project (for example `~/.config/vscode-copilot-telegram/your-project.env`), and set `VSCODE_COPILOT_TELEGRAM_ENV_FILE` to that file in the project's MCP config `env` and in the environment of that project's watcher. A `.env` inside the project is not read. Set `project_name` in each project's `vscode-copilot-telegram.toml` so you can tell them apart.

Also check for leftover processes: a crashed VS Code can leave a `vscode-copilot-telegram` process behind. Windows: `Get-Process vscode-copilot-telegram`; macOS: `pgrep -fl vscode-copilot-telegram`. Stop any you don't expect. Webhooks also conflict: if the bot was ever used with a webhook, open `https://api.telegram.org/bot<TOKEN>/deleteWebhook` once.

The watcher never polls, so it never causes a 409.

## The watcher finds no sessions

Run `vscode-copilot-telegram-watch --workspace PROJECT --list`.

**`no matching workspaceStorage folder found`**

1. Open exactly that folder in VS Code (**File → Open Folder**) and send at least one chat message. VS Code creates the storage folder lazily.
2. Make sure the path matches what VS Code opened. Symlinks are resolved; on Windows and macOS the comparison ignores case. A multi-root `.code-workspace` isn't matched by folder; use `--storage` (below).
3. Check you're looking on the right machine and edition. The watcher searches:
   - Windows: `%APPDATA%\Code\User\workspaceStorage`, plus `Code - Insiders` and `VSCodium`
   - macOS: `~/Library/Application Support/Code/User/workspaceStorage`, plus Insiders and VSCodium
   - Linux: `~/.config/Code/User/workspaceStorage` (or `$XDG_CONFIG_HOME`)
   - **Remote Tunnels, SSH, WSL:** `~/.vscode-server/data/User/workspaceStorage` on the **remote** machine. Run the watcher there, not on the laptop you're browsing from. With `vscode.dev` in a browser plus a tunnel, chat history is stored on the tunnel host under `~/.vscode-server` (or `%USERPROFILE%\.vscode-server` on Windows).
   - Portable or custom installs (`--user-data-dir`): set `VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS` to the `User` folder(s).
4. Find the folder by hand and pass it explicitly. Each `workspaceStorage/<hash>/workspace.json` names its folder:
   ```powershell
   # Windows
   Get-ChildItem "$env:APPDATA\Code\User\workspaceStorage\*\workspace.json" | Select-String your-project
   ```
   ```bash
   # macOS
   grep -l your-project ~/Library/Application\ Support/Code/User/workspaceStorage/*/workspace.json
   ```
   Then run with `--storage "<that hash folder>"`.

**`(no session files yet)`**

The storage folder exists but has no chat files. Newer Copilot builds (and Copilot harness sessions) may write `GitHub.copilot-chat/transcripts/*.jsonl` instead of `chatSessions/`. Try `--source transcripts` or `--source both`. If neither has files, look inside the hash folder for where your VS Code version keeps chat data and open an issue with the folder layout (not the contents).

## The watcher runs but sends nothing

- **It only sends new messages.** On first start, existing history counts as already sent. Send a new prompt, or use `--backfill 5`.
- **Replies are sent when they finish.** A streaming reply is held back until VS Code marks it complete, or until it stops changing for `--settle` seconds (default 8).
- **Preview with `--dry-run`.** If dry-run prints messages but the real run doesn't send, it's a Telegram problem; run `vscode-copilot-telegram --test`.
- **Format change.** If `--list` shows files but `0 messages`, your VS Code version writes a format the parser doesn't understand. See [DEVELOPMENT.md](DEVELOPMENT.md#chatsessions-format-assumptions).
- **Reset its memory.** Stop the watcher and delete `~/.vscode-copilot-telegram/watch-<project>-<hash>.json`.

## Copilot still uses the built-in terminal

Symptoms: VS Code shows its own "Run command?" prompt, or commands run without a Telegram message.

1. **Configure Tools:** in an Agent chat, open Configure Tools and untick **Run in Terminal** (and Run Task / Create and Run Task if present). This is per chat-mode; check again after switching modes or harness.
2. **Copilot harness sessions** may not let you untick it. Apply the fallback in [SETUP §7](SETUP.md#7-local-vs-copilot-harness-sessions) (`chat.tools.eligibleForAutoApproval` with `"runInTerminal": false`, and `chat.tools.terminal.enableAutoApprove: false`) so the built-in tool can never run anything without a click, or switch the session to **Local**.
3. **Instructions:** check `PROJECT/.github/copilot-instructions.md` contains the lines from [`examples/copilot-instructions.md`](../examples/copilot-instructions.md), and that `github.copilot.chat.codeGeneration.useInstructionFiles` is on.
4. **Tool enabled:** in Configure Tools, the vscode-copilot-telegram server and `run_command` must be ticked.
5. **Ask explicitly** once: "Use run_command for this." Models tend to follow the instructions file after that.
6. **Don't use Allow all / Autopilot** permission levels for this workspace; they skip confirmation for built-in tools.

## The server doesn't show up in Copilot

- **Wrong file for your harness.** Local sessions read `PROJECT/.vscode/mcp.json` (`"servers"`). Copilot harness sessions read `PROJECT/.mcp.json` at the root (`"mcpServers"`). See [SETUP §7–8](SETUP.md#7-local-vs-copilot-harness-sessions).
- **JSON error.** `.vscode/mcp.json` allows comments; `.mcp.json` should be plain JSON. VS Code underlines errors.
- **Wrong command path.** Use the full path to the venv executable (`…\.venv\Scripts\vscode-copilot-telegram.exe` on Windows, `…/.venv/bin/vscode-copilot-telegram` on macOS). Test it by running that exact path with `--help` in a terminal.
- **Workspace trust / MCP disabled by policy.** Trust the workspace when VS Code asks. Organizations can disable MCP servers (`chat.mcp.access`); if MCP is turned off by your enterprise, vscode-copilot-telegram can't be used.
- **Server output shows a Python traceback** at startup: reinstall with `pip install -e .` in the venv, and make sure it's Python 3.11+.

## Copilot uses the wrong GitHub account

Common after enabling Remote Tunnels with a personal account while Copilot is licensed through a business account.

1. Click the **Accounts** icon (bottom-left). If the business account isn't listed, sign in with it as an additional GitHub account.
2. Command Palette → **Accounts: Manage Extension Account Preferences**.
3. Choose **GitHub Copilot Chat** → select the business account. Repeat for **GitHub Copilot** if it's listed.
4. **Developer: Reload Window.**

In a `vscode.dev` browser session over a tunnel, repeat the steps there; the browser keeps its own choice. If your business account is on GitHub Enterprise Cloud with data residency (a `*.ghe.com` address), set **`github-enterprise.uri`** to your `https://<subdomain>.ghe.com` URL and sign in with "GitHub Enterprise" instead of a normal GitHub account.

vscode-copilot-telegram itself doesn't care which account Copilot uses.

## Remote Tunnels are blocked by your company

If **Remote Tunnels: Turn on Remote Tunnel Access** is missing or fails, your organization has probably disabled tunnels by policy or blocks `*.tunnels.api.visualstudio.com` / `global.rel.tunnels.api.visualstudio.com` on the network. You don't need tunnels for vscode-copilot-telegram: approvals and the chat mirror work from your phone over Telegram while VS Code runs on your desk. For full remote screen access, use Chrome Remote Desktop or your company's approved remote-access tool. Don't try to get around the policy.

## Commands fail on Windows with syntax errors

The default shell on Windows is `cmd.exe`. If Copilot writes PowerShell (`Get-ChildItem`, `$env:FOO`), set `shell = "powershell"` (or `"pwsh"`) in `vscode-copilot-telegram.toml` and restart the server. Add a line to your instructions file telling Copilot which shell to target.
