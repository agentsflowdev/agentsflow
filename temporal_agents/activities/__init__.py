"""Temporal activities bundled for AgentsFlow workflows."""

from __future__ import annotations

from dataclasses import replace

from temporalio import activity

from .claude_acp import (
    ClaudeACPRequest,
    ClaudeACPResponse,
    close_session as _close_claude_session,
    run_claude_code,
)
from .git_worktree import (
    GitWorktreeRequest,
    GitWorktreeResult,
    create_git_worktree as _create_git_worktree,
)
from .jira import JiraTaskDetails, JiraTaskRequest, fetch_jira_task as _fetch_jira_task

__all__ = [
    "AgentsFlowActivities",
    "ClaudeACPRequest",
    "ClaudeACPResponse",
    "GitWorktreeRequest",
    "GitWorktreeResult",
    "JiraTaskDetails",
    "JiraTaskRequest",
    "close_claude_session",
]


async def close_claude_session(session_id: str) -> None:
    await _close_claude_session(session_id)


class AgentsFlowActivities:
    """Collection of Temporal activity entry points used by the SDLC flow."""

    def __init__(self, *, claude_binary: str | None = None, auto_approve: bool = True) -> None:
        self._claude_binary = claude_binary
        self._auto_approve = auto_approve

    @activity.defn(name="create_git_worktree")
    async def create_git_worktree(self, request: GitWorktreeRequest) -> GitWorktreeResult:
        return await _create_git_worktree(request)

    @activity.defn(name="fetch_jira_task")
    async def fetch_jira_task(self, request: JiraTaskRequest) -> JiraTaskDetails:
        return await _fetch_jira_task(request)

    @activity.defn(name="claude_code_acp")
    async def run_claude_code(self, request: ClaudeACPRequest) -> ClaudeACPResponse:
        req = request
        if req.claude_binary is None and self._claude_binary is not None:
            req = replace(req, claude_binary=self._claude_binary)
        if req.auto_approve is None:
            req = replace(req, auto_approve=self._auto_approve)
        return await run_claude_code(req)

    @activity.defn(name="close_claude_session")
    async def close_claude_session(self, session_id: str) -> None:
        await _close_claude_session(session_id)
