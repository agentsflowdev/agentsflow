"""Temporal activity helpers for finalising git worktrees."""

from __future__ import annotations

import asyncio
from pathlib import Path

import git
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from temporalio import activity
from agentsflow.utils.filesystem import safe_remove_tree
from .models import FinalizeGitRequest, FinalizeGitResult


def _cleanup_worktree(worktree_path: Path) -> None:
    """Remove a git worktree from the filesystem and repo metadata."""

    if not worktree_path.exists():
        return

    git_removed = False
    try:
        repo = git.Repo(worktree_path)
    except (InvalidGitRepositoryError, NoSuchPathError):
        safe_remove_tree(
            worktree_path,
            reason="invalid worktree repository",
            logger=activity.logger,
        )
        return

    try:
        common_dir = Path(repo.git.rev_parse("--git-common-dir")).resolve()
        repo_root = common_dir.parent
        if not repo_root.exists():
            raise FileNotFoundError(f"Common git dir parent missing: {repo_root}")
        git_cmd = git.Git(str(repo_root))
        git_cmd.worktree("remove", "--force", str(worktree_path))
        git_removed = True
        activity.logger.info(
            "Removed git worktree via git",
            extra={"worktree_path": str(worktree_path)},
        )
    except Exception as exc:  # noqa: BLE001 - log and fallback to safe delete
        detail = str(exc)
        activity.logger.warning(
            "Failed to remove git worktree via git",
            extra={"worktree_path": str(worktree_path), "detail": detail},
        )
    finally:
        if not git_removed:
            safe_remove_tree(
                worktree_path,
                reason="git metadata cleanup failed",
                logger=activity.logger,
            )


def _finalize_git_changes(request: FinalizeGitRequest) -> FinalizeGitResult:
    worktree_path = Path(request.worktree_path).expanduser().resolve()
    branch_name = request.branch_name.strip()
    if not branch_name:
        raise ValueError("branch_name is required to finalise git changes.")
    if not request.commit_message.strip():
        raise ValueError("commit_message must not be empty when committing changes.")

    try:
        repo = git.Repo(worktree_path)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise ValueError(f"{worktree_path} is not a valid git worktree path.") from exc

    activity.logger.debug(
        "Finalising git worktree",
        extra={
            "worktree_path": str(worktree_path),
            "branch_name": branch_name,
            "push": request.push,
            "remote": request.remote,
        },
    )

    try:
        repo.git.checkout("-B", branch_name)
        has_changes = repo.is_dirty(index=True, working_tree=True, untracked_files=True)
        if has_changes:
            repo.git.add(all=True)
            repo.index.commit(request.commit_message)
        else:
            activity.logger.debug(
                "No changes detected in worktree; skipping commit",
                extra={"worktree_path": str(worktree_path), "branch_name": branch_name},
            )

        commit_sha = repo.head.commit.hexsha
        pushed = False

        if request.push:
            try:
                remote = repo.remotes[request.remote]
            except IndexError as exc:
                raise RuntimeError(
                    f"Remote '{request.remote}' not found while attempting to push branch '{branch_name}'."
                ) from exc
            push_result = remote.push(refspec=f"{branch_name}:{branch_name}")
            for info in push_result:
                if info.flags & info.ERROR:
                    raise RuntimeError(
                        f"Failed to push branch '{branch_name}' to '{request.remote}': {info.summary}"
                    )
            pushed = True

        activity.logger.info(
            "Finalised git worktree",
            extra={
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "pushed": pushed,
            },
        )
        _cleanup_worktree(worktree_path)
        return FinalizeGitResult(
            branch_name=branch_name, commit_sha=commit_sha, pushed=pushed
        )
    except GitCommandError as exc:
        detail = exc.stderr or exc.stdout or str(exc)
        activity.logger.exception(
            "Git command failed during finalisation",
            extra={
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
                "detail": detail.strip(),
            },
        )
        raise RuntimeError(
            f"Git command failed while finalising worktree: {detail.strip()}"
        ) from exc


async def finalize_git_changes(request: FinalizeGitRequest) -> FinalizeGitResult:
    return await asyncio.to_thread(_finalize_git_changes, request)


__all__ = ["FinalizeGitRequest", "FinalizeGitResult", "finalize_git_changes"]
