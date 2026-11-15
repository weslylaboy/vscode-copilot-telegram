"""Minimal Telegram Bot API client over HTTPS (httpx).

Only the MCP server calls ``get_updates`` (long polling). The watcher only calls
``sendMessage`` through :class:`TelegramSender`, which never polls, so the two
processes never fight over getUpdates (Telegram allows one poller per bot).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

# httpx logs every request URL at INFO, and a Bot API URL contains the token.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

API_BASE = "https://api.telegram.org"
MAX_MESSAGE = 4096


class TelegramError(RuntimeError):
    def __init__(self, message: str, *, retry_after: float | None = None, code: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.code = code


def split_message(text: str, limit: int = MAX_MESSAGE, prefix: str = "") -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters including ``prefix``.

    Prefers newline, then space boundaries. When there is more than one chunk each
    gets a "(i/n)" marker after the prefix.
    """
    text = text or ""
    budget = limit - len(prefix) - 12  # room for " (99/99)\n"
    if budget < 100:
        raise ValueError("prefix too long")
    chunks: list[str] = []
    rest = text
    while len(rest) > budget:
        cut = rest.rfind("\n", budget // 2, budget)
        if cut == -1:
            cut = rest.rfind(" ", budget // 2, budget)
        if cut == -1:
            cut = budget
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    chunks.append(rest)
    if len(chunks) == 1:
        return [prefix + chunks[0]]
    n = len(chunks)
    out = []
    for i, c in enumerate(chunks, 1):
        head = prefix.rstrip("\n")
        out.append(f"{head} ({i}/{n})\n{c}" if head else f"({i}/{n})\n{c}")
    return out


def _check(resp: httpx.Response) -> Any:
    try:
        payload = resp.json()
    except ValueError as exc:
        raise TelegramError(f"HTTP {resp.status_code}: non-JSON response", code=resp.status_code) from exc
    if not payload.get("ok"):
        params = payload.get("parameters") or {}
        raise TelegramError(
            f"Telegram error {payload.get('error_code')}: {payload.get('description')}",
            retry_after=params.get("retry_after"),
            code=payload.get("error_code"),
        )
    return payload.get("result")


def _redact(token: str, exc: Exception) -> str:
    return str(exc).replace(token, "<token>")


class TelegramAPI:
    """Async client used by the MCP server (sends, edits, and polls)."""

    def __init__(self, token: str, chat_id: int, client: httpx.AsyncClient | None = None,
                 base_url: str = API_BASE) -> None:
        self._token = token
        self.chat_id = chat_id
        self._base = f"{base_url}/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=60.0))

    async def _call(self, method: str, _http_timeout: float | None = None, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self._client.post(f"{self._base}/{method}", json=params,
                                           timeout=_http_timeout if _http_timeout else httpx.USE_CLIENT_DEFAULT)
        except httpx.HTTPError as exc:
            raise TelegramError(f"{method} failed: {_redact(self._token, exc)}") from None
        return _check(resp)

    async def send_message(self, text: str, reply_markup: dict | None = None,
                           parse_mode: str | None = "HTML", reply_to: int | None = None) -> int:
        result = await self._call(
            "sendMessage", chat_id=self.chat_id, text=text[:MAX_MESSAGE], parse_mode=parse_mode,
            reply_markup=reply_markup, disable_web_page_preview=True,
            reply_parameters={"message_id": reply_to, "allow_sending_without_reply": True} if reply_to else None,
        )
        return int(result["message_id"])

    async def edit_message_text(self, message_id: int, text: str, parse_mode: str | None = "HTML",
                                reply_markup: dict | None = None) -> None:
        try:
            await self._call("editMessageText", chat_id=self.chat_id, message_id=message_id,
                             text=text[:MAX_MESSAGE], parse_mode=parse_mode, reply_markup=reply_markup,
                             disable_web_page_preview=True)
        except TelegramError as exc:
            if "message is not modified" not in str(exc):
                raise

    async def edit_reply_markup(self, message_id: int, reply_markup: dict) -> None:
        try:
            await self._call("editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id,
                             reply_markup=reply_markup)
        except TelegramError as exc:
            if "message is not modified" not in str(exc):
                raise

    async def answer_callback_query(self, callback_id: str, text: str | None = None) -> None:
        await self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return await self._call("getUpdates", _http_timeout=timeout + 15, offset=offset,
                                allowed_updates=["message", "callback_query"],
                                timeout=timeout) or []

    async def aclose(self) -> None:
        await self._client.aclose()


class TelegramSender:
    """Sync, send-only client used by the watcher. Never calls getUpdates."""

    def __init__(self, token: str, chat_id: int, client: httpx.Client | None = None,
                 base_url: str = API_BASE, max_retries: int = 3) -> None:
        self._token = token
        self.chat_id = chat_id
        self._base = f"{base_url}/bot{token}"
        self._client = client or httpx.Client(timeout=20.0)
        self._max_retries = max_retries

    def send_message(self, text: str, parse_mode: str | None = None) -> int:
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.post(f"{self._base}/sendMessage", json={
                    k: v for k, v in {"chat_id": self.chat_id, "text": text[:MAX_MESSAGE],
                                      "parse_mode": parse_mode, "disable_web_page_preview": True}.items()
                    if v is not None})
                return int(_check(resp)["message_id"])
            except httpx.HTTPError as exc:
                err = TelegramError(f"sendMessage failed: {_redact(self._token, exc)}")
            except TelegramError as exc:
                err = exc
            if attempt < self._max_retries and (err.retry_after or err.code is None or (err.code or 0) >= 500):
                time.sleep(min(float(err.retry_after or 2 ** attempt), 60))
                continue
            raise err
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._client.close()

