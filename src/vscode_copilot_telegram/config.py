"""Configuration: environment variables plus an optional vscode-copilot-telegram.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

CONFIG_FILENAME = "vscode-copilot-telegram.toml"


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
    log_path: Path | None = None
    project_name: str = ""

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


def load_env_files(workspace_root: Path) -> None:
    """Load untracked .env files without overriding variables that are already set.

    Order: $VSCODE_COPILOT_TELEGRAM_ENV_FILE, <workspace>/.env, ~/.config/vscode-copilot-telegram/.env
    """
    candidates = []
    if os.environ.get("VSCODE_COPILOT_TELEGRAM_ENV_FILE"):
        candidates.append(Path(os.environ["VSCODE_COPILOT_TELEGRAM_ENV_FILE"]).expanduser())
    candidates.append(Path(workspace_root) / ".env")
    candidates.append(Path.home() / ".config" / "vscode-copilot-telegram" / ".env")
    for c in candidates:
        if c.is_file():
            load_dotenv(c, override=False)


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


def load_settings(workspace_root: Path) -> Settings:
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
