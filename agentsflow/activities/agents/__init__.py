"""LLM agent integrations used by the automation workflows."""

from dataclasses import replace
from typing import Any

from temporalio import activity

from .acp_agent import ACPRequest, ACPResponse, close_session
from .acp_agent import run_acp_agent as _run_acp_agent
from .models import (
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    IssuePayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)
from .process import (
    DEFAULT_MODEL_NAME,
    MODEL_ENV_VAR,
)
from .process import (
    draft_release_plan as _draft_release_plan,
)
from .process import parse_coding_transcript as _parse_coding_transcript
from .process import parse_review_transcript as _parse_review_transcript
from .process import (
    run_clarification_agent as _run_clarification_agent,
)
from .process import (
    summarize_implementation as _summarize_implementation,
)
from .process import (
    summarize_tests as _summarize_tests,
)


class AgentActivities:
    """Activities involving Claude ACP sessions and LLM planning agents."""

    def __init__(self, *, auto_approve: bool = True) -> None:
        self._auto_approve = auto_approve

    async def _run_acp_stage(self, request: ACPRequest, *, stage: str) -> ACPResponse:
        activity.logger.debug(
            "Preparing ACP activity call",
            extra={
                "stage": stage,
                "agent_type": request.agent_type,
                "session_id": request.session_id,
                "workspace_dir": request.workspace_dir,
                "prompt_chars": len(request.prompt),
                "auto_approve_default": self._auto_approve,
            },
        )
        req = request
        if req.auto_approve is None:
            req = replace(req, auto_approve=self._auto_approve)
        activity.logger.debug(
            "Dispatching ACP activity",
            extra={
                "stage": stage,
                "agent_type": req.agent_type,
                "session_id": req.session_id,
                "workspace_dir": req.workspace_dir,
                "agent_binary": req.agent_binary,
                "auto_approve": req.auto_approve,
                "prompt_chars": len(req.prompt),
            },
        )
        response = await _run_acp_agent(req)
        activity.logger.info(
            "ACP activity completed",
            extra={
                "stage": stage,
                "session_id": response.session_id,
                "prompt_chars": len(req.prompt),
                "message_chars": len(response.message or ""),
                "stop_reason": response.stop_reason,
            },
        )
        return response

    @activity.defn(name="run_acp_implementation")
    async def run_acp_implementation(self, request: ACPRequest) -> ACPResponse:
        return await self._run_acp_stage(request, stage="implementation")

    @activity.defn(name="run_acp_tests")
    async def run_acp_tests(self, request: ACPRequest) -> ACPResponse:
        return await self._run_acp_stage(request, stage="tests")

    @activity.defn(name="run_acp_review")
    async def run_acp_review(self, request: ACPRequest) -> ACPResponse:
        return await self._run_acp_stage(request, stage="review")

    @activity.defn(name="close_acp_session")
    async def close_acp_session(self, session_id: str) -> None:
        activity.logger.info("Closing ACP session", extra={"session_id": session_id})
        await close_session(session_id)
        activity.logger.debug("Closed ACP session", extra={"session_id": session_id})

    @activity.defn(name="summarize_implementation")
    async def summarize_implementation(self, prompt: str) -> ImplementationOutput:
        activity.logger.info(
            "Summarizing implementation",
            extra={"prompt_chars": len(prompt)},
        )
        result = await _summarize_implementation(prompt)
        activity.logger.info(
            "Implementation summary completed",
            extra={
                "prompt_chars": len(prompt),
                "key_steps": len(result.key_steps),
                "files_to_change": len(result.files_to_change),
            },
        )
        return result

    @activity.defn(name="parse_coding_transcript")
    async def parse_coding_transcript(self, prompt: str) -> EvaluationOutput:
        activity.logger.info("Parsing coding transcript", extra={"prompt_chars": len(prompt)})
        result = await _parse_coding_transcript(prompt)
        activity.logger.info(
            "Coding transcript parsed",
            extra={
                "prompt_chars": len(prompt),
                "task_implemented": result.task_implemented,
                "automated_tests_implemented": result.automated_tests_implemented,
            },
        )
        return result

    @activity.defn(name="summarize_tests")
    async def summarize_tests(self, prompt: str) -> TestPlanOutput:
        activity.logger.info("Summarizing tests", extra={"prompt_chars": len(prompt)})
        result = await _summarize_tests(prompt)
        activity.logger.info(
            "Test summary completed",
            extra={
                "prompt_chars": len(prompt),
                "test_cases": len(result.test_cases),
                "tooling_notes": len(result.tooling_notes),
            },
        )
        return result

    @activity.defn(name="parse_review_transcript")
    async def parse_review_transcript(self, prompt: str) -> ReviewOutput:
        activity.logger.info("Parsing review transcript", extra={"prompt_chars": len(prompt)})
        result = await _parse_review_transcript(prompt)
        activity.logger.info(
            "Review transcript parsed",
            extra={
                "prompt_chars": len(prompt),
                "approval": result.approval,
                "issues": len(result.issues),
                "recommendations": len(result.recommendations),
            },
        )
        return result

    @activity.defn(name="run_clarification_agent")
    async def run_clarification_agent(self, prompt: str) -> ClarificationOutput:
        activity.logger.info("Running clarification agent", extra={"prompt_chars": len(prompt)})
        result = await _run_clarification_agent(prompt)
        activity.logger.info(
            "Clarification agent completed",
            extra={
                "prompt_chars": len(prompt),
                "requires_clarification": result.clarification_required,
                "questions": len(result.open_questions),
            },
        )
        return result

    @activity.defn(name="draft_release_plan")
    async def draft_release_plan(self, prompt: str) -> ReleasePlanOutput:
        activity.logger.info("Drafting release plan", extra={"prompt_chars": len(prompt)})
        result = await _draft_release_plan(prompt)
        activity.logger.info(
            "Release plan drafted",
            extra={
                "branch_name": result.branch_name,
                "commit_message": result.commit_message,
            },
        )
        return result

    def activities(self) -> list[Any]:
        return [
            self.run_acp_implementation,
            self.run_acp_tests,
            self.run_acp_review,
            self.close_acp_session,
            self.summarize_implementation,
            self.parse_coding_transcript,
            self.summarize_tests,
            self.parse_review_transcript,
            self.run_clarification_agent,
            self.draft_release_plan,
        ]


__all__ = [
    "ACPRequest",
    "ACPResponse",
    "close_session",
    "run_acp_implementation",
    "run_acp_tests",
    "run_acp_review",
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
    "AgentActivities",
    "draft_release_plan",
]


async def run_acp_implementation(request: ACPRequest) -> ACPResponse:
    return await _run_acp_agent(request)


async def run_acp_tests(request: ACPRequest) -> ACPResponse:
    return await _run_acp_agent(request)


async def run_acp_review(request: ACPRequest) -> ACPResponse:
    return await _run_acp_agent(request)


summarize_implementation = _summarize_implementation
parse_coding_transcript = _parse_coding_transcript
summarize_tests = _summarize_tests
parse_review_transcript = _parse_review_transcript
run_clarification_agent = _run_clarification_agent
draft_release_plan = _draft_release_plan
