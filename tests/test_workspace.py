import os

import pytest

from vscode_copilot_telegram.workspace import CwdError, resolve_cwd


def test_default_and_relative(workspace):
    assert resolve_cwd(workspace, None) == workspace.resolve()
    assert resolve_cwd(workspace, ".") == workspace.resolve()
    assert resolve_cwd(workspace, "sub") == (workspace / "sub").resolve()
    assert resolve_cwd(workspace, str(workspace / "sub")) == (workspace / "sub").resolve()


@pytest.mark.parametrize("bad", ["..", "../", "sub/../..", "/", "/tmp"])
def test_outside_rejected(workspace, bad):
    with pytest.raises(CwdError):
        resolve_cwd(workspace, bad)


def test_sibling_with_common_prefix_rejected(workspace):
    sibling = workspace.parent / (workspace.name + "-evil")
    sibling.mkdir()
    with pytest.raises(CwdError):
        resolve_cwd(workspace, str(sibling))


def test_missing_dir_rejected(workspace):
    with pytest.raises(CwdError):
        resolve_cwd(workspace, "nope")


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape_rejected(workspace, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside)
    with pytest.raises(CwdError):
        resolve_cwd(workspace, "link")
