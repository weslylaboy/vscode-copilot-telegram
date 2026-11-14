# Setup guide

This guide takes you from nothing to "Copilot asks, my phone answers" on **Windows (PowerShell)** and **macOS**. Linux works the same as macOS except for the paths noted in [CONFIGURATION.md](CONFIGURATION.md) and the auto-start section.

Plan on about 20 minutes. Every step ends with a check, so you know it worked before moving on.

Throughout this guide:

| Placeholder | Meaning | Windows example | macOS example |
| --- | --- | --- | --- |
| `TOOL_DIR` | Where you install vscode-copilot-telegram (its own folder, **not** inside your project) | `C:\Users\YOU\tools\vscode-copilot-telegram` | `/Users/YOU/tools/vscode-copilot-telegram` |
| `PROJECT` | The project folder you open in VS Code | `C:\Users\YOU\code\your-project` | `/Users/YOU/code/your-project` |

Contents:

1. [Prerequisites](#1-prerequisites)
2. [Create the Telegram bot](#2-create-the-telegram-bot)
3. [Get your Telegram user id](#3-get-your-telegram-user-id)
4. [Clone and install](#4-clone-and-install)
5. [Save the token and user id](#5-save-the-token-and-user-id)
6. [Test Telegram](#6-test-telegram)
7. [Local vs Copilot harness sessions](#7-local-vs-copilot-harness-sessions)
8. [Register the MCP server in your project](#8-register-the-mcp-server-in-your-project)
9. [Turn off Run in Terminal and auto-approve the vscode-copilot-telegram tools](#9-turn-off-run-in-terminal-and-auto-approve-the-vscode-copilot-telegram-tools)
10. [Tell Copilot to use the tools](#10-tell-copilot-to-use-the-tools)
11. [Run the chat mirror and keep it running](#11-run-the-chat-mirror-and-keep-it-running)
12. [End-to-end verification checklist](#12-end-to-end-verification-checklist)
13. [Updating and uninstalling](#13-updating-and-uninstalling)

---

## 1. Prerequisites

- **Python 3.11 or newer.**
  - Windows: install from [python.org](https://www.python.org/downloads/windows/) and tick **"Add python.exe to PATH"**, or run `winget install Python.Python.3.12`. Check with `py -3 --version`.
  - macOS: `brew install python@3.12` (or the python.org installer). Check with `python3 --version`. The system Python on older macOS is too old.
- **git.** Windows: `winget install Git.Git`. macOS: `xcode-select --install` or `brew install git`.
- **VS Code** with the **GitHub Copilot** and **GitHub Copilot Chat** extensions, signed in with the account that has your Copilot license, and **agent mode** available in the chat view.
- **Telegram** on your phone (and optionally desktop).
- Outbound HTTPS to `api.telegram.org` from the computer that runs VS Code's extension host. If you use VS Code Remote Tunnels or SSH, that's the **remote** machine, so install vscode-copilot-telegram there.

## 2. Create the Telegram bot

1. In Telegram, open a chat with **@BotFather** (blue check mark).
2. Send `/newbot`. Give it a display name (e.g. `Copilot – your-project`) and a username ending in `bot` (e.g. `yourname_copilot_bot`).
3. BotFather replies with a token like `123456789:AAH...`. **Copy it and treat it like a password.** Anyone with it can send messages as your bot.
4. Open the chat with your new bot (BotFather links it) and tap **Start**. A bot can't message you until you've done this.

> Use **one bot per VS Code window** that runs the MCP server. Telegram only lets one process poll a bot for replies, so two windows sharing a bot steal each other's button taps. The watcher only sends, so it can share the bot of the window it mirrors.

✅ Check: you have a token, and your bot's chat shows that you pressed Start.

## 3. Get your Telegram user id

1. Open a chat with **@userinfobot** and send it any message.
2. It replies with your numeric **Id** (e.g. `123456789`). That number is `TELEGRAM_USER_ID`.

It's a number, not your @username. vscode-copilot-telegram ignores every message and button tap from anyone whose id doesn't match.

## 4. Clone and install

Install vscode-copilot-telegram once, in its own folder with its own virtual environment. You don't install it into each project.

**Windows (PowerShell):**

```powershell
mkdir $HOME\tools -Force | Out-Null
cd $HOME\tools
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

If `Activate.ps1` is blocked ("running scripts is disabled"), run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip activation and call `.\.venv\Scripts\pip.exe install -e .` directly.

**macOS (zsh):**

```bash
mkdir -p ~/tools && cd ~/tools
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

`pip install -e .` creates two commands inside the venv. Note their full paths; you'll paste them into VS Code config later:

| Command | Windows path | macOS path |
| --- | --- | --- |
| MCP server | `TOOL_DIR\.venv\Scripts\vscode-copilot-telegram.exe` | `TOOL_DIR/.venv/bin/vscode-copilot-telegram` |
| Chat mirror | `TOOL_DIR\.venv\Scripts\vscode-copilot-telegram-watch.exe` | `TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch` |

✅ Check: `vscode-copilot-telegram --help` and `vscode-copilot-telegram-watch --help` print usage text.

## 5. Save the token and user id

Both programs read credentials from environment variables, and load `.env` files without overriding variables that are already set. They look in this order (the first file that sets a variable wins):

1. The file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE`, if set
2. `~/.config/vscode-copilot-telegram/.env` (Windows: `C:\Users\YOU\.config\vscode-copilot-telegram\.env`)

**Use the second one.** It lives outside every repository, works for all your projects, and both programs find it.

A `.env` inside your project is **never read**, on purpose: Copilot can edit files in the project without approval, so that file must not be able to change who approves commands. If the project `.env` has these settings, both programs write a warning in their log and ignore them.

**Windows (PowerShell):**

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\vscode-copilot-telegram" | Out-Null
@"
TELEGRAM_BOT_TOKEN=123456789:AAH-your-token
TELEGRAM_USER_ID=123456789
"@ | Set-Content -Encoding ascii "$HOME\.config\vscode-copilot-telegram\.env"
```

Use `-Encoding ascii` (or save from an editor as UTF-8 **without** BOM). Windows PowerShell 5's `-Encoding utf8` adds a byte-order mark that breaks the first variable name.

**macOS:**

```bash
mkdir -p ~/.config/vscode-copilot-telegram
cat > ~/.config/vscode-copilot-telegram/.env <<'ENV'
TELEGRAM_BOT_TOKEN=123456789:AAH-your-token
TELEGRAM_USER_ID=123456789
ENV
chmod 600 ~/.config/vscode-copilot-telegram/.env
```

A template is in [`examples/env.example`](../examples/env.example). Other ways to supply the credentials (VS Code input prompts, `envFile`) are in [CONFIGURATION.md](CONFIGURATION.md#ways-to-supply-the-token).

## 6. Test Telegram

```powershell
# Windows
& "$HOME\tools\vscode-copilot-telegram\.venv\Scripts\vscode-copilot-telegram.exe" --test --workspace "C:\Users\YOU\code\your-project"
```

```bash
# macOS
~/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram --test --workspace ~/code/your-project
```

✅ Check: the command prints `sent`, and your bot sends **"[your-project] 📣 ✅ vscode-copilot-telegram test message. Telegram is set up correctly."**

If it prints `vscode-copilot-telegram: TELEGRAM_BOT_TOKEN is not set` (or `TELEGRAM_USER_ID`), the `.env` file wasn't found or is malformed. If it prints `error: could not send to Telegram (...)`, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#no-telegram-messages-at-all).

`--test` doesn't start the MCP server and doesn't poll, so it's safe to run while VS Code is open.

## 7. Local vs Copilot harness sessions

VS Code can run agent sessions with different "harnesses". Two matter here, Local and Copilot. You pick one in the Session Target picker. They read MCP config from different files and handle the built-in terminal tool differently, which matters for the approval gate.

| | **Local** harness | **Copilot** harness |
| --- | --- | --- |
| MCP config it reads | `PROJECT/.vscode/mcp.json` (`"servers"` format) | `PROJECT/.mcp.json` at the workspace root (`"mcpServers"` format) |
| Can you untick **Run in Terminal**? | Yes, in **Configure Tools** | Not always; some builds hide the built-in tools from the picker |
| Status | Deprecated by VS Code; scheduled for removal in **February 2027** | The default going forward |

**Which one to use:** while your VS Code still offers **Local** sessions, use one, because you can switch off the built-in terminal there and the gate is airtight. Create the `.mcp.json` as well (step 8). After Local is removed, use the Copilot harness; the settings below are then the normal setup, not a fallback.

**If you're in a Copilot harness session and can't untick Run in Terminal**, add these to your VS Code **User** settings (Command Palette → **Preferences: Open User Settings (JSON)**):

```jsonc
{
  // The built-in terminal tool always asks in VS Code and can never be auto-approved.
  "chat.tools.eligibleForAutoApproval": { "runInTerminal": false },
  // Don't silently auto-run "safe" commands through the built-in terminal either.
  "chat.tools.terminal.enableAutoApprove": false
}
```

Then the built-in terminal can't run anything without a click **in VS Code**. Your instructions file (step 10) tells Copilot to use `run_command` instead, so the normal path still goes to Telegram. If a VS Code terminal prompt shows up anyway, click **Skip/Deny** and tell Copilot "use run_command". Also keep the session's permission level on **Manual permissions** (`chat.permissions.default` = `default`); **Allow all** and **Autopilot** skip confirmations for built-in tools.

This fallback means commands never run unapproved, but approvals that slip through the built-in tool happen at the desk, not on the phone. The roadmap item that closes this gap (a `preToolUse` hook) is in [DEVELOPMENT.md](DEVELOPMENT.md#roadmap).

## 8. Register the MCP server in your project

Use the **full path** to the `vscode-copilot-telegram` executable from step 4. Don't rely on `PATH`; VS Code may not see your venv.

### Local harness: `PROJECT/.vscode/mcp.json`

Copy [`examples/mcp.envfile.json`](../examples/mcp.envfile.json) to `PROJECT/.vscode/mcp.json` and fix the `command` path.

Windows:

```jsonc
{
  "servers": {
    "vscode-copilot-telegram": {
      "type": "stdio",
      "command": "C:\\Users\\YOU\\tools\\vscode-copilot-telegram\\.venv\\Scripts\\vscode-copilot-telegram.exe",
      "args": ["--workspace", "${workspaceFolder}"],
      "cwd": "${workspaceFolder}",
      "envFile": "${userHome}/.config/vscode-copilot-telegram/.env"
    }
  }
}
```

macOS: same, with `"command": "/Users/YOU/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram"`.

`envFile` is optional (the server reads `~/.config/vscode-copilot-telegram/.env` on its own); it just makes the source explicit. If you'd rather have VS Code prompt for the token and store it in its secret storage, use [`examples/mcp.json`](../examples/mcp.json) instead.

### Copilot harness: `PROJECT/.mcp.json`

Copy [`examples/dot-mcp.json`](../examples/dot-mcp.json) to `PROJECT/.mcp.json` (the root of the project, not `.vscode/`). This format has no working-directory field, so pass the project path explicitly with `--workspace`:

```json
{
  "mcpServers": {
    "vscode-copilot-telegram": {
      "type": "stdio",
      "command": "/Users/YOU/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram",
      "args": ["--workspace", "/Users/YOU/code/your-project"],
      "tools": ["*"]
    }
  }
}
```

On Windows use `"command": "C:\\Users\\YOU\\tools\\vscode-copilot-telegram\\.venv\\Scripts\\vscode-copilot-telegram.exe"` and `"args": ["--workspace", "C:\\Users\\YOU\\code\\your-project"]`.

The `--workspace` folder is the jail: `run_command` refuses any `cwd` outside it, and the audit log goes to `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl`, outside the project. If you leave `--workspace` out, the server uses `$WORKSPACE_ROOT`, then its current directory.

Both files contain only paths, no secrets, so you can commit them if your team uses the same layout. Add `.vscode-copilot-telegram/` to the project's `.gitignore`.

### Start it

Open the file in VS Code. Click the **Start** code lens above `"vscode-copilot-telegram"` (or run **MCP: List Servers** → vscode-copilot-telegram → **Start Server**). Then **MCP: List Servers** → vscode-copilot-telegram → **Show Output** should show a line like `workspace /…/your-project, audit log /Users/YOU/.vscode-copilot-telegram/audit-your-project-<hash>.jsonl`.

If the output says `configuration error: …`, the server still starts, but every tool refuses to run commands (fail closed). Fix the error and restart the server.

✅ Check: the server status is **Running** and lists 3 tools: `ask_user`, `run_command`, `notify`.

## 9. Turn off Run in Terminal and auto-approve the vscode-copilot-telegram tools

1. Open Copilot Chat and select **Agent** mode.
2. Click the **Configure Tools** (🔧) button in the chat input.
3. **Untick "Run in Terminal"** (`runInTerminal`, under Built-In). If you see other built-in tools that run shell commands or tasks (e.g. **Run Task**, **Create and Run Task**), untick them too.
4. **Tick the `vscode-copilot-telegram` server** and its three tools.
5. Run **Chat: Manage Tool Approval** from the Command Palette. Under **vscode-copilot-telegram**, tick the top-level box for **pre-approval ("without approval")**. You don't need post-approval.
   Alternatively, the first time Copilot calls one of these tools, choose **Always Allow** in the confirmation dropdown.

Why step 5: otherwise every `run_command` asks twice, once in VS Code and once in Telegram. Telegram is the real gate; VS Code's prompt adds nothing. Pre-approving `run_command` is safe because the tool itself waits for your Telegram tap.

If you can't untick Run in Terminal (Copilot harness), apply the fallback settings in [§7](#7-local-vs-copilot-harness-sessions).

✅ Check: in Configure Tools, Run in Terminal is unticked and vscode-copilot-telegram is ticked.

### Ask for a click before Copilot edits the files that control the gate

Copilot can edit files in the project without approval, including `.vscode/mcp.json` (which decides what program VS Code starts as the server) and `vscode-copilot-telegram.toml`. VS Code gives MCP servers in `.vscode/mcp.json` and `.mcp.json` the same trust as the workspace, so it doesn't ask again when their `command` changes. Add this to your VS Code **User** settings (Command Palette → **Preferences: Open User Settings (JSON)**), so edits to these files wait for your click:

```jsonc
{
  "chat.tools.edits.autoApprove": {
    "**/.vscode/mcp.json": false,
    "**/.mcp.json": false,
    "**/vscode-copilot-telegram.toml": false,
    "**/.env": false
  }
}
```

More in [SECURITY.md](../SECURITY.md#accepting-the-allow-list).

## 10. Tell Copilot to use the tools

Create or edit `PROJECT/.github/copilot-instructions.md` and paste the contents of [`examples/copilot-instructions.md`](../examples/copilot-instructions.md):

```markdown
## Running commands and asking questions (vscode-copilot-telegram)

- Run every shell command with the `run_command` tool from the vscode-copilot-telegram MCP server. Do not use any other terminal or shell tool. Always pass a one-sentence `reason`.
- If `run_command` returns a decision other than `approved` or `auto-approved`, the command did not run. Do not retry the same command in another form. Read the user's note if there is one, adjust your plan, or use `ask_user`.
- When you need a decision, a preference, a missing value, or confirmation from me, call `ask_user` instead of asking in chat and stopping. Offer short `options` when the choice is between a few alternatives. If it returns `timeout`, pick the safest option or stop and explain.
- Call `notify` with a one-line status at milestones: plan ready, tests passing or failing, task finished, or blocked.
- Never put secrets, tokens, or .env contents in a command, question, or notification.
```

The server also sends short usage instructions to Copilot when it connects, but the instructions file is what Copilot reliably follows. Check that **GitHub › Copilot › Chat › Code Generation: Use Instruction Files** (`github.copilot.chat.codeGeneration.useInstructionFiles`) is on (the default).

## 11. Run the chat mirror and keep it running

The watcher forwards your prompts and Copilot's replies. It's optional: approvals and questions work without it.

### Find the session files first

Open `PROJECT` in VS Code and send at least one chat message, then:

```powershell
# Windows
& "$HOME\tools\vscode-copilot-telegram\.venv\Scripts\vscode-copilot-telegram-watch.exe" --workspace "C:\Users\YOU\code\your-project" --list
```

```bash
# macOS
~/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram-watch --workspace ~/code/your-project --list
```

✅ Check: it prints `storage: …/workspaceStorage/<hash>` and at least one session file with a message count. If not, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#the-watcher-finds-no-sessions).

To preview what would be sent, without a token: add `--dry-run --backfill 5` (Ctrl+C to stop).

### Run it in a terminal

```bash
vscode-copilot-telegram-watch --workspace ~/code/your-project        # use the full path as above
```

On first start it treats existing history as already sent, then forwards everything new. Use `--backfill N` to also send the last N messages of existing sessions, and `--no-tools` to leave out tool and file-edit lines. All flags are in [CONFIGURATION.md](CONFIGURATION.md#vscode-copilot-telegram-watch-flags).

Run one watcher per project. It keeps its "already sent" state in `~/.vscode-copilot-telegram/watch-<project>-<hash>.json`, so restarts don't send duplicates.

### Keep it running on Windows (Task Scheduler)

This starts the watcher at logon, without a console window, and restarts it if it crashes. Run in PowerShell (no admin needed):

```powershell
$venv    = "$HOME\tools\vscode-copilot-telegram\.venv"
$project = "C:\Users\YOU\code\your-project"
$name    = "vscode-copilot-telegram-watch (your-project)"

$action   = New-ScheduledTaskAction -Execute "$venv\Scripts\pythonw.exe" `
              -Argument "-m vscode_copilot_telegram.watcher --workspace `"$project`"" `
              -WorkingDirectory $project
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
  -Description "Mirror Copilot chat for $project to Telegram"
Start-ScheduledTask -TaskName $name
```

`pythonw.exe -m vscode_copilot_telegram.watcher` is the same program as `vscode-copilot-telegram-watch.exe`, minus the console window (so it also has no visible log; test it in a terminal first). Manage it with `Get-ScheduledTask -TaskName $name`, `Stop-ScheduledTask`, and `Unregister-ScheduledTask -TaskName $name -Confirm:$false`.

### Keep it running on macOS (launchd)

Create `~/Library/LaunchAgents/com.vscode-copilot-telegram.watch.your-project.plist` (replace `YOU` and the paths; launchd doesn't expand `~`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vscode-copilot-telegram.watch.your-project</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram-watch</string>
    <string>--workspace</string>
    <string>/Users/YOU/code/your-project</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>/Users/YOU/Library/Logs/vscode-copilot-telegram-watch.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/Library/Logs/vscode-copilot-telegram-watch.log</string>
</dict>
</plist>
```

Load, check, and stop it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vscode-copilot-telegram.watch.your-project.plist
launchctl print gui/$(id -u)/com.vscode-copilot-telegram.watch.your-project | grep state
tail -f ~/Library/Logs/vscode-copilot-telegram-watch.log
launchctl bootout gui/$(id -u)/com.vscode-copilot-telegram.watch.your-project      # stop and unload
```

If the file named by `VSCODE_COPILOT_TELEGRAM_ENV_FILE` is under `~/Documents`, `~/Desktop`, or `~/Downloads`, macOS privacy protection may block a background agent from reading it. Keep the credentials in `~/.config/vscode-copilot-telegram/` (step 5), which isn't protected.

### Keep it running on Linux (systemd)

This starts the watcher when you log in and restarts it if it stops. It is a user service, so you don't need `sudo`.

Create `~/.config/systemd/user/vscode-copilot-telegram-watch-your-project.service` (replace the paths; `%h` is your home folder, systemd fills it in):

```ini
[Unit]
Description=Mirror Copilot chat for your-project to Telegram

[Service]
ExecStart=%h/tools/vscode-copilot-telegram/.venv/bin/vscode-copilot-telegram-watch --workspace %h/code/your-project
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

If a path has spaces, put that argument in double quotes.

Load, check, and stop it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now vscode-copilot-telegram-watch-your-project.service
systemctl --user status vscode-copilot-telegram-watch-your-project.service
journalctl --user -u vscode-copilot-telegram-watch-your-project.service -f               # log
systemctl --user disable --now vscode-copilot-telegram-watch-your-project.service        # stop and remove from startup
```

A user service only runs while you are logged in. On a machine you reach over SSH or a tunnel, run `loginctl enable-linger "$USER"` once so the watcher starts at boot and keeps running after you log out.

## 12. End-to-end verification checklist

Do these in order in a fresh **Agent** chat in `PROJECT`. Each should pass before you rely on the setup.

- [ ] **Telegram works:** `vscode-copilot-telegram --test --workspace PROJECT` prints `sent` and the ✅ message arrives (§6).
- [ ] **Server running:** **MCP: List Servers** shows vscode-copilot-telegram **Running** with 3 tools (§8).
- [ ] **Built-in terminal off:** Configure Tools shows Run in Terminal unticked, or the §7 fallback settings are in place.
- [ ] **Approve path:** ask Copilot *"Use run_command to run `git status`"*. A **🖥 Run command?** message arrives with the command, *Why*, *cwd*, and *id*. Tap **✅ Approve**. The message changes to show the exit code and output, and Copilot reports the result.
- [ ] **Deny path:** ask Copilot to run `echo should-not-run > denied.txt` and tap **❌ Deny**. Copilot reports it was denied, and `denied.txt` does **not** exist.
- [ ] **Deny with note:** ask for another command, tap **📝 Deny with note**, and reply with a note. Copilot receives your note.
- [ ] **Timeout fails closed:** ask Copilot *"Use run_command with timeout_s 30 to run `echo late`"* and don't tap anything. After 30 s the message shows **⏱ Timed out → denied**. Tapping Approve afterwards says *Already answered* and nothing runs.
- [ ] **Single-use buttons:** approve a request, then tap Approve again on the same message (if the buttons are still visible in your client). It says *Already answered*.
- [ ] **Block list:** ask Copilot to run `git push --force`. You get a **⛔ Blocked command** notice with no buttons, and nothing runs.
- [ ] **Workspace jail:** ask Copilot to run `ls` with `cwd` `..`. It's rejected without asking you.
- [ ] **Question:** ask Copilot *"Use ask_user to ask me which database to use, with options Postgres and SQLite"*. Tap one; Copilot gets your choice. Repeat and type a free-text answer instead.
- [ ] **Only you:** while a request is waiting, send a text message to your bot from another Telegram account. Nothing happens, and the server output (MCP: List Servers → Show Output) shows `ignored message from unauthorized user …`.
- [ ] **Chat mirror:** with the watcher running, send Copilot a prompt. Within a few seconds you get **🧑 You:** and then **🤖 Copilot:** messages.
- [ ] **Audit log:** `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` (the path is in the server output, step 8) has one line per request with `decision` values like `approved`, `denied`, `denied-timeout`, `blocked`, `rejected`.
- [ ] **Allow list needs your acceptance:** add `allow = ['git status']` to `PROJECT/vscode-copilot-telegram.toml` and restart the server (MCP: List Servers → Restart). The server output has a warning that the allow list is not accepted. Ask Copilot to run `git status`: Telegram asks, and the message says the allow list is not accepted. Run `vscode-copilot-telegram --accept-policy --workspace PROJECT` in a normal terminal **and** in the VS Code terminal, read the patterns, and type `accept`. Restart the server and ask again: now `git status` shows **✅ Auto-approved** with no buttons. Add a second pattern to the file, restart, and check that it asks again.
- [ ] **The accept command refuses scripts:** `echo accept | vscode-copilot-telegram --accept-policy --workspace PROJECT` prints `must be run by you` and saves nothing.
- [ ] **Restart safety:** restart the MCP server (MCP: List Servers → Restart). Tap a button on an old request; it says *Already answered* or *expired*, and nothing runs twice.
- [ ] **`/pending`:** while a request is waiting, send `/pending` to the bot; it lists the request id.

## 13. Updating and uninstalling

**Update:**

```bash
cd TOOL_DIR && git pull && pip install -e .     # with the venv activated
```

Then restart the MCP server in VS Code (MCP: List Servers → Restart) and restart the watcher.

**Uninstall:** remove the server entry from `PROJECT/.vscode/mcp.json` / `PROJECT/.mcp.json`, delete the scheduled task, launchd agent, or systemd unit, then delete `TOOL_DIR`, `~/.config/vscode-copilot-telegram/`, `~/.vscode-copilot-telegram/`, and `PROJECT/.vscode-copilot-telegram/`. To invalidate the bot token, send `/revoke` (or `/deletebot`) to @BotFather.
