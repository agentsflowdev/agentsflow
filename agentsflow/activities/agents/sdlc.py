"""Activities that invoke Pydantic AI agents for the SDLC workflow."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import (
    EvaluationOutput,
    ImplementationOutput,
    JiraTaskPayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)

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


_SETTINGS = AgentSettings()


def _ensure_openai_key() -> None:
    if _SETTINGS.openai_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = _SETTINGS.openai_api_key
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set; please configure an API key before starting the workflow worker."
        )


def _model_name(override: str | None = None) -> str:
    return override or os.getenv(MODEL_ENV_VAR) or DEFAULT_MODEL_NAME


def _build_agent(*, name: str, instructions: str, output_type: type) -> Agent[None, Any]:
    _ensure_openai_key()
    model = OpenAIChatModel(_model_name())
    return Agent(
        model=model,
        instructions=instructions,
        name=name,
        output_type=output_type,
    )


@cache
def _implementation_agent() -> Agent[None, ImplementationOutput]:
    return _build_agent(
        name="sdlc-implementation-verification",
        instructions=(
            "You are reviewing the transcript produced by an autonomous coding agent (Claude Code ACP). "
            "Use the issue context and the coding agent's latest response to summarise what work was reported. "
            "Treat actions as completed when the transcript clearly states they were performed, even if artefacts "
            "such as file diffs or command output are not shown. "
            "Populate ImplementationOutput with the described steps, touched files, and noted testing actions. "
            "If the transcript expresses uncertainty or mentions outstanding work, reflect that in "
            "testing_considerations instead of claiming completion. "
            "Only reference repository-relative paths that the transcript explicitly names."
        ),
        output_type=ImplementationOutput,
    )


@cache
def _evaluation_agent() -> Agent[None, EvaluationOutput]:
    return _build_agent(
        name="sdlc-evaluation",
        instructions=(
            "You evaluate coding transcripts for tracked issues. Review the issue details alongside the transcript "
            "and decide whether the implementation sounds complete and whether automated tests were carried out. "
            "Set task_implemented to True when the transcript confidently states the required work was finished "
            "and does not mention outstanding issues or TODOs. "
            "Set automated_tests_implemented to True only when the transcript indicates automated regression tests "
            "existed or were executed—look for mentions of specific test files, frameworks (e.g., pytest, unit test "
            "suites), or explicit automated commands. Manual spot checks, ad-hoc script runs, or unverifiable claims "
            "should leave automated_tests_implemented as False. "
            "When the transcript highlights missing work, failed verification, or uncertainty, mark the corresponding "
            "flag False and explain what appears incomplete."
        ),
        output_type=EvaluationOutput,
    )


@cache
def _tests_agent() -> Agent[None, TestPlanOutput]:
    return _build_agent(
        name="sdlc-tests",
        instructions=(
            "You design automated test coverage for the tracked issue. Focus on the uncovered gaps highlighted by "
            "the evaluation. "
            "Provide a short summary, enumerate concrete test cases, and list any tooling commands needed to "
            "execute them."
        ),
        output_type=TestPlanOutput,
    )


@cache
def _review_agent() -> Agent[None, ReviewOutput]:
    return _build_agent(
        name="sdlc-review",
        instructions=(
            "Perform a critical, evidence-based code review of the proposed implementation and automated tests. "
            "Document every finding with a severity. Blocking problems—missing or ambiguous error handling, "
            "absent documentation updates, missing or incomplete automated tests, type-safety regressions, "
            "unmet acceptance criteria, or any follow-up work beyond trivial formatting—must be promoted to issues. "
            "Only leave an item in recommendations if it is purely cosmetic (e.g., punctuation, whitespace). "
            "If you identify any issue or any recommendation that requires writing or modifying code, tests, "
            "or documentation, set approval to False. "
            "Flag approval as False whenever unresolved defects, missing automated tests, insufficient review "
            "evidence, or non-trivial follow-up work remain. "
            "If the transcript does not reference specific files, behaviours, or test results, treat the review as "
            "incomplete and record a blocking issue. "
            "Do not raise issues solely because changes are uncommitted or files appear untracked—the workflow "
            "performs the commit in a later step."
        ),
        output_type=ReviewOutput,
    )


@cache
def _release_agent() -> Agent[None, ReleasePlanOutput]:
    return _build_agent(
        name="sdlc-release",
        instructions=(
            "Draft the source control release plan for the task. Provide an actionable branch name, commit message, "
            "and pull request summary. "
            "Include follow-up items if reviewers flagged any. Do not include markdown formatting characters such "
            "as backticks."
        ),
        output_type=ReleasePlanOutput,
    )


async def run_implementation_agent(prompt: str) -> ImplementationOutput:
    return (await _implementation_agent().run(prompt)).data  # type: ignore[attr-defined,no-any-return]


async def run_evaluation_agent(prompt: str) -> EvaluationOutput:
    return (await _evaluation_agent().run(prompt)).data  # type: ignore[attr-defined,no-any-return]


async def run_tests_agent(prompt: str) -> TestPlanOutput:
    return (await _tests_agent().run(prompt)).data  # type: ignore[attr-defined,no-any-return]


async def run_review_agent(prompt: str) -> ReviewOutput:
    return (await _review_agent().run(prompt)).data  # type: ignore[attr-defined,no-any-return]


async def run_release_agent(prompt: str) -> ReleasePlanOutput:
    return (await _release_agent().run(prompt)).data  # type: ignore[attr-defined,no-any-return]


__all__ = [
    "DEFAULT_MODEL_NAME",
    "MODEL_ENV_VAR",
    "JiraTaskPayload",
    "ImplementationOutput",
    "EvaluationOutput",
    "TestPlanOutput",
    "ReviewOutput",
    "ReleasePlanOutput",
    "run_implementation_agent",
    "run_evaluation_agent",
    "run_tests_agent",
    "run_review_agent",
    "run_release_agent",
]
