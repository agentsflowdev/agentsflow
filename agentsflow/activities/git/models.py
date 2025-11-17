"""Shared dataclasses for git-related activities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GitWorktreeRequest:
    """Parameters required to create a git worktree."""

    repository: str
    reference: str | None = None


@dataclass
class GitWorktreeResult:
    """Returned information about the created worktree."""

    worktree_path: str
    repository_path: str
    reference: str
    cloned_from_remote: bool


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


__all__ = [
    "GitWorktreeRequest",
    "GitWorktreeResult",
    "FinalizeGitRequest",
    "FinalizeGitResult",
]
