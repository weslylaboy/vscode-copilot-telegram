# Configuration

There are three ways to configure the tool:

1. Environment variables, for the token and for paths.
2. `vscode-copilot-telegram.toml` in the project folder, for behavior. It is optional.
3. Command-line flags.

Never put the token in the TOML file. The server refuses its tools if it finds `token` or `bot_token` there.

## Environment variables

| Variable | Used by | Required | Default | What it does |
| --- | --- | --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | server, watcher | yes | | Bot token from @BotFather. It is removed from the environment of the commands that `run_command` runs. |
| `TELEGRAM_USER_ID` | server, watcher | yes | | Your numeric Telegram id. Messages go to this chat. Only this id can answer. |
| `VSCODE_COPILOT_TELEGRAM_ENV_FILE` | server, watcher | no | | One more `.env` file to load first. `~` works. |
| `WORKSPACE_ROOT` | server, watcher | no | current folder | Project folder, if you do not pass `--workspace`. |
| `LOG_PATH` | server | no | `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` | Audit log file. Read only from the environment, never from the project. A relative path is relative to the project folder. |
| `VSCODE_COPILOT_TELEGRAM_VSCODE_USER_DIRS` | watcher | no | see [Where things are](#where-things-are) | VS Code `User` folders to search. Separate them with `;` on Windows, `:` on macOS and Linux. |
| `VSCODE_COPILOT_TELEGRAM_API_BASE` | server | no | `https://api.telegram.org` | Bot API address. Only for tests or your own Bot API server. Your token is sent to it. |
| `HTTPS_PROXY` | server, watcher | no | | Proxy to reach Telegram. The HTTP library reads it. |

### Where the `.env` is read from

Both programs read these files, in this order. A variable that is already set is never replaced, so a real environment variable wins over any file, and the first file wins over the second.

1. The file in `VSCODE_COPILOT_TELEGRAM_ENV_FILE`.
2. `~/.config/vscode-copilot-telegram/.env`. On Windows: `$HOME\.config\vscode-copilot-telegram\.env`.

A missing file is skipped.

The `.env` of your project is never read. Copilot can edit it without asking, and a cloned repository can bring its own. If it has `TELEGRAM_*`, `VSCODE_COPILOT_TELEGRAM_*` or `LOG_PATH`, both programs write a warning and ignore them.

One bot for each project: keep one file outside the project, like `~/.config/vscode-copilot-telegram/PROJECT_NAME.env` (`PROJECT_NAME` is the name of the project folder), and set `VSCODE_COPILOT_TELEGRAM_ENV_FILE` to it. Set it in the `env` of `.mcp.json` and in the environment of the watcher.

## The TOML file

Create `PROJECT/vscode-copilot-telegram.toml`. You can start from [examples/vscode-copilot-telegram.toml](../examples/vscode-copilot-telegram.toml). An unknown key is an error, so a typo is not silent. Restart the server after you change it (**MCP: List Servers**, then **Restart**).

| Key | Type | Default | What it does |
| --- | --- | --- | --- |
| `timeout_s` | integer > 0 | `600` | Seconds to wait for your tap or your answer on Telegram. It starts when the Telegram message is sent. No answer = denied (or `timeout` for a question). Copilot can send its own `timeout_s`, up to 24 hours. |
| `vscode_wait_s` | integer, 0 to 86400 | `180` | Copilot asks you in VS Code first. After this many seconds without an answer, the same question also goes to Telegram. The VS Code form stays open, so you can answer in either place. `0` = Telegram only, with no form in VS Code. |
| `run_timeout_s` | integer > 0 | `900` | An approved command is killed, with all its child processes, after this time. |
| `max_output_chars` | integer > 0 | `8000` | Output (stdout and stderr) returned to Copilot. If it is longer, the first quarter and the end stay, with a `[N characters truncated]` mark. |
| `telegram_output_chars` | integer | `1500` | How much of the end of the output is shown in Telegram. Telegram has a limit of 4096 characters in a message. |
| `allow` | list of regex | `[]` | Commands that run without asking. You still get a notice. Ignored until you accept it. |
| `block` | list of regex | `[]` | More patterns to deny, added to the built-in list. |
| `use_default_block` | boolean | `true` | `false` removes the built-in block list. Not recommended. Ignored until you accept it. |
| `shell` | string | `"default"` | `default` (`/bin/sh` on macOS and Linux, `cmd.exe` on Windows), `sh`, `bash`, `powershell`, `pwsh` or `cmd`. |
| `project_name` | string | folder name | Name shown in brackets at the start of each Telegram message. |

`log_path` in this file is ignored. The audit log is outside the project, because Copilot can edit this file. The server writes a warning with the new path. To move the log, use `LOG_PATH`.

### Ask in VS Code first, then Telegram

`run_command` (when it needs your approval) and `ask_user` work in two steps:

1. The server asks in VS Code, with a form in the chat. For a command, you choose approve or deny and can add a note. For a question, you choose an option or type the answer.
2. If you do not answer in `vscode_wait_s` seconds, the same question also goes to Telegram. The form in VS Code stays open. The first answer wins, and the other place is closed.

Details:

- An answer in VS Code never sends a Telegram message.
- If VS Code cannot show forms, or you close the form without answering, the question goes to Telegram at once.
- Copilot in Autopilot mode cannot show forms. VS Code cancels them, so the question goes to Telegram at once.
- `timeout_s` starts when the Telegram message is sent. If nobody answers by then, the command is denied.
- If Telegram cannot be reached, you can still answer the form in VS Code until `timeout_s` runs out. After that the command is denied.
- If both answer at the same moment with different decisions, the denial wins.
- Auto-approved commands and blocked commands never ask in VS Code.
- With `mcp` 1.x the form stays open in VS Code after Telegram answered. `mcp` 2.x closes it. Answers that come late are ignored.
- Set `vscode_wait_s = 0` for the old way: Telegram only. Do this if your VS Code answers forms without asking you.

### Accept the allow list

An allow list runs commands without your tap. This file is inside the project, so Copilot or a cloned repository can change it. For this reason, `allow` and `use_default_block = false` do nothing until you accept them yourself:

```bash
vscode-copilot-telegram --accept-policy --workspace /path/to/your/project
```

Use the full path to the command from the `.venv`. What happens:

- You type it in a terminal. It shows the patterns and asks you to type `accept`.
- It refuses to run from a script, from a pipe, or from `run_command`.
- It saves the accepted list in `~/.config/vscode-copilot-telegram/accepted-policy.json`, outside the project. Restart the server after that.
- It refuses a pattern that approves almost everything, like `.*` or `\S+`.
- For other patterns, it prints a WARNING if the pattern also approves risky commands (for example `git diff --output=/tmp/out.txt`, `npm install some-package`, `python script.py`). Read these lines before you type `accept`.
- It refuses to save if the accepted file would be inside the project (for example, when you open your home folder as the project).
- If the list in the file is different from what you accepted, even by one pattern, it is ignored again. The allow list is empty, the block list is on, and every command asks. The server output and each approval message say it.

`block`, the timeouts, `shell` and the other keys do not need acceptance. They cannot run a command without your tap.

### Allow list rules

- Each pattern is a Python regular expression. It is matched against the whole command, without case, after removing spaces at the start and the end. `git status` matches only `git status`, not `git status && rm -rf x`.
- A command with `;`, `&&`, `||`, `|`, a backtick, `$(`, `>`, `<`, a new line, or `&` at the end is never auto-approved. It goes to Telegram.
- The block list is checked first. It always wins.
- An auto-approved command sends an Auto-approved notice, and it is written to the audit log as `auto-approved`.

Keep the patterns narrow:

- `( .*)?` at the end accepts any argument. `git (status|diff|log)( .*)?` also accepts `git diff --output=/tmp/out.txt`, which writes a file anywhere.
- `pytest`, `npm test` and `make` run any code in the project, also code that Copilot just wrote. Do not add them unless you accept this.
- `npm .*` and `python .*` accept package installs and any script.

Example. Use single quotes in TOML, so you do not need to escape backslashes:

```toml
allow = [
  'git status',
  'git diff( --stat)?',
  'git log( --oneline)?( -[0-9]+)?',
  'ls( -[a-zA-Z]+)?',
]
```

### Block list rules

- Each pattern is a Python regular expression. It is searched anywhere in the command, without case.
- A match is denied at once. You get a Blocked command notice without buttons, and Copilot is told not to try another way.
- An empty command is always blocked.

The built-in list is `DEFAULT_BLOCK` in [policy.py](../src/vscode_copilot_telegram/policy.py). It blocks:

- `rm -r` on `/`, `/*`, `~`, `~/`, `$HOME`, and anything with `--no-preserve-root`
- forced push: `git push --force`, `--force-with-lease`, `-f`, and `+refspec`
- `mkfs`, `dd ... of=/dev/...`, redirects to `/dev/sd*`, `/dev/nvme*`, `/dev/disk*`, and `chmod -R 777 /`
- a download piped to a shell or Python: `curl ... | sh`, `wget ... | bash`, `curl ... | python`, `iwr ... | iex`
- the fork bomb `:(){ :|:& };:`
- Windows wipes: `format C:`, `rd /s ... C:\`, `Remove-Item -Recurse ... C:\`
- `shutdown`, `reboot`, `halt`, `poweroff`

Your own patterns:

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

The block list is a safety net, not a sandbox. The same thing can be written in another way. For this reason, everything else still needs your tap.

## Server flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--workspace PATH` | `$WORKSPACE_ROOT`, then the current folder | The project folder. It is the jail for commands, the place of the TOML file, and the place of `.vscode-copilot-telegram/`. |
| `--test` | off | Sends one test message, prints `sent` and exits. Exit code 0 if it works, 1 if not. It does not start the server. |
| `--accept-policy` | off | Review and accept the allow list. Needs a terminal. Does not start the server. |
| `--log-level LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs go to stderr. VS Code shows them in the output of the server. |

### Tools

| Tool | Parameters | Returns |
| --- | --- | --- |
| `run_command` | `command`, `reason`, `cwd` (optional, inside the project), `timeout_s` (optional) | `request_id`, `command`, `decision`, `exit_code` (null if it did not run), `output`, and sometimes `cwd`, `note`, `timed_out` |
| `ask_user` | `question`, `options` (optional, up to 20 buttons), `timeout_s` (optional) | The answer, `timeout`, or a text that starts with `error:` |
| `notify` | `message` | `sent`, or a text that starts with `error:` |

The values of `decision` are `approved`, `auto-approved`, `denied`, `denied-timeout`, `denied-error`, `blocked` and `rejected`. Only `approved` and `auto-approved` mean the command ran.

## Watcher flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--workspace PATH` | `$WORKSPACE_ROOT`, then the current folder | The project folder, as you opened it in VS Code. |
| `--storage DIR` | auto | A `workspaceStorage/<hash>` folder to read. You can repeat it. It skips the search. |
| `--interval SECONDS` | `2` | How often it looks for changes. |
| `--settle SECONDS` | `8` | A reply that does not finish is sent after it stops changing for this time. |
| `--source` | `auto` | `chatsessions`, `transcripts`, `both`, or `auto` (chatSessions if they exist, if not the Copilot transcripts). |
| `--backfill N` | `0` | On the first look at an old session, also send its last N messages. |
| `--no-tools` | off | Leave out the lines about tool calls and file edits. |
| `--state-file PATH` | `~/.vscode-copilot-telegram/watch-<project>-<hash>.json` | Where it saves what it already sent. |
| `--dry-run` | off | Print the messages and do not send them. No token needed. |
| `--list` | off | Show the storage folders and session files, then exit. Exit code 1 if there are none. |
| `--once` | off | Look one time and exit. |
| `-v`, `--verbose` | off | Debug logs. |

## Where things are

| Path | Written by | What is inside |
| --- | --- | --- |
| `~/.config/vscode-copilot-telegram/.env` | you | Token and user id |
| `PROJECT/vscode-copilot-telegram.toml` | you | Optional settings |
| `~/.config/vscode-copilot-telegram/accepted-policy.json` | `--accept-policy` | The allow lists you accepted, for each project |
| `~/.vscode-copilot-telegram/audit-<project>-<hash>.jsonl` | server | One JSON line for each request and decision. Secrets are masked. It is outside the project, so Copilot cannot edit it. |
| `PROJECT/.vscode-copilot-telegram/broker-state.json` | server | The Telegram update offset and the last 500 answered request ids. This makes the buttons single-use after a restart. |
| `~/.vscode-copilot-telegram/watch-<project>-<hash>.json` | watcher | The messages that were already sent |

The watcher reads the chat files of VS Code (read only). It looks in these `User` folders:

| System | Folders |
| --- | --- |
| Windows | `%APPDATA%\Code\User`, `%APPDATA%\Code - Insiders\User`, `%APPDATA%\VSCodium\User` |
| macOS | `~/Library/Application Support/Code/User`, `.../Code - Insiders/User`, `.../VSCodium/User` |
| Linux | `$XDG_CONFIG_HOME/Code/User` (default `~/.config/Code/User`), and the Insiders and VSCodium ones |
| Remote (Tunnels, SSH, WSL) | `~/.vscode-server/data/User` and `~/.vscode-server-insiders/data/User`, on the remote machine |

Inside each one: `workspaceStorage/<hash>/workspace.json` (tells which folder it is), `workspaceStorage/<hash>/chatSessions/*.json` or `*.jsonl`, and `workspaceStorage/<hash>/GitHub.copilot-chat/transcripts/*.jsonl`.
