"""Temporal-ready Pydantic AI agents for the SDLC workflow."""

from __future__ import annotations

import os
from collections.abc import Sequence

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import TemporalAgent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL_ENV_VAR = "SDLC_AGENT_MODEL"
DEFAULT_MODEL_NAME = "gpt-4.1-mini"


class AgentSettings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


_AGENT_SETTINGS = AgentSettings()


def _ensure_openai_key() -> None:
    if _AGENT_SETTINGS.openai_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = _AGENT_SETTINGS.openai_api_key
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set; please configure an API key before starting the workflow worker."
        )


def _model_name(override: str | None = None) -> str:
    return override or os.getenv(MODEL_ENV_VAR) or DEFAULT_MODEL_NAME


def _make_agent(
    *,
    name: str,
    instructions: str,
    result_type: type[BaseModel],
    model_name: str | None = None,
) -> TemporalAgent:
    _ensure_openai_key()
    model = OpenAIChatModel(_model_name(model_name))
    return TemporalAgent(
        Agent(
            model=model,
            instructions=instructions,
            name=name,
            output_type=result_type,
        )
    )


class JiraTaskPayload(BaseModel):
    """Minimal payload describing a Jira issue."""

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


IMPLEMENTATION_AGENT = _make_agent(
    name="sdlc-implementation-verification",
    instructions=(
        "You are reviewing the transcript produced by an autonomous coding agent (Claude Code ACP). "
        "Use the Jira task context and the coding agent's latest response to summarise what work was reported. "
        "Treat actions as completed when the transcript clearly states they were performed, even if artefacts such as file diffs or command output are not shown. "
        "Populate ImplementationOutput with the described steps, touched files, and noted testing actions. "
        "If the transcript expresses uncertainty or mentions outstanding work, reflect that in testing_considerations instead of claiming completion. "
        "Only reference repository-relative paths that the transcript explicitly names."
    ),
    result_type=ImplementationOutput,
)


class EvaluationOutput(BaseModel):
    """Boolean verdict on whether the task and automated tests are implemented."""

    task_implemented: bool = Field(..., description="True if the transcript indicates the implementation is complete.")
    automated_tests_implemented: bool = Field(
        ...,
        description="True if the transcript reports automated tests were added or executed with tooling.",
    )
    reasoning: str = Field(..., description="Short justification for the verdicts.")


EVALUATION_AGENT = _make_agent(
    name="sdlc-evaluation",
    instructions=(
        "You evaluate coding transcripts for Jira tasks. Review the Jira details alongside the transcript and decide whether the implementation sounds complete and whether automated tests were carried out. "
        "Set task_implemented to True when the transcript confidently states the required work was finished and does not mention outstanding issues or TODOs. "
        "Set automated_tests_implemented to True only when the transcript indicates automated regression tests existed or were executed—look for mentions of specific test files, frameworks (e.g., pytest, unit test suites), or explicit automated commands. Manual spot checks, ad-hoc script runs, or unverifiable claims should leave automated_tests_implemented as False. "
        "When the transcript highlights missing work, failed verification, or uncertainty, mark the corresponding flag False and explain what appears incomplete."
    ),
    result_type=EvaluationOutput,
)


class TestPlanOutput(BaseModel):
    """Follow-up plan ensuring tests exist."""

    summary: str = Field(..., description="High-level explanation of the testing approach.")
    test_cases: list[str] = Field(default_factory=list, description="Specific tests to add or adjust.")
    tooling_notes: list[str] = Field(default_factory=list, description="Commands or frameworks required.")


TESTS_AGENT = _make_agent(
    name="sdlc-tests",
    instructions=(
        "You design automated test coverage for Jira tasks. Focus on the uncovered gaps highlighted by the "
        "evaluation. Provide a short summary, enumerate concrete test cases, and list any tooling commands needed "
        "to execute them."
    ),
    result_type=TestPlanOutput,
)


class ReviewOutput(BaseModel):
    """Peer review style feedback on the proposed implementation."""

    approval: bool = Field(..., description="False if any blocking issues exist.")
    issues: list[str] = Field(default_factory=list, description="Blocking or high-risk findings.")
    recommendations: list[str] = Field(default_factory=list, description="Improvements that are nice to have.")
    praise: list[str] = Field(default_factory=list, description="Positive observations worth keeping.")


REVIEW_AGENT = _make_agent(
    name="sdlc-review",
    instructions=(
        "Perform a critical, evidence-based code review of the proposed implementation and automated tests. "
        "Document every finding with a severity. Blocking problems—missing or ambiguous error handling, absent documentation updates, missing or incomplete automated tests, type-safety regressions, unmet acceptance criteria, or any follow-up work beyond trivial formatting—must be promoted to issues. "
        "Only leave an item in recommendations if it is purely cosmetic (e.g., punctuation, whitespace). If you identify any issue or any recommendation that requires writing or modifying code, tests, or documentation, set approval to False. "
        "Flag approval as False whenever unresolved defects, missing automated tests, insufficient review evidence, or non-trivial follow-up work remain. "
        "If the transcript does not reference specific files, behaviours, or test results, treat the review as incomplete and record a blocking issue. "
        "Do not raise issues solely because changes are uncommitted or files appear untracked—the workflow performs the commit in a later step."
    ),
    result_type=ReviewOutput,
)


class ReleasePlanOutput(BaseModel):
    """Plan for landing the work in source control."""

    branch_name: str = Field(..., description="Suggested git branch name using lowercase kebab-case.")
    commit_message: str = Field(..., description="Single-sentence conventional commit style message.")
    pr_title: str = Field(..., description="Concise pull request title.")
    pr_body: str = Field(..., description="Paragraph summarising the changes and tests.")
    follow_up_tasks: list[str] = Field(default_factory=list, description="Any TODOs that should follow the PR.")


RELEASE_AGENT = _make_agent(
    name="sdlc-release",
    instructions=(
        "Draft the source control release plan for the task. Provide an actionable branch name, commit message, and "
        "pull request summary. Include follow-up items if reviewers flagged any. "
        "Do not include markdown formatting characters such as backticks."
    ),
    result_type=ReleasePlanOutput,
)


__all__ = [
    "DEFAULT_MODEL_NAME",
    "EVALUATION_AGENT",
    "EvaluationOutput",
    "IMPLEMENTATION_AGENT",
    "ImplementationOutput",
    "JiraTaskPayload",
    "MODEL_ENV_VAR",
    "RELEASE_AGENT",
    "ReleasePlanOutput",
    "REVIEW_AGENT",
    "ReviewOutput",
    "TESTS_AGENT",
    "TestPlanOutput",
]
