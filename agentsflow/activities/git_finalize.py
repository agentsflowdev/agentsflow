"""Temporal activity helpers for finalising git worktrees."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import git
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from temporalio import activity


@dataclass
class FinalizeGitRequest:
    """Parameters describing how to commit worktree changes."""

    worktree_path: str
    branch_name: str
    commit_message: str
    push: bool = False
    remote: str = "origin"


@dataclass
class FinalizeGitResult:
    """Result of finalising the worktree."""

    branch_name: str
    commit_sha: str
    pushed: bool


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
                    raise RuntimeError(f"Failed to push branch '{branch_name}' to '{request.remote}': {info.summary}")
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
        return FinalizeGitResult(branch_name=branch_name, commit_sha=commit_sha, pushed=pushed)
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
        raise RuntimeError(f"Git command failed while finalising worktree: {detail.strip()}") from exc


async def finalize_git_changes(request: FinalizeGitRequest) -> FinalizeGitResult:
    return await asyncio.to_thread(_finalize_git_changes, request)


__all__ = ["FinalizeGitRequest", "FinalizeGitResult", "finalize_git_changes"]
