import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Literal, Sequence
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentsflow.activities import (
    ClaudeACPRequest,
    ClaudeACPResponse,
    GitWorktreeRequest,
    GitWorktreeResult,
    JiraTaskDetails,
    JiraTaskRequest,
)
from temporalio.exceptions import FailureError

from agentsflow.workflows import ClaudeRun, SDLCWorkflow, SDLCWorkflowInput
from agentsflow.workflows.sdlc_agents import (
    EVALUATION_AGENT,
    IMPLEMENTATION_AGENT,
    RELEASE_AGENT,
    REVIEW_AGENT,
    TESTS_AGENT,
    EvaluationOutput,
    ImplementationOutput,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)


class FakeAgentResult:
    def __init__(self, output):
        self.output = output


@dataclass
class ScenarioState:
    implementation_messages: Sequence[str]
    test_messages: Sequence[str]
    review_messages: Sequence[str]
    git_result: GitWorktreeResult
    jira_result: JiraTaskDetails
    claude_calls: list[ClaudeRun] = field(default_factory=list)
    closed_sessions: list[str] = field(default_factory=list)


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

    async def __call__(self, request: ClaudeACPRequest) -> ClaudeACPResponse:
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

        run = ClaudeRun(
            stage=stage,
            prompt=request.prompt,
            message=message,
            stop_reason="completed",
        )
        self._scenario.claude_calls.append(run)
        return ClaudeACPResponse(
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

    @activity.defn(name="create_git_worktree")
    async def create_git_worktree_activity(request: GitWorktreeRequest) -> GitWorktreeResult:
        return scenario.git_result

    @activity.defn(name="fetch_jira_task")
    async def fetch_jira_task_activity(request: JiraTaskRequest) -> JiraTaskDetails:
        return scenario.jira_result

    @activity.defn(name="claude_code_acp")
    async def claude_code_acp_activity(request: ClaudeACPRequest) -> ClaudeACPResponse:
        return await mock_claude(request)

    @activity.defn(name="close_claude_session")
    async def close_claude_session_activity(session_id: str) -> None:
        scenario.closed_sessions.append(session_id)

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client,
            task_queue="test-sdlc",
            workflows=[SDLCWorkflow],
            activities=[
                create_git_worktree_activity,
                fetch_jira_task_activity,
                claude_code_acp_activity,
                close_claude_session_activity,
            ],
        ):
            workflow_input = SDLCWorkflowInput(
                repository="git@example.com:org/repo.git",
                reference="main",
                jira_task_url="https://example.atlassian.net/browse/ABC-123",
                jira_email="dev@example.com",
                jira_api_token="token",
            )
            return await env.client.execute_workflow(
                SDLCWorkflow.run,
                workflow_input,
                id=f"sdlc-test-{uuid4().hex}",
                task_queue="test-sdlc",
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
    finally:
        await env.shutdown()


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
        jira_result=JiraTaskDetails(
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
            EvaluationOutput(task_done=False, tests_created=False, reasoning="Null inputs still fail"),
            EvaluationOutput(task_done=True, tests_created=False, reasoning="Implementation complete; tests missing"),
        ],
        test_outputs=[
            EvaluationOutput(task_done=True, tests_created=False, reasoning="Tests still fail"),
            EvaluationOutput(task_done=True, tests_created=True, reasoning="All tests pass"),
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

    monkeypatch.setattr(EVALUATION_AGENT, "run", evaluation_agent.run)
    monkeypatch.setattr(REVIEW_AGENT, "run", review_agent.run)
    monkeypatch.setattr(IMPLEMENTATION_AGENT, "run", implementation_summary)
    monkeypatch.setattr(TESTS_AGENT, "run", test_summary)
    monkeypatch.setattr(RELEASE_AGENT, "run", release_plan)

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
    assert result.evaluation.tests_created is True
    assert result.test_plan is not None and "pytest" in result.test_plan.tooling_notes[0]
    assert result.review.approval is True
    assert result.release_plan.branch_name == "feature/abc-123-null-toggle"


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
        jira_result=JiraTaskDetails(
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
            EvaluationOutput(task_done=False, tests_created=False, reasoning="Validation missing"),
            EvaluationOutput(task_done=True, tests_created=True, reasoning="Implementation done"),
        ],
        test_outputs=[
            EvaluationOutput(task_done=True, tests_created=True, reasoning="Tests pass"),
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

    monkeypatch.setattr(EVALUATION_AGENT, "run", evaluation_agent.run)
    monkeypatch.setattr(REVIEW_AGENT, "run", review_agent.run)
    monkeypatch.setattr(IMPLEMENTATION_AGENT, "run", dummy_summary)
    monkeypatch.setattr(TESTS_AGENT, "run", dummy_summary)
    monkeypatch.setattr(RELEASE_AGENT, "run", dummy_release)

    with pytest.raises(FailureError) as exc:
        await _run_workflow_with_mocks(
            scenario,
            evaluation_agent=evaluation_agent,
            implementation_summary=dummy_summary,
            test_summary=dummy_summary,
            review_agent=review_agent,
            release_agent=dummy_release,
        )

    cause = exc.value.cause
    assert cause is not None
    assert isinstance(cause, RuntimeError)
    assert "Code review stage did not reach approval." in str(cause)
    assert scenario.closed_sessions
    assert scenario.closed_sessions[-1] == "session-001"

    assert scenario.closed_sessions == ["session-001"]
