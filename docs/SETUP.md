# Setup

Install the tool, connect it to Telegram, and approve your first command. It works on Windows, macOS, and Linux.

There are two different folders in this guide. Do not mix them:

- `TOOL_DIR` is this tool. It is the folder `vscode-copilot-telegram` that `git clone` creates in [step 3](#3-install).
- `PROJECT` is your own project, the project you want Copilot to work on. It is the folder you open in VS Code. The tool is set up for this folder, and it can only run commands inside it.

In the commands, write the full path instead of the words `TOOL_DIR` and `PROJECT`.

Install the tool once, in its own folder. Do not install it inside `PROJECT`. You do not need to change the code of the tool. You only add two small files to `PROJECT`: `.mcp.json` and `.github/copilot-instructions.md`.

## TLDR

The steps below explain each line.

```bash
# 1. Install (creates the folder vscode-copilot-telegram = TOOL_DIR)
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Credentials (token from @BotFather, id from @userinfobot)
mkdir -p ~/.config/vscode-copilot-telegram
# 3. Add bot token and user id to env file
printf 'TELEGRAM_BOT_TOKEN=123456789:AA...\nTELEGRAM_USER_ID=123456789\n' > ~/.config/vscode-copilot-telegram/.env
chmod 600 ~/.config/vscode-copilot-telegram/.env

# 4. Test
.venv/bin/vscode-copilot-telegram --test --workspace PROJECT
```

Then:

1. Copy the example and put your paths in it (`command` and `--workspace`):

   ```bash
   cp TOOL_DIR/examples/mcp.example.json PROJECT/.mcp.json
   ```

   Details in [step 6](#6-add-the-server-to-project).
2. Add the two settings from [step 7](#7-turn-off-the-built-in-terminal) to your VS Code user settings.
3. Run **Chat: Manage Tool Approval** and pre-approve the `vscode-copilot-telegram` tools.
4. Copy the instructions for Copilot (if the file already exists, add the text at the end instead):

   ```bash
   mkdir -p PROJECT/.github
   cp TOOL_DIR/examples/copilot-instructions.md PROJECT/.github/copilot-instructions.md
   ```
5. In Copilot Chat (agent mode) ask: `Use run_command to run git status`. Approve it on your phone.

## What you need

- Python 3.11 or newer.
  - Windows: `winget install Python.Python.3.12`. Check with `py -3 --version`.
  - macOS: `brew install python@3.12`. Check with `python3 --version`.
- VS Code with the GitHub Copilot and GitHub Copilot Chat extensions, and agent mode.
- Telegram on your phone.
- A connection from your computer to `api.telegram.org`. If you use VS Code Remote (SSH or Tunnels), install the tool on the remote machine.

## 1. Create the bot

1. In Telegram, open a chat with @BotFather.
2. Send `/newbot`. Choose a name, and a username that ends in `bot`.
3. BotFather sends you a token, like `123456789:AAH...`. Copy it. It is a password. Do not share it.
4. Open your new bot and tap Start. A bot cannot write to you before you do this.

Use one bot for each VS Code window. Telegram lets only one program read the answers of a bot. If two windows use the same bot, they take the taps from each other.

You are done when you have the token and you pressed Start.

## 2. Get your user id

1. Open a chat with @userinfobot and send any message.
2. It answers with your `Id`, a number like `123456789`.

Use the number, not your @username. The tool ignores every message and tap that does not come from this id.

## 3. Install

Open a terminal in the folder where you want to download the tool (not inside `PROJECT`).

Windows (PowerShell):

```powershell
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

If PowerShell says "running scripts is disabled", run this once, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

macOS:

```bash
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You are now inside `TOOL_DIR`. Run `pwd` (Windows: `(Get-Location).Path`) and keep this path. You need it in the next steps.

The install creates two commands inside the `.venv` folder:

| Program | Windows | macOS |
| --- | --- | --- |
| Server | `TOOL_DIR\.venv\Scripts\vscode-copilot-telegram.exe` | `TOOL_DIR/.venv/bin/vscode-copilot-telegram` |
| Watcher | `TOOL_DIR\.venv\Scripts\vscode-copilot-telegram-watch.exe` | `TOOL_DIR/.venv/bin/vscode-copilot-telegram-watch` |

Check it:

```bash
vscode-copilot-telegram --help
```

You should see the usage text.

## 4. Save the token and the user id

1. Create this folder:

   macOS: `mkdir -p ~/.config/vscode-copilot-telegram`

   Windows (PowerShell): `mkdir $HOME\.config\vscode-copilot-telegram`

2. In that folder, create a file named `.env` with this content. Put your own token and user id.

   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH-your-token
   TELEGRAM_USER_ID=123456789
   ```

   File path:

   - macOS: `~/.config/vscode-copilot-telegram/.env`
   - Windows: `$HOME\.config\vscode-copilot-telegram\.env`

   Use any text editor. With VS Code you can run `code ~/.config/vscode-copilot-telegram/.env` (Windows: `code $HOME\.config\vscode-copilot-telegram\.env`). The file name is `.env`, with no `.txt` at the end.

3. macOS only: make the file private.

   ```bash
   chmod 600 ~/.config/vscode-copilot-telegram/.env
   ```

Why this place: it is outside every project, and both programs find it.

A `.env` inside your project is never read. Copilot can edit project files without asking, so that file must not decide who approves commands.

More options are in [CONFIGURATION.md](CONFIGURATION.md#environment-variables). A template is in [.env.example](../.env.example).

## 5. Test Telegram

Windows:

```powershell
& "TOOL_DIR\.venv\Scripts\vscode-copilot-telegram.exe" --test --workspace "PROJECT"
```

macOS:

```bash
TOOL_DIR/.venv/bin/vscode-copilot-telegram --test --workspace PROJECT
```

It prints `sent`, and your bot sends a message that ends with `✅ vscode-copilot-telegram test message. Telegram is set up correctly.`

If it fails, see [Troubleshooting](TROUBLESHOOTING.md#no-telegram-messages). The test does not start the server, so you can run it while VS Code is open.

## 6. Add the server to PROJECT

Create `PROJECT/.mcp.json`, in the root of your project (not in `.vscode/`).

### Copy the example file

macOS:

```bash
cp TOOL_DIR/examples/mcp.example.json PROJECT/.mcp.json
```

Windows (PowerShell):

```powershell
Copy-Item "TOOL_DIR\examples\mcp.example.json" "PROJECT\.mcp.json"
```

### Put your paths in it

Open `.mcp.json` and replace the word `TOOL_DIR` and the word `PROJECT` with your full paths. They appear in `command` and in `--workspace`. On Windows, use the second block and write each `\` twice (`\\`), because it is JSON.

macOS:

```json
{
  "mcpServers": {
    "vscode-copilot-telegram": {
      "type": "stdio",
      "command": "TOOL_DIR/.venv/bin/vscode-copilot-telegram",
      "args": ["--workspace", "PROJECT"],
      "tools": ["*"]
    }
  }
}
```

Windows:

```json
{
  "mcpServers": {
    "vscode-copilot-telegram": {
      "type": "stdio",
      "command": "TOOL_DIR\\.venv\\Scripts\\vscode-copilot-telegram.exe",
      "args": ["--workspace", "PROJECT"],
      "tools": ["*"]
    }
  }
}
```

Rules:

- Use full paths. Do not use `~`, and do not rely on `PATH`. Check that the `command` file exists.
- `--workspace` is `PROJECT`, the folder where Copilot works. It is the jail: `run_command` refuses any folder outside of it.
- The file has no secrets, only paths.
- Add `.vscode-copilot-telegram/` to the `.gitignore` of your project.
- Only the Copilot harness (the default agent runtime of VS Code) is supported. It reads `.mcp.json`. The old Local harness is not supported.

Start the server: open `.mcp.json` and click Start above `"vscode-copilot-telegram"`. You can also run **MCP: List Servers**, choose the server, and choose **Start Server**.

Check it: **MCP: List Servers**, then the server, then **Show Output**. You should see a line that starts with `workspace`, and the status is Running with 3 tools: `run_command`, `ask_user`, `notify`.

If the output says `configuration error`, the server starts but refuses all commands. Fix the error and restart it.

If you see `MCP server failed to initialize inside the sandbox` or `PermissionError: ... pyvenv.cfg`, the VS Code sandbox is on and it blocks the server. The server needs to read its `.venv` and to run the commands you approve, so it must run outside the sandbox. Add this to your user settings (Command Palette, **Preferences: Open User Settings (JSON)**) and start the server again:

```jsonc
{
  "chat.agent.sandbox.mcpServers": false
}
```

The terminal of Copilot stays sandboxed. Only locally started MCP servers leave the sandbox ([VS Code docs](https://code.visualstudio.com/docs/agents/run/agent-sandboxing)).

## 7. Turn off the built-in terminal

VS Code does not let other programs answer the confirmations of Copilot. So the gate works only if Copilot cannot use its own terminal tool without you.

Open your user settings as JSON (Command Palette, **Preferences: Open User Settings (JSON)**) and add:

```jsonc
{
  "chat.tools.eligibleForAutoApproval": { "runInTerminal": false },
  "chat.tools.terminal.enableAutoApprove": false
}
```

This makes the built-in terminal always ask you inside VS Code. Also keep the permission level of the chat on Manual permissions. Allow all and Autopilot skip the confirmations.

If your VS Code shows the Configure Tools button in the chat, also untick Run in Terminal there (and Run Task, if you see it). This may not be available in Copilot harness. The settings above are enough.

If a VS Code prompt for the terminal appears anyway, click Deny and write: `use run_command`.

A command that goes through the built-in terminal is not on Telegram. You approve it at the computer.

### Optional: ask before Copilot edits the files of the gate

Copilot can edit `.mcp.json` and `vscode-copilot-telegram.toml` without asking. To get a click before it edits them, add this to the same user settings file:

```jsonc
{
  "chat.tools.edits.autoApprove": {
    "**/.mcp.json": false,
    "**/vscode-copilot-telegram.toml": false,
    "**/.env": false
  }
}
```

More in [SECURITY.md](../SECURITY.md#files-in-the-project-that-can-change-the-gate).

## 8. Pre-approve the tools

Without this, every `run_command` asks twice. First VS Code asks `Allow tool from vscode-copilot-telegram?` with the buttons **Allow in this Session** and **Skip**. Then Telegram asks. Telegram is the real gate. It is safe to pre-approve because the tool waits for your tap.

1. Run **Chat: Manage Tool Approval** from the Command Palette.
2. Under `vscode-copilot-telegram`, tick the box for pre-approval ("without approval").

If you see the VS Code prompt before you do this, click **Allow in this Session**. The command still waits for your tap in Telegram. You can also open the arrow next to the button and choose a longer option, if it is there.

## 9. Tell Copilot to use the tools

Copy [examples/copilot-instructions.md](../examples/copilot-instructions.md) to `PROJECT/.github/copilot-instructions.md`. If the file exists, add the text at the end.

```markdown
## Running commands and asking questions (vscode-copilot-telegram)

- Run every shell command with the `run_command` tool from the vscode-copilot-telegram MCP server. Do not use any other terminal or shell tool. Always pass a one-sentence `reason`.
- If `run_command` returns a decision other than `approved` or `auto-approved`, the command did not run. Do not retry the same command in another form. Read the user's note if there is one, adjust your plan, or use `ask_user`.
- When you need a decision, a preference, a missing value, or confirmation from me, call `ask_user` instead of asking in chat and stopping. Offer short `options` when the choice is between a few alternatives. If it returns `timeout`, pick the safest option or stop and explain.
- Call `notify` with a one-line status at milestones: plan ready, tests passing or failing, task finished, or blocked.
- Never put secrets, tokens, or .env contents in a command, question, or notification.
```

Check that VS Code found the file:

1. Run **Chat: Open Customizations** from the Command Palette.
2. Open **Instructions**. `.github/copilot-instructions.md` must be in the list.
3. After a reply, look at **References** under it. The file should be there.

That checks that VS Code found the file, not that Copilot follows it. There is no setting to turn on. The Copilot harness reads this file by itself ([VS Code docs](https://code.visualstudio.com/docs/agent-customization/custom-instructions)).

## 10. Try it

Open a new chat in agent mode, in `PROJECT`.

Approve:

1. Write: `Use run_command to run git status`.
2. In Telegram you get a message with the command, the reason, the folder, and three buttons.
3. Tap Approve. The message changes to show the exit code and the output. Copilot shows the result.

Deny:

1. Write: `Use run_command to run echo hello > denied.txt`.
2. Tap Deny.
3. Copilot says the command was denied, and `denied.txt` does not exist.

Block list:

1. Write: `Use run_command to run git push --force`.
2. You get a Blocked message without buttons. Nothing runs.

If something does not work, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md). The full list of checks is in [DEVELOPMENT.md](DEVELOPMENT.md#manual-checklist).

## Next

- [Chat mirror](WATCHER.md): see your Copilot chat in Telegram.
- [Configuration](CONFIGURATION.md): timeouts, allow list, block list, shell.

## Update

```bash
cd TOOL_DIR
git pull
pip install -e .
```

Run it with the venv active. Then restart the server (**MCP: List Servers**, then **Restart**) and the watcher.

## Uninstall

1. Remove the server from `PROJECT/.mcp.json`.
2. Stop the watcher and remove its auto-start (see [WATCHER.md](WATCHER.md#keep-it-running)).
3. Delete `TOOL_DIR`, `~/.config/vscode-copilot-telegram/`, `~/.vscode-copilot-telegram/` and `PROJECT/.vscode-copilot-telegram/`.
4. In @BotFather, send `/revoke` to cancel the token.
