import asyncio
import json
import logging

from conftest import USER_ID, FakeTelegram, wait_for

from vscode_copilot_telegram.broker import Broker
from vscode_copilot_telegram.config import Settings
from vscode_copilot_telegram.bridge import Bridge
from vscode_copilot_telegram.telegram import TelegramError


async def _start_command(bridge, cmd="make build", **kw):
    return asyncio.create_task(bridge.run_command(cmd, "build it", **kw))


async def test_approve_runs_once_and_second_tap_is_ignored(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    approve, deny, note = fake_tg.buttons()
    assert approve.endswith("|a") and deny.endswith("|d") and note.endswith("|n")
    assert "make build" in fake_tg.sent[0]["text"] and "build it" in fake_tg.sent[0]["text"]
    assert "[proj]" in fake_tg.sent[0]["text"]
    fake_tg.tap(approve, cb_id="first")
    fake_tg.tap(approve, cb_id="second")
    fake_tg.tap(deny, cb_id="third")
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "approved" and result["exit_code"] == 0
    assert result["output"] == "ran: make build"
    # stale taps that arrive after the first one get "Already answered"
    await asyncio.sleep(0.05)
    bridge.broker._ensure_poller()  # poller stops when idle; drain remaining taps
    await bridge.broker.handle_update({"callback_query": {"id": "late", "from": {"id": USER_ID},
                                                         "data": approve}})
    assert len(runner.calls) == 1
    assert ("late", "Already answered.") in fake_tg.callback_answers
    assert any("exit code 0" in e.get("text", "") for e in fake_tg.edits)


async def test_answered_ids_survive_restart(make_bridge, fake_tg, workspace):
    bridge, runner = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    approve = fake_tg.buttons()[0]
    fake_tg.tap(approve)
    await asyncio.wait_for(task, 2)
    # new broker, same state dir: tapping the old button does nothing
    tg2 = FakeTelegram()
    broker2 = Broker(tg2, USER_ID, state_dir=workspace / ".vscode-copilot-telegram", poll_timeout=0)
    await broker2.handle_update({"callback_query": {"id": "x", "from": {"id": USER_ID}, "data": approve}})
    assert tg2.callback_answers == [("x", "Already answered.")]
    assert len(runner.calls) == 1


async def test_deny(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    fake_tg.tap(fake_tg.buttons()[1])
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "denied" and result["exit_code"] is None
    assert runner.calls == []


async def test_failed_button_answer_is_logged_and_the_decision_still_counts(make_bridge, fake_tg, monkeypatch,
                                                                            caplog):
    async def fail(callback_id, text=None):
        raise TelegramError("network down")

    monkeypatch.setattr(fake_tg, "answer_callback_query", fail)
    bridge, runner = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    with caplog.at_level(logging.WARNING, logger="vscode_copilot_telegram.broker"):
        fake_tg.tap(fake_tg.buttons()[1])
        result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "denied" and runner.calls == []
    assert "could not answer the button tap: network down" in caplog.text


async def test_deny_with_note(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    fake_tg.tap(fake_tg.buttons()[2])
    await wait_for(lambda: len(fake_tg.sent) == 2)  # the "reply with your note" prompt
    prompt_id = fake_tg.sent[1]["id"]
    fake_tg.type("use make test instead", reply_to=prompt_id)
    result = await asyncio.wait_for(task, 2)
    assert result["decision"] == "denied"
    assert result["note"] == "use make test instead"
    assert "use make test instead" in result["output"]
    assert runner.calls == []


async def test_timeout_fails_closed(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    result = await bridge.run_command("make build", "x", timeout_s=1)
    assert result["decision"] == "denied-timeout"
    assert runner.calls == []
    # a tap after the timeout does nothing
    approve = fake_tg.buttons(0)[0]
    await bridge.broker.handle_update({"callback_query": {"id": "late", "from": {"id": USER_ID}, "data": approve}})
    assert runner.calls == []
    assert fake_tg.callback_answers[-1][1] == "Already answered."
    assert any("Timed out" in e.get("text", "") for e in fake_tg.edits)


async def test_telegram_error_fails_closed(workspace):
    tg = FakeTelegram(fail_send=True)
    from conftest import FakeRunner
    runner = FakeRunner()
    bridge = Bridge(Settings(workspace_root=workspace), Broker(tg, USER_ID, poll_timeout=0), runner=runner)
    result = await bridge.run_command("make build", "x")
    assert result["decision"] == "denied-error"
    assert runner.calls == []
    assert (await bridge.ask_user("q?")).startswith("error:")


async def test_unauthorized_user_ignored(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    task = await _start_command(bridge, timeout_s=1)
    await wait_for(lambda: fake_tg.sent)
    fake_tg.tap(fake_tg.buttons()[0], user_id=666)
    fake_tg.type("yes", user_id=666)
    result = await asyncio.wait_for(task, 3)
    assert result["decision"] == "denied-timeout"
    assert runner.calls == []
    assert fake_tg.callback_answers == []


async def test_several_pending_at_once(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    t1 = await _start_command(bridge, "make one")
    t2 = await _start_command(bridge, "make two")
    await wait_for(lambda: len(fake_tg.sent) == 2)
    b1 = fake_tg.buttons(0)
    b2 = fake_tg.buttons(1)
    assert b1[0] != b2[0]
    fake_tg.tap(b2[1])  # deny the second
    fake_tg.tap(b1[0])  # approve the first
    r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), 2)
    assert r1["decision"] == "approved" and r2["decision"] == "denied"
    assert [c[0] for c in runner.calls] == ["make one"]


async def test_blocked_never_asks(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    result = await bridge.run_command("git push --force", "ship it")
    assert result["decision"] == "blocked"
    assert runner.calls == []
    assert fake_tg.sent and fake_tg.sent[0]["markup"] is None


async def test_allow_list_auto_approves_with_notice(make_bridge, fake_tg):
    bridge, runner = make_bridge(allow=[r"npm test"])
    result = await bridge.run_command("npm test", "check")
    assert result["decision"] == "auto-approved"
    assert len(runner.calls) == 1
    assert "Auto-approved" in fake_tg.sent[0]["text"] and fake_tg.sent[0]["markup"] is None


async def test_cwd_outside_workspace_rejected(make_bridge, fake_tg):
    bridge, runner = make_bridge()
    result = await bridge.run_command("ls", "look", cwd="..")
    assert result["decision"] == "rejected"
    assert runner.calls == [] and fake_tg.sent == []
    ok = asyncio.create_task(bridge.run_command("ls", "look", cwd="sub"))
    await wait_for(lambda: fake_tg.sent)
    fake_tg.tap(fake_tg.buttons()[0])
    result = await asyncio.wait_for(ok, 2)
    assert result["cwd"] == "sub" and runner.calls[0][1].name == "sub"


async def test_secrets_masked_in_telegram(make_bridge, fake_tg):
    bridge, _ = make_bridge()
    task = asyncio.create_task(bridge.run_command("API_KEY=abc123 node x.js", "use ghp_" + "a" * 36, timeout_s=1))
    await wait_for(lambda: fake_tg.sent)
    text = fake_tg.sent[0]["text"]
    assert "abc123" not in text and "ghp_aaaa" not in text
    await task


async def test_audit_log(make_bridge, fake_tg, workspace):
    bridge, _ = make_bridge()
    task = await _start_command(bridge)
    await wait_for(lambda: fake_tg.sent)
    fake_tg.tap(fake_tg.buttons()[0])
    await asyncio.wait_for(task, 2)
    await bridge.run_command("rm -rf /", "oops")
    lines = [json.loads(x) for x in (workspace / ".vscode-copilot-telegram" / "audit.jsonl").read_text().splitlines()]
    assert [r["decision"] for r in lines] == ["approved", "blocked"]
    for r in lines:
        assert {"ts", "request_id", "type", "command", "decision", "exit_code"} <= set(r)
    assert lines[0]["exit_code"] == 0 and lines[0]["type"] == "run_command"


async def test_ask_user_option_and_text(make_bridge, fake_tg):
    bridge, _ = make_bridge()
    task = asyncio.create_task(bridge.ask_user("Which DB?", ["Postgres", "SQLite"]))
    await wait_for(lambda: fake_tg.sent)
    assert [b.split("|")[2] for b in fake_tg.buttons()] == ["o0", "o1"]
    fake_tg.tap(fake_tg.buttons()[1])
    assert await asyncio.wait_for(task, 2) == "SQLite"

    task = asyncio.create_task(bridge.ask_user("Name?", ["a", "b"]))
    await wait_for(lambda: len(fake_tg.sent) == 2)
    fake_tg.type("call it bridge")
    assert await asyncio.wait_for(task, 2) == "call it bridge"


async def test_ask_user_timeout(make_bridge):
    bridge, _ = make_bridge()
    assert await bridge.ask_user("anyone?", timeout_s=1) == "timeout"


async def test_typed_reply_routed_by_reply_to_when_ambiguous(make_bridge, fake_tg):
    bridge, _ = make_bridge()
    t1 = asyncio.create_task(bridge.ask_user("first?"))
    t2 = asyncio.create_task(bridge.ask_user("second?"))
    await wait_for(lambda: len(fake_tg.sent) == 2)
    fake_tg.type("ambiguous")
    await wait_for(lambda: any("Several requests" in m["text"] for m in fake_tg.sent))
    fake_tg.type("two", reply_to=fake_tg.sent[1]["id"])
    fake_tg.type("one", reply_to=fake_tg.sent[0]["id"])
    assert await asyncio.wait_for(asyncio.gather(t1, t2), 2) == ["one", "two"]


async def test_notify(make_bridge, fake_tg):
    bridge, _ = make_bridge()
    assert await bridge.notify("Tests passing, token ghp_" + "b" * 36) == "sent"
    assert "Tests passing" in fake_tg.sent[0]["text"] and "ghp_bbbb" not in fake_tg.sent[0]["text"]
    assert fake_tg.sent[0]["markup"] is None
