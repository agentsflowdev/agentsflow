"""FastMCP server exposing the AgentsFlow SDLC workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastmcp import Context, FastMCP

from agentsflow.cli import CLISettings, _await_workflow_result, _start_workflow_handle

mcp = FastMCP(
    "AgentsFlow SDLC",
    instructions=(
        "AgentsFlow exposes the SDLC Temporal workflow over MCP. Start the workflow with "
        "start_sdlc_workflow (issue_url + repository, optional branch/workflow_id) to receive the workflow_id/run_id, then call "
        "await_sdlc_workflow_result with those identifiers when you're ready to fetch the SDLCWorkflowOutput. "
        "If you prefer a single blocking call, run_sdlc_workflow chains both steps. "
        "Authentication, Temporal connection details, and overrides are read from environment variables or .env."
    ),
)


def _build_workflow_args(
    *,
    defaults: CLISettings,
    repository: str,
    issue_url: str,
    branch_name: str | None,
    workflow_id: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        repository=repository,
        issue_url=issue_url,
        reference=defaults.reference,
        address=defaults.address,
        namespace=defaults.namespace,
        task_queue=defaults.task_queue,
        workflow_id=workflow_id or defaults.workflow_id,
        model=defaults.model,
        branch_name=branch_name or defaults.branch_name,
    )


async def _start_workflow_tool_impl(
    *,
    issue_url: str,
    repository: str,
    branch_name: str | None,
    workflow_id: str | None,
    ctx: Context,
    remind_about_result: bool,
) -> dict[str, Any]:
    defaults = CLISettings()
    args = _build_workflow_args(
        defaults=defaults,
        repository=repository,
        issue_url=issue_url,
        branch_name=branch_name,
        workflow_id=workflow_id,
    )

    await ctx.info(
        f"Submitting SDLC workflow for issue {issue_url} against repository {repository}."
    )

    handle = await _start_workflow_handle(args)

    payload = {
        "workflow_id": handle.id,
        "run_id": handle.run_id,
        "first_execution_run_id": handle.first_execution_run_id,
        "task_queue": args.task_queue,
        "namespace": args.namespace,
        "address": args.address,
        "issue_url": issue_url,
        "repository": repository,
        "branch_name": args.branch_name,
    }

    if remind_about_result:
        await ctx.info(
            "Workflow started. Call await_sdlc_workflow_result with the workflow_id/run_id to fetch the output."
        )

    return payload


async def _await_workflow_tool_impl(
    *,
    workflow_id: str,
    run_id: str | None,
    ctx: Context,
) -> dict[str, Any]:
    defaults = CLISettings()
    await ctx.info(
        f"Waiting for workflow {workflow_id} (run {run_id or 'latest'}) to finish."
    )
    result = await _await_workflow_result(
        defaults.address,
        defaults.namespace,
        workflow_id,
        run_id=run_id,
    )
    await ctx.info("Workflow completed successfully.")
    return result.model_dump()


@mcp.tool
async def start_sdlc_workflow(
    issue_url: str,
    repository: str,
    branch_name: str | None = None,
    workflow_id: str | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Kick off the workflow asynchronously and return the workflow identifiers."""

    return await _start_workflow_tool_impl(
        issue_url=issue_url,
        repository=repository,
        branch_name=branch_name,
        workflow_id=workflow_id,
        ctx=ctx,
        remind_about_result=True,
    )


@mcp.tool
async def await_sdlc_workflow_result(
    workflow_id: str,
    run_id: str | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Wait for the specified workflow execution to finish and return the result."""

    return await _await_workflow_tool_impl(
        workflow_id=workflow_id,
        run_id=run_id,
        ctx=ctx,
    )


@mcp.tool
async def run_sdlc_workflow(
    issue_url: str,
    repository: str,
    branch_name: str | None = None,
    workflow_id: str | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Backwards-compatible synchronous workflow run. Prefer the start/await tools for async control."""

    start_payload = await _start_workflow_tool_impl(
        issue_url=issue_url,
        repository=repository,
        branch_name=branch_name,
        workflow_id=workflow_id,
        ctx=ctx,
        remind_about_result=False,
    )
    return await _await_workflow_tool_impl(
        workflow_id=start_payload["workflow_id"],
        run_id=start_payload["run_id"],
        ctx=ctx,
    )


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    mcp.run()
