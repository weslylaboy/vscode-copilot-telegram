"""Keep commands inside the workspace folder."""

from __future__ import annotations

from pathlib import Path


class CwdError(ValueError):
    pass


def resolve_cwd(workspace_root: Path, cwd: str | None) -> Path:
    """Resolve ``cwd`` (absolute or relative to the root) and require it to be inside the root.

    Symlinks are resolved first, so a link pointing outside the workspace is rejected.
    """
    root = Path(workspace_root).expanduser().resolve()
    if cwd is None or str(cwd).strip() in ("", "."):
        target = root
    else:
        p = Path(str(cwd).strip()).expanduser()
        target = (p if p.is_absolute() else root / p).resolve()
    if target != root and not target.is_relative_to(root):
        raise CwdError(f"cwd {target} is outside the workspace {root}")
    if not target.is_dir():
        raise CwdError(f"cwd {target} does not exist or is not a directory")
    return target
