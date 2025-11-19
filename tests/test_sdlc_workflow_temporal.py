from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio import client as temporal_client
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentsflow.activities import (
    ACPRequest,
    ACPResponse,
    FinalizeGitRequest,
    FinalizeGitResult,
    GitWorktreeRequest,
    GitWorktreeResult,
    IssueDetails,
)
from agentsflow.activities.agents.models import (
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)
from agentsflow.workflows import AgentRun, SDLCWorkflow, SDLCWorkflowInput
from temporal_settings import TemporalTestSettings


@pytest.fixture(autouse=True)
def fast_attempt_limits(monkeypatch):
    """Keep workflow retry loops tiny so Temporal tests finish quickly."""
    monkeypatch.setattr("agentsflow.workflows.sdlc.MAX_IMPLEMENTATION_ATTEMPTS", 2)
    monkeypatch.setattr("agentsflow.workflows.sdlc.MAX_TEST_ATTEMPTS", 2)
    monkeypatch.setattr("agentsflow.workflows.sdlc.MAX_REVIEW_ATTEMPTS", 2)


class FakeAgentResult:
    def __init__(self, output):
        self.output = output


@dataclass
class ScenarioState:
    implementation_messages: Sequence[str]
    test_messages: Sequence[str]
    review_messages: Sequence[str]
    git_result: GitWorktreeResult
    issue_result: IssueDetails
    claude_calls: list[AgentRun] = field(default_factory=list)
    closed_sessions: list[str] = field(default_factory=list)
    finalize_requests: list[FinalizeGitRequest] = field(default_factory=list)
    finalize_results: list[FinalizeGitResult] = field(default_factory=list)
    branch_override: str | None = None
    clarification_result: ClarificationOutput | None = None


class MockClaude:
    def __init__(self, scenario: ScenarioState):
        self._scenario = scenario
        self._stage_counts: defaultdict[str, int] = defaultdict(int)

    def _detect_stage(self, prompt: str) -> Literal["implementation", "tests", "review"]:
        if "Focus exclusively on automated tests" in prompt:
            return "tests"
        if "Perform a thorough code review" in prompt:
            return "review"
        return "implementation"

    async def __call__(self, request: ACPRequest) -> ACPResponse:
        stage = self._detect_stage(request.prompt)
        stage_index = self._stage_counts[stage]
        self._stage_counts[stage] += 1

        sequences = {
            "implementation": self._scenario.implementation_messages,
            "tests": self._scenario.test_messages,
            "review": self._scenario.review_messages,
        }
        messages = sequences[stage]
        if stage_index < len(messages):
            message = messages[stage_index]
        elif messages:
            message = messages[-1]
        else:
            message = ""

        run = AgentRun(
            stage=stage,
            prompt=request.prompt,
            message=message,
            stop_reason="completed",
        )
        self._scenario.claude_calls.append(run)
        return ACPResponse(
            session_id="session-001",
            message=message,
            stop_reason="completed",
        )


class FakeEvaluationAgent:
    def __init__(self, implementation_outputs, test_outputs):
        self._impl = deque(implementation_outputs)
        self._tests = deque(test_outputs)
        self._last_impl = implementation_outputs[-1] if implementation_outputs else None
        self._last_tests = test_outputs[-1] if test_outputs else None

    async def run(self, prompt, **_kwargs):
        is_tests_prompt = "adequate automated tests now exist" in prompt
        queue = self._tests if is_tests_prompt else self._impl
        if queue:
            result = queue.popleft()
        else:
            result = self._last_tests if is_tests_prompt else self._last_impl
            if result is None:
                raise AssertionError("Evaluation agent exhausted with no fallback result")
        return FakeAgentResult(result)


class FakeReviewAgent:
    def __init__(self, outputs):
        self._outputs = deque(outputs)
        self._last = outputs[-1] if outputs else None

    async def run(self, prompt, **_kwargs):
        if self._outputs:
            result = self._outputs.popleft()
        else:
            if self._last is None:
                raise AssertionError("Review agent exhausted with no fallback result")
            result = self._last
        return FakeAgentResult(result)


async def _run_workflow_with_mocks(
    scenario: ScenarioState,
    *,
    evaluation_agent,
    implementation_summary,
    test_summary,
    review_agent,
    release_agent,
):
    mock_claude = MockClaude(scenario)
    external_settings = TemporalTestSettings.from_env()

    @activity.defn(name="create_git_worktree")
    async def create_git_worktree_activity(
        request: GitWorktreeRequest,
    ) -> GitWorktreeResult:
        return scenario.git_result

    @activity.defn(name="read_issue")
    async def read_issue_activity(_request) -> IssueDetails:
        return scenario.issue_result

    @activity.defn(name="run_acp_agent")
    async def run_acp_agent_activity(request: ACPRequest) -> ACPResponse:
        return await mock_claude(request)

    @activity.defn(name="finalize_git_changes")
    async def finalize_git_changes_activity(
        request: FinalizeGitRequest,
    ) -> FinalizeGitResult:
        scenario.finalize_requests.append(request)
        result = FinalizeGitResult(
            branch_name=request.branch_name,
            commit_sha=f"{request.branch_name}-sha",
            pushed=False,
        )
        scenario.finalize_results.append(result)
        return result

    @activity.defn(name="close_acp_session")
    async def close_acp_session_activity(session_id: str) -> None:
        scenario.closed_sessions.append(session_id)

    async def _call_stub(fn, prompt: str):
        result = await fn(prompt)
        return result.output if isinstance(result, FakeAgentResult) else result

    @activity.defn(name="run_implementation_agent")
    async def run_implementation_agent_activity(prompt: str) -> ImplementationOutput:
        return await _call_stub(implementation_summary, prompt)

    @activity.defn(name="run_evaluation_agent")
    async def run_evaluation_agent_activity(prompt: str) -> EvaluationOutput:
        return await _call_stub(evaluation_agent.run, prompt)

    @activity.defn(name="run_tests_agent")
    async def run_tests_agent_activity(prompt: str) -> TestPlanOutput:
        return await _call_stub(test_summary, prompt)

    @activity.defn(name="run_clarification_agent")
    async def run_clarification_agent_activity(prompt: str) -> ClarificationOutput:  # noqa: ARG001
        return scenario.clarification_result or ClarificationOutput(
            clarification_required=False,
            open_questions=[],
            assumptions=[],
        )

    @activity.defn(name="run_review_agent")
    async def run_review_agent_activity(prompt: str) -> ReviewOutput:
        return await _call_stub(review_agent.run, prompt)

    @activity.defn(name="run_release_agent")
    async def run_release_agent_activity(prompt: str) -> ReleasePlanOutput:
        return await _call_stub(release_agent, prompt)

    if external_settings is None:
        env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
        client = env.client
        shutdown_cb = env.shutdown
        task_queue = "test-sdlc"
    else:
        client = await temporal_client.Client.connect(
            external_settings.address,
            namespace=external_settings.namespace,
            data_converter=pydantic_data_converter,
        )
        task_queue = external_settings.task_queue

        async def shutdown_cb():
            # Temporal's async client currently has no shutdown/close hook, so
            # remote test runs just drop the reference.
            return None

    try:
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[SDLCWorkflow],
            activities=[
                create_git_worktree_activity,
                read_issue_activity,
                run_acp_agent_activity,
                finalize_git_changes_activity,
                close_acp_session_activity,
                run_implementation_agent_activity,
                run_evaluation_agent_activity,
                run_tests_agent_activity,
                run_review_agent_activity,
                run_release_agent_activity,
                run_clarification_agent_activity,
            ],
        ):
            workflow_input = SDLCWorkflowInput(
                repository="git@example.com:org/repo.git",
                reference="main",
                issue_url="https://example.atlassian.net/browse/ABC-123",
                branch_name=scenario.branch_override,
            )
            return await client.execute_workflow(
                SDLCWorkflow.run,
                workflow_input,
                id=f"sdlc-test-{uuid4().hex}",
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
    finally:
        await shutdown_cb()


@pytest.mark.asyncio
async def test_workflow_retries_claude_until_checks_pass(monkeypatch):
    scenario = ScenarioState(
        implementation_messages=[
            "Attempted initial implementation but API contract unmet.",
            "Implemented missing API contract and updated docs.",
        ],
        test_messages=[
            "Added failing tests placeholder.",
            "Completed pytest suite covering edge cases.",
        ],
        review_messages=[
            "Found blocking issue in error handling path.",
            "All issues resolved; code ready to merge.",
        ],
        git_result=GitWorktreeResult(
            worktree_path="/tmp/worktree",
            repository_path="/tmp/repo",
            reference="main",
            cloned_from_remote=False,
        ),
        issue_result=IssueDetails(
            issue_key="ABC-123",
            issue_url="https://example.atlassian.net/browse/ABC-123",
            summary="Enhance feature toggle",
            description="Ensure feature toggle handles null inputs.",
            status="In Progress",
            comments=[],
        ),
    )

    evaluation_agent = FakeEvaluationAgent(
        implementation_outputs=[
            EvaluationOutput(
                task_implemented=False,
                automated_tests_implemented=False,
                reasoning="Null inputs still fail",
            ),
            EvaluationOutput(
                task_implemented=True,
                automated_tests_implemented=False,
                reasoning="Implementation complete; tests missing",
            ),
        ],
        test_outputs=[
            EvaluationOutput(
                task_implemented=True,
                automated_tests_implemented=False,
                reasoning="Tests still fail",
            ),
            EvaluationOutput(
                task_implemented=True,
                automated_tests_implemented=True,
                reasoning="All tests pass",
            ),
        ],
    )
    review_agent = FakeReviewAgent(
        outputs=[
            ReviewOutput(
                approval=False,
                issues=["Error handling still missing logging for null inputs"],
                recommendations=[],
                praise=[],
            ),
            ReviewOutput(
                approval=True,
                issues=[],
                recommendations=["Schedule refactor for toggle service"],
                praise=["Good coverage of edge cases"],
            ),
        ]
    )

    async def implementation_summary(prompt, **_kwargs):
        return FakeAgentResult(
            ImplementationOutput(
                summary="Implemented null handling for toggle.",
                key_steps=["Add guard", "Update docs"],
                files_to_change=["src/toggle.py"],
                testing_considerations=["pytest::tests/test_toggle.py"],
            )
        )

    async def test_summary(prompt, **_kwargs):
        return FakeAgentResult(
            TestPlanOutput(
                summary="Null input cases covered.",
                test_cases=["tests/test_toggle.py::test_null_input"],
                tooling_notes=["pytest"],
            )
        )

    async def release_plan(prompt, **_kwargs):
        return FakeAgentResult(
            ReleasePlanOutput(
                branch_name="feature/abc-123-null-toggle",
                commit_message="feat: handle null inputs in toggle",
                pr_title="Handle null inputs for feature toggle",
                pr_body="## Summary\n- add guards\n- add tests\n\n## Testing\n- pytest",
                follow_up_tasks=["Monitor toggle metrics"],
            )
        )

    result = await _run_workflow_with_mocks(
        scenario,
        evaluation_agent=evaluation_agent,
        implementation_summary=implementation_summary,
        test_summary=test_summary,
        review_agent=review_agent,
        release_agent=release_plan,
    )

    assert scenario.closed_sessions
    assert scenario.closed_sessions[-1] == "session-001"
    stages = [run.stage for run in result.coding_stops]
    assert stages.count("implementation") >= 2
    assert stages.count("tests") >= 2
    assert stages.count("review") >= 2
    assert stages[-1] == "review"

    assert result.implementation.summary == "Implemented null handling for toggle."
    assert result.evaluation.automated_tests_implemented is True
    assert result.test_plan is not None and "pytest" in result.test_plan.tooling_notes[0]
    assert result.review.approval is True
    assert result.release_plan.branch_name == "feature/abc-123-null-toggle"
    assert scenario.finalize_requests
    assert scenario.finalize_requests[0].commit_message == "feat: handle null inputs in toggle"
    assert result.committed_branch == scenario.finalize_requests[0].branch_name
    assert result.committed_sha == scenario.finalize_results[0].commit_sha
    assert result.commit_pushed is False


@pytest.mark.asyncio
async def test_workflow_fails_when_review_never_approves(monkeypatch):
    scenario = ScenarioState(
        implementation_messages=[
            "Initial implementation",
            "Refinements complete",
            "Further tweaks",
            "Last attempt",
        ],
        test_messages=[
            "Added tests",
            "Re-ran tests",
            "Final testing pass",
        ],
        review_messages=[
            "Blocking issue persists",
            "Still failing review",
            "Final attempt still blocked",
        ],
        git_result=GitWorktreeResult(
            worktree_path="/tmp/worktree",
            repository_path="/tmp/repo",
            reference="main",
            cloned_from_remote=False,
        ),
        issue_result=IssueDetails(
            issue_key="XYZ-789",
            issue_url="https://example.atlassian.net/browse/XYZ-789",
            summary="Add validation",
            description="Ensure inputs are validated.",
            status="In Progress",
            comments=[],
        ),
    )

    evaluation_agent = FakeEvaluationAgent(
        implementation_outputs=[
            EvaluationOutput(
                task_implemented=False,
                automated_tests_implemented=False,
                reasoning="Validation missing",
            ),
            EvaluationOutput(
                task_implemented=True,
                automated_tests_implemented=True,
                reasoning="Implementation done",
            ),
        ],
        test_outputs=[
            EvaluationOutput(
                task_implemented=True,
                automated_tests_implemented=True,
                reasoning="Tests pass",
            ),
        ],
    )
    review_agent = FakeReviewAgent(
        outputs=[
            ReviewOutput(
                approval=False,
                issues=["Logging missing"],
                recommendations=[],
                praise=[],
            ),
            ReviewOutput(
                approval=False,
                issues=["Logging still missing"],
                recommendations=[],
                praise=[],
            ),
            ReviewOutput(
                approval=False,
                issues=["Blocking issue persists"],
                recommendations=[],
                praise=[],
            ),
        ]
    )

    async def dummy_summary(prompt, **_kwargs):
        return FakeAgentResult(
            ImplementationOutput(
                summary="Placeholder",
                key_steps=[],
                files_to_change=[],
                testing_considerations=[],
            )
        )

    async def dummy_release(prompt, **_kwargs):
        return FakeAgentResult(
            ReleasePlanOutput(
                branch_name="placeholder",
                commit_message="placeholder",
                pr_title="placeholder",
                pr_body="placeholder",
                follow_up_tasks=[],
            )
        )

    with pytest.raises(WorkflowFailureError) as exc:
        await _run_workflow_with_mocks(
            scenario,
            evaluation_agent=evaluation_agent,
            implementation_summary=dummy_summary,
            test_summary=dummy_summary,
            review_agent=review_agent,
            release_agent=dummy_release,
        )

    cause = exc.value.cause
    assert isinstance(cause, ApplicationError)
    assert cause.non_retryable is True
    assert "Code review stage did not reach approval." in str(cause)
    assert scenario.closed_sessions
    assert scenario.closed_sessions[-1] == "session-001"

    assert scenario.closed_sessions == ["session-001"]
    assert scenario.finalize_requests == []
