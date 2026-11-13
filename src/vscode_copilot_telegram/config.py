"""Configuration: environment variables plus an optional vscode-copilot-telegram.toml."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from dotenv import dotenv_values, load_dotenv

CONFIG_FILENAME = "vscode-copilot-telegram.toml"
ACCEPTED_POLICY_FILENAME = "accepted-policy.json"
# Names in a project .env that would change how this tool works. That file is never loaded.
_OWN_ENV_PREFIXES = ("TELEGRAM_", "VSCODE_COPILOT_TELEGRAM_")
_OWN_ENV_NAMES = ("LOG_PATH",)


class ConfigError(RuntimeError):
    pass


@dataclass
class Settings:
    workspace_root: Path
    timeout_s: int = 600              # approval / answer timeout
    run_timeout_s: int = 900          # max runtime of an approved command
    max_output_chars: int = 8000      # output returned to Copilot
    telegram_output_chars: int = 1500  # output tail shown in Telegram
    allow: list[str] = field(default_factory=list)
    block: list[str] = field(default_factory=list)
    use_default_block: bool = True
    shell: str = "default"            # default | bash | powershell | pwsh | cmd
    # Leave unset for the default; __post_init__ always turns it into an absolute Path.
    log_path: Path = None  # type: ignore[assignment]
    project_name: str = ""
    # Set by load_settings when the project file asks for auto-approval that you have not accepted.
    policy_warning: str = ""

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).expanduser().resolve()
        if not self.project_name:
            self.project_name = self.workspace_root.name or str(self.workspace_root)
        if self.log_path is None:
            self.log_path = self.workspace_root / ".vscode-copilot-telegram" / "audit.jsonl"
        else:
            p = Path(self.log_path).expanduser()
            self.log_path = p if p.is_absolute() else self.workspace_root / p

    @property
    def state_dir(self) -> Path:
        return self.workspace_root / ".vscode-copilot-telegram"


@dataclass(frozen=True)
class TelegramCredentials:
    token: str
    user_id: int


def load_env_files() -> None:
    """Load .env files from outside the project, without overriding variables that are already set.

    Order: $VSCODE_COPILOT_TELEGRAM_ENV_FILE, ~/.config/vscode-copilot-telegram/.env

    <workspace>/.env is never loaded: anything that can write to the project (Copilot's
    file edits, a cloned repository) could use it to replace the Telegram credentials or
    the Bot API address, and so decide who approves commands.
    """
    candidates = []
    if os.environ.get("VSCODE_COPILOT_TELEGRAM_ENV_FILE"):
        candidates.append(Path(os.environ["VSCODE_COPILOT_TELEGRAM_ENV_FILE"]).expanduser())
    candidates.append(Path.home() / ".config" / "vscode-copilot-telegram" / ".env")
    for c in candidates:
        if c.is_file():
            load_dotenv(c, override=False)


def ignored_project_env_names(workspace_root: Path) -> list[str]:
    """Names of this tool's settings found in <workspace>/.env, so callers can say they were ignored."""
    path = Path(workspace_root) / ".env"
    if not path.is_file():
        return []
    try:
        names = list(dotenv_values(path))
    except (OSError, UnicodeDecodeError):
        return []
    return sorted(n for n in names if n.startswith(_OWN_ENV_PREFIXES) or n in _OWN_ENV_NAMES)


def telegram_credentials() -> TelegramCredentials:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    uid = os.environ.get("TELEGRAM_USER_ID", "").strip()
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is not set")
    if not uid:
        raise ConfigError("TELEGRAM_USER_ID is not set")
    try:
        user_id = int(uid)
    except ValueError as exc:
        raise ConfigError("TELEGRAM_USER_ID must be a number (get it from @userinfobot)") from exc
    return TelegramCredentials(token=token, user_id=user_id)


def resolve_workspace_root(cli_value: str | None = None) -> Path:
    raw = cli_value or os.environ.get("WORKSPACE_ROOT") or os.getcwd()
    return Path(raw).expanduser().resolve()


def _load_raw_settings(workspace_root: Path) -> Settings:
    """Read the project TOML and the environment. Does not check whether the allow list was accepted."""
    data: dict = {}
    cfg = Path(workspace_root) / CONFIG_FILENAME
    if cfg.is_file():
        with cfg.open("rb") as fh:
            data = tomllib.load(fh)
        if "token" in data or "bot_token" in data:
            raise ConfigError(f"{cfg}: do not put the bot token in the config file; use TELEGRAM_BOT_TOKEN")
    known = {"timeout_s", "run_timeout_s", "max_output_chars", "telegram_output_chars", "allow",
             "block", "use_default_block", "shell", "log_path", "project_name"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{cfg}: unknown keys {sorted(unknown)}")
    if "log_path" in data:
        data["log_path"] = Path(data["log_path"])
    if os.environ.get("LOG_PATH"):
        data["log_path"] = Path(os.environ["LOG_PATH"])
    s = Settings(workspace_root=workspace_root, **data)
    if s.shell not in {"default", "bash", "powershell", "pwsh", "cmd", "sh"}:
        raise ConfigError(f"shell must be one of default, sh, bash, powershell, pwsh, cmd (got {s.shell!r})")
    for name in ("timeout_s", "run_timeout_s", "max_output_chars"):
        if int(getattr(s, name)) <= 0:
            raise ConfigError(f"{name} must be positive")
    return s


# ---------- accepted policy ----------
# An allow list, or turning off the built-in block list, makes commands run without a tap. The
# project file can be written by Copilot or brought by a cloned repository, so those two settings
# only count after you accept them yourself with `vscode-copilot-telegram --accept-policy`. The
# accepted copy lives outside the project.

def accepted_policy_path() -> Path:
    return Path.home() / ".config" / "vscode-copilot-telegram" / ACCEPTED_POLICY_FILENAME


def _policy(allow: list[str], use_default_block: bool) -> dict:
    # Order has no effect (any match allows), so compare without it.
    return {"allow": sorted(set(allow)), "use_default_block": bool(use_default_block)}


def policy_needs_acceptance(s: Settings) -> bool:
    return bool(s.allow) or not s.use_default_block


def _read_accepted() -> dict:
    try:
        workspaces = json.loads(accepted_policy_path().read_text("utf-8")).get("workspaces")
    except (OSError, ValueError, AttributeError):
        return {}
    return workspaces if isinstance(workspaces, dict) else {}


def is_policy_accepted(workspace_root: Path, allow: list[str], use_default_block: bool) -> bool:
    return _read_accepted().get(str(workspace_root)) == _policy(allow, use_default_block)


def save_accepted_policy(workspace_root: Path, allow: list[str], use_default_block: bool) -> Path:
    path = accepted_policy_path()
    workspaces = _read_accepted()
    workspaces[str(workspace_root)] = _policy(allow, use_default_block)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "workspaces": workspaces}, indent=2), "utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass  # not supported on every file system
    tmp.replace(path)
    return path


def load_settings(workspace_root: Path) -> Settings:
    s = _load_raw_settings(workspace_root)
    if policy_needs_acceptance(s) and not is_policy_accepted(s.workspace_root, s.allow, s.use_default_block):
        what = " and ".join(x for x in (f"an allow list with {len(s.allow)} pattern(s)" if s.allow else "",
                                         "use_default_block = false" if not s.use_default_block else "") if x)
        s.policy_warning = (f"{CONFIG_FILENAME} sets {what}, but you have not accepted it, so it is ignored: "
                            "every command asks in Telegram and the built-in block list stays on. Read the "
                            "file, then run in your own terminal: "
                            f"vscode-copilot-telegram --accept-policy --workspace {s.workspace_root}")
        s.allow = []
        s.use_default_block = True
    return s


def accept_policy(workspace_root: Path, *, ask: Callable[[str], str] = input,
                  interactive: bool | None = None) -> int:
    """Show the allow list from the project file and, if you type "accept", remember it. Returns an exit code."""
    root = Path(workspace_root).expanduser().resolve()
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        print("vscode-copilot-telegram: --accept-policy must be run by you, typing it in a terminal. "
              "It does not run from scripts, pipes, or run_command.", file=sys.stderr)
        return 1
    try:
        s = _load_raw_settings(root)
        for pattern in s.allow:
            re.compile(pattern)
    except (ConfigError, ValueError, re.error) as exc:
        print(f"vscode-copilot-telegram: {exc}", file=sys.stderr)
        return 1
    if not policy_needs_acceptance(s):
        print(f"Nothing to accept for {root}: no allow list, and the built-in block list is on.")
        return 0
    print(f"Workspace: {root}\nFile:      {root / CONFIG_FILENAME}\n")
    if s.allow:
        print("These commands will run WITHOUT asking you (each pattern must match the whole command; "
              "commands with ; && || | ` $( > < or a newline still ask):")
        for pattern in s.allow:
            print(f"  {pattern}")
    if not s.use_default_block:
        print("The built-in block list (rm -rf /, force push, curl | sh, ...) will be OFF.")
    print("\nIf this file was written by Copilot, or came with a repository you cloned, read it before you accept.")
    try:
        answer = ask("Type 'accept' to trust this for this workspace: ")
    except EOFError:
        answer = ""
    if answer.strip().lower() != "accept":
        print("Not accepted. Nothing was saved.")
        return 1
    path = save_accepted_policy(s.workspace_root, s.allow, s.use_default_block)
    print(f"Saved to {path}.\nRestart the MCP server (MCP: List Servers -> Restart) for it to apply.")
    return 0
