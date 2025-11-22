"""Temporal activities bundled for AgentsFlow workflows."""

from __future__ import annotations

from typing import Any

from .agents import (
    ACPRequest,
    ACPResponse,
    AgentActivities,
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
    close_session,
)
from .git import (
    FinalizeGitRequest,
    FinalizeGitResult,
    GitActivities,
    GitWorktreeRequest,
    GitWorktreeResult,
    create_git_worktree,
    finalize_git_changes,
)
from .issues import IssueActivities, IssueDetails, IssueRequest, read_issue

__all__ = [
    "AgentsFlowActivities",
    "ACPRequest",
    "ACPResponse",
    "GitWorktreeRequest",
    "GitWorktreeResult",
    "FinalizeGitRequest",
    "FinalizeGitResult",
    "create_git_worktree",
    "finalize_git_changes",
    "IssueDetails",
    "IssueRequest",
    "ImplementationOutput",
    "EvaluationOutput",
    "TestPlanOutput",
    "ReviewOutput",
    "ReleasePlanOutput",
    "ClarificationOutput",
    "read_issue",
    "close_acp_session",
]


async def close_acp_session(session_id: str) -> None:
    await close_session(session_id)


class AgentsFlowActivities:
    """Collection of Temporal activity entry points used by the SDLC flow."""

    def __init__(self, *, auto_approve: bool = True) -> None:
        self.git = GitActivities()
        self.issues = IssueActivities()
        self.agents = AgentActivities(auto_approve=auto_approve)

        # Backwards-compatible attribute exposure
        self.create_git_worktree = self.git.create_git_worktree
        self.finalize_git_changes = self.git.finalize_git_changes
        self.read_issue = self.issues.read_issue
        self.run_acp_agent = self.agents.run_acp_agent
        self.close_acp_session = self.agents.close_acp_session
        self.run_implementation_agent = self.agents.run_implementation_agent
        self.run_evaluation_agent = self.agents.run_evaluation_agent
        self.run_tests_agent = self.agents.run_tests_agent
        self.run_review_agent = self.agents.run_review_agent
        self.run_clarification_agent = self.agents.run_clarification_agent
        self.run_release_agent = self.agents.run_release_agent

    def activities(self) -> list[Any]:
        return self.git.activities() + self.issues.activities() + self.agents.activities()
