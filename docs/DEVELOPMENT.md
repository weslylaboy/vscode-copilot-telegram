# Development

How to change this project safely. Read [ARCHITECTURE.md](ARCHITECTURE.md) first.

## Instructions for coding agents

For agents that work on this repository (not for projects that use the tool):

- [AGENTS.md](../AGENTS.md): the main guide.
- [.github/copilot-instructions.md](../.github/copilot-instructions.md): for GitHub Copilot. It is not [examples/copilot-instructions.md](../examples/copilot-instructions.md). That file is the template that users copy into their own projects.
- [CLAUDE.md](../CLAUDE.md): for Claude Code. It imports `AGENTS.md`.

Writing docs? Follow [STYLE.md](STYLE.md).

## Dev environment

```bash
git clone https://github.com/weslylaboy/vscode-copilot-telegram.git
cd vscode-copilot-telegram
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Python 3.11 is the minimum (`tomllib`, `Path.is_relative_to`, modern typing). CI runs 3.11 and 3.12.

## Run the tests

```bash
pytest -q                          # all tests (175, about 20 s)
pytest -q tests/test_bridge.py     # one file
pytest -q -k timeout               # by name
mypy                               # type check of src/
```

The pytest options are in `pyproject.toml` (`asyncio_mode = "auto"`).

| File | What it tests |
| --- | --- |
| `tests/test_bridge.py` | Approve once and ignore a second tap, answered ids after a restart, deny, deny with note, timeout, Telegram send failure (all fail closed), unauthorized users, several requests at once, block list, allow list notice, cwd jail, masking, audit log, `ask_user` (options, text, timeout, reply routing), `notify` |
| `tests/test_policy.py` | Built-in block list (with the accept command and the accepted file), allow list full match, chaining is never auto-approved |
| `tests/test_masking.py` | Each masking pattern |
| `tests/test_runner.py` | Output capture, timeout kill, Windows kill with the full path of `taskkill`, token removed from the environment, truncation |
| `tests/test_workspace.py` | cwd resolution, escapes with `..`, absolute paths, sibling prefix and symlinks, missing folders |
| `tests/test_config.py` | The project `.env` is never loaded, the `.env` order, the audit log default and a leftover `log_path`, `vscode_wait_s` (default and limits), the allow list (ignored until accepted, ignored again when it changes, per project, refused when too broad, warnings, a copy inside the project not trusted), `--accept-policy` refusing as a script and working in a pseudo-terminal (not on Windows) |
| `tests/test_vscode_first.py` | Ask in VS Code first, then Telegram: an answer in VS Code sends no Telegram message, Telegram after the wait and the form closed when it answers, a VS Code answer after Telegram was sent (the Telegram button stops working), deny with note, a client that cannot ask, a prompt that crashes, `vscode_wait_s = 0`, a dismissed form, nobody answers, Telegram down (fail closed, but a VS Code answer still counts), a cancelled tool call, a denial beating an approval, auto-approved commands, and the same for `ask_user` |
| `tests/test_sessions.py` | The three chat formats (fixtures in `tests/fixtures/`), replay of the log, file URI decoding, storage matching, message splitting, and the watcher: no duplicates after a restart, settle time, no flood of old history, backfill, retry after a send failure |
| `tests/test_mcp_smoke.py` | Starts the real server with `python -m vscode_copilot_telegram` over stdio, lists the tools, checks that calls fail closed with Telegram on a closed local port, and without credentials. It also answers the VS Code form like VS Code would: approve, deny with a note, an `ask_user` option, a dismissed form, a late answer when Telegram is down, and the form being cancelled when the server gives up (skipped on `mcp` 1.x) |

`tests/conftest.py` has `FakeTelegram` (an in-memory replacement for `TelegramAPI`) and the `make_bridge` fixture.

No test uses the real Telegram API or needs a token. `VSCODE_COPILOT_TELEGRAM_API_BASE` points the smoke test to a closed local port.

## CI

`.github/workflows/ci.yml` runs `pip install -e ".[dev]"` and `pytest -q` on Linux, macOS and Windows with Python 3.11 and 3.12. It runs `mypy` once, on Linux. It runs on every branch push and pull request. Results are in the Actions tab.

## Test with a real Telegram

1. Create a test bot with @BotFather and save its token in `~/.config/vscode-copilot-telegram/.env`.
2. Run `vscode-copilot-telegram --test --workspace /tmp/scratch`. You get the message.
3. Run the server without VS Code, with the MCP Inspector:

   ```bash
   npx @modelcontextprotocol/inspector .venv/bin/vscode-copilot-telegram --workspace /tmp/scratch
   ```

   Call `run_command` with `{"command": "echo hi", "reason": "test"}` and approve on your phone.
4. Watcher: `vscode-copilot-telegram-watch --workspace <a folder with chats> --dry-run --backfill 3`.
5. Then do the [manual checklist](#manual-checklist) in VS Code.

## Manual checklist

Do these in order, in a new Agent chat in your project. Each one must pass.

The Telegram checks below need the message on Telegram without waiting. Put `vscode_wait_s = 10` in `vscode-copilot-telegram.toml` (restart the server), and do not answer the VS Code form. Or use `vscode_wait_s = 0` to skip the form.

- [ ] VS Code form: with the default `vscode_wait_s`, ask `Use run_command to run git status`. A form appears in the chat. Choose approve. The command runs, and you get no Telegram message.
- [ ] Telegram after the wait: with `vscode_wait_s = 10`, ask the same and do not answer. After 10 seconds a message arrives that says "No answer in VS Code", and the form is still open. Tap Approve. The form closes (this needs `mcp` 2.x) and Copilot reports the result.
- [ ] VS Code after Telegram: do it again, but answer the form after the message arrived. The Telegram message says "Approved in VS Code", and tapping its button says Already answered.
- [ ] Autopilot: switch the chat to Autopilot and ask for a command. The question goes to Telegram at once.

- [ ] Telegram: `vscode-copilot-telegram --test --workspace PROJECT` prints `sent`, and the message arrives.
- [ ] Server: **MCP: List Servers** shows it Running with 3 tools.
- [ ] Built-in terminal: the settings from [SETUP.md](SETUP.md#7-turn-off-the-built-in-terminal) are saved, and the permission level is Manual permissions.
- [ ] Approve: ask `Use run_command to run git status`. A Run command? message arrives with the command, Why, cwd and id. Tap Approve. The message shows the exit code and output, and Copilot reports the result.
- [ ] Deny: ask for `echo should-not-run > denied.txt` and tap Deny. `denied.txt` does not exist.
- [ ] Deny with note: ask for another command, tap Deny with note, and write a note. Copilot gets the note.
- [ ] Timeout: ask `Use run_command with timeout_s 30 to run echo late` and do not tap. After 30 seconds the message shows Timed out, denied. A later Approve says Already answered and nothing runs.
- [ ] Single-use: approve a request, then tap Approve again on the same message. It says Already answered.
- [ ] Block list: ask for `git push --force`. You get a Blocked command notice without buttons, and nothing runs.
- [ ] Jail: ask for `ls` with `cwd` set to `..`. It is rejected without asking you.
- [ ] Question: ask `Use ask_user to ask me which database to use, with options Postgres and SQLite`. Tap one. Repeat and type a free answer.
- [ ] Only you: while a request waits, send a message to your bot from another Telegram account. Nothing happens. The server output shows `ignored message from unauthorized user`.
- [ ] Chat mirror: with the watcher running, send a prompt to Copilot. In a few seconds you get your prompt and the answer.
- [ ] Audit log: the file has one line for each request, with `decision` values like `approved`, `denied`, `denied-timeout`, `blocked`, `rejected`.
- [ ] Allow list: add `allow = ['git status']` to the TOML and restart the server. The output warns that it is not accepted. Ask for `git status`: Telegram asks. Run `--accept-policy` in a normal terminal and in the VS Code terminal, and type `accept`. Restart and ask again: it shows Auto-approved without buttons. Add a second pattern, restart, and check that it asks again.
- [ ] Accept refuses scripts: `echo accept | vscode-copilot-telegram --accept-policy --workspace PROJECT` prints `must be run by you` and saves nothing.
- [ ] Restart: restart the server. Tap a button on an old request. It says Already answered or expired. Nothing runs twice.
- [ ] `/pending`: while a request waits, send `/pending` to the bot. It lists the request id.

If something breaks in a real run, please add a test or a fixture for it.

## Chat file formats

These are internals of VS Code that are not documented. `sessions.py` reads them with care: unknown kinds and missing fields are skipped.

Finding the storage of a project: each `.../User/workspaceStorage/<hash>/workspace.json` has `"folder": "<uri>"` (`file:///...`, `vscode-remote://...`, `vscode-vfs://...`). The URI is decoded (`%3A` becomes `:`, drive letters in lower case, UNC kept) and compared after resolving symlinks, without case on Windows and macOS. Multi-root workspaces (`"workspace": ...`) are not matched. Use `--storage`.

Format 1, `chatSessions/<id>.json`:

```
{"version": 3, "sessionId", "customTitle"?, "requests": [
  {"requestId", "message": {"text" | "parts": [{"text"}]}, "response": [parts],
   "result"?, "isComplete"?, "modelState"?}]}
```

Format 2, `chatSessions/<id>.jsonl` (VS Code 1.109 and newer). One operation for each line, replayed in order:

- `{"kind": 0, "v": <full session>}`: snapshot
- `{"kind": 1, "k": [path], "v": value}`: set
- `{"kind": 2, "k": [path], "v": [items], "i"?: index}`: push or splice
- `{"kind": 3, "k": [path]}`: delete

The result is format 1.

Response parts that are used (`kind`):

- `markdownContent`, `markdownVuln`, or no kind: text in `content` or `value`
- `inlineReference`: file name
- `toolInvocation`, `toolInvocationSerialized`: `pastTenseMessage` or `invocationMessage`, and `toolSpecificData.commandLine` for terminal commands
- `textEditGroup`: name of the edited file
- `confirmation`: `title` or `message`

Skipped on purpose: `thinking`, progress, warnings, references, code-block URIs, undo stops and other interface parts (`SKIP_KINDS`).

A reply is complete when its request has `result`, or `isComplete: true`, or a `modelState` with `completedAt` or a value that is not zero, or when it is not the last request. An incomplete reply is sent after it stays the same for `--settle` seconds.

Format 3, `GitHub.copilot-chat/transcripts/<id>.jsonl`: events `{"type", "id"?, "data": {...}}`, with `user.message` and `assistant.message` (`content`, `text` or `message`), and `tool.execution_start` (`toolName`, and `arguments` with `command`, `filePath` or `path`).

Dedupe keys: `<requestId>:u` and `:a` for chat sessions, `<event id>:u`, `:a` and `:t` for transcripts. If you change these keys, every watcher sends all its history again. Do not change them.

When a format changes: copy a small, scrubbed sample into `tests/fixtures/`, add a test in `tests/test_sessions.py`, and then fix the parser.

## Rules for the code

- `bridge.py` has no MCP imports. `server.py` is the only module that knows MCP.
- Everything that goes to Telegram passes through `mask_secrets`. Every audit field passes through `AuditLog`.
- Everything that can fail on the approval path must end in a deny. Add a test for each new failure path.
- In the server, stdout is for the MCP protocol. Log only to stderr.
- To release: change `version` in `pyproject.toml` and `__init__.py` together, and add a `CHANGELOG.md` entry.

Known limitations are only in [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations).

## Roadmap

To do, in order of value:

1. A `preToolUse` hook that blocks the built-in shell. Use the agent hooks of Copilot (`.github/hooks/*.json`, `preToolUse`) to deny the built-in terminal and point the model to `run_command`. This closes the gap in the Copilot harness where Run in Terminal cannot be unticked. It needs a test with the current hook schema.
2. Approval for file edits. Options: a `write_file` or `apply_patch` MCP tool that shows a diff in Telegram, with `chat.tools.edits.autoApprove` rules so built-in edits to sensitive paths ask for a click. Or an approval of the diff before a commit.
3. One poller for several windows (a small local daemon), to remove the one-bot-for-each-window rule.
4. Full paths for the shells on Windows. `runner.py` starts `powershell`, `pwsh`, `cmd.exe` and `bash` by name. For a bare name, Windows looks in the current folder of the server before the system folders. A file with that name in the project could run in place of the real shell. `taskkill` already uses its full path. It needs a Windows machine to test.
5. Publish to PyPI, so setup is `pipx install vscode-copilot-telegram`.
6. Slack and Discord. Move the `Api` protocol in `broker.py` to a transport interface (send, edit, buttons, read), and add Slack (Socket Mode, Block Kit) and Discord (gateway, components).
7. Real chat file samples from Windows, macOS and VS Code Server, as fixtures.
