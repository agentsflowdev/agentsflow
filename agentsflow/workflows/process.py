"""Temporal workflow orchestrating the development process automation pipeline."""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from agentsflow.activities import (
    ACPRequest,
    ACPResponse,
    FinalizeGitRequest,
    FinalizeGitResult,
    GitWorktreeRequest,
    GitWorktreeResult,
    IssueDetails,
    IssueRequest,
)
from agentsflow.activities.agents import (
    ClarificationOutput,
    EvaluationOutput,
    ImplementationOutput,
    IssuePayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)

MAX_IMPLEMENTATION_ATTEMPTS = 4
MAX_TEST_ATTEMPTS = 5
MAX_REVIEW_ATTEMPTS = 5
ACP_ACTIVITY_TIMEOUT_ENV = "PROCESS_ACP_ACTIVITY_TIMEOUT_MINUTES"
DEFAULT_ACP_ACTIVITY_TIMEOUT_MINUTES = 60
CLARIFICATION_MARKER = "clarification_required"
CLARIFICATION_SEARCH_ATTRIBUTE = "ClarificationRequired"


def _acp_activity_timeout() -> timedelta:
    """Resolve the ACP start_to_close timeout from env with a safe default."""

    raw = os.getenv(ACP_ACTIVITY_TIMEOUT_ENV)
    try:
        minutes = int(raw) if raw is not None else DEFAULT_ACP_ACTIVITY_TIMEOUT_MINUTES
    except ValueError:
        minutes = DEFAULT_ACP_ACTIVITY_TIMEOUT_MINUTES
    if minutes <= 0:
        minutes = DEFAULT_ACP_ACTIVITY_TIMEOUT_MINUTES
    return timedelta(minutes=minutes)


class AgentRun(BaseModel):
    stage: Literal["implementation", "tests", "review"]
    prompt: str
    message: str
    stop_reason: str | None = None


class ProcessWorkflowInput(BaseModel):
    """Parameters required to kick off the process workflow."""

    repository: str = Field(..., description="Local path or remote URL to the source repository.")
    reference: str | None = Field(default=None, description="Optional git reference to base the worktree on.")
    issue_url: str | None = Field(
        default=None,
        description="URL pointing to the issue (Jira, GitHub, etc.).",
        validation_alias=AliasChoices("issue_url", "jira_task_url"),
    )
    task_text: str | None = Field(
        default=None,
        description=(
            "Free-form task description when no issue tracker URL is available. The first non-empty line is "
            "treated as the summary; remaining lines form the description."
        ),
    )
    branch_name: str | None = Field(
        default=None,
        description="Optional git branch name to write the committed changes to.",
    )
    coding_agent_provider: Literal["claude", "gemini", "codex"] = Field(
        default="claude",
        description="Which coding agent to use (Claude, Gemini, or Codex).",
    )

    @model_validator(mode="after")
    def _require_single_task_source(self) -> ProcessWorkflowInput:
        issue_present = bool(self.issue_url)
        text_present = bool(self.task_text)
        if issue_present == text_present:
            raise ValueError("Provide exactly one of issue_url or task_text.")
        return self


class ProcessWorkflowOutput(BaseModel):
    """Aggregated result of the process workflow."""

    repository_path: str
    reference: str
    coding_session_id: str | None
    coding_stops: list[AgentRun]
    issue: IssuePayload
    implementation: ImplementationOutput
    evaluation: EvaluationOutput
    test_plan: TestPlanOutput | None
    review: ReviewOutput
    release_plan: ReleasePlanOutput
    committed_branch: str | None
    committed_sha: str | None
    commit_pushed: bool


@workflow.defn(name="process_workflow", sandboxed=False)
class ProcessWorkflow:
    """Temporal workflow mirroring the automation pipeline."""

    def __init__(self) -> None:
        self._clarification_state: ClarificationOutput | None = None
        self._clarification_resolved = False
        self._clarification_answers: list[str] = []
        self._clarification_assumptions: list[str] = []
        self._workflow_completed = False
        self._task_payload: IssuePayload | None = None

    @workflow.signal
    async def clarification_requested(self, payload: dict[str, Any]) -> None:  # pragma: no cover - notification only
        # Notification-only signal; state is handled where it originates.
        return None

    @workflow.signal
    async def provide_clarification(
        self,
        answers: Sequence[str] | None = None,
        assumptions: Sequence[str] | None = None,
    ) -> None:
        if self._clarification_state is None:
            return
        self._clarification_answers = list(answers or [])
        self._clarification_assumptions = list(assumptions or [])
        self._clarification_resolved = True

    @workflow.query
    def clarification_status(self) -> dict[str, Any]:
        if self._clarification_state and not self._clarification_resolved:
            return {
                "status": "clarification_required",
                "questions": list(self._clarification_state.open_questions),
                "assumptions": list(self._clarification_state.assumptions),
            }
        if self._workflow_completed:
            return {"status": "completed"}
        return {"status": "running"}

    @workflow.run
    async def run(self, params: ProcessWorkflowInput) -> ProcessWorkflowOutput:  # noqa: D401
        logger = workflow.logger
        source = "issue_url" if params.issue_url else "task_text"
        logger.info(
            "Process workflow started",
            extra={
                "repository": params.repository,
                "reference": params.reference,
                "issue_url": params.issue_url,
                "task_source": source,
                "branch_name": params.branch_name,
            },
        )
        git_result = await workflow.execute_activity(
            "create_git_worktree",
            GitWorktreeRequest(repository=params.repository, reference=params.reference),
            start_to_close_timeout=timedelta(minutes=4),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=GitWorktreeResult,
        )
        logger.info(
            "Git worktree created",
            extra={
                "repository_path": git_result.repository_path,
                "worktree_path": git_result.worktree_path,
                "reference": git_result.reference,
            },
        )

        if params.issue_url:
            issue_result = await workflow.execute_activity(
                "read_issue",
                IssueRequest(issue_url=params.issue_url),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=4),
                result_type=IssueDetails,
            )
        else:
            issue_result = _issue_details_from_task_text(params.task_text or "")
        logger.info(
            "Issue context loaded",
            extra={
                "issue_key": issue_result.issue_key,
                "status": issue_result.status,
                "source": source,
            },
        )

        task_payload = _build_task_payload(issue_result)
        self._task_payload = task_payload

        clarification = await workflow.execute_activity(
            "run_clarification_agent",
            _render_clarification_prompt(task_payload),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
            result_type=ClarificationOutput,
        )
        if clarification.clarification_required:
            logger.warning(
                "Workflow waiting for clarification",
                extra={"questions": clarification.open_questions},
            )
            self._clarification_state = clarification
            self._clarification_resolved = False
            # Emit a self-signal so history reflects the clarification event without polling.
            info = workflow.info()
            self_handle = workflow.get_external_workflow_handle(info.workflow_id, run_id=info.run_id)
            await self_handle.signal("clarification_requested", clarification.model_dump())
            question_notes = [
                f"Clarification question: {question}" for question in clarification.open_questions if question
            ]
            if question_notes and self._task_payload is not None:
                updated_comments = list(self._task_payload.comments)
                updated_comments.extend(question_notes)
                self._task_payload.comments = updated_comments
                task_payload.comments = updated_comments
            await workflow.wait_condition(lambda: self._clarification_resolved)
            clarification_notes = [
                f"Clarification answer: {answer}" for answer in self._clarification_answers if answer
            ]
            assumption_notes = [
                f"Clarification assumption: {assumption}"
                for assumption in self._clarification_assumptions
                if assumption
            ]
            note_entries = clarification_notes + assumption_notes
            if note_entries and self._task_payload is not None:
                updated_comments = list(self._task_payload.comments)
                updated_comments.extend(note_entries)
                self._task_payload.comments = updated_comments
                task_payload.comments = updated_comments
            self._clarification_state = None
            self._clarification_answers = []
            self._clarification_assumptions = []

        coding_session_id: str | None = None
        review_session_id: str | None = None
        agent_runs: list[AgentRun] = []

        async def _invoke_coding_agent(
            stage: Literal["implementation", "tests", "review"],
            prompt: str,
            *,
            session_kind: Literal["coding", "review"],
        ) -> ACPResponse:
            nonlocal coding_session_id, review_session_id
            session_id = coding_session_id if session_kind == "coding" else review_session_id
            response = await workflow.execute_activity(
                "run_acp_agent",
                ACPRequest(
                    prompt=prompt,
                    agent_type=params.coding_agent_provider,
                    session_id=session_id,
                    workspace_dir=git_result.worktree_path,
                ),
                start_to_close_timeout=_acp_activity_timeout(),
                retry_policy=RetryPolicy(maximum_attempts=1),
                result_type=ACPResponse,
            )
            if session_kind == "coding":
                coding_session_id = response.session_id
            else:
                review_session_id = response.session_id
            agent_runs.append(
                AgentRun(
                    stage=stage,
                    prompt=prompt,
                    message=response.message,
                    stop_reason=response.stop_reason,
                )
            )
            return response  # type: ignore[no-any-return]

        async def _run_agent_activity(
            name: str,
            prompt: str,
            result_type: type,
            *,
            timeout_minutes: int = 2,
        ) -> Any:
            return await workflow.execute_activity(
                name,
                prompt,
                start_to_close_timeout=timedelta(minutes=timeout_minutes),
                retry_policy=RetryPolicy(maximum_attempts=2),
                result_type=result_type,
            )

        evaluation: EvaluationOutput | None = None
        implementation: ImplementationOutput | None = None
        test_plan: TestPlanOutput | None = None
        review: ReviewOutput | None = None
        release_plan: ReleasePlanOutput | None = None
        finalize_result: FinalizeGitResult | None = None

        coding_feedback: list[str] = []
        review_feedback: list[str] = []
        implementation_attempts = 0
        tests_attempts = 0
        review_attempts = 0

        try:
            while True:
                # Implementation loop
                while True:
                    if implementation_attempts >= MAX_IMPLEMENTATION_ATTEMPTS:
                        raise ApplicationError(
                            "Exceeded implementation attempts without satisfying task requirements.",
                            non_retryable=True,
                        )
                    implementation_attempts += 1
                    logger.info(
                        "Implementation attempt",
                        extra={
                            "attempt": implementation_attempts,
                            "feedback_items": len(coding_feedback),
                        },
                    )
                    coding_prompt = _render_coding_prompt(
                        stage="implementation",
                        task=task_payload,
                        workspace_dir=git_result.worktree_path,
                        feedback=coding_feedback,
                    )
                    coding_response = await _invoke_coding_agent("implementation", coding_prompt, session_kind="coding")
                    implementation_history = _history_transcripts(
                        agent_runs[:-1],
                        stages=("implementation", "tests"),
                    )
                    evaluation = await _run_agent_activity(
                        "run_evaluation_agent",
                        _render_evaluation_prompt(
                            stage="implementation",
                            task=task_payload,
                            transcript=coding_response.message,
                            history=implementation_history,
                        ),
                        EvaluationOutput,
                    )
                    logger.info(
                        "Implementation evaluation",
                        extra={
                            "attempt": implementation_attempts,
                            "task_implemented": evaluation.task_implemented,
                            "tests_implemented": evaluation.automated_tests_implemented,
                        },
                    )

                    if evaluation.task_implemented:
                        coding_feedback = []
                        implementation_attempts = 0
                        logger.info("Implementation stage satisfied")
                        break

                    coding_feedback = _build_feedback(
                        "Implementation gaps detected",
                        evaluation.reasoning,
                    )

                if evaluation is None:
                    raise ApplicationError(
                        "Evaluation did not complete during implementation stage.",
                        non_retryable=True,
                    )

                # Tests loop (if needed)
                if not evaluation.automated_tests_implemented:
                    tests_feedback = _build_feedback(
                        "Automated tests missing",
                        evaluation.reasoning,
                    )
                    while True:
                        if tests_attempts >= MAX_TEST_ATTEMPTS:
                            raise ApplicationError(
                                "Exceeded automated testing attempts without success.",
                                non_retryable=True,
                            )
                        tests_attempts += 1
                        logger.info(
                            "Tests attempt",
                            extra={
                                "attempt": tests_attempts,
                                "feedback_items": len(tests_feedback),
                            },
                        )
                        tests_prompt = _render_coding_prompt(
                            stage="tests",
                            task=task_payload,
                            workspace_dir=git_result.worktree_path,
                            feedback=tests_feedback,
                        )
                        test_response = await _invoke_coding_agent("tests", tests_prompt, session_kind="coding")
                        tests_history = _history_transcripts(
                            agent_runs[:-1],
                            stages=("implementation", "tests"),
                        )

                        evaluation = await _run_agent_activity(
                            "run_evaluation_agent",
                            _render_evaluation_prompt(
                                stage="tests",
                                task=task_payload,
                                transcript=test_response.message,
                                history=tests_history,
                            ),
                            EvaluationOutput,
                        )
                        logger.info(
                            "Tests evaluation",
                            extra={
                                "attempt": tests_attempts,
                                "task_implemented": evaluation.task_implemented,
                                "tests_implemented": evaluation.automated_tests_implemented,
                            },
                        )

                        if evaluation.automated_tests_implemented:
                            tests_feedback = []
                            tests_attempts = 0
                            logger.info("Automated tests satisfied")
                            break

                        tests_feedback = _build_feedback(
                            "Automated tests still insufficient",
                            evaluation.reasoning,
                        )

                    if not evaluation.task_implemented:
                        coding_feedback = _build_feedback(
                            "Implementation regressed after tests",
                            evaluation.reasoning,
                        )
                        continue

                # Review loop
                while True:
                    if review_attempts >= MAX_REVIEW_ATTEMPTS:
                        raise ApplicationError(
                            "Code review stage did not reach approval.",
                            non_retryable=True,
                        )
                    review_attempts += 1
                    logger.info(
                        "Review attempt",
                        extra={
                            "attempt": review_attempts,
                            "feedback_items": len(review_feedback),
                        },
                    )
                    review_prompt_text = _render_coding_prompt(
                        stage="review",
                        task=task_payload,
                        workspace_dir=git_result.worktree_path,
                        feedback=review_feedback,
                    )
                    review_response = await _invoke_coding_agent("review", review_prompt_text, session_kind="review")

                    review = await _run_agent_activity(
                        "run_review_agent",
                        _render_review_evaluation_prompt(task_payload, review_response.message),
                        ReviewOutput,
                    )
                    logger.info(
                        "Review evaluation",
                        extra={
                            "attempt": review_attempts,
                            "approval": review.approval,
                            "issues": len(review.issues),
                        },
                    )

                    if review.approval:
                        review_feedback = []
                        logger.info("Review approved")
                        break

                    review_feedback = _build_review_feedback(review)
                    coding_feedback = list(review_feedback)
                    break

                if review and review.approval:
                    break

            if review is None:
                raise ApplicationError(
                    "Review stage did not produce a result.",
                    non_retryable=True,
                )

            implementation = await _run_agent_activity(
                "run_implementation_agent",
                _render_implementation_summary_prompt(task_payload, agent_runs),
                ImplementationOutput,
            )
            if implementation is None:
                raise ApplicationError(
                    "Implementation summary could not be generated.",
                    non_retryable=True,
                )

            if evaluation.automated_tests_implemented:
                test_plan = await _run_agent_activity(
                    "run_tests_agent",
                    _render_test_summary_prompt(task_payload, agent_runs),
                    TestPlanOutput,
                )
                logger.info("Test plan produced", extra={"cases": len(test_plan.test_cases)})
            else:
                test_plan = None

            release_plan = await _run_agent_activity(
                "run_release_agent",
                _render_release_prompt(
                    task_payload,
                    implementation,
                    evaluation,
                    review,
                    test_plan,
                ),
                ReleasePlanOutput,
                timeout_minutes=3,
            )
            logger.info(
                "Release plan ready",
                extra={
                    "branch_name": release_plan.branch_name,
                    "commit_message": release_plan.commit_message,
                },
            )
            if release_plan is None:
                raise ApplicationError(
                    "Release plan generation failed.",
                    non_retryable=True,
                )

            branch_override = (params.branch_name or "").strip()
            plan_branch = (release_plan.branch_name or "").strip()
            branch_name = branch_override or plan_branch
            if not branch_name:
                raise ApplicationError(
                    "No branch name available to commit the workflow changes.",
                    non_retryable=True,
                )

            commit_message = (release_plan.commit_message or "").strip()
            if not commit_message:
                raise ApplicationError(
                    "Release plan did not provide a commit message.",
                    non_retryable=True,
                )

            finalize_result = await workflow.execute_activity(
                "finalize_git_changes",
                FinalizeGitRequest(
                    worktree_path=git_result.worktree_path,
                    branch_name=branch_name,
                    commit_message=commit_message,
                ),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
                result_type=FinalizeGitResult,
            )
            logger.info(
                "Git changes finalised",
                extra={
                    "branch_name": finalize_result.branch_name,
                    "commit_sha": finalize_result.commit_sha,
                    "pushed": finalize_result.pushed,
                },
            )
        finally:
            closed_session_ids: set[str] = set()
            if coding_session_id and coding_session_id not in closed_session_ids:
                logger.info("Closing coding session", extra={"session_id": coding_session_id})
                await workflow.execute_activity(
                    "close_acp_session",
                    coding_session_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                closed_session_ids.add(coding_session_id)
            if review_session_id and review_session_id not in closed_session_ids:
                logger.info("Closing review session", extra={"session_id": review_session_id})
                await workflow.execute_activity(
                    "close_acp_session",
                    review_session_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

        output = ProcessWorkflowOutput(
            repository_path=git_result.repository_path,
            reference=git_result.reference,
            coding_session_id=coding_session_id,
            coding_stops=agent_runs,
            issue=task_payload,
            implementation=implementation,
            evaluation=evaluation,
            test_plan=test_plan,
            review=review,
            release_plan=release_plan,
            committed_branch=finalize_result.branch_name if finalize_result else None,
            committed_sha=finalize_result.commit_sha if finalize_result else None,
            commit_pushed=finalize_result.pushed if finalize_result else False,
        )
        logger.info(
            "Process workflow completed",
            extra={
                "branch": output.committed_branch,
                "commit_sha": output.committed_sha,
                "commit_pushed": output.commit_pushed,
            },
        )
        self._workflow_completed = True
        return output


def _build_task_payload(details: IssueDetails) -> IssuePayload:
    comments = [
        f"{comment.author}: {comment.body.strip()}"
        for comment in details.comments
        if comment.body and comment.body.strip()
    ]
    return IssuePayload(
        issue_key=details.issue_key,
        summary=details.summary,
        description=details.description,
        comments=comments,
    )


def _issue_details_from_task_text(task_text: str) -> IssueDetails:
    """Create a synthetic IssueDetails payload from ad-hoc task text."""

    normalized_lines = [line.strip() for line in task_text.splitlines() if line.strip()]
    summary = normalized_lines[0] if normalized_lines else "Ad-hoc task"
    description = "\n".join(normalized_lines[1:]).strip()
    if not description:
        description = summary

    issue_key = f"TASK-{uuid.uuid4().hex[:8].upper()}"
    # Cap summary to avoid excessively long prompt headers
    capped_summary = summary[:200]
    return IssueDetails(
        issue_key=issue_key,
        issue_url="adhoc://task",
        summary=capped_summary,
        description=description,
        status=None,
        comments=[],
    )


def _render_clarification_prompt(task: IssuePayload) -> str:
    parts = [
        _format_task_section(task),
        (
            "Before any coding begins, verify the requirements are fully specified. Identify conflicting acceptance "
            "criteria, missing environment details, undefined inputs/outputs, deployment concerns, or required "
            "approvals that a coding agent cannot guess."
        ),
        (
            "Respond with ClarificationOutput. Set clarification_required to True only when the open questions would "
            "block progress, and list each question as a concise bullet the stakeholder can answer. Even when "
            "everything is clear, include any assumptions that should be confirmed downstream."
        ),
    ]
    return "\n\n".join(parts)


def _render_coding_prompt(
    *,
    stage: Literal["implementation", "tests", "review"],
    task: IssuePayload,
    workspace_dir: str | None,
    feedback: Sequence[str],
) -> str:
    base = [
        _format_task_section(task),
        f"Workspace directory: {workspace_dir or 'unknown'}",
    ]
    if feedback:
        base.append("Outstanding feedback:\n" + "\n".join(f"- {item}" for item in feedback))

    if stage == "implementation":
        base.append(
            "Implement the task end-to-end. Stay tightly scoped to the acceptance criteria—avoid creating "
            "placeholder assets, renaming files, or adding new dependencies unless they are essential to the solution. "
            "Summarise the work by listing each file you touched alongside the intent of the change. "
            "Before you conclude, run the repository's existing linting and automated test commands that validate "
            "the implementation and include their outcomes."
        )
    elif stage == "tests":
        base.append(
            "Focus exclusively on automated tests. Limit edits to test code and supporting fixtures unless a minimal "
            "production change is strictly required for the tests to run. Report which tests you created or updated "
            "and any commands you ran. "
            "Run the available linting and test suites (e.g., pytest, npm test, go test) to prove the new tests pass "
            "and capture their results."
        )
    else:  # review
        base.append(
            "Perform a thorough code review of the changes made in the current workspace. Highlight blockers, risks,"
            "and suggested improvements. Do not make further code changes unless strictly required to inspect the code."
            "Before concluding, run the relevant automated test or lint commands (e.g., pytest, npm test, go test) to "
            "validate the current state and include the commands and results in your response."
        )
    if stage == "implementation" or stage == "tests":
        base.append(
            "When finished, provide a concise summary of your actions that enumerates every file created or modified,"
            "explains the intent for each, and confirms you avoided unrelated or unnecessary changes."
        )
    return "\n\n".join(base)


def _history_transcripts(
    runs: Sequence[AgentRun],
    *,
    stages: Sequence[Literal["implementation", "tests", "review"]] | None = None,
    limit: int = 3,
) -> list[str]:
    """Return formatted snippets of the most recent coding transcripts."""

    allowed = set(stages) if stages else {"implementation", "tests", "review"}
    entries = [
        (run.stage, run.message.strip()) for run in runs if run.stage in allowed and run.message and run.message.strip()
    ]
    if not entries:
        return []
    window = entries[-limit:]
    formatted: list[str] = []
    for idx, (stage, message) in enumerate(reversed(window), start=1):
        formatted.append(f"Prior {stage} transcript #{idx}:\n{message}")
    return formatted


def _render_evaluation_prompt(
    *,
    stage: Literal["implementation", "tests"],
    task: IssuePayload,
    transcript: str,
    history: Sequence[str] | None = None,
) -> str:
    focus = (
        "Decide whether the issue appears complete based on the transcript narrative. Assume the coding agent's "
        "statements are accurate unless they acknowledge missing work or failures."
        if stage == "implementation"
        else "Decide whether adequate automated tests now exist according to the transcript. Only treat the tests as "
        "implemented when the transcript references running automated suites, commands, or specific test artefacts; "
        "manual spot checks alone are insufficient."
    )
    parts = [_format_task_section(task)]
    transcript_section = [
        "Coding agent transcript:",
        transcript.strip() or "(no output)",
    ]
    if history:
        transcript_section.append(
            "Earlier coding transcripts for context (most recent first):\n" + "\n\n".join(history)
        )
    parts.extend(transcript_section)
    parts.append(
        f"{focus} Reply with EvaluationOutput so that task_implemented and automated_tests_implemented mirror the "
        "transcript's own claims. When the agent notes TODOs, failures, or uncertainty, mark the appropriate flag "
        "False and explain why."
    )
    return "\n\n".join(parts)


def _render_review_evaluation_prompt(task: IssuePayload, transcript: str) -> str:
    parts = [
        _format_task_section(task),
        "Coding agent review transcript:",
        transcript.strip() or "(no output)",
        (
            "Summarise the review findings and respond with ReviewOutput. Focus only on behaviours and files "
            "described in the transcript—do not invent new requirements or hardening tasks outside that scope. "
            "If you identify any issue that requires modifying code, tests, documentation, or automation, classify "
            "it as an issue and set approval to False. When only recommendations remain, set approval to True and "
            "leave the issues list empty. "
            "Flag approval as False if any blocking issues remain or if the transcript lacks concrete evidence that "
            "code and automated tests were inspected. "
            "Ignore the state of git commits or untracked files—the workflow handles committing in a later step."
        ),
    ]
    return "\n\n".join(parts)


def _render_implementation_summary_prompt(task: IssuePayload, runs: Sequence[AgentRun]) -> str:
    relevant = [run for run in runs if run.stage in {"implementation", "tests"}]
    transcript = "\n\n".join(f"[{run.stage}] {run.message.strip()}" for run in relevant if run.message)
    parts = [
        _format_task_section(task),
        "Coding agent sessions:",
        transcript or "(no transcript)",
        "Return an ImplementationOutput capturing the implemented behaviour, key steps, touched files, and testing "
        "considerations.",
    ]
    return "\n\n".join(parts)


def _render_test_summary_prompt(task: IssuePayload, runs: Sequence[AgentRun]) -> str:
    transcript = "\n\n".join(
        f"[{run.stage}] {run.message.strip()}" for run in runs if run.stage == "tests" and run.message
    )
    parts = [
        _format_task_section(task),
        "Coding agent testing transcripts:",
        transcript or "(no dedicated testing transcript)",
        "Summarise the automated tests that now exist and respond with TestPlanOutput.",
    ]
    return "\n\n".join(parts)


def _render_release_prompt(
    task: IssuePayload,
    implementation: ImplementationOutput,
    evaluation: EvaluationOutput,
    review: ReviewOutput,
    test_plan: TestPlanOutput | None,
) -> str:
    parts = [
        _format_task_section(task),
        _format_implementation_section(implementation),
        f"Final evaluation: task_implemented={evaluation.task_implemented}, "
        f"automated_tests_implemented={evaluation.automated_tests_implemented}. Reasoning: {evaluation.reasoning}",
        _format_review_section(review),
    ]
    if test_plan is not None:
        parts.append(_format_test_plan_section(test_plan))
    parts.append(
        "Draft the source-control rollout details and respond with ReleasePlanOutput, including branch, commit "
        "message, PR title/body, and follow-up tasks."
    )
    return "\n\n".join(parts)


def _build_feedback(title: str, reasoning: str) -> list[str]:
    lines = [title]
    detail = reasoning.strip()
    if detail:
        lines.append(detail)
    return lines


def _build_review_feedback(review: ReviewOutput) -> list[str]:
    feedback: list[str] = []
    if review.issues:
        feedback.append("Address the following blocking issues:")
        feedback.extend(f"Issue: {issue}" for issue in review.issues)
    if review.recommendations:
        feedback.append("Consider these follow-up improvements:")
        feedback.extend(f"Recommendation: {rec}" for rec in review.recommendations)
    if not feedback:
        feedback.append("Review lacked sufficient detail—provide explicit findings.")
    return feedback


def _format_task_section(task: IssuePayload) -> str:
    lines = [
        f"Issue: {task.issue_key}",
        f"Summary: {task.summary}",
        "Description:",
        task.description.strip() or "(no description)",
    ]
    if task.comments:
        lines.append("Comments:")
        lines.extend(f"- {comment}" for comment in task.comments)
    return "\n".join(lines)


def _format_implementation_section(implementation: ImplementationOutput) -> str:
    lines = [
        f"Implementation summary: {implementation.summary}",
        _format_list_section("Key steps", implementation.key_steps),
        _format_list_section("Files to change", implementation.files_to_change),
        _format_list_section("Testing considerations", implementation.testing_considerations),
    ]
    return "\n".join(lines)


def _format_test_plan_section(test_plan: TestPlanOutput) -> str:
    lines = [
        f"Testing summary: {test_plan.summary}",
        _format_list_section("Test cases", test_plan.test_cases),
        _format_list_section("Tooling notes", test_plan.tooling_notes),
    ]
    return "\n".join(lines)


def _format_review_section(review: ReviewOutput) -> str:
    lines = [
        f"Review approval: {'approved' if review.approval else 'blocked'}",
        _format_list_section("Issues", review.issues),
        _format_list_section("Recommendations", review.recommendations),
        _format_list_section("Praise", review.praise),
    ]
    return "\n".join(lines)


def _format_list_section(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}: (none)"
    return "\n".join([f"{title}:", *[f"- {item}" for item in items]])


__all__ = [
    "ProcessWorkflow",
    "ProcessWorkflowInput",
    "ProcessWorkflowOutput",
    "AgentRun",
]
