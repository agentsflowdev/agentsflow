"""Git-related Temporal activities."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from .finalize import finalize_git_changes as _finalize_git_changes
from .models import (
    FinalizeGitRequest,
    FinalizeGitResult,
    GitWorktreeRequest,
    GitWorktreeResult,
)
from .worktree import create_git_worktree as _create_git_worktree


class GitActivities:
    """Bundle of git-oriented activities (worktree + finalize)."""

    @activity.defn(name="create_git_worktree")
    async def create_git_worktree(self, request: GitWorktreeRequest) -> GitWorktreeResult:
        activity.logger.info(
            "Starting create_git_worktree activity",
            extra={"repository": request.repository, "reference": request.reference},
        )
        result = await _create_git_worktree(request)
        activity.logger.info(
            "Completed create_git_worktree activity",
            extra={
                "repository": result.repository_path,
                "worktree": result.worktree_path,
                "reference": result.reference,
            },
        )
        return result

    @activity.defn(name="finalize_git_changes")
    async def finalize_git_changes(self, request: FinalizeGitRequest) -> FinalizeGitResult:
        activity.logger.info(
            "Starting finalize_git_changes activity",
            extra={
                "worktree_path": request.worktree_path,
                "branch_name": request.branch_name,
                "push": request.push,
            },
        )
        result = await _finalize_git_changes(request)
        activity.logger.info(
            "Completed finalize_git_changes activity",
            extra={
                "branch_name": result.branch_name,
                "commit_sha": result.commit_sha,
                "pushed": result.pushed,
            },
        )
        return result

    def activities(self) -> list[Any]:
        return [
            self.create_git_worktree,
            self.finalize_git_changes,
        ]


__all__ = [
    "GitActivities",
    "FinalizeGitRequest",
    "FinalizeGitResult",
    "GitWorktreeRequest",
    "GitWorktreeResult",
    "create_git_worktree",
    "finalize_git_changes",
]


# Re-export the implementation helpers for direct unit tests.
create_git_worktree = _create_git_worktree
finalize_git_changes = _finalize_git_changes
