# Writing style

Rules for writing the docs of this project. Short on purpose.

## Who reads this

- A newbie who never used MCP, Telegram bots or a terminal much.
- An experienced user who only wants the commands.

Write for the newbie, but make it fast for the expert.

## Rules

1. **Short sentences.** One idea each. If a sentence has two "and", cut it.
2. **Simple words.** Write "use", not "utilize". Write "start", not "initiate".
3. **No filler.** Do not write "simply", "just", "easily", "robust", "seamless", "powerful", "note that".
4. **No bold, emoji or decoration** unless it stops a real mistake (for example, a secret token).
5. **One step = one action.** Write the command, then what you should see.
6. **Say why in one line.** A newbie needs the reason. The expert can skip it.
7. **Commands first.** Put the full command in a code block. Never describe a command in words only.
8. **Quick path on top.** Each page starts with the commands only. The explanation comes after.
9. **Do not repeat.** If something is explained in another page, link to it. Do not copy it.
10. **Only write what we ran.** If we did not test it, we do not document it.
11. **Same word for the same thing.** Pick one name (for example "bot token") and keep it.
12. **Windows and macOS** commands go side by side, with the same layout every time.

## Tone

Plain and direct, like a colleague explaining over chat. Not a sales page, not a manual from a big company.

Do not try to sound like a native speaker. Simple and correct is better than fancy.

## Page layout

1. One line: what this page does.
2. Quick path (commands only).
3. Steps, each with: action, command, expected result.
4. If it fails: link to [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Examples

Before:

> This guide takes you from nothing to "Copilot asks, my phone answers" on **Windows (PowerShell)** and **macOS**. Plan on about 20 minutes. Every step ends with a check, so you know it worked before moving on.

After:

> Install the tool and connect it to Telegram. Takes about 20 minutes. Works on Windows, macOS and Linux.

Before:

> Outbound HTTPS to `api.telegram.org` from the computer that runs VS Code's extension host. If you use VS Code Remote Tunnels or SSH, that's the **remote** machine, so install vscode-copilot-telegram there.

After:

> Your computer must reach `api.telegram.org`. If you use VS Code Remote (SSH or Tunnels), install the tool on the remote machine.

Before:

> Make sure that you are able to successfully run the following command in order to verify the installation.

After:

> Check the install:
>
> ```bash
> vscode-copilot-telegram-watch --list --workspace .
> ```
>
> You should see `project: ...` and the matched session files. If you have not used Copilot Chat in that folder yet, it says "no matching workspaceStorage folder found" and exits with code 1.
