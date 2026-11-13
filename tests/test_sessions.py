import json
import shutil
import time
from pathlib import Path

import pytest
from conftest import FIXTURES

from vscode_copilot_telegram.sessions import (file_uri_to_path, find_workspace_storage, load_session, replay_oplog,
                                    session_files, turns_for_file)
from vscode_copilot_telegram.telegram import split_message
from vscode_copilot_telegram.watcher import Watcher, WatchState, format_messages


def test_legacy_json_session():
    turns = turns_for_file(FIXTURES / "session_v3.json")
    assert [(t.key, t.role) for t in turns] == [
        ("request_1:u", "user"), ("request_1:a", "assistant"),
        ("request_2:u", "user"), ("request_2:a", "assistant"),
        ("request_3:u", "user"), ("request_3:a", "assistant")]
    reply = turns[1].text
    assert reply.startswith("Sure. I'll create `login.tsx` and wire it up.")
    assert "🔧 $ npm test" in reply
    assert reply.count("✏️ edited login.tsx") == 1  # consecutive edits to one file collapse
    assert "private reasoning" not in reply
    assert "Done." in reply
    assert turns[0].text == "Add a login page"
    assert turns[2].text == "Now add tests" and turns[3].text == "Old builds stored plain strings."
    # last request has no result yet -> still streaming
    assert turns[1].complete and turns[3].complete and not turns[5].complete


def test_jsonl_oplog_replay():
    s = load_session(FIXTURES / "session_log.jsonl")
    assert s["customTitle"] == "Build fix"
    assert [r["requestId"] for r in s["requests"]] == ["r1", "r2"]  # r3 deleted, r4 half-written line skipped
    turns = turns_for_file(FIXTURES / "session_log.jsonl")
    texts = [(t.role, t.text, t.complete) for t in turns]
    assert texts == [
        ("user", "Fix the build", True),
        ("assistant", "Looking at the error now.", True),
        ("user", "Thanks", True),
        ("assistant", "You're welcome!", True),  # splice with "i": 0 replaced the draft
    ]


def test_oplog_ignores_ops_before_snapshot_and_bad_paths():
    lines = ['{"kind":1,"k":["x"],"v":1}', '{"kind":0,"v":{"requests":[]}}', '{"kind":3,"k":["requests",9]}',
             '{"kind":1,"k":["a","b"],"v":2}', "not json"]
    assert replay_oplog(lines) == {"requests": [], "a": {"b": 2}}


def test_json_file_containing_oplog(tmp_path):
    f = tmp_path / "s.json"
    shutil.copy(FIXTURES / "session_log.jsonl", f)
    assert load_session(f)["customTitle"] == "Build fix"


def test_transcript_events(tmp_path):
    d = tmp_path / "GitHub.copilot-chat" / "transcripts"
    d.mkdir(parents=True)
    shutil.copy(FIXTURES / "transcript.jsonl", d / "t1.jsonl")
    turns = turns_for_file(d / "t1.jsonl")
    assert [(t.role, t.text) for t in turns] == [
        ("user", "Run the linter"), ("assistant", "Running ruff now."), ("tool", "🔧 $ ruff check ."),
        ("assistant", "All clean.")]


@pytest.mark.parametrize("uri,expected", [
    ("file:///home/me/proj", "/home/me/proj"),
    ("file:///c%3A/Users/me/My%20Proj", "c:/Users/me/My Proj"),
    ("file:///Users/me/proj", "/Users/me/proj"),
    ("file://server/share/proj", "//server/share/proj"),
    ("https://x", None),
])
def test_file_uri(uri, expected):
    assert file_uri_to_path(uri) == expected


def _make_storage(tmp_path: Path, project: Path, files: dict[str, Path]) -> Path:
    user = tmp_path / "Code" / "User"
    other = user / "workspaceStorage" / "aaaa"
    other.mkdir(parents=True)
    (other / "workspace.json").write_text(json.dumps({"folder": "file:///somewhere/else"}))
    h = user / "workspaceStorage" / "bbbb"
    (h / "chatSessions").mkdir(parents=True)
    (h / "workspace.json").write_text(json.dumps({"folder": project.resolve().as_uri()}))
    for name, src in files.items():
        shutil.copy(src, h / "chatSessions" / name)
    return user


def test_find_storage_and_jsonl_wins(tmp_path):
    project = tmp_path / "my proj"
    project.mkdir()
    user = _make_storage(tmp_path, project, {"s1.json": FIXTURES / "session_v3.json",
                                             "s2.json": FIXTURES / "session_v3.json",
                                             "s2.jsonl": FIXTURES / "session_log.jsonl"})
    dirs = find_workspace_storage(project, roots=[user])
    assert [d.name for d in dirs] == ["bbbb"]
    assert [f.name for f in session_files(dirs[0])] == ["s1.json", "s2.jsonl"]


def test_split_message():
    parts = split_message("x" * 9000, prefix="[p] 🤖 Copilot:\n")
    assert len(parts) == 3 and all(len(p) <= 4096 for p in parts)
    assert parts[0].startswith("[p] 🤖 Copilot: (1/3)\n")
    assert "".join(p.split("\n", 1)[1] for p in parts) == "x" * 9000
    assert split_message("hi", prefix="[p] ") == ["[p] hi"]


def test_format_messages_groups_and_masks():
    from vscode_copilot_telegram.sessions import Turn
    msgs = format_messages("proj", [Turn("1", "user", "hello"), Turn("2", "assistant", "key ghp_" + "c" * 36),
                                    Turn("3", "tool", "🔧 $ ls")], title="T")
    assert msgs[0] == "[proj · T] 🧑 You:\nhello"
    assert msgs[1].startswith("[proj · T] 🤖 Copilot:\n") and "🔧 $ ls" in msgs[1] and "ghp_cccc" not in msgs[1]


class Clock:
    """Fake clock. offset < 0: the watcher "started" before files written now; > 0: after."""

    def __init__(self, offset=-5.0):
        self.t = time.time() + offset

    def __call__(self):
        return self.t


def test_watcher_new_session_dedupe_restart_and_settle(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    user = _make_storage(tmp_path, project, {})
    storage = user / "workspaceStorage" / "bbbb"
    clock = Clock()
    out: list[str] = []
    state_path = tmp_path / "state.json"
    w = Watcher(project, out.append, WatchState(state_path), storage_dirs=[storage], settle_s=5, clock=clock)
    assert w.poll_once() == 0

    # a new session appears after the watcher started
    f = storage / "chatSessions" / "new.json"
    shutil.copy(FIXTURES / "session_v3.json", f)
    assert w.poll_once() == 5  # 3 prompts + 2 finished replies grouped per role run
    assert out[0] == "[proj · Add login page] 🧑 You:\nAdd a login page"
    assert not any("Working on it" in m for m in out)  # still streaming
    out.clear()

    # unchanged file, reply unchanged but settle time not reached
    assert w.poll_once() == 0
    clock.t += 6
    assert w.poll_once() == 1 and "Working on it" in out[-1]
    out.clear()

    # restart with the same state file: nothing is resent
    w2 = Watcher(project, out.append, WatchState(state_path), storage_dirs=[storage], clock=clock)
    assert w2.poll_once() == 0
    # new request appended -> only it is sent
    data = json.loads(f.read_text())
    data["requests"].append({"requestId": "request_4", "message": {"text": "ship it"},
                             "response": [{"value": "Shipped."}], "result": {}})
    f.write_text(json.dumps(data))
    assert w2.poll_once() == 2
    assert out == ["[proj · Add login page] 🧑 You:\nship it", "[proj · Add login page] 🤖 Copilot:\nShipped."]


def test_watcher_existing_history_not_flooded_and_backfill(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    user = _make_storage(tmp_path, project, {"old.jsonl": FIXTURES / "session_log.jsonl"})
    storage = user / "workspaceStorage" / "bbbb"
    out: list[str] = []
    w = Watcher(project, out.append, WatchState(None), storage_dirs=[storage], clock=Clock(+10))
    assert w.poll_once() == 0 and out == []
    w = Watcher(project, out.append, WatchState(None), storage_dirs=[storage], backfill=2, clock=Clock(+10))
    w.poll_once()
    # baseline happens first; the next poll (same mtime) sends nothing either, backfill applies on change
    f = storage / "chatSessions" / "old.jsonl"
    f.write_text(f.read_text() + "\n")
    assert w.poll_once() == 2
    assert out[0].endswith("Thanks") and out[1].endswith("You're welcome!")


def test_watcher_send_failure_retries(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    user = _make_storage(tmp_path, project, {})
    storage = user / "workspaceStorage" / "bbbb"
    calls = {"n": 0}
    sent: list[str] = []

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("telegram down")
        sent.append(text)

    w = Watcher(project, flaky, WatchState(None), storage_dirs=[storage], clock=Clock())
    shutil.copy(FIXTURES / "session_log.jsonl", storage / "chatSessions" / "s.jsonl")
    with pytest.raises(RuntimeError):
        w.poll_once()
    assert w.poll_once() == 4 and sent[0].endswith("Fix the build")
