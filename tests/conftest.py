import asyncio
from pathlib import Path

import pytest

from vscode_copilot_telegram.broker import Broker
from vscode_copilot_telegram.config import Settings
from vscode_copilot_telegram.bridge import Bridge
from vscode_copilot_telegram.runner import RunResult
from vscode_copilot_telegram.telegram import TelegramError

FIXTURES = Path(__file__).parent / "fixtures"
USER_ID = 4242


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """No test may read or write the real home folder (audit logs, the accepted allow list, .env files)."""
    home = tmp_path / "home-isolated"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


class FakeTelegram:
    """In-memory stand-in for TelegramAPI. Tests push updates with ``push``."""

    def __init__(self, fail_send: bool = False) -> None:
        self.chat_id = USER_ID
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self.callback_answers: list[tuple[str, str | None]] = []
        self.fail_send = fail_send
        self._updates: asyncio.Queue = asyncio.Queue()
        self._next_msg = 100
        self._next_update = 1

    async def send_message(self, text, reply_markup=None, parse_mode="HTML", reply_to=None):
        if self.fail_send:
            raise TelegramError("network down")
        self._next_msg += 1
        self.sent.append({"id": self._next_msg, "text": text, "markup": reply_markup, "reply_to": reply_to})
        return self._next_msg

    async def edit_message_text(self, message_id, text, parse_mode="HTML", reply_markup=None):
        self.edits.append({"id": message_id, "text": text})

    async def edit_reply_markup(self, message_id, reply_markup):
        self.edits.append({"id": message_id, "markup": reply_markup})

    async def answer_callback_query(self, callback_id, text=None):
        self.callback_answers.append((callback_id, text))

    async def get_updates(self, offset, timeout=25):
        if offset == -1:
            return []
        try:
            first = await asyncio.wait_for(self._updates.get(), timeout=0.05)
        except asyncio.TimeoutError:
            return []
        out = [first]
        while not self._updates.empty():
            out.append(self._updates.get_nowait())
        return out

    # helpers
    def push(self, update: dict) -> None:
        update = {"update_id": self._next_update, **update}
        self._next_update += 1
        self._updates.put_nowait(update)

    def tap(self, data: str, user_id: int = USER_ID, cb_id: str = "cb") -> None:
        self.push({"callback_query": {"id": cb_id, "from": {"id": user_id}, "data": data,
                                      "message": {"message_id": 1, "chat": {"id": USER_ID}}}})

    def type(self, text: str, user_id: int = USER_ID, reply_to: int | None = None) -> None:
        msg = {"message_id": 999, "from": {"id": user_id}, "chat": {"id": user_id}, "text": text,
               "date": 4102444800}
        if reply_to is not None:
            msg["reply_to_message"] = {"message_id": reply_to}
        self.push({"message": msg})

    def buttons(self, sent_index: int = -1) -> list[str]:
        markup = self.sent[sent_index]["markup"] or {}
        return [b["callback_data"] for row in markup.get("inline_keyboard", []) for b in row]


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path]] = []

    async def __call__(self, command, cwd, timeout_s, shell):
        self.calls.append((command, cwd))
        return RunResult(exit_code=0, output=f"ran: {command}")


@pytest.fixture
def fake_tg():
    return FakeTelegram()


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "proj"
    (ws / "sub").mkdir(parents=True)
    return ws


@pytest.fixture
def make_bridge(workspace, fake_tg):
    def _make(**settings_kw):
        settings_kw.setdefault("log_path", workspace / ".vscode-copilot-telegram" / "audit.jsonl")
        settings = Settings(workspace_root=workspace, **settings_kw)
        broker = Broker(fake_tg, USER_ID, state_dir=settings.state_dir, poll_timeout=0)
        runner = FakeRunner()
        bridge = Bridge(settings, broker, runner=runner)
        return bridge, runner
    return _make


async def wait_for(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")
