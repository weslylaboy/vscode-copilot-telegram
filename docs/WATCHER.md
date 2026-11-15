# Chat mirror (the watcher)

The watcher sends your prompts and the answers of Copilot to Telegram. It is optional. Approvals and questions work without it.

It reads the chat files that VS Code saves on your disk. It only sends messages. It never reads your Telegram replies, so it can use the same bot as the server.

## Quick path

`TOOL_DIR` and `PROJECT` are the two folders from [SETUP.md](SETUP.md). Write their full paths.

```bash
TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch --workspace PROJECT --list     # find the chat files
TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch --workspace PROJECT --dry-run  # preview, no token needed
TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch --workspace PROJECT            # run it
```

On Windows the program is `TOOL_DIR\.venv\Scripts\vscode-copilot-telegram-watch.exe`. If the `.venv` is active, you can write only `vscode-copilot-telegram-watch`.

## 1. Find the chat files

Open `PROJECT` in VS Code and send one chat message. VS Code creates the storage folder only after that. Then run:

```bash
vscode-copilot-telegram-watch --workspace PROJECT --list
```

You should see `project: ...`, a `storage:` line with a `workspaceStorage/<hash>` folder, and at least one session file with a message count.

If you see `no matching workspaceStorage folder found`, see [Troubleshooting](TROUBLESHOOTING.md#the-watcher-finds-no-sessions).

## 2. Preview

```bash
vscode-copilot-telegram-watch --workspace PROJECT --dry-run --backfill 5
```

It prints the messages and does not send them. Press Ctrl+C to stop.

## 3. Run it

```bash
vscode-copilot-telegram-watch --workspace PROJECT
```

- On the first start, the old history counts as already sent. You get only new messages.
- `--backfill N` also sends the last N messages of the old sessions.
- `--no-tools` leaves out the lines about tool calls and file edits.
- Run one watcher for each project.

It saves what it sent in `~/.vscode-copilot-telegram/watch-<project>-<hash>.json`, so a restart does not send the same messages again.

All the flags are in [CONFIGURATION.md](CONFIGURATION.md#watcher-flags).

## Keep it running

Test it in a terminal first. Write your full paths instead of `TOOL_DIR` and `PROJECT`. `PROJECT_NAME` is the name of the `PROJECT` folder (only the last part). You need it so each project has its own name.

### Windows (Task Scheduler)

It starts at logon, with no console window, and restarts if it stops. Run it in PowerShell. You do not need admin.

```powershell
$venv    = "TOOL_DIR\.venv"
$project = "PROJECT"
$name    = "vscode-copilot-telegram-watch (PROJECT_NAME)"

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

`pythonw.exe` has no console, so you do not see a log.

Manage it:

```powershell
Get-ScheduledTask -TaskName $name
Stop-ScheduledTask -TaskName $name
Unregister-ScheduledTask -TaskName $name -Confirm:$false
```

### macOS (launchd)

Create `~/Library/LaunchAgents/com.vscode-copilot-telegram.watch.PROJECT_NAME.plist`. launchd does not expand `~`, so write full paths. `HOME_DIR` is your home folder (run `echo $HOME`).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.vscode-copilot-telegram.watch.PROJECT_NAME</string>
  <key>ProgramArguments</key>
  <array>
    <string>TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch</string>
    <string>--workspace</string>
    <string>PROJECT</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>HOME_DIR/Library/Logs/vscode-copilot-telegram-watch.log</string>
  <key>StandardErrorPath</key>
  <string>HOME_DIR/Library/Logs/vscode-copilot-telegram-watch.log</string>
</dict>
</plist>
```

Start, check and stop it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vscode-copilot-telegram.watch.PROJECT_NAME.plist
launchctl print gui/$(id -u)/com.vscode-copilot-telegram.watch.PROJECT_NAME | grep state
tail -f ~/Library/Logs/vscode-copilot-telegram-watch.log
launchctl bootout gui/$(id -u)/com.vscode-copilot-telegram.watch.PROJECT_NAME
```

macOS can block a background agent from reading files in `~/Documents`, `~/Desktop` and `~/Downloads`. Keep the `.env` in `~/.config/vscode-copilot-telegram/`, as in the setup.

### Linux (systemd)

It is a user service. You do not need `sudo`. Create `~/.config/systemd/user/vscode-copilot-telegram-watch-PROJECT_NAME.service`.

```ini
[Unit]
Description=Mirror Copilot chat for PROJECT_NAME to Telegram

[Service]
ExecStart=TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch --workspace PROJECT
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

If a path has spaces, put that argument in double quotes.

Start, check and stop it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now vscode-copilot-telegram-watch-PROJECT_NAME.service
systemctl --user status vscode-copilot-telegram-watch-PROJECT_NAME.service
journalctl --user -u vscode-copilot-telegram-watch-PROJECT_NAME.service -f
systemctl --user disable --now vscode-copilot-telegram-watch-PROJECT_NAME.service
```

A user service runs only while you are logged in. On a machine you reach by SSH or tunnel, run `loginctl enable-linger "$USER"` once. Then it starts at boot.

## Remote machines

With VS Code Remote (SSH, Tunnels, WSL), the chat files are on the remote machine, in `~/.vscode-server/data/User/workspaceStorage`. Run the watcher there.
