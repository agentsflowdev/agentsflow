from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import git
import pytest

from agentsflow.activities.git import (
    FinalizeGitRequest,
    GitWorktreeRequest,
    create_git_worktree,
    finalize_git_changes,
)
from agentsflow.utils.filesystem import WORKTREE_PREFIX, is_managed_temp_dir


def _init_repo(repo_path: Path) -> git.Repo:
    repo = git.Repo.init(repo_path)
    readme = repo_path / "README.md"
    readme.write_text("hello worktree\n", encoding="utf-8")
    repo.index.add([str(readme)])
    repo.index.commit("initial commit")
    return repo


@pytest.mark.asyncio
async def test_finalize_removes_worktree(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir)

    git_result = await create_git_worktree(GitWorktreeRequest(repository=str(repo_dir)))
    worktree_path = Path(git_result.worktree_path)
    readme = worktree_path / "README.md"
    readme.write_text("updated content\n", encoding="utf-8")

    request = FinalizeGitRequest(
        worktree_path=str(worktree_path),
        branch_name="feature/remove-worktree",
        commit_message="Update README",
    )
    result = await finalize_git_changes(request)

    assert result.branch_name == "feature/remove-worktree"
    base_repo = git.Repo(repo_dir)
    branch = base_repo.heads["feature/remove-worktree"]
    assert branch.commit.hexsha == result.commit_sha
    assert not worktree_path.exists()


def test_managed_worktree_guard() -> None:
    managed_dir = Path(tempfile.mkdtemp(prefix="temporal-worktree-"))
    try:
        assert is_managed_temp_dir(managed_dir, prefixes=(WORKTREE_PREFIX,))
    finally:
        shutil.rmtree(managed_dir, ignore_errors=True)

    unmanaged_dir = Path(tempfile.mkdtemp(prefix="agentsflow-unmanaged-"))
    try:
        assert not is_managed_temp_dir(unmanaged_dir, prefixes=(WORKTREE_PREFIX,))
    finally:
        shutil.rmtree(unmanaged_dir, ignore_errors=True)
