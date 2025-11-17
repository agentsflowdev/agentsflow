"""Temporal activity for creating Git worktrees.

The implementation closely mirrors our reference `GitWorktreeComponent` so we
can reuse the same behaviour within Temporal workflows.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile

import git
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from temporalio import activity

from .models import GitWorktreeRequest, GitWorktreeResult


def _is_local_path(path_or_url: str) -> bool:
    path = Path(path_or_url).expanduser()
    return path.exists()


def _create_git_worktree(request: GitWorktreeRequest) -> GitWorktreeResult:
    repository_input = (request.repository or "").strip()
    reference = (request.reference or "HEAD").strip() or "HEAD"

    if not repository_input:
        raise ValueError("repository is required")

    clone_dir: Path | None = None
    worktree_dir: Path | None = None
    success = False

    try:
        if _is_local_path(repository_input):
            repo_path = Path(repository_input).expanduser().resolve()
            repo = git.Repo(repo_path)
            cloned_from_remote = False
        else:
            clone_dir = Path(tempfile.mkdtemp(prefix="temporal-worktree-repo-"))
            repo = git.Repo.clone_from(repository_input, clone_dir)
            repo_path = clone_dir
            cloned_from_remote = True

        worktree_dir = Path(tempfile.mkdtemp(prefix="temporal-worktree-"))

        worktree_args: list[str] = ["add", "--detach", str(worktree_dir)]
        if reference:
            worktree_args.append(reference)

        repo.git.worktree(*worktree_args)

        success = True
        return GitWorktreeResult(
            worktree_path=str(worktree_dir),
            repository_path=str(repo_path),
            reference=reference,
            cloned_from_remote=cloned_from_remote,
        )
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise ValueError("The provided path is not a valid git repository.") from exc
    except GitCommandError as exc:
        detail = exc.stderr or exc.stdout or str(exc)
        raise RuntimeError(f"Git error while creating worktree: {detail.strip()}") from exc
    except Exception:
        # Let unexpected exceptions bubble up after cleanup.
        raise
    finally:
        if not success:
            if worktree_dir is not None and worktree_dir.exists():
                shutil.rmtree(worktree_dir, ignore_errors=True)
            if clone_dir is not None and clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)


async def create_git_worktree(request: GitWorktreeRequest) -> GitWorktreeResult:
    """Implementation function callable from an activity wrapper."""

    reference = request.reference or "HEAD"
    activity.logger.debug(
        "Creating git worktree",
        extra={"repository": request.repository, "reference": reference},
    )

    try:
        result = await asyncio.to_thread(_create_git_worktree, request)
    except Exception:
        activity.logger.exception(
            "Failed to create git worktree", extra={"repository": request.repository, "reference": reference}
        )
        raise

    activity.logger.info(
        "Created git worktree",
        extra={
            "repository": result.repository_path,
            "worktree": result.worktree_path,
            "reference": result.reference,
            "cloned_from_remote": result.cloned_from_remote,
        },
    )
    return result
