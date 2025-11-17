"""LLM agent integrations used by AgentsFlow workflows."""

from dataclasses import replace

from temporalio import activity

from .claude_acp import (
    ClaudeACPRequest,
    ClaudeACPResponse,
    close_session,
    run_claude_code as _run_claude_code,
)
from .models import (
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
    run_evaluation_agent as _run_evaluation_agent,
    run_implementation_agent as _run_implementation_agent,
    run_release_agent as _run_release_agent,
    run_review_agent as _run_review_agent,
    run_tests_agent as _run_tests_agent,
)


class AgentActivities:
    """Activities involving Claude ACP sessions and LLM planning agents."""

    def __init__(self, *, claude_binary: str | None = None, auto_approve: bool = True) -> None:
        self._claude_binary = claude_binary
        self._auto_approve = auto_approve

    @activity.defn(name="claude_code_acp")
    async def run_claude_code(self, request: ClaudeACPRequest) -> ClaudeACPResponse:
        activity.logger.debug(
            "Preparing Claude ACP activity call",
            extra={
                "session_id": request.session_id,
                "workspace_dir": request.workspace_dir,
                "prompt_chars": len(request.prompt),
                "has_binary_override": self._claude_binary is not None,
                "auto_approve_default": self._auto_approve,
            },
        )
        req = request
        if req.claude_binary is None and self._claude_binary is not None:
            req = replace(req, claude_binary=self._claude_binary)
        if req.auto_approve is None:
            req = replace(req, auto_approve=self._auto_approve)
        activity.logger.debug(
            "Dispatching Claude ACP activity",
            extra={
                "session_id": req.session_id,
                "workspace_dir": req.workspace_dir,
                "claude_binary": req.claude_binary,
                "auto_approve": req.auto_approve,
                "prompt_chars": len(req.prompt),
            },
        )
        return await _run_claude_code(req)

    @activity.defn(name="close_claude_session")
    async def close_claude_session(self, session_id: str) -> None:
        await close_session(session_id)

    @activity.defn(name="run_implementation_agent")
    async def run_implementation_agent(self, prompt: str) -> ImplementationOutput:
        return await _run_implementation_agent(prompt)

    @activity.defn(name="run_evaluation_agent")
    async def run_evaluation_agent(self, prompt: str) -> EvaluationOutput:
        return await _run_evaluation_agent(prompt)

    @activity.defn(name="run_tests_agent")
    async def run_tests_agent(self, prompt: str) -> TestPlanOutput:
        return await _run_tests_agent(prompt)

    @activity.defn(name="run_review_agent")
    async def run_review_agent(self, prompt: str) -> ReviewOutput:
        return await _run_review_agent(prompt)

    @activity.defn(name="run_release_agent")
    async def run_release_agent(self, prompt: str) -> ReleasePlanOutput:
        return await _run_release_agent(prompt)

    def activities(self) -> list:
        return [
            self.run_claude_code,
            self.close_claude_session,
            self.run_implementation_agent,
            self.run_evaluation_agent,
            self.run_tests_agent,
            self.run_review_agent,
            self.run_release_agent,
        ]

__all__ = [
    "ClaudeACPRequest",
    "ClaudeACPResponse",
    "close_session",
    "run_claude_code",
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
    "AgentActivities",
    "run_release_agent",
]


run_claude_code = _run_claude_code
run_implementation_agent = _run_implementation_agent
run_evaluation_agent = _run_evaluation_agent
run_tests_agent = _run_tests_agent
run_review_agent = _run_review_agent
run_release_agent = _run_release_agent
