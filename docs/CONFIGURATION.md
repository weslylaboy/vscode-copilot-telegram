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
| `LOG_PATH` | server | no | `<workspace>/.vscode-copilot-telegram/audit.jsonl` | Audit log path. Overrides `log_path` in the TOML. Relative paths are relative to the workspace root. |
| `VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS` | watcher | no | per-OS list below | VS Code `User` folders to search for `workspaceStorage`, separated by `os.pathsep` (`;` on Windows, `:` on macOS/Linux). Replaces the built-in list. |
| `VSCODE_COPILOT_TELEGRAM_API_BASE` | server | no | `https://api.telegram.org` | Bot API base URL. Only for tests or a self-hosted Bot API server. The watcher always uses the default. |
| `APPDATA` (Windows), `XDG_CONFIG_HOME` (Linux) | watcher | no | OS default | Standard locations used to find VS Code's data folder. |

### `.env` load order

Both programs call the same loader at startup. It reads these files in order and **never overrides a variable that is already set** (so a real environment variable beats every file, and an earlier file beats a later one):

1. `$VSCODE_COPILOT_TELEGRAM_ENV_FILE`
2. `<workspace>/.env`
3. `~/.config/vscode-copilot-telegram/.env` (Windows: `%USERPROFILE%\.config\vscode-copilot-telegram\.env`)

Missing files are skipped. Note that variables from `<workspace>/.env` (your project's own `.env`, if it has one) end up in the server's environment and therefore in the environment of approved commands, except `TELEGRAM_BOT_TOKEN`, which is always stripped.

### Ways to supply the token

| Method | Where | Notes |
| --- | --- | --- |
| Shared `.env` file (recommended) | `~/.config/vscode-copilot-telegram/.env` | Works for every project and for the watcher. Outside every repo. |
| `envFile` in `.vscode/mcp.json` | [`examples/mcp.envfile.json`](../examples/mcp.envfile.json) | Same file, made explicit to VS Code. Local harness only. |
| VS Code input prompts | [`examples/mcp.json`](../examples/mcp.json) | VS Code asks once and keeps the value in its secret storage. Local harness only. The watcher still needs the `.env` file or real environment variables. |
| Real environment variables | your shell profile, or `env` in `.mcp.json` | Don't write literal tokens into a committed `.mcp.json`. |

## `vscode-copilot-telegram.toml`

Place it at `<workspace>/vscode-copilot-telegram.toml` (the folder passed as `--workspace`). Copy [`examples/vscode-copilot-telegram.toml`](../examples/vscode-copilot-telegram.toml) to start. Unknown keys are an error, so typos don't fail silently. Changes take effect when the MCP server restarts (MCP: List Servers → Restart).

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `timeout_s` | int > 0 | `600` | Seconds to wait for **Approve/Deny** or an answer to `ask_user`. No answer means **denied** (or `timeout` for questions). Copilot can pass a per-call `timeout_s`, capped at 24 h. |
| `run_timeout_s` | int > 0 | `900` | An approved command is killed (with its whole process tree) after this many seconds. |
| `max_output_chars` | int > 0 | `8000` | Combined stdout+stderr returned to Copilot. Longer output keeps the first quarter and the end, with a `[N characters truncated]` marker. |
| `telegram_output_chars` | int | `1500` | How much of the output tail is shown in the Telegram message (also limited by Telegram's 4096-character message size). |
| `allow` | list of regex | `[]` | Commands auto-approved without asking (you still get a notice). See below. |
| `block` | list of regex | `[]` | Extra patterns denied without asking, added to the built-in list. |
| `use_default_block` | bool | `true` | Set to `false` to drop the built-in block list (not recommended). |
| `shell` | string | `"default"` | How commands are run: `default` (the OS shell: `/bin/sh` on macOS/Linux, `cmd.exe` on Windows), `sh`, `bash`, `powershell`, `pwsh`, or `cmd`. Use `powershell` or `pwsh` on Windows if Copilot writes PowerShell syntax. |
| `log_path` | path | `.vscode-copilot-telegram/audit.jsonl` | Audit log location; relative to the workspace. `LOG_PATH` overrides it. |
| `project_name` | string | workspace folder name | Label shown in brackets at the start of every Telegram message. Useful when several projects share a chat. |

### Allow list rules

- Each pattern is a Python regular expression, matched **case-insensitively** against the **whole** command (leading and trailing spaces removed). `git status` matches only `git status`, not `git status && rm -rf x`.
- A command that contains any of `;` `&&` `||` `|` `` ` `` `$(` `>` `<`, a newline, or ends in `&` is **never** auto-approved, whatever the patterns say. It goes to Telegram for a normal approval.
- The block list is checked first and always wins.
- Auto-approved commands still post a **✅ Auto-approved** notice to Telegram and are written to the audit log as `auto-approved`.

Examples:

```toml
allow = [
  'git (status|diff|log)( .*)?',     # read-only git
  'npm (test|run lint)',
  'pytest( -q)?( [\w/.-]+)*',         # pytest, optionally with paths
  'python -m pytest( -q)?',
  'ls( -[a-zA-Z]+)?( [\w/.-]+)?',
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
| `--workspace PATH` | `$WORKSPACE_ROOT`, then the current directory | Workspace root: the command jail, where `vscode-copilot-telegram.toml` and `.env` are read, and where `.vscode-copilot-telegram/` state lives. |
| `--test` | off | Send one test message to Telegram, print `sent`, and exit (exit code 0 on success, 1 on failure). Doesn't start the MCP server. |
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
| `<workspace>/.vscode-copilot-telegram/audit.jsonl` | server | One JSON line per request: `ts`, `request_id`, `type`, `command`, `decision`, `exit_code`, `cwd`, `reason`, `note`, … (secrets masked) |
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
