"""LLM agent integrations used by AgentsFlow workflows."""

from dataclasses import replace
from typing import Any

from temporalio import activity

from .acp_agent import (
    ACPRequest,
    ACPResponse,
    close_session,
)
from .acp_agent import (
    run_acp_agent as _run_acp_agent,
)
from .models import (
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    JiraTaskPayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)
from .sdlc import (
    DEFAULT_MODEL_NAME,
    MODEL_ENV_VAR,
)
from .sdlc import (
    run_clarification_agent as _run_clarification_agent,
)
from .sdlc import (
    run_evaluation_agent as _run_evaluation_agent,
)
from .sdlc import (
    run_implementation_agent as _run_implementation_agent,
)
from .sdlc import (
    run_release_agent as _run_release_agent,
)
from .sdlc import (
    run_review_agent as _run_review_agent,
)
from .sdlc import (
    run_tests_agent as _run_tests_agent,
)


class AgentActivities:
    """Activities involving Claude ACP sessions and LLM planning agents."""

    def __init__(self, *, auto_approve: bool = True) -> None:
        self._auto_approve = auto_approve

    @activity.defn(name="run_acp_agent")
    async def run_acp_agent(self, request: ACPRequest) -> ACPResponse:
        activity.logger.debug(
            "Preparing ACP activity call",
            extra={
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
                "session_id": response.session_id,
                "prompt_chars": len(req.prompt),
                "message_chars": len(response.message or ""),
                "stop_reason": response.stop_reason,
            },
        )
        return response

    @activity.defn(name="close_acp_session")
    async def close_acp_session(self, session_id: str) -> None:
        activity.logger.info("Closing ACP session", extra={"session_id": session_id})
        await close_session(session_id)
        activity.logger.debug("Closed ACP session", extra={"session_id": session_id})

    @activity.defn(name="run_implementation_agent")
    async def run_implementation_agent(self, prompt: str) -> ImplementationOutput:
        activity.logger.info(
            "Running implementation agent",
            extra={"prompt_chars": len(prompt)},
        )
        result = await _run_implementation_agent(prompt)
        activity.logger.info(
            "Implementation agent completed",
            extra={
                "prompt_chars": len(prompt),
                "key_steps": len(result.key_steps),
                "files_to_change": len(result.files_to_change),
            },
        )
        return result

    @activity.defn(name="run_evaluation_agent")
    async def run_evaluation_agent(self, prompt: str) -> EvaluationOutput:
        activity.logger.info("Running evaluation agent", extra={"prompt_chars": len(prompt)})
        result = await _run_evaluation_agent(prompt)
        activity.logger.info(
            "Evaluation agent completed",
            extra={
                "prompt_chars": len(prompt),
                "task_implemented": result.task_implemented,
                "automated_tests_implemented": result.automated_tests_implemented,
            },
        )
        return result

    @activity.defn(name="run_tests_agent")
    async def run_tests_agent(self, prompt: str) -> TestPlanOutput:
        activity.logger.info("Running tests agent", extra={"prompt_chars": len(prompt)})
        result = await _run_tests_agent(prompt)
        activity.logger.info(
            "Tests agent completed",
            extra={
                "prompt_chars": len(prompt),
                "test_cases": len(result.test_cases),
                "tooling_notes": len(result.tooling_notes),
            },
        )
        return result

    @activity.defn(name="run_review_agent")
    async def run_review_agent(self, prompt: str) -> ReviewOutput:
        activity.logger.info("Running review agent", extra={"prompt_chars": len(prompt)})
        result = await _run_review_agent(prompt)
        activity.logger.info(
            "Review agent completed",
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

    @activity.defn(name="run_release_agent")
    async def run_release_agent(self, prompt: str) -> ReleasePlanOutput:
        activity.logger.info("Running release agent", extra={"prompt_chars": len(prompt)})
        result = await _run_release_agent(prompt)
        activity.logger.info(
            "Release agent completed",
            extra={
                "branch_name": result.branch_name,
                "commit_message": result.commit_message,
            },
        )
        return result

    def activities(self) -> list[Any]:
        return [
            self.run_acp_agent,
            self.close_acp_session,
            self.run_implementation_agent,
            self.run_evaluation_agent,
            self.run_tests_agent,
            self.run_review_agent,
            self.run_clarification_agent,
            self.run_release_agent,
        ]


__all__ = [
    "ACPRequest",
    "ACPResponse",
    "close_session",
    "run_acp_agent",
    "DEFAULT_MODEL_NAME",
    "MODEL_ENV_VAR",
    "JiraTaskPayload",
    "ImplementationOutput",
    "EvaluationOutput",
    "TestPlanOutput",
    "ReviewOutput",
    "ReleasePlanOutput",
    "ClarificationOutput",
    "run_implementation_agent",
    "run_evaluation_agent",
    "run_tests_agent",
    "run_review_agent",
    "run_clarification_agent",
    "AgentActivities",
    "run_release_agent",
]


run_acp_agent = _run_acp_agent
run_implementation_agent = _run_implementation_agent
run_evaluation_agent = _run_evaluation_agent
run_tests_agent = _run_tests_agent
run_review_agent = _run_review_agent
run_clarification_agent = _run_clarification_agent
run_release_agent = _run_release_agent
