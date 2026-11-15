"""The bot token is part of every Bot API URL, so request logging must not print it."""

from __future__ import annotations

import logging

import httpx

from vscode_copilot_telegram.telegram import TelegramAPI, TelegramSender

TOKEN = "123456789:AA-not-a-real-token"


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})


def test_sender_does_not_log_the_token(caplog):
    sender = TelegramSender(TOKEN, 42, client=httpx.Client(transport=httpx.MockTransport(_ok)))
    with caplog.at_level(logging.DEBUG):
        sender.send_message("hello")
    assert TOKEN not in caplog.text


async def test_api_does_not_log_the_token(caplog):
    api = TelegramAPI(TOKEN, 42, client=httpx.AsyncClient(transport=httpx.MockTransport(_ok)))
    with caplog.at_level(logging.DEBUG):
        await api.send_message("hello")
    assert TOKEN not in caplog.text
