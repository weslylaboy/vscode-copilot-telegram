import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from vscode_copilot_telegram import config
from vscode_copilot_telegram.policy import CommandPolicy, Verdict

OWN_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID", "VSCODE_COPILOT_TELEGRAM_API_BASE",
             "VSCODE_COPILOT_TELEGRAM_ENV_FILE", "LOG_PATH")


@pytest.fixture
def env(monkeypatch, tmp_path):
    """A private copy of the environment with an empty home folder, so nothing leaks between tests."""
    fake = {k: v for k, v in config.os.environ.items() if k not in OWN_NAMES}
    home = tmp_path / "home"
    (home / ".config" / "vscode-copilot-telegram").mkdir(parents=True)
    fake["HOME"] = fake["USERPROFILE"] = str(home)
    monkeypatch.setattr(config.os, "environ", fake)
    return fake


def _write(path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), "utf-8")


def test_project_env_cannot_change_who_approves_or_where_the_server_connects(env, tmp_path):
    project = tmp_path / "proj"
    _write(project / ".env", TELEGRAM_BOT_TOKEN="111:from-project", TELEGRAM_USER_ID="999",
           VSCODE_COPILOT_TELEGRAM_API_BASE="http://127.0.0.1:9", LOG_PATH="elsewhere.jsonl", OTHER="x")
    _write(tmp_path / "home" / ".config" / "vscode-copilot-telegram" / ".env",
           TELEGRAM_BOT_TOKEN="222:from-home", TELEGRAM_USER_ID="4242")

    config.load_env_files()

    creds = config.telegram_credentials()
    assert (creds.token, creds.user_id) == ("222:from-home", 4242)
    assert "VSCODE_COPILOT_TELEGRAM_API_BASE" not in env and "LOG_PATH" not in env and "OTHER" not in env
    assert config.load_settings(project).log_path == config.default_audit_path(project.resolve())
    # the caller can still tell the user which settings were left out (names only, never values)
    assert config.ignored_project_env_names(project) == [
        "LOG_PATH", "TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID", "VSCODE_COPILOT_TELEGRAM_API_BASE"]


def test_project_env_alone_gives_no_credentials(env, tmp_path):
    project = tmp_path / "proj"
    _write(project / ".env", TELEGRAM_BOT_TOKEN="111:from-project", TELEGRAM_USER_ID="999")

    config.load_env_files()

    with pytest.raises(config.ConfigError, match="TELEGRAM_BOT_TOKEN is not set"):
        config.telegram_credentials()


def test_env_file_outside_the_project_wins_over_the_home_file(env, tmp_path):
    _write(tmp_path / "home" / ".config" / "vscode-copilot-telegram" / ".env",
           TELEGRAM_BOT_TOKEN="222:from-home", TELEGRAM_USER_ID="4242")
    _write(tmp_path / "per-project.env", TELEGRAM_BOT_TOKEN="333:from-env-file")
    env["VSCODE_COPILOT_TELEGRAM_ENV_FILE"] = str(tmp_path / "per-project.env")

    config.load_env_files()

    creds = config.telegram_credentials()
    assert (creds.token, creds.user_id) == ("333:from-env-file", 4242)


# ---------- the allow list must be accepted by you ----------

def _toml(project, text):
    project.mkdir(parents=True, exist_ok=True)
    (project / "vscode-copilot-telegram.toml").write_text(text, "utf-8")


def _verdict(s, command):
    return CommandPolicy(s.allow, s.block, s.use_default_block).evaluate(command).verdict


def test_allow_list_in_the_project_file_is_ignored_until_accepted(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['.*']\nuse_default_block = false\n")

    s = config.load_settings(project)

    assert s.allow == [] and s.use_default_block is True
    assert "--accept-policy" in s.policy_warning and "allow list" in s.policy_warning
    assert _verdict(s, "ls") is Verdict.ASK
    assert _verdict(s, "git push --force") is Verdict.BLOCK


def test_accepted_allow_list_works_until_the_file_changes(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['git status', 'ls']\n")
    s = config.load_settings(project)
    config.save_accepted_policy(s.workspace_root, ["ls", "git status"], True)  # order does not matter

    s = config.load_settings(project)
    assert s.policy_warning == "" and _verdict(s, "git status") is Verdict.ALLOW

    _toml(project, "allow = ['git status', 'ls', '.*']\n")  # Copilot adds a pattern
    s = config.load_settings(project)
    assert s.allow == [] and s.policy_warning
    assert _verdict(s, "git status") is Verdict.ASK


def test_acceptance_is_per_workspace(env, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for p in (a, b):
        _toml(p, "allow = ['ls']\n")
    config.save_accepted_policy(config.load_settings(a).workspace_root, ["ls"], True)

    assert config.load_settings(a).allow == ["ls"]
    assert config.load_settings(b).allow == []


def test_settings_that_do_not_loosen_the_gate_need_no_acceptance(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "block = ['terraform apply']\ntimeout_s = 30\n")

    s = config.load_settings(project)

    assert s.policy_warning == "" and s.block == ["terraform apply"] and s.timeout_s == 30


def test_vscode_wait_defaults_to_three_minutes_and_needs_no_acceptance(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "block = ['x']\n")
    assert config.load_settings(project).vscode_wait_s == 180

    _toml(project, "vscode_wait_s = 0\n")
    s = config.load_settings(project)
    assert s.vscode_wait_s == 0 and s.policy_warning == ""


@pytest.mark.parametrize("value", ["-1", "86401", "1.5", "'3 min'", "true"])
def test_vscode_wait_must_be_a_whole_number_of_seconds(env, tmp_path, value):
    project = tmp_path / "proj"
    _toml(project, f"vscode_wait_s = {value}\n")
    with pytest.raises(config.ConfigError, match="vscode_wait_s"):
        config.load_settings(project)


def test_unreadable_accepted_file_means_not_accepted(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['ls']\n")
    path = config.accepted_policy_path()
    path.write_text("{ not json", "utf-8")

    assert config.load_settings(project).allow == []


def test_accept_command_refuses_without_a_terminal(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['ls']\n")

    assert config.accept_policy(project, ask=lambda _: "accept", interactive=False) == 1
    assert config.load_settings(project).allow == []  # nothing was saved


def test_accept_command_needs_you_to_type_accept(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['ls']\n")

    assert config.accept_policy(project, ask=lambda _: "yes", interactive=True) == 1
    assert config.load_settings(project).allow == []

    def eof(_):
        raise EOFError

    assert config.accept_policy(project, ask=eof, interactive=True) == 1
    assert config.load_settings(project).allow == []

    assert config.accept_policy(project, ask=lambda _: " Accept ", interactive=True) == 0
    assert config.load_settings(project).allow == ["ls"]


def test_accept_command_rejects_a_bad_pattern(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['(']\n")

    assert config.accept_policy(project, ask=lambda _: "accept", interactive=True) == 1
    assert not config.accepted_policy_path().exists()


# ---------- the audit log lives outside the project ----------

def test_audit_log_default_is_outside_the_project(env, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()

    log_path = config.load_settings(project).log_path

    assert not log_path.is_relative_to(project.resolve())
    assert log_path.parent == tmp_path / "home" / ".vscode-copilot-telegram" and log_path.name.startswith("audit-proj-")


def test_log_path_in_the_project_file_is_ignored_with_a_warning(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "log_path = 'elsewhere.jsonl'\n")

    s = config.load_settings(project)

    assert s.log_path == config.default_audit_path(project.resolve())  # the setting has no effect
    assert len(s.startup_warnings) == 1
    assert "no longer read" in s.startup_warnings[0] and str(s.log_path) in s.startup_warnings[0]
    assert "older audit log" not in s.startup_warnings[0]  # nothing is left at the old place


def test_the_warning_names_an_older_audit_log_that_is_still_there(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "log_path = 'old/custom.jsonl'\n")
    for old in (project / ".vscode-copilot-telegram" / "audit.jsonl", project / "old" / "custom.jsonl"):
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text("{}\n", "utf-8")

    warning = config.load_settings(project).startup_warnings[0]

    assert "older audit log is still at" in warning
    assert str(project.resolve() / ".vscode-copilot-telegram" / "audit.jsonl") in warning
    assert str(project.resolve() / "old" / "custom.jsonl") in warning


def test_the_server_still_starts_and_logs_the_warning_for_a_leftover_log_path(env, tmp_path, caplog):
    from vscode_copilot_telegram import server

    project = tmp_path / "proj"
    _toml(project, 'log_path = ".vscode-copilot-telegram/audit.jsonl"\n')  # the first example file had this line
    env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_USER_ID"] = "111:fake", "4242"

    with caplog.at_level("WARNING", logger="vscode_copilot_telegram"):
        bridge = server.build_bridge(str(project))

    assert "no longer read" in caplog.text
    assert bridge.s.log_path == config.default_audit_path(project.resolve())
    assert bridge.s.policy_warning == ""  # not stopped, and nothing else changed


def test_log_path_can_still_be_set_in_the_environment(env, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    env["LOG_PATH"] = "logs/audit.jsonl"  # relative paths are relative to the workspace

    assert config.load_settings(project).log_path == project.resolve() / "logs" / "audit.jsonl"


# ---------- checks when you accept an allow list ----------

@pytest.mark.parametrize("pattern", [".*", r"\S+", r"[\w-]+( .*)?", r"\w+|.+"])
def test_accept_refuses_patterns_that_approve_every_command(env, tmp_path, capsys, pattern):
    project = tmp_path / "proj"
    _toml(project, f"allow = ['git status', '{pattern}']\n")

    assert config.accept_policy(project, ask=lambda _: "accept", interactive=True) == 1

    assert pattern in capsys.readouterr().err
    assert config.load_settings(project).allow == []  # nothing was saved


def test_accept_warns_when_a_pattern_also_approves_risky_commands(env, tmp_path, capsys):
    project = tmp_path / "proj"
    _toml(project, "allow = ['git (status|diff|log)( .*)?', 'npm (test|run lint)']\n")

    assert config.accept_policy(project, ask=lambda _: "accept", interactive=True) == 0

    lines = capsys.readouterr().out.splitlines()
    warnings = [x for x in lines if "WARNING: also approves" in x]
    assert len(warnings) == 1 and "git diff --output=/tmp/out.txt" in warnings[0]
    assert lines[lines.index("  git (status|diff|log)( .*)?") + 1] == warnings[0]  # right under its own pattern


def test_example_allow_list_is_narrow():
    example = Path(__file__).parent.parent / "examples" / "vscode-copilot-telegram.toml"
    allow = tomllib.loads(example.read_text("utf-8"))["allow"]

    assert allow
    for pattern in allow:
        assert not config.approves_anything(pattern), pattern
        assert config.risky_samples_approved(pattern) == [], pattern


def test_accepted_copy_inside_the_workspace_is_not_trusted(env, tmp_path, capsys):
    home = tmp_path / "home"  # your home folder was opened as the workspace
    _toml(home, "allow = ['git status']\n")
    config.save_accepted_policy(home.resolve(), ["git status"], True)

    s = config.load_settings(home)

    assert s.allow == [] and "inside this workspace" in s.policy_warning
    assert config.accept_policy(home, ask=lambda _: "accept", interactive=True) == 1
    assert "inside" in capsys.readouterr().err


# ---------- the accept command, run as a real program ----------

def test_accept_command_refuses_when_run_as_a_script(env, tmp_path):
    project = tmp_path / "proj"
    _toml(project, "allow = ['git status']\n")

    done = subprocess.run([sys.executable, "-m", "vscode_copilot_telegram", "--accept-policy", "--workspace",
                           str(project)], env=env, input="accept\n", capture_output=True, text=True, timeout=120)

    assert done.returncode == 1 and "must be run by you" in done.stderr
    assert not config.accepted_policy_path().exists()


@pytest.mark.skipif(sys.platform == "win32", reason="needs a pseudo-terminal")
def test_accept_command_in_a_real_terminal(env, tmp_path):
    import pty
    import select

    project = tmp_path / "proj"
    _toml(project, "allow = ['git status']\n")
    master, slave = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-m", "vscode_copilot_telegram", "--accept-policy", "--workspace",
                             str(project)], stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
    os.close(slave)
    out, typed = b"", False
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if select.select([master], [], [], 1)[0]:
                try:
                    chunk = os.read(master, 4096)
                except OSError:  # the program ended and closed its side
                    break
                if not chunk:
                    break
                out += chunk
                if not typed and b"Type 'accept'" in out:
                    os.write(master, b"accept\n")
                    typed = True
            elif proc.poll() is not None:
                break
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
        os.close(master)

    assert typed and proc.returncode == 0, out.decode(errors="replace")
    assert config.load_settings(project).allow == ["git status"]
