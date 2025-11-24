"""FastMCP server exposing the process workflow."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from agentsflow.logging_utils import configure_logging
from agentsflow.settings import CLISettings
from agentsflow.workflow_client import (
    ClarificationPending,
    await_workflow_result,
    create_temporal_client,
    start_process_workflow,
)

configure_logging(CLISettings().log_level)

mcp = FastMCP(
    "AgentsFlow",
    instructions=(
        "This MCP server exposes the automation workflow. Start it with "
        "start_agentsflow_process (issue_url or task_text + repository_path) to receive the workflow_id/run_id, then "
        "call await_agentsflow_result with a list of workflow_ids; it returns after the first workflow finishes or "
        "pauses for clarification. Call again for remaining workflows. "
        "If a run pauses for clarifications, answer them via provide_agentsflow_clarification before waiting again. "
        "The repository_path argument must be the absolute filesystem path to the repo root "
        "(e.g., /Users/acme/src/app). "
        "Authentication, Temporal connection details, and overrides are read from environment variables or .env."
    ),
)


async def _start_workflow_tool_impl(
    *,
    issue_url: str | None,
    task_text: str | None,
    repository_path: str,
    ctx: Context,
    remind_about_result: bool,
) -> dict[str, Any]:
    defaults = CLISettings()
    if bool(issue_url) == bool(task_text):
        raise ValueError("Provide exactly one of issue_url or task_text.")

    target = f"issue {issue_url}" if issue_url else "ad-hoc task"
    await ctx.info(f"Submitting workflow for {target} against repository path {repository_path}.")

    handle = await start_process_workflow(
        address=defaults.address,
        namespace=defaults.namespace,
        task_queue=defaults.task_queue,
        repository=repository_path,
        reference=defaults.reference,
        issue_url=issue_url,
        task_text=task_text,
        branch_name=defaults.branch_name,
        coding_agent_provider=defaults.coding_agent_provider,
        model=defaults.model,
    )

    payload = {
        "workflow_id": handle.id,
        "run_id": handle.run_id,
        "first_execution_run_id": handle.first_execution_run_id,
        "task_queue": defaults.task_queue,
        "namespace": defaults.namespace,
        "address": defaults.address,
        "issue_url": issue_url,
        "task_text": task_text,
        "repository_path": repository_path,
        "branch_name": defaults.branch_name,
        "coding_agent_provider": defaults.coding_agent_provider,
    }

    if remind_about_result:
        await ctx.info("Workflow started. Call await_agentsflow_result with [workflow_id] to fetch the output.")

    return payload


async def _await_workflow_tool_impl(
    *,
    workflow_ids: list[str],
    ctx: Context,
) -> dict[str, Any]:
    defaults = CLISettings()
    if not workflow_ids:
        raise ValueError("Provide at least one workflow_id.")

    await ctx.info(f"Waiting for {len(workflow_ids)} workflow(s) (latest runs) to finish.")

    async def _wait_one(workflow_id: str) -> tuple[str, dict[str, Any]]:
        try:
            result = await await_workflow_result(
                defaults.address,
                defaults.namespace,
                workflow_id,
            )
            return workflow_id, {"status": "completed", "result": result.model_dump()}
        except ClarificationPending as pending:
            return workflow_id, {"status": "clarification_required", **pending.payload}

    task_map = {asyncio.create_task(_wait_one(wid)): wid for wid in workflow_ids}
    done, pending = await asyncio.wait(task_map.keys(), return_when=asyncio.FIRST_COMPLETED)

    results: dict[str, dict[str, Any]] = {}
    for task in done:
        workflow_id, payload = await task
        results[workflow_id] = payload
        await ctx.info(f"Workflow {workflow_id} finished with status {payload['status']}.")

    # Cancel remaining waits to avoid background work.
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    return results


@mcp.tool
async def provide_agentsflow_clarification(
    workflow_id: Annotated[str, Field(description="Workflow ID to resume")],
    answers: Annotated[list[str], Field(description="Answers to the clarification questions")],
    assumptions: Annotated[list[str] | None, Field(description="Optional list of assumptions to confirm")] = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Send clarification answers to an in-flight workflow."""

    defaults = CLISettings()
    client = await create_temporal_client(defaults.address, defaults.namespace)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("provide_clarification", args=[answers, assumptions or []])
    await ctx.info("Clarification signal delivered.")
    return {"status": "clarification_delivered"}


@mcp.tool
async def start_agentsflow_process(
    repository_path: Annotated[str, Field(description="Absolute filesystem path to the repository root")],
    issue_url: Annotated[
        str | None,
        Field(description="Issue URL to process (Jira/GitHub/etc.); mutually exclusive with task_text"),
    ] = None,
    task_text: Annotated[
        str | None,
        Field(
            description="Free-text task description when no issue_url is available; mutually exclusive with issue_url"
        ),
    ] = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Kick off the workflow asynchronously and return the workflow identifiers.

    Provide the repository_path as an absolute path on disk so the worker can access it.
    """

    return await _start_workflow_tool_impl(
        issue_url=issue_url,
        task_text=task_text,
        repository_path=repository_path,
        ctx=ctx,
        remind_about_result=True,
    )


@mcp.tool
async def await_agentsflow_result(
    workflow_ids: Annotated[
        list[str],
        Field(description="One or more workflow IDs to watch; returns after the first finishes or clarifies"),
    ],
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Wait for the specified workflow executions to finish and return their results."""

    return await _await_workflow_tool_impl(
        workflow_ids=workflow_ids,
        ctx=ctx,
    )


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    mcp.run()
