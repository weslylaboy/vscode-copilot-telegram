# Claude Code

@AGENTS.md

Follow `AGENTS.md` as the canonical guide for work on this repository (purpose, module map, commands, conventions, tests, security invariants, docs, and commits).

## Notes for Claude Code

- This repo is developed on GitHub: https://github.com/weslylaboy/vscode-copilot-telegram. Open pull requests there.
- `.github/copilot-instructions.md` is for GitHub Copilot working **on this repo**. `examples/copilot-instructions.md` is a template for end users of the tool. Do not confuse the two, and do not overwrite the example template with repo-agent instructions.
- Before finishing a code change, run `pytest -q`. Do not hit the real Telegram API in tests.
- The MCP server process must keep stdout clean (protocol only). Put logs on stderr.
