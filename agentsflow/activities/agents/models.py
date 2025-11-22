"""Shared data models for SDLC-related agent activities."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field


class JiraTaskPayload(BaseModel):
    """Minimal payload describing an issue fetched from Jira, GitHub, etc."""

    issue_key: str
    summary: str
    description: str
    comments: Sequence[str] = Field(default_factory=list)


class ImplementationOutput(BaseModel):
    """Structured assessment distilled from the coding agent's transcript."""

    summary: str = Field(..., description="Two to three sentence summary of the implementation approach.")
    key_steps: list[str] = Field(
        default_factory=list,
        description="Ordered list of actionable steps to complete the implementation.",
    )
    files_to_change: list[str] = Field(
        default_factory=list,
        description="Repository-relative file paths that will likely require edits.",
    )
    testing_considerations: list[str] = Field(
        default_factory=list,
        description="Tests to create or update to validate the change.",
    )


class EvaluationOutput(BaseModel):
    """Boolean verdict on whether the task and automated tests are implemented."""

    task_implemented: bool = Field(
        ...,
        description="True if the transcript indicates the implementation is complete.",
    )
    automated_tests_implemented: bool = Field(
        ...,
        description="True if the transcript reports automated tests were added or executed with tooling.",
    )
    reasoning: str = Field(..., description="Short justification for the verdicts.")


class TestPlanOutput(BaseModel):
    """Follow-up plan ensuring tests exist."""

    __test__ = False  # prevent pytest from collecting this Pydantic model as a test class

    summary: str = Field(..., description="High-level explanation of the testing approach.")
    test_cases: list[str] = Field(default_factory=list, description="Specific tests to add or adjust.")
    tooling_notes: list[str] = Field(default_factory=list, description="Commands or frameworks required.")


class ReviewOutput(BaseModel):
    """Peer review style feedback on the proposed implementation."""

    approval: bool = Field(..., description="False if any blocking issues exist.")
    issues: list[str] = Field(default_factory=list, description="Blocking or high-risk findings.")
    recommendations: list[str] = Field(default_factory=list, description="Improvements that are nice to have.")
    praise: list[str] = Field(default_factory=list, description="Positive observations worth keeping.")


class ReleasePlanOutput(BaseModel):
    """Plan for landing the work in source control."""

    branch_name: str = Field(..., description="Suggested git branch name using lowercase kebab-case.")
    commit_message: str = Field(..., description="Single-sentence conventional commit style message.")
    pr_title: str = Field(..., description="Concise pull request title.")
    pr_body: str = Field(..., description="Paragraph summarising the changes and tests.")
    follow_up_tasks: list[str] = Field(default_factory=list, description="Any TODOs that should follow the PR.")


class ClarificationOutput(BaseModel):
    """Signals whether the workflow must pause for missing requirements."""

    clarification_required: bool = Field(..., description="True when outstanding questions block further automation.")
    open_questions: list[str] = Field(
        default_factory=list,
        description="Actionable questions that must be answered before continuing.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Important assumptions or decisions that should be confirmed.",
    )


__all__ = [
    "JiraTaskPayload",
    "ImplementationOutput",
    "EvaluationOutput",
    "TestPlanOutput",
    "ReviewOutput",
    "ReleasePlanOutput",
    "ClarificationOutput",
]
