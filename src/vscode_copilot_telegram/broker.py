"""Routes Telegram replies (button taps and typed text) back to waiting requests.

* Every request gets a random id that travels in the button's callback_data
  (``ct|<id>|<action>``), so several requests can be pending at once.
* A request id can be answered exactly once. Answered ids are remembered (and
  persisted), so a second tap, or a tap on a button from before a restart, does nothing.
* Updates from anyone other than the configured Telegram user are ignored.
* The broker only long-polls getUpdates while something is waiting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Protocol

from .telegram import TelegramError

log = logging.getLogger("vscode_copilot_telegram.broker")

CB_PREFIX = "ct"


class Api(Protocol):
    chat_id: int

    async def send_message(self, text: str, reply_markup: dict | None = None,
                           parse_mode: str | None = "HTML", reply_to: int | None = None) -> int: ...
    async def edit_message_text(self, message_id: int, text: str, parse_mode: str | None = "HTML",
                                reply_markup: dict | None = None) -> None: ...
    async def answer_callback_query(self, callback_id: str, text: str | None = None) -> None: ...
    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]: ...


@dataclass
class Answer:
    action: str            # approve | deny | note | option | text
    value: str | None = None


@dataclass
class Pending:
    rid: str
    kind: str              # approval | question
    future: asyncio.Future
    options: list[str] = field(default_factory=list)
    message_id: int | None = None
    note_prompt_id: int | None = None
    awaiting_note: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class Ticket:
    rid: str
    message_id: int | None
    answer: Answer | None   # None means timed out


def new_request_id() -> str:
    return secrets.token_hex(6)  # 12 chars; callback_data stays far below 64 bytes


def callback_data(rid: str, action: str) -> str:
    return f"{CB_PREFIX}|{rid}|{action}"


def keyboard(rows: list[list[tuple[str, str]]], rid: str) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": callback_data(rid, act)}
                                 for label, act in row] for row in rows]}


class Broker:
    def __init__(self, api: Api, user_id: int, state_dir: Path | None = None,
                 poll_timeout: int = 25, clock_skew_s: float = 5.0) -> None:
        self.api = api
        self.user_id = int(user_id)
        self.poll_timeout = poll_timeout
        self.clock_skew_s = clock_skew_s
        self._pending: dict[str, Pending] = {}
        self._answered: dict[str, str] = {}
        self._state_dir = Path(state_dir) if state_dir else None
        self._offset: int | None = None
        self._poll_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._load_state()

    # ---------- persistence ----------
    def _state_file(self) -> Path | None:
        return self._state_dir / "broker-state.json" if self._state_dir else None

    def _load_state(self) -> None:
        f = self._state_file()
        if f and f.is_file():
            try:
                data = json.loads(f.read_text("utf-8"))
                self._offset = data.get("offset")
                self._answered = dict(data.get("answered", {}))
            except (OSError, ValueError):
                log.warning("could not read %s; starting fresh", f)

    def _save_state(self) -> None:
        f = self._state_file()
        if not f:
            return
        answered = dict(list(self._answered.items())[-500:])
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"offset": self._offset, "answered": answered}), "utf-8")
            tmp.replace(f)
        except OSError:
            log.exception("could not write %s", f)

    # ---------- public API ----------
    @property
    def pending_ids(self) -> list[str]:
        return list(self._pending)

    def is_answered(self, rid: str) -> bool:
        return rid in self._answered

    def message_id_of(self, rid: str) -> int | None:
        """The Telegram message of a request that is still waiting (None if it has none yet or is done)."""
        p = self._pending.get(rid)
        return p.message_id if p else None

    async def ask(self, rid: str, kind: str, html: str, reply_markup: dict | None,
                  timeout_s: float, options: list[str] | None = None,
                  note_grace_s: float = 120.0) -> Ticket:
        """Send a message and wait for its answer. Raises TelegramError if sending fails."""
        loop = asyncio.get_running_loop()
        p = Pending(rid=rid, kind=kind, future=loop.create_future(), options=list(options or []))
        self._pending[rid] = p
        try:
            p.message_id = await self.api.send_message(html, reply_markup=reply_markup)
            self._ensure_poller()
            try:
                answer = await asyncio.wait_for(asyncio.shield(p.future), timeout=timeout_s)
            except asyncio.TimeoutError:
                if p.awaiting_note and not p.future.done():
                    try:
                        answer = await asyncio.wait_for(asyncio.shield(p.future), timeout=note_grace_s)
                    except asyncio.TimeoutError:
                        answer = Answer("note", None)
                else:
                    answer = None
            return Ticket(rid=rid, message_id=p.message_id, answer=answer)
        finally:
            if self._pending.pop(rid, None) is not None:
                # timed out / cancelled: buttons must not work afterwards
                self._mark_answered(rid, "timeout")
            if not p.future.done():
                p.future.cancel()

    async def update_message(self, message_id: int | None, html: str) -> None:
        if message_id is None:
            return
        try:
            await self.api.edit_message_text(message_id, html, reply_markup={"inline_keyboard": []})
        except TelegramError as exc:
            log.warning("could not edit message: %s", exc)

    async def close(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:
                log.warning("the poller ended with an error while closing", exc_info=True)

    # ---------- polling ----------
    def _ensure_poller(self) -> None:
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop(), name="vscode-copilot-telegram-poll")

    async def _poll_loop(self) -> None:
        backoff = 1.0
        if self._offset is None:
            await self._skip_backlog()
        while self._pending:
            try:
                updates = await self.api.get_updates(self._offset, timeout=self.poll_timeout)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                if exc.code == 409:
                    log.error("another process is polling this bot (409 Conflict). "
                              "Use one bot per open VS Code window, and never poll from the watcher.")
                else:
                    log.warning("getUpdates failed: %s", exc)
                await asyncio.sleep(float(exc.retry_after or backoff))
                backoff = min(backoff * 2, 30)
                continue
            except Exception:  # noqa: BLE001 - keep polling; requests fail closed on timeout
                log.exception("unexpected polling error")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            for upd in updates:
                self._offset = int(upd["update_id"]) + 1
                try:
                    await self.handle_update(upd)
                except Exception:  # noqa: BLE001
                    log.exception("error handling update")
            if updates:
                self._save_state()

    async def _skip_backlog(self) -> None:
        """On a first run, ignore whatever was sent to the bot before we started."""
        try:
            backlog = await self.api.get_updates(-1, timeout=0)
            if backlog:
                self._offset = int(backlog[-1]["update_id"]) + 1
                self._save_state()
        except TelegramError as exc:
            log.warning("could not skip backlog: %s", exc)

    # ---------- update handling ----------
    def _authorized(self, user: dict | None) -> bool:
        if not user:
            return False
        return int(user.get("id", 0)) == self.user_id

    async def handle_update(self, upd: dict[str, Any]) -> None:
        if "callback_query" in upd:
            await self._handle_callback(upd["callback_query"])
        elif "message" in upd:
            await self._handle_message(upd["message"])

    async def _handle_callback(self, cq: dict[str, Any]) -> None:
        if not self._authorized(cq.get("from")):
            log.warning("ignored button press from unauthorized user %s", (cq.get("from") or {}).get("id"))
            return
        msg_chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
        if msg_chat is not None and int(msg_chat) != int(self.api.chat_id):
            return
        parts = str(cq.get("data", "")).split("|")
        if len(parts) != 3 or parts[0] != CB_PREFIX:
            await self._ack(cq, None)
            return
        _, rid, act = parts
        if rid in self._answered:
            await self._ack(cq, "Already answered.")
            return
        p = self._pending.get(rid)
        if p is None:
            await self._ack(cq, "This request has expired.")
            return
        if p.awaiting_note:
            await self._ack(cq, "Waiting for your note. Reply with text.")
            return
        if p.kind == "approval" and act == "a":
            self._resolve(p, Answer("approve"))
            await self._ack(cq, "Approved")
        elif p.kind == "approval" and act == "d":
            self._resolve(p, Answer("deny"))
            await self._ack(cq, "Denied")
        elif p.kind == "approval" and act == "n":
            p.awaiting_note = True
            await self._ack(cq, "Type your note")
            await self._safe_edit(p.message_id, None)  # drop the buttons: one decision per request
            try:
                p.note_prompt_id = await self.api.send_message(
                    f"✍️ Reply with your note for request <code>{rid}</code>. The command stays denied.",
                    reply_markup={"force_reply": True, "input_field_placeholder": "Why deny?"},
                    reply_to=p.message_id)
            except TelegramError:
                self._resolve(p, Answer("note", None))
        elif p.kind == "question" and act.startswith("o") and act[1:].isdigit():
            idx = int(act[1:])
            if 0 <= idx < len(p.options):
                self._resolve(p, Answer("option", p.options[idx]))
                await self._ack(cq, p.options[idx][:190])
            else:
                await self._ack(cq, "Unknown option.")
        else:
            await self._ack(cq, "Unknown action.")

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        if not self._authorized(msg.get("from")):
            log.warning("ignored message from unauthorized user %s", (msg.get("from") or {}).get("id"))
            return
        if int((msg.get("chat") or {}).get("id", 0)) != int(self.api.chat_id):
            return
        text = msg.get("text")
        if text is None:
            return
        if text.strip().startswith("/"):
            await self._command(text.strip())
            return
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        sent_at = float(msg.get("date", time.time()))
        target: Pending | None = None
        if reply_to is not None:
            for p in self._pending.values():
                if reply_to in (p.message_id, p.note_prompt_id):
                    target = p
                    break
            if target is not None and target.kind == "approval" and not target.awaiting_note:
                await self._say("Use the buttons on that request (or tap “Deny with note”).")
                return
        if target is None:
            waiting = [p for p in self._pending.values()
                       if (p.awaiting_note or p.kind == "question")
                       and sent_at >= p.created_at - self.clock_skew_s]
            if len(waiting) == 1:
                target = waiting[0]
            elif not waiting:
                if reply_to is None:
                    await self._say("Nothing is waiting for a typed answer right now.")
                return
            else:
                await self._say("Several requests are waiting. Swipe-reply to the one you mean.")
                return
        if target.awaiting_note:
            self._resolve(target, Answer("note", text))
        else:
            self._resolve(target, Answer("text", text))

    async def _command(self, text: str) -> None:
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/pending":
            if not self._pending:
                await self._say("Nothing pending.")
            else:
                lines = [f"• <code>{p.rid}</code> {p.kind}" for p in self._pending.values()]
                await self._say("Pending:\n" + "\n".join(lines))
        elif cmd in ("/start", "/help"):
            await self._say("vscode-copilot-telegram is connected. Questions and command approvals from Copilot "
                            "show up here. /pending lists what is waiting.")

    # ---------- helpers ----------
    def _mark_answered(self, rid: str, how: str) -> None:
        self._answered[rid] = how
        self._save_state()

    def _resolve(self, p: Pending, answer: Answer) -> None:
        if p.rid in self._answered or p.future.done():
            return
        self._pending.pop(p.rid, None)
        self._mark_answered(p.rid, answer.action)
        p.future.set_result(answer)

    async def _ack(self, cq: dict, text: str | None) -> None:
        try:
            await self.api.answer_callback_query(cq.get("id", ""), text)
        except TelegramError as exc:
            log.warning("could not answer the button tap: %s", exc)

    async def _say(self, html: str) -> None:
        try:
            await self.api.send_message(html)
        except TelegramError as exc:
            log.warning("could not send message: %s", exc)

    async def _safe_edit(self, message_id: int | None, html: str | None) -> None:
        if message_id is None:
            return
        try:
            if html is None:
                # only remove the keyboard
                edit = getattr(self.api, "edit_reply_markup", None)
                if edit:
                    await edit(message_id, {"inline_keyboard": []})
            else:
                await self.api.edit_message_text(message_id, html, reply_markup={"inline_keyboard": []})
        except TelegramError:
            pass


def h(text: str) -> str:
    return escape(text, quote=False)
