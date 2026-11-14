"""Configuration: environment variables plus an optional vscode-copilot-telegram.toml."""

from __future__ import annotations

import hashlib
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


def default_audit_path(workspace_root: Path) -> Path:
    """The audit log lives outside the project: Copilot's file edits can only reach the workspace."""
    digest = hashlib.sha256(str(workspace_root).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".vscode-copilot-telegram" / f"audit-{workspace_root.name or 'workspace'}-{digest}.jsonl"


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
    # Other things to tell the user at start-up (the server logs them).
    startup_warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).expanduser().resolve()
        if not self.project_name:
            self.project_name = self.workspace_root.name or str(self.workspace_root)
        if self.log_path is None:
            self.log_path = default_audit_path(self.workspace_root)
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


def _legacy_log_path_warning(cfg: Path, s: Settings, value: object) -> str:
    """A leftover log_path (the first version's example file had one) is ignored, not an error: ignoring it
    doesn't weaken the gate. Say where the log is now, and name an older log file if one is still there."""
    candidates = [s.workspace_root / ".vscode-copilot-telegram" / "audit.jsonl"]
    if isinstance(value, str) and value:
        p = Path(value).expanduser()
        candidates.append(p if p.is_absolute() else s.workspace_root / p)
    old: list[Path] = []
    for p in candidates:
        try:
            if p != s.log_path and p not in old and p.is_file():
                old.append(p)
        except OSError:
            pass
    msg = (f"{cfg} sets log_path, which is no longer read, because Copilot can edit that file. The audit log is "
           f"now {s.log_path}. To choose another place, set LOG_PATH in the server's environment.")
    if old:
        msg += f" An older audit log is still at {', '.join(str(p) for p in old)}; move or delete it."
    return msg


def _load_raw_settings(workspace_root: Path) -> Settings:
    """Read the project TOML and the environment. Does not check whether the allow list was accepted."""
    data: dict = {}
    legacy_log_path: object = None
    cfg = Path(workspace_root) / CONFIG_FILENAME
    if cfg.is_file():
        with cfg.open("rb") as fh:
            data = tomllib.load(fh)
        if "token" in data or "bot_token" in data:
            raise ConfigError(f"{cfg}: do not put the bot token in the config file; use TELEGRAM_BOT_TOKEN")
        legacy_log_path = data.pop("log_path", None)
    known = {"timeout_s", "run_timeout_s", "max_output_chars", "telegram_output_chars", "allow",
             "block", "use_default_block", "shell", "project_name"}
    unknown = set(data) - known
    if unknown:
        raise ConfigError(f"{cfg}: unknown keys {sorted(unknown)}")
    if os.environ.get("LOG_PATH"):
        data["log_path"] = Path(os.environ["LOG_PATH"])
    s = Settings(workspace_root=workspace_root, **data)
    if legacy_log_path is not None:
        s.startup_warnings.append(_legacy_log_path_warning(cfg, s, legacy_log_path))
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


def accepted_policy_inside_workspace(workspace_root: Path) -> bool:
    """True if the accepted copy sits where Copilot's file edits can reach it (for example, your home folder
    was opened as the workspace). Then acceptance can't be trusted."""
    try:
        return accepted_policy_path().resolve().is_relative_to(Path(workspace_root).resolve())
    except (OSError, RuntimeError):
        return True  # can't tell: fail closed


# Commands people don't expect an allow list to approve. Used only to warn you when you accept.
RISKY_SAMPLES = (
    "rm -rf build", "git push origin main", "git reset --hard", "git checkout -- .", "git config core.pager sh",
    "git diff --output=/tmp/out.txt", "npm install some-package", "pip install some-package",
    "python -c 'print(1)'", "python script.py", "node script.js", "bash script.sh", "curl https://example.com",
    "docker run alpine", "cat ~/.ssh/id_rsa", "ls ../..", "pytest ../other-project",
)
# Made-up commands. A pattern that approves one of these approves (nearly) every command.
_ANYTHING_SAMPLES = ("zq-no-such-command", "zq-no-such-command 12345 --flag value")


def approves_anything(pattern: str) -> bool:
    rx = re.compile(pattern, re.IGNORECASE)
    return any(rx.fullmatch(c) for c in _ANYTHING_SAMPLES)


def risky_samples_approved(pattern: str) -> list[str]:
    rx = re.compile(pattern, re.IGNORECASE)
    return [c for c in RISKY_SAMPLES if rx.fullmatch(c)]


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
    if not policy_needs_acceptance(s):
        return s
    inside = accepted_policy_inside_workspace(s.workspace_root)
    if not inside and is_policy_accepted(s.workspace_root, s.allow, s.use_default_block):
        return s
    what = " and ".join(x for x in (f"an allow list with {len(s.allow)} pattern(s)" if s.allow else "",
                                     "use_default_block = false" if not s.use_default_block else "") if x)
    if inside:
        why = (f"the accepted copy ({accepted_policy_path()}) is inside this workspace, where Copilot's file "
               "edits could change it. Open a project folder, not your home folder")
    else:
        why = ("you have not accepted it. Read the file, then run in your own terminal: "
               f"vscode-copilot-telegram --accept-policy --workspace {s.workspace_root}")
    s.policy_warning = (f"{CONFIG_FILENAME} sets {what}, which is ignored: {why}. Until then every command asks "
                        "in Telegram and the built-in block list stays on.")
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
        broad = [p for p in s.allow if approves_anything(p)]
        risky = {p: risky_samples_approved(p) for p in s.allow}
    except (ConfigError, ValueError, re.error) as exc:
        print(f"vscode-copilot-telegram: {exc}", file=sys.stderr)
        return 1
    if not policy_needs_acceptance(s):
        print(f"Nothing to accept for {root}: no allow list, and the built-in block list is on.")
        return 0
    if accepted_policy_inside_workspace(root):
        print(f"vscode-copilot-telegram: {accepted_policy_path()} is inside {root}, where Copilot's file edits "
              "could change it. Open a project folder, not your home folder.", file=sys.stderr)
        return 1
    if broad:
        print("vscode-copilot-telegram: these patterns approve (almost) every command, so they are refused:",
              file=sys.stderr)
        for pattern in broad:
            print(f"  {pattern}", file=sys.stderr)
        print("Write patterns for the exact commands you trust, for example 'git status'.", file=sys.stderr)
        return 1
    print(f"Workspace: {root}\nFile:      {root / CONFIG_FILENAME}\n")
    if s.allow:
        print("These commands will run WITHOUT asking you (each pattern must match the whole command; "
              "commands with ; && || | ` $( > < or a newline still ask):")
        for pattern in s.allow:
            print(f"  {pattern}")
            if risky[pattern]:
                print(f"    WARNING: also approves, for example: {', '.join(risky[pattern][:4])}")
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
