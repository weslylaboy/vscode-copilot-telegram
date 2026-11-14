# Configuration reference

vscode-copilot-telegram has three layers of configuration:

1. **Environment variables**, for secrets and paths (loaded from `.env` files too).
2. **`vscode-copilot-telegram.toml`** in the workspace root, for behaviour (timeouts, allow and block lists, shell). Optional.
3. **Command-line flags** for each program.

Nothing secret ever goes in the TOML file; the server refuses to start its tools if it finds a `token` or `bot_token` key there.

## Environment variables

| Variable | Used by | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | server, watcher | **yes** | — | Bot token from @BotFather. Removed from the environment of every command `run_command` executes. |
| `TELEGRAM_USER_ID` | server, watcher | **yes** | — | Your numeric Telegram user id (from @userinfobot). Messages go to this chat, and only updates from this id are accepted. Must be a number. |
| `VSCODE_COPILOT_TELEGRAM_ENV_FILE` | server, watcher | no | — | Extra `.env` file to load first (see load order below). `~` is expanded. |
| `WORKSPACE_ROOT` | server, watcher | no | current directory | Workspace root, used when `--workspace` isn't given. |
| `LOG_PATH` | server | no | `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` | Audit log path. Only read from the environment (VS Code's `env`, or the `.env` files outside the project), never from the project. Relative paths are relative to the workspace root. |
| `VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS` | watcher | no | per-OS list below | VS Code `User` folders to search for `workspaceStorage`, separated by `os.pathsep` (`;` on Windows, `:` on macOS/Linux). Replaces the built-in list. |
| `VSCODE_COPILOT_TELEGRAM_API_BASE` | server | no | `https://api.telegram.org` | Bot API base URL. Only for tests or a self-hosted Bot API server. The watcher always uses the default. |
| `APPDATA` (Windows), `XDG_CONFIG_HOME` (Linux) | watcher | no | OS default | Standard locations used to find VS Code's data folder. |

### `.env` load order

Both programs call the same loader at startup. It reads these files in order and **never overrides a variable that is already set** (so a real environment variable beats every file, and an earlier file beats a later one):

1. `$VSCODE_COPILOT_TELEGRAM_ENV_FILE`
2. `~/.config/vscode-copilot-telegram/.env` (Windows: `%USERPROFILE%\.config\vscode-copilot-telegram\.env`)

Missing files are skipped.

`<workspace>/.env` (your project's own `.env`) is **never loaded**. Copilot can edit files in the project without approval, and a cloned repository can bring its own `.env`, so that file must not be able to set the Telegram credentials, the Bot API address, or the audit log path. If it contains `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*`, or `LOG_PATH`, both programs log a warning with the names and ignore them. To give one project its own bot, keep a file outside the project (for example `~/.config/vscode-copilot-telegram/your-project.env`) and point `VSCODE_COPILOT_TELEGRAM_ENV_FILE` at it. See [SECURITY.md → Project files that can change the gate](../SECURITY.md#project-files-that-can-change-the-gate).

### Ways to supply the token

| Method | Where | Notes |
| --- | --- | --- |
| Shared `.env` file (recommended) | `~/.config/vscode-copilot-telegram/.env` | Works for every project and for the watcher. Outside every repo. |
| `envFile` in `.vscode/mcp.json` | [`examples/mcp.envfile.json`](../examples/mcp.envfile.json) | Same file, made explicit to VS Code. Local harness only. |
| VS Code input prompts | [`examples/mcp.json`](../examples/mcp.json) | VS Code asks once and keeps the value in its secret storage. Local harness only. The watcher still needs the `.env` file or real environment variables. |
| Real environment variables | your shell profile, or `env` in `.mcp.json` | Don't write literal tokens into a committed `.mcp.json`. |

## `vscode-copilot-telegram.toml`

Place it at `<workspace>/vscode-copilot-telegram.toml` (the folder passed as `--workspace`). Copy [`examples/vscode-copilot-telegram.toml`](../examples/vscode-copilot-telegram.toml) to start. Unknown keys are an error, so typos don't fail silently. Changes take effect when the MCP server restarts (MCP: List Servers → Restart).

This file lives in the project, so anything that can write to the project can change it, including Copilot's file edits. For that reason an `allow` list and `use_default_block = false` only work after **you accept them** (see [Accepting the allow list](#accepting-the-allow-list)). Everything else in this file is trusted as written. See [SECURITY.md → Project files that can change the gate](../SECURITY.md#project-files-that-can-change-the-gate).

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `timeout_s` | int > 0 | `600` | Seconds to wait for **Approve/Deny** or an answer to `ask_user`. No answer means **denied** (or `timeout` for questions). Copilot can pass a per-call `timeout_s`, capped at 24 h. |
| `run_timeout_s` | int > 0 | `900` | An approved command is killed (with its whole process tree) after this many seconds. |
| `max_output_chars` | int > 0 | `8000` | Combined stdout+stderr returned to Copilot. Longer output keeps the first quarter and the end, with a `[N characters truncated]` marker. |
| `telegram_output_chars` | int | `1500` | How much of the output tail is shown in the Telegram message (also limited by Telegram's 4096-character message size). |
| `allow` | list of regex | `[]` | Commands auto-approved without asking (you still get a notice). Ignored until you accept it. See below. |
| `block` | list of regex | `[]` | Extra patterns denied without asking, added to the built-in list. |
| `use_default_block` | bool | `true` | Set to `false` to drop the built-in block list (not recommended). Ignored until you accept it. |
| `shell` | string | `"default"` | How commands are run: `default` (the OS shell: `/bin/sh` on macOS/Linux, `cmd.exe` on Windows), `sh`, `bash`, `powershell`, `pwsh`, or `cmd`. Use `powershell` or `pwsh` on Windows if Copilot writes PowerShell syntax. |
| `project_name` | string | workspace folder name | Label shown in brackets at the start of every Telegram message. Useful when several projects share a chat. |

`log_path` is **ignored** in this file now. The audit log is outside the project, because Copilot can edit this file. If the file still has a `log_path` (the first example file did), the server starts normally and writes a warning in its output that says where the log is now and names an older log file if one is still there. To move the log, set `LOG_PATH` (see above).

### Accepting the allow list

An allow list makes commands run without your tap, and turning off the built-in block list removes a safety net. Because this file can be written by Copilot (file edits aren't gated) or come with a repository you cloned, these two settings are **ignored until you accept them**:

```bash
vscode-copilot-telegram --accept-policy --workspace /path/to/your/project     # full path to the venv executable
```

- Type it yourself in a terminal. It shows the patterns, asks you to type `accept`, and refuses to run from a script, a pipe, or `run_command` (the built-in block list also denies a `run_command` that contains it).
- It saves the accepted allow list for that workspace in `~/.config/vscode-copilot-telegram/accepted-policy.json`, outside the project. Restart the MCP server afterwards.
- It checks the patterns first. It **refuses** a pattern that approves (almost) every command, such as `.*` or `\S+`, and prints it. For the other patterns it prints a **WARNING** under the pattern when it also approves risky commands (for example `git diff --output=/tmp/out.txt`, `npm install some-package`, `python script.py`, `pytest ../other-project`). Read these lines before you type `accept`.
- It refuses to save if the accepted file would be inside the workspace (for example, your home folder was opened as the workspace).
- If the file's `allow` list or `use_default_block` is **different** from what you accepted (any pattern added, removed, or changed), the whole thing is ignored again: the allow list is empty, the built-in block list is on, and every command asks in Telegram. The server output shows a warning with the command to run, and each approval message says the allow list is not accepted.
- `block`, the timeouts, `shell`, and the other keys don't need acceptance, because they can't make a command run without your tap.

### Allow list rules

- Each pattern is a Python regular expression, matched **case-insensitively** against the **whole** command (leading and trailing spaces removed). `git status` matches only `git status`, not `git status && rm -rf x`.
- A command that contains any of `;` `&&` `||` `|` `` ` `` `$(` `>` `<`, a newline, or ends in `&` is **never** auto-approved, whatever the patterns say. It goes to Telegram for a normal approval.
- The block list is checked first and always wins.
- Auto-approved commands still post a **✅ Auto-approved** notice to Telegram and are written to the audit log as `auto-approved`.

Keep patterns **narrow**:

- A trailing `( .*)?` accepts any argument. `git (status|diff|log)( .*)?` also approves `git diff --output=/tmp/out.txt`, which writes a file anywhere.
- A test runner or build tool (`pytest`, `npm test`, `make`) runs any code in the project, including code Copilot just wrote. Don't put one in the list unless you accept that.
- A pattern like `npm .*` or `python .*` approves installing packages and running any script.

Examples:

```toml
allow = [
  'git status',
  'git diff( --stat)?',
  'git log( --oneline)?( -[0-9]+)?',
  'ls( -[a-zA-Z]+)?',
]
```

Use single-quoted TOML strings ('literal strings') so backslashes in regexes don't need escaping.

### Block list rules

- Each pattern is a Python regex, **searched anywhere** in the command, case-insensitively.
- A match is denied immediately: you get a **⛔ Blocked command** notice (no buttons), and Copilot is told not to work around it.
- An empty command is always blocked.

The built-in list (`DEFAULT_BLOCK` in [`src/vscode_copilot_telegram/policy.py`](../src/vscode_copilot_telegram/policy.py)) covers:

- `rm -r…` on `/`, `/*`, `~`, `~/`, `$HOME`, and anything with `--no-preserve-root`
- force pushes: `git push --force`, `--force-with-lease`, `-f`, and `+refspec`
- `mkfs`, `dd … of=/dev/…`, redirects onto `/dev/sd*`, `/dev/nvme*`, `/dev/disk*`, `chmod -R 777 /`
- piping downloads into a shell or Python: `curl … | sh`, `wget … | bash`, `curl … | python`, `iwr … | iex`
- the `:(){ :|:& };:` fork bomb
- Windows wipes: `format C:`, `rd /s … C:\`, `Remove-Item -Recurse … C:\`
- `shutdown`, `reboot`, `halt`, `poweroff`

Examples of your own additions:

```toml
block = [
  'terraform (apply|destroy)',
  'kubectl (delete|drain)',
  'docker system prune',
  'npm publish',
  '\bgit\s+reset\s+--hard\b',
  'DROP\s+(TABLE|DATABASE)',
]
```

The block list is a safety net, not a sandbox. A determined or confused model can write the same thing another way, which is why everything else still needs your tap.

## `vscode-copilot-telegram` (MCP server) flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--workspace PATH` | `$WORKSPACE_ROOT`, then the current directory | Workspace root: the command jail, where `vscode-copilot-telegram.toml` is read, and where `.vscode-copilot-telegram/` state lives. |
| `--test` | off | Send one test message to Telegram, print `sent`, and exit (exit code 0 on success, 1 on failure). Doesn't start the MCP server. |
| `--accept-policy` | off | Show the `allow` list and `use_default_block` from `vscode-copilot-telegram.toml`, ask you to type `accept`, and save them as accepted for the workspace. Needs a terminal; doesn't start the MCP server. See [Accepting the allow list](#accepting-the-allow-list). |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Logs go to stderr, which VS Code shows in the server's output channel. |

### Tools exposed to Copilot

| Tool | Parameters | Returns |
| --- | --- | --- |
| `run_command` | `command` (str), `reason` (str), `cwd` (str, optional, inside the workspace), `timeout_s` (int, optional) | Object with `request_id`, `command`, `decision` (`approved`, `auto-approved`, `denied`, `denied-timeout`, `denied-error`, `blocked`, `rejected`), `exit_code` (null if not run), `output`, plus `cwd`, `note`, and `timed_out` where relevant. |
| `ask_user` | `question` (str), `options` (list of str, optional, up to 20 buttons), `timeout_s` (int, optional) | The answer text, `timeout`, or a string starting with `error:`. |
| `notify` | `message` (str) | `sent` or a string starting with `error:`. |

## `vscode-copilot-telegram-watch` flags

| Flag | Default | Meaning |
| --- | --- | --- |
| `--workspace PATH` | `$WORKSPACE_ROOT`, then the current directory | The project folder exactly as opened in VS Code. |
| `--storage DIR` | auto-detect | A `workspaceStorage/<hash>` folder to read; repeatable. Skips auto-detection. |
| `--interval SECONDS` | `2` | How often to check for changes. |
| `--settle SECONDS` | `8` | A reply with no completion marker is sent once it stops changing for this long. |
| `--source` | `auto` | `chatsessions`, `transcripts`, `both`, or `auto` (chatSessions if any exist, else Copilot transcripts). |
| `--backfill N` | `0` | On first sight of an existing session, also send its last N messages. |
| `--no-tools` | off | Leave out the one-line tool-call and file-edit summaries. |
| `--state-file PATH` | `~/.vscode-copilot-telegram/watch-<project>-<hash>.json` | Where to remember what was already sent. |
| `--dry-run` | off | Print messages to the console instead of sending. No token needed; nothing is remembered. |
| `--list` | off | Print the matched storage folders and session files with message counts, then exit (exit code 1 if none). |
| `--once` | off | Check once and exit. |
| `-v`, `--verbose` | off | Debug logging. |

## Where things live

| Path | Written by | Contents |
| --- | --- | --- |
| `~/.config/vscode-copilot-telegram/.env` | you | Token and user id |
| `<workspace>/vscode-copilot-telegram.toml` | you | Optional behaviour settings |
| `~/.config/vscode-copilot-telegram/accepted-policy.json` | `--accept-policy` | The allow lists you accepted, per workspace |
| `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` | server | One JSON line per request: `ts`, `request_id`, `type`, `command`, `decision`, `exit_code`, `cwd`, `reason`, `note`, … (secrets masked). Outside the project, so Copilot's file edits can't change it. |
| `<workspace>/.vscode-copilot-telegram/broker-state.json` | server | Telegram update offset and the last 500 answered request ids (makes buttons single-use across restarts) |
| `~/.vscode-copilot-telegram/watch-<project>-<hash>.json` | watcher | Which chat messages were already forwarded |

VS Code's own chat data, read by the watcher (all read-only):

| OS | VS Code `User` folders searched |
| --- | --- |
| Windows | `%APPDATA%\Code\User`, `%APPDATA%\Code - Insiders\User`, `%APPDATA%\VSCodium\User` |
| macOS | `~/Library/Application Support/Code/User`, `…/Code - Insiders/User`, `…/VSCodium/User` |
| Linux | `$XDG_CONFIG_HOME/Code/User` (default `~/.config/Code/User`), `… - Insiders`, `VSCodium` |
| Remote (Tunnels, SSH, WSL) | `~/.vscode-server/data/User`, `~/.vscode-server-insiders/data/User` on the remote machine |

Inside each: `workspaceStorage/<hash>/workspace.json` (identifies the folder), `workspaceStorage/<hash>/chatSessions/*.json` or `*.jsonl`, and `workspaceStorage/<hash>/GitHub.copilot-chat/transcripts/*.jsonl`.
