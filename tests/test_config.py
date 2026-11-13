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
    assert config.load_settings(project).log_path == project / ".vscode-copilot-telegram" / "audit.jsonl"
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
