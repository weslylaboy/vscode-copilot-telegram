"""The tool logic behind the MCP server, kept free of MCP so it can be tested directly."""

from __future__ import annotations

import logging
from html import escape
from typing import Any, Awaitable, Callable

from .audit import AuditLog
from .broker import Broker, keyboard, new_request_id
from .config import Settings
from .masking import mask_secrets
from .policy import CommandPolicy, Verdict
from .runner import RunResult, run_command, truncate
from .telegram import TelegramError
from .workspace import CwdError, resolve_cwd

log = logging.getLogger("vscode_copilot_telegram.bridge")

Runner = Callable[[str, Any, float, str], Awaitable[RunResult]]

MAX_CMD_IN_MESSAGE = 2500


def h(s: str) -> str:
    return escape(s, quote=False)


class Bridge:
    def __init__(self, settings: Settings, broker: Broker, runner: Runner = run_command,
                 policy: CommandPolicy | None = None, audit: AuditLog | None = None) -> None:
        self.s = settings
        self.broker = broker
        self.runner = runner
        self.policy = policy or CommandPolicy(settings.allow, settings.block, settings.use_default_block)
        self.audit = audit or AuditLog(settings.log_path)

    @property
    def tag(self) -> str:
        return f"<b>[{h(self.s.project_name)}]</b>"

    def _timeout(self, requested: int | None) -> float:
        if requested is None or requested <= 0:
            return float(self.s.timeout_s)
        return float(min(requested, 24 * 3600))

    # ---------------- notify ----------------
    async def notify(self, message: str) -> str:
        rid = new_request_id()
        text = mask_secrets(message or "")
        try:
            await self.broker.api.send_message(f"{self.tag} 📣 {h(text)[:3900]}")
            self.audit.write(request_id=rid, type="notify", decision="sent", message=text[:500])
            return "sent"
        except TelegramError as exc:
            self.audit.write(request_id=rid, type="notify", decision="error", error=str(exc))
            return f"error: could not send to Telegram ({exc})"

    # ---------------- ask_user ----------------
    async def ask_user(self, question: str, options: list[str] | None = None,
                       timeout_s: int | None = None) -> str:
        rid = new_request_id()
        opts = [str(o) for o in (options or []) if str(o).strip()][:20]
        q = mask_secrets(question or "")
        body = f"{self.tag} ❓ <b>Copilot asks</b>\n\n{h(q)[:3000]}\n\n<i>Tap an option or type a reply.</i>"
        markup = keyboard([[(o[:60], f"o{i}")] for i, o in enumerate(opts)], rid) if opts else None
        try:
            ticket = await self.broker.ask(rid, "question", body, markup, self._timeout(timeout_s), opts)
        except TelegramError as exc:
            self.audit.write(request_id=rid, type="ask_user", decision="error", question=q[:500], error=str(exc))
            return f"error: could not reach the user on Telegram ({exc}). Do not assume an answer."
        if ticket.answer is None:
            self.audit.write(request_id=rid, type="ask_user", decision="timeout", question=q[:500])
            await self.broker.update_message(ticket.message_id, body + "\n\n⏱ <i>No answer (timed out).</i>")
            return "timeout"
        answer = ticket.answer.value or ""
        self.audit.write(request_id=rid, type="ask_user", decision="answered", question=q[:500],
                         answer=answer[:500])
        await self.broker.update_message(
            ticket.message_id, body.replace("<i>Tap an option or type a reply.</i>", "")
            + f"✅ <b>Answer:</b> {h(mask_secrets(answer))[:800]}")
        return answer

    # ---------------- run_command ----------------
    async def run_command(self, command: str, reason: str, cwd: str | None = None,
                          timeout_s: int | None = None) -> dict[str, Any]:
        rid = new_request_id()
        command = command or ""
        reason = reason or ""
        base = {"request_id": rid, "command": command}

        def done(decision: str, exit_code: int | None = None, **extra: Any) -> dict[str, Any]:
            self.audit.write(request_id=rid, type="run_command", command=command, decision=decision,
                             exit_code=exit_code, cwd=extra.get("cwd"), reason=reason[:500],
                             note=extra.get("note"))
            return {**base, "decision": decision, "exit_code": exit_code, **extra}

        # 1. confine cwd
        try:
            workdir = resolve_cwd(self.s.workspace_root, cwd)
        except CwdError as exc:
            return done("rejected", cwd=cwd, output=f"Rejected: {exc}. Commands may only run inside "
                        f"the workspace {self.s.workspace_root}.")
        rel = "." if workdir == self.s.workspace_root else str(workdir.relative_to(self.s.workspace_root))

        # 2. block / allow lists
        verdict = self.policy.evaluate(command)
        shown_cmd = h(mask_secrets(command))
        if len(shown_cmd) > MAX_CMD_IN_MESSAGE:
            shown_cmd = shown_cmd[:MAX_CMD_IN_MESSAGE] + "\n…"
        header = (f"{self.tag} 🖥 <b>Run command?</b>\n<pre>{shown_cmd}</pre>\n"
                  f"<b>Why:</b> {h(mask_secrets(reason))[:600]}\n<b>cwd:</b> <code>{h(rel)}</code>\n"
                  f"<b>id:</b> <code>{rid}</code>")

        if verdict.verdict is Verdict.BLOCK:
            try:
                await self.broker.api.send_message(
                    header.replace("Run command?", "Blocked command") +
                    f"\n\n⛔ Denied by block list: <code>{h(verdict.pattern or '')}</code>")
            except TelegramError:
                pass
            return done("blocked", cwd=rel, output=f"Denied without asking: the command matches the block "
                        f"list pattern {verdict.pattern!r}. Do not try to work around it; ask the user.")

        message_id: int | None = None
        note = None
        if verdict.verdict is Verdict.ALLOW:
            try:
                message_id = await self.broker.api.send_message(
                    header.replace("Run command?", "Auto-approved") + "\n\n✅ Allow list → running…")
            except TelegramError:
                message_id = None  # notice only; allow-listed commands still run
            decision = "auto-approved"
        else:
            markup = keyboard([[("✅ Approve", "a"), ("❌ Deny", "d")], [("📝 Deny with note", "n")]], rid)
            try:
                ticket = await self.broker.ask(rid, "approval", header, markup, self._timeout(timeout_s))
            except TelegramError as exc:
                # fail closed
                return done("denied-error", cwd=rel, output=f"Denied: could not reach the user on Telegram "
                            f"({exc}). The command was NOT run.")
            message_id = ticket.message_id
            if ticket.answer is None:
                await self.broker.update_message(message_id, header + "\n\n⏱ <b>Timed out → denied.</b> Not run.")
                return done("denied-timeout", cwd=rel, output="Denied: no approval before the timeout. "
                            "The command was NOT run.")
            if ticket.answer.action in ("deny", "note"):
                note = ticket.answer.value
                extra = f"\n📝 {h(mask_secrets(note))[:800]}" if note else ""
                await self.broker.update_message(message_id, header + f"\n\n❌ <b>Denied.</b>{extra}")
                msg = "Denied by the user. The command was NOT run."
                if note:
                    msg += f" Note from the user: {note}"
                return done("denied", cwd=rel, note=note, output=msg)
            decision = "approved"
            await self.broker.update_message(message_id, header + "\n\n✅ <b>Approved</b> → running…")

        # 3. run
        result = await self.runner(command, workdir, float(self.s.run_timeout_s), self.s.shell)
        output = truncate(result.output, self.s.max_output_chars)
        status = ("⏱ killed (run timeout)" if result.timed_out else f"exit code {result.exit_code}")
        icon = "✅" if result.exit_code == 0 else "⚠️"
        label = "Auto-approved" if decision == "auto-approved" else "Approved"
        prefix = header.replace("Run command?", label) + f"\n\n{icon} <b>{status}</b>"
        budget = min(self.s.telegram_output_chars, 4000 - len(prefix) - 20)
        masked = mask_secrets(result.output).strip()
        tail = ""
        while budget > 50:
            tail = h(truncate(masked, budget))
            if len(prefix) + len(tail) + 20 <= 4096:
                break
            budget = int(budget * 0.8)
        final = prefix + (f"\n<pre>{tail}</pre>" if tail else "")
        if message_id is not None:
            await self.broker.update_message(message_id, final)
        return done(decision, exit_code=result.exit_code, cwd=rel, timed_out=result.timed_out, output=output)
