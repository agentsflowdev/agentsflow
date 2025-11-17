"""Git-related Temporal activities."""

from temporalio import activity

from .finalize import finalize_git_changes as _finalize_git_changes
from .models import FinalizeGitRequest, FinalizeGitResult, GitWorktreeRequest, GitWorktreeResult
from .worktree import create_git_worktree as _create_git_worktree


class GitActivities:
    """Bundle of git-oriented activities (worktree + finalize)."""

    @activity.defn(name="create_git_worktree")
    async def create_git_worktree(self, request: GitWorktreeRequest) -> GitWorktreeResult:
        return await _create_git_worktree(request)

    @activity.defn(name="finalize_git_changes")
    async def finalize_git_changes(self, request: FinalizeGitRequest) -> FinalizeGitResult:
        return await _finalize_git_changes(request)

    def activities(self) -> list:
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
