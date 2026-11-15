# Troubleshooting

First, look at the logs:

- Server: Command Palette, **MCP: List Servers**, choose the server, **Show Output**. Add `"--log-level", "DEBUG"` to `args` for more detail.
- Watcher: the terminal where you started it. With launchd: `~/Library/Logs/vscode-copilot-telegram-watch.log`. With systemd: `journalctl --user -u vscode-copilot-telegram-watch-PROJECT_NAME.service`. Add `-v` for debug.
- Audit log: `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl`. The server prints the exact path when it starts.

Problems:

- [A change has no effect](#a-change-has-no-effect)
- [No Telegram messages](#no-telegram-messages)
- [The question does not come to Telegram, or no form appears in VS Code](#the-question-does-not-come-to-telegram-or-no-form-appears-in-vs-code)
- [Buttons do not answer](#buttons-do-not-answer)
- [409 Conflict](#409-conflict)
- [The allow list does nothing](#the-allow-list-does-nothing)
- [The server says log_path is ignored](#the-server-says-log_path-is-ignored)
- [Copilot uses the built-in terminal](#copilot-uses-the-built-in-terminal)
- [The server does not appear](#the-server-does-not-appear)
- [The watcher finds no sessions](#the-watcher-finds-no-sessions)
- [The watcher sends nothing](#the-watcher-sends-nothing)
- [Commands fail on Windows](#commands-fail-on-windows)
- [Copilot uses the wrong GitHub account](#copilot-uses-the-wrong-github-account)
- [Remote Tunnels are blocked](#remote-tunnels-are-blocked)

## A change has no effect

You changed `vscode-copilot-telegram.toml`, updated the tool, or changed the code, but Copilot behaves as before.

VS Code runs two copies of the server. The editor has one. The Copilot runtime has its own, and it starts a new one for each chat. A copy never reloads: it keeps the code and the settings it started with.

**MCP: List Servers**, then **Restart**, only restarts the editor's copy. Your chat keeps using its own copy.

To use the change:

1. Start a **new chat** in the project (agent mode, Copilot harness). It starts a fresh server.
2. Or stop and start the server for the chat you have: **Chat: Open Customizations**, then **MCP Servers**, then the server.

To check which copy answered: the `via` field of the newest line in the audit log shows where an approval came from (`vscode` or `telegram`). A line for the server with "connected" in the Copilot log (`agenthost.log` in the VS Code logs folder) shows when the runtime started it.

## No Telegram messages

Run the test in a terminal:

```bash
vscode-copilot-telegram --test --workspace /path/to/project
```

Use the full path to the command from the `.venv`.

| Output | Cause | Fix |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN is not set` (or `TELEGRAM_USER_ID`) | The `.env` file was not found. Or the values are only in the `.env` of the project, which is never read. | Create `~/.config/vscode-copilot-telegram/.env` ([SETUP.md](SETUP.md#4-save-the-token-and-the-user-id)). On Windows, check that the file is not `.env.txt` and has no BOM. |
| `TELEGRAM_USER_ID must be a number` | You used your @username. | Use the number from @userinfobot. |
| `Telegram error 401: Unauthorized` | The token is wrong or revoked. | Copy it again from @BotFather: `/mybots`, your bot, API Token. |
| `Telegram error 400: Bad Request: chat not found` | You did not press Start in the bot, or the user id is wrong. | Open your bot, tap Start, check the id. |
| `Telegram error 403: Forbidden: bot was blocked by the user` | You blocked the bot. | Unblock it in Telegram. |
| `sendMessage failed: ...` (connect error, timeout) | Your computer cannot reach `api.telegram.org`. | Try another network. If you need a proxy, set `HTTPS_PROXY` in the environment of the server. |

If `--test` works but nothing arrives from Copilot:

- Look at the output of the server. A line with `configuration error` means all commands are refused. The test runs in your terminal, but VS Code can start the server with another environment. Check `command` and `--workspace` in `.mcp.json`.
- Copilot may use its built-in terminal. See [Copilot uses the built-in terminal](#copilot-uses-the-built-in-terminal).

## The question does not come to Telegram, or no form appears in VS Code

Copilot asks in VS Code first. The same question goes to Telegram after `vscode_wait_s` seconds (180 by default), if you did not answer. See [CONFIGURATION.md](CONFIGURATION.md#ask-in-vs-code-first-then-telegram).

| What you see | What it means |
| --- | --- |
| Nothing in Telegram for 3 minutes | This is normal. The form in VS Code is waiting for you. Answer it, or wait. To test faster, set `vscode_wait_s = 10` in `vscode-copilot-telegram.toml` and start a new chat (see [A change has no effect](#a-change-has-no-effect)). |
| The message in Telegram comes at once | VS Code cannot show the form, so the server skipped the wait. Look for `VS Code did not take the question` in the output of the server. The chat may be in Autopilot, or your VS Code does not support forms for MCP servers. |
| No form in VS Code, and the message comes at once | Same as above. Telegram still works, so you are not blocked. |
| The form stays open in VS Code after you answered on Telegram | You use `mcp` 1.x, which does not close it. Install `mcp` 2.x (`pip install -U mcp`) and restart the server. Answers to the old form are ignored. |
| The server output says `Cannot send 'elicitation/create': this transport context has no back-channel` | The client connected with the 2026-07-28 protocol, where forms cannot work. The server should refuse that protocol and print `answering server/discover with 'method not found'` at the start. If you do not see that line, you may run an old copy of the server: restart it and check the `command` in `.mcp.json`. |
| You want Telegram only | Set `vscode_wait_s = 0`. |

The server output is in **MCP: List Servers**, the server, **Show Output**.

## Buttons do not answer

The server reads Telegram only while a request is waiting.

| What you see | What it means |
| --- | --- |
| The button spins and nothing happens | The server is not reading Telegram. It crashed, it was restarted, or another program reads the same bot (see [409 Conflict](#409-conflict)). Look at the output of the server. |
| This request has expired. | The request is not waiting anymore. The server restarted, or Copilot cancelled the call. Ask Copilot to try again. |
| Already answered. | That request was already approved, denied or timed out. Buttons work only once. |
| Waiting for your note. Reply with text. | You tapped Deny with note. Write the note. If several requests wait, swipe-reply to the right message. |
| Several requests are waiting. Swipe-reply to the one you mean. | Two questions are open. Reply to one message. |
| Nothing is waiting for a typed answer right now. | You wrote text, but no question or note is open. Approvals use buttons only. |

Check that you tap with the account whose id is in `TELEGRAM_USER_ID`. Taps from other accounts are ignored. The log says `ignored button press from unauthorized user`.

## 409 Conflict

Telegram lets one program read the answers of a bot. If two VS Code windows use the same bot, the output shows:

```
another process is polling this bot (409 Conflict). Use one bot per open VS Code window, and never poll from the watcher.
```

Fix:

1. Create one bot for each project in @BotFather.
2. Save each token in its own file outside the project, like `~/.config/vscode-copilot-telegram/PROJECT_NAME.env`.
3. Set `VSCODE_COPILOT_TELEGRAM_ENV_FILE` to that file, in the `env` of `.mcp.json` and in the environment of the watcher.
4. Set `project_name` in each `vscode-copilot-telegram.toml`, so you can see which project sends the message.

Also look for old processes. A VS Code that crashed can leave one. Windows: `Get-Process vscode-copilot-telegram`. macOS: `pgrep -fl vscode-copilot-telegram`. Stop the ones you do not expect.

If the bot was ever used with a webhook, delete it once. Use curl, so the token does not stay in your browser history:

```bash
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

The watcher never reads Telegram, so it never causes a 409.

## The allow list does nothing

Commands from your `allow` list still ask in Telegram. The approval message says `The allow list in the project file is not accepted, so it is ignored.` The output of the server has a warning that starts with `vscode-copilot-telegram.toml sets an allow list`.

You must accept the allow list yourself. Read the patterns in the file, then run this in a terminal (not through Copilot):

```bash
vscode-copilot-telegram --accept-policy --workspace /path/to/your/project
```

Type `accept`, then restart the server.

- If it says `must be run by you`, you ran it from a script or a pipe. Use a normal terminal.
- If it refuses a pattern like `.*`, use patterns for the exact commands you trust.
- If it says the accepted file is inside the project, you opened your home folder as the project. Open a project folder.
- If the warning appears and you did not change the file, run `git diff` first. Something changed the list.

## The server says log_path is ignored

Nothing is broken. The output has a warning like `vscode-copilot-telegram.toml sets log_path, which is no longer read`. The audit log is outside the project now, and the warning shows where. If an old log is still in the project, the warning names it. Move it or delete it.

Delete the `log_path` line from the TOML file to remove the warning. To use another path, set `LOG_PATH` in the environment of the server.

## Copilot uses the built-in terminal

You see a VS Code prompt "Run command?", or a command runs and there is no Telegram message.

1. Add the two settings from [SETUP.md](SETUP.md#7-turn-off-the-built-in-terminal). You cannot switch the built-in terminal off in the Copilot harness. The Tools tab shows it as read-only.
2. Check that `PROJECT/.github/copilot-instructions.md` has the text from [examples/copilot-instructions.md](../examples/copilot-instructions.md). Then check that VS Code found it: **Chat: Open Customizations**, then **Instructions**.
3. Check that the server and `run_command` are enabled.
4. Ask once: `Use run_command for this.`
5. Do not use the permission levels Allow all and Autopilot in this project. They skip confirmations for built-in tools.

## The server does not appear

- Wrong file. The server must be in `PROJECT/.mcp.json`, in the root of the project. `.vscode/mcp.json` is not supported.
- JSON error. `.mcp.json` is plain JSON. It cannot have comments. VS Code underlines errors.
- Sandbox. If the output says `MCP server failed to initialize inside the sandbox` or `PermissionError: ... pyvenv.cfg`, set `chat.agent.sandbox.mcpServers` to `false` in your user settings and restart the server.
- Wrong path. Use the full path to the file in the `.venv`. Run that exact path with `--help` in a terminal to check it.
- Trust and policy. Trust the workspace when VS Code asks. Your organization can disable MCP servers (`chat.mcp.access`). Then this tool cannot be used.
- Python error in the output. Run `pip install -e .` again in the `.venv`, and check that Python is 3.11 or newer.

## The watcher finds no sessions

Run:

```bash
vscode-copilot-telegram-watch --workspace PROJECT --list
```

If you see `no matching workspaceStorage folder found`:

1. Open that exact folder in VS Code (File, Open Folder), and send one chat message. VS Code creates the storage folder only after that.
2. Check that the path is the same one VS Code opened. Symlinks are resolved. On Windows and macOS, the case is ignored. A multi-root `.code-workspace` is not matched. Use `--storage`.
3. Check the machine and the edition. The folders it searches are in [CONFIGURATION.md](CONFIGURATION.md#where-things-are). With Tunnels, SSH or WSL, run the watcher on the remote machine. For a portable install or `--user-data-dir`, set `VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS`.
4. Find the folder by hand. Each `workspaceStorage/<hash>/workspace.json` tells which folder it is.

   Windows:

   ```powershell
   Get-ChildItem "$env:APPDATA\Code\User\workspaceStorage\*\workspace.json" | Select-String PROJECT_NAME
   ```

   macOS:

   ```bash
   grep -l PROJECT_NAME ~/Library/Application\ Support/Code/User/workspaceStorage/*/workspace.json
   ```

   Then run the watcher with `--storage "<that folder>"`.

If you see `(no session files yet)`: the folder exists but has no chat files. New Copilot builds can write `GitHub.copilot-chat/transcripts/*.jsonl` and not `chatSessions/`. Try `--source transcripts` or `--source both`. If both are empty, open an issue with the folder layout (not the content).

## The watcher sends nothing

- It sends only new messages. On the first start, the old history counts as sent. Send a new prompt, or use `--backfill 5`.
- A reply is sent when it is finished, or when it does not change for `--settle` seconds (8 by default).
- Try `--dry-run`. If it prints messages but the real run does not send, the problem is Telegram. Run `vscode-copilot-telegram --test`.
- If `--list` shows files but `0 messages`, your VS Code writes a format the parser does not know. See [DEVELOPMENT.md](DEVELOPMENT.md#chat-file-formats).
- To reset its memory, stop the watcher and delete `~/.vscode-copilot-telegram/watch-<project>-<hash>.json`.

## Commands fail on Windows

The default shell on Windows is `cmd.exe`. If Copilot writes PowerShell (`Get-ChildItem`, `$env:FOO`), set `shell = "powershell"` (or `"pwsh"`) in `vscode-copilot-telegram.toml` and restart the server. Also tell Copilot in your instructions file which shell to use.

## Copilot uses the wrong GitHub account

This happens often when you use Remote Tunnels with a personal account, but Copilot has a license from your company.

1. Click the Accounts icon (bottom left). If the company account is not there, sign in with it.
2. Command Palette, **Accounts: Manage Extension Account Preferences**.
3. Choose **GitHub Copilot Chat** and select the company account. Do the same for **GitHub Copilot**, if it is in the list.
4. Run **Developer: Reload Window**.

In a `vscode.dev` session over a tunnel, do it again there. The browser keeps its own choice.

If your company uses GitHub Enterprise Cloud with data residency (an address like `*.ghe.com`), set `github-enterprise.uri` to `https://<subdomain>.ghe.com` and sign in with GitHub Enterprise.

This tool does not care which account Copilot uses.

## Remote Tunnels are blocked

If **Remote Tunnels: Turn on Remote Tunnel Access** is missing or fails, your company probably blocks tunnels, or blocks `*.tunnels.api.visualstudio.com` and `global.rel.tunnels.api.visualstudio.com`.

You do not need tunnels for this tool. Approvals and the chat mirror work on your phone while VS Code runs on your computer. Do not try to go around the company policy.
