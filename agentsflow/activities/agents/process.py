"""Activities that invoke Pydantic AI agents for the process workflow."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

from pydantic import Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import (
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    IssuePayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)

MODEL_ENV_VAR = "PROCESS_AGENT_MODEL"
DEFAULT_MODEL_NAME = "gpt-4.1-mini"


class AgentSettings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    model_config = SettingsConfigDict(
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
        name="process-implementation-verification",
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
        name="process-evaluation",
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
        name="process-tests",
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
        name="process-review",
        instructions=(
            "Perform a critical, evidence-based code review of the proposed implementation and automated tests. "
            "Document every finding with a severity. Blocking problems—missing or ambiguous error handling, "
            "absent documentation updates, missing or incomplete automated tests, type-safety regressions, "
            "unmet acceptance criteria, or any follow-up work beyond trivial formatting—must be promoted to issues. "
            "Only leave an item in recommendations if it is cosmetic or a best-practice hardening suggestion. "
            "Scope your review to behaviours and files explicitly mentioned in the transcript—do not invent new "
            "acceptance criteria or demand unrelated hardening (e.g., pinning third-party actions, extra infra "
            "checks) unless a clear defect is evident in the described changes. "
            "If you identify any issue that requires writing or modifying code, tests, or documentation, set "
            "approval to False. When only recommendations remain (no blocking issues), set approval to True and "
            "leave the issues list empty. "
            "Do not block on external setup assumptions (e.g., PyPI publisher configuration, repository secrets) "
            "unless the transcript shows a concrete failure caused by them—note such concerns as recommendations. "
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
        name="process-release",
        instructions=(
            "Draft the source control release plan for the task. Provide an actionable branch name, commit message, "
            "and pull request summary. "
            "Include follow-up items if reviewers flagged any. Do not include markdown formatting characters such "
            "as backticks."
        ),
        output_type=ReleasePlanOutput,
    )


@cache
def _clarification_agent() -> Agent[None, ClarificationOutput]:
    return _build_agent(
        name="process-clarification",
        instructions=(
            "You audit the issue description and recent comments before any coding begins. Identify whether the"
            " requirements are fully specified. Only set clarification_required to True when missing inputs,"
            " conflicting acceptance criteria, external approvals, or environment constraints would block progress."
            " Always return concrete, answerable open_questions (or an empty list when none exist) and list any"
            " assumptions that downstream agents should double-check. If everything looks clear, set"
            " clarification_required to False and leave open_questions empty."
        ),
        output_type=ClarificationOutput,
    )


async def summarize_implementation(prompt: str) -> ImplementationOutput:
    return (await _implementation_agent().run(prompt)).output


async def parse_coding_transcript(prompt: str) -> EvaluationOutput:
    return (await _evaluation_agent().run(prompt)).output


async def summarize_tests(prompt: str) -> TestPlanOutput:
    return (await _tests_agent().run(prompt)).output


async def parse_review_transcript(prompt: str) -> ReviewOutput:
    return (await _review_agent().run(prompt)).output


async def draft_release_plan(prompt: str) -> ReleasePlanOutput:
    return (await _release_agent().run(prompt)).output


async def run_clarification_agent(prompt: str) -> ClarificationOutput:
    return (await _clarification_agent().run(prompt)).output


__all__ = [
    "DEFAULT_MODEL_NAME",
    "MODEL_ENV_VAR",
    "IssuePayload",
    "ImplementationOutput",
    "EvaluationOutput",
    "TestPlanOutput",
    "ReviewOutput",
    "ReleasePlanOutput",
    "ClarificationOutput",
    "summarize_implementation",
    "parse_coding_transcript",
    "summarize_tests",
    "parse_review_transcript",
    "run_clarification_agent",
    "draft_release_plan",
]
