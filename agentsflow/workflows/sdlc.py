"""Temporal workflow orchestrating the SDLC automation pipeline."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal, Sequence

from pydantic import AliasChoices, BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from agentsflow.activities import (
    ClaudeACPRequest,
    ClaudeACPResponse,
    FinalizeGitRequest,
    FinalizeGitResult,
    GitWorktreeRequest,
    GitWorktreeResult,
    IssueDetails,
    IssueRequest,
)
from agentsflow.activities.agents import (
    EvaluationOutput,
    ImplementationOutput,
    JiraTaskPayload,
    ReleasePlanOutput,
    ReviewOutput,
    TestPlanOutput,
)


MAX_IMPLEMENTATION_ATTEMPTS = 4
MAX_TEST_ATTEMPTS = 3
MAX_REVIEW_ATTEMPTS = 3


class ClaudeRun(BaseModel):
    stage: Literal["implementation", "tests", "review"]
    prompt: str
    message: str
    stop_reason: str | None = None


class SDLCWorkflowInput(BaseModel):
    """Parameters required to kick off the SDLC workflow."""

    repository: str = Field(
        ..., description="Local path or remote URL to the source repository."
    )
    reference: str | None = Field(
        default=None, description="Optional git reference to base the worktree on."
    )
    issue_url: str = Field(
        ...,
        description="URL pointing to the issue (Jira, GitHub, etc.).",
        validation_alias=AliasChoices("issue_url", "jira_task_url"),
    )
    branch_name: str | None = Field(
        default=None,
        description="Optional git branch name to write the committed changes to.",
    )


class SDLCWorkflowOutput(BaseModel):
    """Aggregated result of the SDLC workflow."""

    worktree_path: str
    repository_path: str
    reference: str
    coding_session_id: str | None
    coding_stops: list[ClaudeRun]
    jira: JiraTaskPayload
    implementation: ImplementationOutput
    evaluation: EvaluationOutput
    test_plan: TestPlanOutput | None
    review: ReviewOutput
    release_plan: ReleasePlanOutput
    committed_branch: str | None
    committed_sha: str | None
    commit_pushed: bool


@workflow.defn(name="sdlc_workflow", sandboxed=False)
class SDLCWorkflow:
    """Temporal workflow mirroring the Agentsflow SDLC pipeline."""

    @workflow.run
    async def run(self, params: SDLCWorkflowInput) -> SDLCWorkflowOutput:  # noqa: D401
        git_result = await workflow.execute_activity(
            "create_git_worktree",
            GitWorktreeRequest(
                repository=params.repository, reference=params.reference
            ),
            start_to_close_timeout=timedelta(minutes=4),
            retry_policy=RetryPolicy(maximum_attempts=3),
            result_type=GitWorktreeResult,
        )

        issue_result = await workflow.execute_activity(
            "read_issue",
            IssueRequest(issue_url=params.issue_url),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=4),
            result_type=IssueDetails,
        )

        task_payload = _build_task_payload(issue_result)

        coding_session_id: str | None = None
        review_session_id: str | None = None
        claude_runs: list[ClaudeRun] = []

        async def _invoke_claude(
            stage: Literal["implementation", "tests", "review"],
            prompt: str,
            *,
            session_kind: Literal["coding", "review"],
        ) -> ClaudeACPResponse:
            nonlocal coding_session_id, review_session_id
            session_id = (
                coding_session_id if session_kind == "coding" else review_session_id
            )
            response = await workflow.execute_activity(
                "claude_code_acp",
                ClaudeACPRequest(
                    prompt=prompt,
                    session_id=session_id,
                    workspace_dir=git_result.worktree_path,
                ),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=1),
                result_type=ClaudeACPResponse,
            )
            if session_kind == "coding":
                coding_session_id = response.session_id
            else:
                review_session_id = response.session_id
            claude_runs.append(
                ClaudeRun(
                    stage=stage,
                    prompt=prompt,
                    message=response.message,
                    stop_reason=response.stop_reason,
                )
            )
            return response

        async def _run_agent_activity(
            name: str,
            prompt: str,
            result_type,
            *,
            timeout_minutes: int = 2,
        ):
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
                    coding_prompt = _render_claude_prompt(
                        stage="implementation",
                        task=task_payload,
                        workspace_dir=git_result.worktree_path,
                        feedback=coding_feedback,
                    )
                    coding_response = await _invoke_claude(
                        "implementation", coding_prompt, session_kind="coding"
                    )
                    evaluation = await _run_agent_activity(
                        "run_evaluation_agent",
                        _render_evaluation_prompt(
                            stage="implementation",
                            task=task_payload,
                            transcript=coding_response.message,
                        ),
                        EvaluationOutput,
                    )

                    if evaluation.task_implemented:
                        coding_feedback = []
                        implementation_attempts = 0
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
                        tests_prompt = _render_claude_prompt(
                            stage="tests",
                            task=task_payload,
                            workspace_dir=git_result.worktree_path,
                            feedback=tests_feedback,
                        )
                        test_response = await _invoke_claude(
                            "tests", tests_prompt, session_kind="coding"
                        )

                        evaluation = await _run_agent_activity(
                            "run_evaluation_agent",
                            _render_evaluation_prompt(
                                stage="tests",
                                task=task_payload,
                                transcript=test_response.message,
                            ),
                            EvaluationOutput,
                        )

                        if evaluation.automated_tests_implemented:
                            tests_feedback = []
                            tests_attempts = 0
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
                    review_prompt_text = _render_claude_prompt(
                        stage="review",
                        task=task_payload,
                        workspace_dir=git_result.worktree_path,
                        feedback=review_feedback,
                    )
                    review_response = await _invoke_claude(
                        "review", review_prompt_text, session_kind="review"
                    )

                    review = await _run_agent_activity(
                        "run_review_agent",
                        _render_review_evaluation_prompt(
                            task_payload, review_response.message
                        ),
                        ReviewOutput,
                    )

                    if review.approval:
                        review_feedback = []
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
                _render_implementation_summary_prompt(task_payload, claude_runs),
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
                    _render_test_summary_prompt(task_payload, claude_runs),
                    TestPlanOutput,
                )
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
        finally:
            closed_session_ids: set[str] = set()
            if coding_session_id and coding_session_id not in closed_session_ids:
                await workflow.execute_activity(
                    "close_claude_session",
                    coding_session_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                closed_session_ids.add(coding_session_id)
            if review_session_id and review_session_id not in closed_session_ids:
                await workflow.execute_activity(
                    "close_claude_session",
                    review_session_id,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

        return SDLCWorkflowOutput(
            worktree_path=git_result.worktree_path,
            repository_path=git_result.repository_path,
            reference=git_result.reference,
            coding_session_id=coding_session_id,
            coding_stops=claude_runs,
            jira=task_payload,
            implementation=implementation,
            evaluation=evaluation,
            test_plan=test_plan,
            review=review,
            release_plan=release_plan,
            committed_branch=finalize_result.branch_name if finalize_result else None,
            committed_sha=finalize_result.commit_sha if finalize_result else None,
            commit_pushed=finalize_result.pushed if finalize_result else False,
        )


def _build_task_payload(details: IssueDetails) -> JiraTaskPayload:
    comments = [
        f"{comment.author}: {comment.body.strip()}"
        for comment in details.comments
        if comment.body and comment.body.strip()
    ]
    return JiraTaskPayload(
        issue_key=details.issue_key,
        summary=details.summary,
        description=details.description,
        comments=comments,
    )


def _render_claude_prompt(
    *,
    stage: Literal["implementation", "tests", "review"],
    task: JiraTaskPayload,
    workspace_dir: str | None,
    feedback: Sequence[str],
) -> str:
    base = [
        _format_task_section(task),
        f"Workspace directory: {workspace_dir or 'unknown'}",
    ]
    if feedback:
        base.append(
            "Outstanding feedback:\n" + "\n".join(f"- {item}" for item in feedback)
        )

    if stage == "implementation":
        base.append(
            "Implement the task end-to-end. Stay tightly scoped to the acceptance criteria—avoid creating placeholder assets, "
            "renaming files, or adding new dependencies unless they are essential to the solution. "
            "Summarise the work by listing each file you touched alongside the intent of the change."
        )
    elif stage == "tests":
        base.append(
            "Focus exclusively on automated tests. Limit edits to test code and supporting fixtures unless a minimal production "
            "change is strictly required for the tests to run. Report which tests you created or updated and any commands you ran."
        )
    else:  # review
        base.append(
            "Perform a thorough code review of the current workspace. Highlight blockers, risks, and suggested improvements. "
            "Do not make further code changes unless strictly required to inspect the code."
        )

    base.append(
        "When finished, provide a concise summary of your actions that enumerates every file you created or modified, "
        "explains the intent for each, and confirms you avoided unrelated or unnecessary changes."
    )
    return "\n\n".join(base)


def _render_evaluation_prompt(
    *, stage: Literal["implementation", "tests"], task: JiraTaskPayload, transcript: str
) -> str:
    focus = (
        "Decide whether the Jira task appears complete based on the transcript narrative. Assume the coding agent's statements are accurate unless they acknowledge missing work or failures."
        if stage == "implementation"
        else "Decide whether adequate automated tests now exist according to the transcript. Only treat the tests as implemented when the transcript references running automated suites, commands, or specific test artefacts; manual spot checks alone are insufficient."
    )
    parts = [
        _format_task_section(task),
        "Coding agent transcript:",
        transcript.strip() or "(no output)",
        f"{focus} Reply with EvaluationOutput so that task_implemented and automated_tests_implemented mirror the transcript's own claims. When the agent notes TODOs, failures, or uncertainty, mark the appropriate flag False and explain why.",
    ]
    return "\n\n".join(parts)


def _render_review_evaluation_prompt(task: JiraTaskPayload, transcript: str) -> str:
    parts = [
        _format_task_section(task),
        "Coding agent review transcript:",
        transcript.strip() or "(no output)",
        (
            "Summarise the review findings and respond with ReviewOutput. If you identify any issue or recommendation that requires modifying code, tests, documentation, or automation, classify it as an issue and set approval to False. Flag approval as False if any blocking issues remain or if the transcript lacks concrete evidence that code and automated tests were inspected. "
            "Ignore the state of git commits or untracked files—the workflow handles committing in a later step."
        ),
    ]
    return "\n\n".join(parts)


def _render_implementation_summary_prompt(
    task: JiraTaskPayload, runs: Sequence[ClaudeRun]
) -> str:
    relevant = [run for run in runs if run.stage in {"implementation", "tests"}]
    transcript = "\n\n".join(
        f"[{run.stage}] {run.message.strip()}" for run in relevant if run.message
    )
    parts = [
        _format_task_section(task),
        "Claude Code ACP sessions:",
        transcript or "(no transcript)",
        "Return an ImplementationOutput capturing the implemented behaviour, key steps, touched files, and testing considerations.",
    ]
    return "\n\n".join(parts)


def _render_test_summary_prompt(
    task: JiraTaskPayload, runs: Sequence[ClaudeRun]
) -> str:
    transcript = "\n\n".join(
        f"[{run.stage}] {run.message.strip()}"
        for run in runs
        if run.stage == "tests" and run.message
    )
    parts = [
        _format_task_section(task),
        "Claude Code ACP testing transcripts:",
        transcript or "(no dedicated testing transcript)",
        "Summarise the automated tests that now exist and respond with TestPlanOutput.",
    ]
    return "\n\n".join(parts)


def _render_release_prompt(
    task: JiraTaskPayload,
    implementation: ImplementationOutput,
    evaluation: EvaluationOutput,
    review: ReviewOutput,
    test_plan: TestPlanOutput | None,
) -> str:
    parts = [
        _format_task_section(task),
        _format_implementation_section(implementation),
        f"Final evaluation: task_implemented={evaluation.task_implemented}, automated_tests_implemented={evaluation.automated_tests_implemented}. Reasoning: {evaluation.reasoning}",
        _format_review_section(review),
    ]
    if test_plan is not None:
        parts.append(_format_test_plan_section(test_plan))
    parts.append(
        "Draft the source-control rollout details and respond with ReleasePlanOutput, including branch, commit message, PR title/body, and follow-up tasks."
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


def _format_task_section(task: JiraTaskPayload) -> str:
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
        _format_list_section(
            "Testing considerations", implementation.testing_considerations
        ),
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
    "SDLCWorkflow",
    "SDLCWorkflowInput",
    "SDLCWorkflowOutput",
    "ClaudeRun",
]
