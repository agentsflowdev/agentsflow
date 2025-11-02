from __future__ import annotations

import shutil
from pathlib import Path

import git
import pytest

from agentsflow.activities.git_worktree import GitWorktreeRequest, create_git_worktree


def _init_repo(repo_path: Path) -> git.Repo:
    repo = git.Repo.init(repo_path)
    readme = repo_path / "README.md"
    readme.write_text("hello worktree\n", encoding="utf-8")
    repo.index.add([str(readme)])
    repo.index.commit("initial commit")
    return repo


@pytest.mark.asyncio
async def test_create_worktree_from_local_repo(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = _init_repo(repo_dir)

    request = GitWorktreeRequest(repository=str(repo_dir))
    result = await create_git_worktree(request)

    worktree_path = Path(result.worktree_path)
    assert worktree_path.exists()

    worktree_repo = git.Repo(worktree_path)
    assert worktree_repo.head.commit.hexsha == repo.head.commit.hexsha

    shutil.rmtree(worktree_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_create_worktree_from_remote_repo(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    repo = _init_repo(source_dir)

    bare_dir = tmp_path / "bare.git"
    git.Repo.clone_from(str(source_dir), str(bare_dir), bare=True)

    request = GitWorktreeRequest(repository=bare_dir.as_uri())
    result = await create_git_worktree(request)

    worktree_path = Path(result.worktree_path)
    assert worktree_path.exists()

    worktree_repo = git.Repo(worktree_path)
    assert worktree_repo.head.commit.hexsha == repo.head.commit.hexsha

    repo_path = Path(result.repository_path)
    assert repo_path.exists()

    shutil.rmtree(worktree_path, ignore_errors=True)
    shutil.rmtree(repo_path, ignore_errors=True)
