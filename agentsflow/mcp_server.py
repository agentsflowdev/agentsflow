"""FastMCP server exposing the AgentsFlow SDLC workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastmcp import Context, FastMCP

from agentsflow.cli import CLISettings, _await_workflow_result, _start_workflow_handle
from agentsflow.logging_utils import configure_logging

configure_logging(CLISettings().log_level)

mcp = FastMCP(
    "AgentsFlow SDLC",
    instructions=(
        "AgentsFlow exposes the SDLC Temporal workflow over MCP. Start the workflow with "
        "start_sdlc_workflow (issue_url + repository_path, optional branch) to receive the workflow_id/run_id, then call "
        "await_sdlc_workflow_result with the workflow_id when you're ready to fetch the SDLCWorkflowOutput. "
        "The repository_path argument must be the absolute filesystem path to the repo root (e.g., /Users/acme/src/app). "
        "Authentication, Temporal connection details, and overrides are read from environment variables or .env."
    ),
)


def _build_workflow_args(
    *,
    defaults: CLISettings,
    repository_path: str,
    issue_url: str,
    branch_name: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        repository=repository_path,
        issue_url=issue_url,
        reference=defaults.reference,
        address=defaults.address,
        namespace=defaults.namespace,
        task_queue=defaults.task_queue,
        model=defaults.model,
        branch_name=branch_name or defaults.branch_name,
    )


async def _start_workflow_tool_impl(
    *,
    issue_url: str,
    repository_path: str,
    branch_name: str | None,
    ctx: Context,
    remind_about_result: bool,
) -> dict[str, Any]:
    defaults = CLISettings()
    args = _build_workflow_args(
        defaults=defaults,
        repository_path=repository_path,
        issue_url=issue_url,
        branch_name=branch_name,
    )

    await ctx.info(
        f"Submitting SDLC workflow for issue {issue_url} against repository path {repository_path}."
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
        "repository_path": repository_path,
        "branch_name": args.branch_name,
    }

    if remind_about_result:
        await ctx.info(
            "Workflow started. Call await_sdlc_workflow_result with the workflow_id to fetch the output."
        )

    return payload


async def _await_workflow_tool_impl(
    *,
    workflow_id: str,
    ctx: Context,
) -> dict[str, Any]:
    defaults = CLISettings()
    await ctx.info(f"Waiting for workflow {workflow_id} (latest run) to finish.")
    result = await _await_workflow_result(
        defaults.address,
        defaults.namespace,
        workflow_id,
    )
    await ctx.info("Workflow completed successfully.")
    return result.model_dump()


@mcp.tool
async def start_sdlc_workflow(
    issue_url: str,
    repository_path: str,
    branch_name: str | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Kick off the workflow asynchronously and return the workflow identifiers.

    Provide the repository_path as an absolute path on disk so the worker can access it.
    """

    return await _start_workflow_tool_impl(
        issue_url=issue_url,
        repository_path=repository_path,
        branch_name=branch_name,
        ctx=ctx,
        remind_about_result=True,
    )


@mcp.tool
async def await_sdlc_workflow_result(
    workflow_id: str,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Wait for the specified workflow execution to finish and return the result."""

    return await _await_workflow_tool_impl(
        workflow_id=workflow_id,
        ctx=ctx,
    )


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    mcp.run()
