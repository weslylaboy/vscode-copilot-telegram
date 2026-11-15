"""The tool logic behind the MCP server, kept free of MCP so it can be tested directly."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from html import escape
from typing import Any, Awaitable, Callable

from .audit import AuditLog
from .broker import Answer, Broker, keyboard, new_request_id
from .config import Settings
from .masking import mask_secrets
from .policy import CommandPolicy, Verdict
from .runner import RunResult, run_command, truncate
from .telegram import TelegramError
from .workspace import CwdError, resolve_cwd

log = logging.getLogger("vscode_copilot_telegram.bridge")

Runner = Callable[[str, Any, float, str], Awaitable[RunResult]]

MAX_CMD_IN_MESSAGE = 2500


@dataclass(frozen=True)
class LocalQuestion:
    """What to ask the user inside VS Code (the server turns this into an MCP elicitation form)."""
    kind: str                                   # approval | question
    message: str
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LocalAnswer:
    action: str                                 # approve | deny | option | text
    value: str | None = None                    # note, chosen option, or typed text


# Asks in VS Code and waits until the user answers. Returns None when VS Code cannot ask or the user
# dismisses the form. The bridge cancels it (so the form closes) when Telegram answers first.
LocalPrompt = Callable[[LocalQuestion], Awaitable[LocalAnswer | None]]


@dataclass
class Decision:
    answer: Answer | None       # None means nobody answered in time
    message_id: int | None      # the Telegram message, if one was sent
    via: str                    # vscode | telegram
    escalated: bool             # a Telegram message was sent because VS Code got no answer in time


def h(s: str) -> str:
    return escape(s, quote=False)


def _fmt_wait(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 120 and seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


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

    # ---------------- VS Code first, then Telegram ----------------
    async def _safe_local(self, prompt: LocalPrompt, question: LocalQuestion) -> LocalAnswer | None:
        try:
            return await prompt(question)
        except Exception:  # noqa: BLE001 - a broken VS Code prompt must not stop the Telegram path
            log.warning("could not ask in VS Code; using Telegram only", exc_info=True)
            return None

    @staticmethod
    def _to_answer(local: LocalAnswer) -> Answer:
        return Answer(local.action, local.value)

    @staticmethod
    def _safer(a: Answer, b: Answer) -> Answer:
        """If VS Code and Telegram answered at the same moment with different decisions, a denial wins."""
        return b if b.action in ("deny", "note") and a.action == "approve" else a

    async def _decide(self, rid: str, kind: str, html: str, markup: dict | None, timeout_s: float,
                      options: list[str] | None, local_prompt: LocalPrompt | None,
                      local_question: LocalQuestion | None) -> Decision:
        """Ask in VS Code first. If nobody answers within vscode_wait_s, also ask on Telegram and take
        whichever answer comes first. Raises TelegramError if the Telegram message cannot be sent and
        VS Code has not answered either."""
        wait = float(self.s.vscode_wait_s)
        if local_prompt is None or local_question is None or wait <= 0:
            ticket = await self.broker.ask(rid, kind, html, markup, timeout_s, options)
            return Decision(ticket.answer, ticket.message_id, "telegram", False)

        local = asyncio.ensure_future(self._safe_local(local_prompt, local_question))
        tg: asyncio.Future | None = None
        try:
            done, _ = await asyncio.wait({local}, timeout=wait)
            if local in done:
                answered = local.result()
                if answered is not None:
                    return Decision(self._to_answer(answered), None, "vscode", False)
                # VS Code cannot ask, or the form was dismissed: go to Telegram right away.
                ticket = await self.broker.ask(rid, kind, html, markup, timeout_s, options)
                return Decision(ticket.answer, ticket.message_id, "telegram", False)

            notice = (f"\n\n⏰ <i>No answer in VS Code after {_fmt_wait(wait)}. "
                      f"You can still answer there.</i>")
            tg = asyncio.ensure_future(self.broker.ask(rid, kind, html + notice, markup, timeout_s, options))
            waiting: set[asyncio.Future] = {local, tg}
            while True:
                finished, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                local_answer: LocalAnswer | None = None
                if local in finished and local in waiting:
                    waiting.discard(local)
                    local_answer = local.result()
                if tg in finished:
                    if tg.cancelled() or tg.exception() is not None:
                        exc = tg.exception() if not tg.cancelled() else None
                        # Telegram failed (fail closed), but a VS Code answer can still arrive.
                        if local_answer is None and local in waiting:
                            await asyncio.wait({local}, timeout=timeout_s)
                            local_answer = local.result() if local.done() else None
                        if local_answer is not None:
                            return Decision(self._to_answer(local_answer), None, "vscode", True)
                        if isinstance(exc, TelegramError):
                            raise exc
                        raise exc or asyncio.CancelledError()
                    ticket = tg.result()
                    if local_answer is not None and ticket.answer is not None:
                        chosen = self._safer(self._to_answer(local_answer), ticket.answer)
                        via = "vscode" if chosen.action == local_answer.action else "telegram"
                        return Decision(chosen, ticket.message_id, via, True)
                    if local_answer is not None:
                        return Decision(self._to_answer(local_answer), ticket.message_id, "vscode", True)
                    return Decision(ticket.answer, ticket.message_id, "telegram", True)
                if local_answer is not None:
                    # Answered in VS Code: take the Telegram request back so its buttons stop working.
                    mid = self.broker.message_id_of(rid)
                    return Decision(self._to_answer(local_answer), mid, "vscode", True)
                # The form was dismissed in VS Code: keep waiting for Telegram.
        finally:
            leftovers = [f for f in (local, tg) if f is not None and not f.done()]
            for f in leftovers:
                f.cancel()
            if leftovers:
                await asyncio.gather(*leftovers, return_exceptions=True)

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
                       timeout_s: int | None = None, local_prompt: LocalPrompt | None = None) -> str:
        rid = new_request_id()
        opts = [str(o) for o in (options or []) if str(o).strip()][:20]
        q = mask_secrets(question or "")
        body = f"{self.tag} ❓ <b>Copilot asks</b>\n\n{h(q)[:3000]}\n\n<i>Tap an option or type a reply.</i>"
        markup = keyboard([[(o[:60], f"o{i}")] for i, o in enumerate(opts)], rid) if opts else None
        local_q = LocalQuestion("question", question or "", opts)
        try:
            decision = await self._decide(rid, "question", body, markup, self._timeout(timeout_s), opts,
                                          local_prompt, local_q)
        except TelegramError as exc:
            self.audit.write(request_id=rid, type="ask_user", decision="error", question=q[:500], error=str(exc))
            return f"error: could not reach the user on Telegram ({exc}). Do not assume an answer."
        shown = body + (f"\n\n⏰ <i>No answer in VS Code after {_fmt_wait(self.s.vscode_wait_s)}.</i>"
                        if decision.escalated else "")
        if decision.answer is None:
            self.audit.write(request_id=rid, type="ask_user", decision="timeout", question=q[:500])
            await self.broker.update_message(decision.message_id, shown + "\n\n⏱ <i>No answer (timed out).</i>")
            return "timeout"
        answer = decision.answer.value or ""
        self.audit.write(request_id=rid, type="ask_user", decision="answered", question=q[:500],
                         answer=answer[:500], via=decision.via)
        where = " (in VS Code)" if decision.via == "vscode" else ""
        await self.broker.update_message(
            decision.message_id, shown.replace("<i>Tap an option or type a reply.</i>", "").rstrip("\n")
            + f"\n\n✅ <b>Answer{where}:</b> {h(mask_secrets(answer))[:800]}")
        return answer

    # ---------------- run_command ----------------
    async def run_command(self, command: str, reason: str, cwd: str | None = None,
                          timeout_s: int | None = None, local_prompt: LocalPrompt | None = None) -> dict[str, Any]:
        rid = new_request_id()
        command = command or ""
        reason = reason or ""
        base = {"request_id": rid, "command": command}
        via: str | None = None

        def done(decision: str, exit_code: int | None = None, **extra: Any) -> dict[str, Any]:
            record: dict[str, Any] = {"via": via} if via else {}
            self.audit.write(request_id=rid, type="run_command", command=command, decision=decision,
                             exit_code=exit_code, cwd=extra.get("cwd"), reason=reason[:500],
                             note=extra.get("note"), **record)
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
        if self.s.policy_warning:
            header += "\n⚠️ <i>The allow list in the project file is not accepted, so it is ignored.</i>"

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
        header_sent = header  # what the Telegram message says now (it gains a line if we escalate)
        if verdict.verdict is Verdict.ALLOW:
            try:
                message_id = await self.broker.api.send_message(
                    header.replace("Run command?", "Auto-approved") + "\n\n✅ Allow list → running…")
            except TelegramError:
                message_id = None  # notice only; allow-listed commands still run
            decision = "auto-approved"
        else:
            markup = keyboard([[("✅ Approve", "a"), ("❌ Deny", "d")], [("📝 Deny with note", "n")]], rid)
            local_q = LocalQuestion(
                "approval", f"Run this command?\n\n{command[:MAX_CMD_IN_MESSAGE]}\n\nWhy: {reason[:600]}\ncwd: {rel}")
            try:
                got = await self._decide(rid, "approval", header, markup, self._timeout(timeout_s), None,
                                         local_prompt, local_q)
            except TelegramError as exc:
                # fail closed
                return done("denied-error", cwd=rel, output=f"Denied: could not reach the user on Telegram "
                            f"({exc}). The command was NOT run.")
            message_id = got.message_id
            via = got.via
            if got.escalated:
                header_sent = header + (f"\n\n⏰ <i>No answer in VS Code after "
                                        f"{_fmt_wait(self.s.vscode_wait_s)}. You can still answer there.</i>")
            if got.answer is None:
                await self.broker.update_message(message_id, header_sent + "\n\n⏱ <b>Timed out → denied.</b> Not run.")
                return done("denied-timeout", cwd=rel, output="Denied: no approval before the timeout. "
                            "The command was NOT run.")
            where = " in VS Code" if got.via == "vscode" else ""
            if got.answer.action in ("deny", "note"):
                note = got.answer.value
                extra = f"\n📝 {h(mask_secrets(note))[:800]}" if note else ""
                await self.broker.update_message(message_id, header_sent + f"\n\n❌ <b>Denied{where}.</b>{extra}")
                msg = "Denied by the user. The command was NOT run."
                if note:
                    msg += f" Note from the user: {note}"
                return done("denied", cwd=rel, note=note, output=msg)
            decision = "approved"
            await self.broker.update_message(message_id, header_sent + f"\n\n✅ <b>Approved{where}</b> → running…")

        # 3. run
        result = await self.runner(command, workdir, float(self.s.run_timeout_s), self.s.shell)
        output = truncate(result.output, self.s.max_output_chars)
        status = ("⏱ killed (run timeout)" if result.timed_out else f"exit code {result.exit_code}")
        icon = "✅" if result.exit_code == 0 else "⚠️"
        label = "Auto-approved" if decision == "auto-approved" else "Approved"
        prefix = header_sent.replace("Run command?", label) + f"\n\n{icon} <b>{status}</b>"
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
