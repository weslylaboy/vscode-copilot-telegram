<!-- Add these lines to <your project>/.github/copilot-instructions.md -->
<!-- This is the end-user template for projects that *use* vscode-copilot-telegram.
     Instructions for agents developing this repository itself are in /AGENTS.md
     and /.github/copilot-instructions.md — do not replace this file with those. -->

## Running commands and asking questions (vscode-copilot-telegram)

- Run every shell command with the `run_command` tool from the vscode-copilot-telegram MCP server. Do not use any other terminal or shell tool. Always pass a one-sentence `reason`.
- If `run_command` returns a decision other than `approved` or `auto-approved`, the command did not run. Do not retry the same command in another form. Read the user's note if there is one, adjust your plan, or use `ask_user`.
- When you need a decision, a preference, a missing value, or confirmation from me, call `ask_user` instead of asking in chat and stopping. Offer short `options` when the choice is between a few alternatives. If it returns `timeout`, pick the safest option or stop and explain.
- Call `notify` with a one-line status at milestones: plan ready, tests passing or failing, task finished, or blocked.
- Never put secrets, tokens, or .env contents in a command, question, or notification.
