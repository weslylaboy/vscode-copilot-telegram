"""VS Code first, Telegram after vscode_wait_s: the race between the two, with fakes for both."""

import asyncio

import pytest
from conftest import USER_ID, wait_for

from vscode_copilot_telegram.bridge import Bridge, LocalAnswer
from vscode_copilot_telegram.broker import Answer
from vscode_copilot_telegram.telegram import TelegramError


class FakeLocal:
    """A VS Code prompt that waits until the test releases it. Records whether it was cancelled."""

    def __init__(self, result: LocalAnswer | None = None, release_now: bool = False,
                 raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list = []
        self.cancelled = False
        self.release = asyncio.Event()
        if release_now:
            self.release.set()

    async def __call__(self, question):
        self.calls.append(question)
        if self.raises:
            raise self.raises
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.result


async def _run(bridge, local, **kw):
    return asyncio.create_task(bridge.run_command("make build", "build it", local_prompt=local, **kw))


async def test_answer_in_vscode_never_contacts_telegram(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=5)
    local = FakeLocal(LocalAnswer("approve"), release_now=True)
    result = await asyncio.wait_for(await _run(bridge, local), 2)
    assert result["decision"] == "approved" and len(runner.calls) == 1
    assert fake_tg.sent == []
    assert "make build" in local.calls[0].message and "build it" in local.calls[0].message
    assert local.calls[0].kind == "approval"


async def test_no_answer_in_time_asks_on_telegram_and_telegram_wins(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))  # never released: nobody answers in VS Code
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent)
    assert "No answer in VS Code" in fake_tg.sent[0]["text"]
    assert not task.done()
    fake_tg.tap(fake_tg.buttons()[0])
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "approved" and len(runner.calls) == 1
    assert local.cancelled  # the VS Code form is closed once Telegram has answered
    assert any("No answer in VS Code" in e.get("text", "") for e in fake_tg.edits)


async def test_vscode_answers_after_telegram_was_sent(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent)
    approve = fake_tg.buttons()[0]
    local.release.set()
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "approved" and len(runner.calls) == 1
    assert any("Approved in VS Code" in e.get("text", "") for e in fake_tg.edits)
    # the Telegram button is dead now: tapping it later runs nothing
    await bridge.broker.handle_update({"callback_query": {"id": "late", "from": {"id": USER_ID}, "data": approve}})
    assert ("late", "Already answered.") in fake_tg.callback_answers
    assert len(runner.calls) == 1


async def test_vscode_deny_with_note(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=5)
    local = FakeLocal(LocalAnswer("deny", "use make test"), release_now=True)
    result = await asyncio.wait_for(await _run(bridge, local), 2)
    assert result["decision"] == "denied" and result["note"] == "use make test"
    assert runner.calls == [] and fake_tg.sent == []


async def test_vscode_that_cannot_ask_goes_straight_to_telegram(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=30)
    local = FakeLocal(None, release_now=True)  # returns None at once, like a client without forms
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent, timeout=1)  # far sooner than 30 s
    assert "No answer in VS Code" not in fake_tg.sent[0]["text"]
    fake_tg.tap(fake_tg.buttons()[1])
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "denied" and runner.calls == []


async def test_a_prompt_that_crashes_falls_back_to_telegram(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=30)
    local = FakeLocal(raises=RuntimeError("boom"))
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent, timeout=1)
    fake_tg.tap(fake_tg.buttons()[0])
    assert (await asyncio.wait_for(task, 2))["decision"] == "approved"


async def test_zero_wait_means_telegram_only(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0)
    local = FakeLocal(LocalAnswer("approve"), release_now=True)
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent)
    assert local.calls == []
    fake_tg.tap(fake_tg.buttons()[0])
    assert (await asyncio.wait_for(task, 2))["decision"] == "approved"


async def test_form_dismissed_after_telegram_sent_keeps_waiting_for_telegram(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(None)  # the user closes the form later, without answering
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent)
    local.release.set()
    await asyncio.sleep(0.1)
    assert not task.done()
    fake_tg.tap(fake_tg.buttons()[0])
    assert (await asyncio.wait_for(task, 2))["decision"] == "approved"


async def test_nobody_answers_is_denied_and_the_form_is_closed(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))
    result = await asyncio.wait_for(await _run(bridge, local, timeout_s=1), 4)
    assert result["decision"] == "denied-timeout" and runner.calls == []
    assert local.cancelled


async def test_telegram_down_and_nobody_answers_in_vscode_is_denied(make_bridge, fake_tg):
    fake_tg.fail_send = True
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))
    result = await asyncio.wait_for(await _run(bridge, local, timeout_s=1), 4)
    assert result["decision"] == "denied-error" and runner.calls == []
    assert local.cancelled


async def test_telegram_down_but_vscode_answers_later(make_bridge, fake_tg):
    fake_tg.fail_send = True
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))
    task = await _run(bridge, local, timeout_s=5)
    await asyncio.sleep(0.4)
    assert not task.done()
    local.release.set()
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "approved" and len(runner.calls) == 1


async def test_cancelling_the_tool_call_closes_the_form_and_the_telegram_request(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("approve"))
    task = await _run(bridge, local)
    await wait_for(lambda: fake_tg.sent)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert local.cancelled and bridge.broker.pending_ids == []
    assert runner.calls == []


async def test_a_denial_beats_an_approval_at_the_same_moment():
    assert Bridge._safer(Answer("approve"), Answer("deny")).action == "deny"
    assert Bridge._safer(Answer("approve"), Answer("note", "x")).action == "note"
    assert Bridge._safer(Answer("deny"), Answer("approve")).action == "deny"


async def test_auto_approved_commands_do_not_ask_in_vscode(make_bridge, fake_tg):
    bridge, runner = make_bridge(vscode_wait_s=5, allow=["make build"])
    local = FakeLocal(LocalAnswer("approve"), release_now=True)
    result = await asyncio.wait_for(await _run(bridge, local), 2)
    assert result["decision"] == "auto-approved" and local.calls == []


# ---- ask_user ----

async def test_question_answered_in_vscode(make_bridge, fake_tg):
    bridge, _ = make_bridge(vscode_wait_s=5)
    local = FakeLocal(LocalAnswer("option", "SQLite"), release_now=True)
    answer = await asyncio.wait_for(
        bridge.ask_user("Which database?", ["Postgres", "SQLite"], local_prompt=local), 2)
    assert answer == "SQLite" and fake_tg.sent == []
    assert local.calls[0].kind == "question" and local.calls[0].options == ["Postgres", "SQLite"]


async def test_question_goes_to_telegram_when_vscode_does_not_answer(make_bridge, fake_tg):
    bridge, _ = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("text", "ignored"))
    task = asyncio.create_task(bridge.ask_user("Which database?", None, local_prompt=local))
    await wait_for(lambda: fake_tg.sent)
    assert "No answer in VS Code" in fake_tg.sent[0]["text"]
    fake_tg.type("SQLite")
    assert await asyncio.wait_for(task, 2) == "SQLite"
    assert local.cancelled
    assert any("Answer:" in e.get("text", "") for e in fake_tg.edits)


async def test_question_with_telegram_down_and_no_vscode_answer_reports_an_error(make_bridge, fake_tg):
    fake_tg.fail_send = True
    bridge, _ = make_bridge(vscode_wait_s=0.1)
    local = FakeLocal(LocalAnswer("text", "x"))
    answer = await asyncio.wait_for(bridge.ask_user("Which?", None, 1, local_prompt=local), 4)
    assert answer.startswith("error:") and local.cancelled
