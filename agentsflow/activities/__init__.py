"""Temporal activities bundled for the automation workflows."""

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
    draft_release_plan,
    parse_coding_transcript,
    parse_review_transcript,
    run_acp_implementation,
    run_acp_review,
    run_acp_tests,
    run_clarification_agent,
    summarize_implementation,
    summarize_tests,
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
    "run_acp_implementation",
    "run_acp_tests",
    "run_acp_review",
    "parse_coding_transcript",
    "parse_review_transcript",
    "summarize_implementation",
    "summarize_tests",
    "run_clarification_agent",
    "draft_release_plan",
]


async def close_acp_session(session_id: str) -> None:
    await close_session(session_id)


class AgentsFlowActivities:
    """Collection of Temporal activity entry points used by the process flow."""

    def __init__(self, *, auto_approve: bool = True) -> None:
        self.git = GitActivities()
        self.issues = IssueActivities()
        self.agents = AgentActivities(auto_approve=auto_approve)

        # Attribute exposure for worker registration
        self.create_git_worktree = self.git.create_git_worktree
        self.finalize_git_changes = self.git.finalize_git_changes
        self.read_issue = self.issues.read_issue
        self.run_acp_implementation = self.agents.run_acp_implementation
        self.run_acp_tests = self.agents.run_acp_tests
        self.run_acp_review = self.agents.run_acp_review
        self.close_acp_session = self.agents.close_acp_session
        self.summarize_implementation = self.agents.summarize_implementation
        self.parse_coding_transcript = self.agents.parse_coding_transcript
        self.summarize_tests = self.agents.summarize_tests
        self.parse_review_transcript = self.agents.parse_review_transcript
        self.run_clarification_agent = self.agents.run_clarification_agent
        self.draft_release_plan = self.agents.draft_release_plan

    def activities(self) -> list[Any]:
        return self.git.activities() + self.issues.activities() + self.agents.activities()
