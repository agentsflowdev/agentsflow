"""FastMCP server exposing the process workflow."""

from __future__ import annotations

import argparse
from typing import Any

from fastmcp import Context, FastMCP

from agentsflow.cli import CLISettings
from agentsflow.logging_utils import configure_logging
from agentsflow.workflow_client import _await_first_change, _create_temporal_client, _start_workflow_handle

_LAST_SEEN_EVENT: dict[str, int] = {}

configure_logging(CLISettings().log_level)

mcp = FastMCP(
    "AgentsFlow",
    instructions=(
        "This MCP server exposes the automation workflow. Start it with "
        "start_agentsflow_process (issue_url or task_text + repository_path) to receive the workflow_id/run_id, then "
        "call await_agentsflow_result with the workflow_ids list to get the first completion or clarification event. "
        "If a run pauses for clarifications, answer them via provide_agentsflow_clarification before waiting again. "
        "The repository_path argument must be the absolute filesystem path to the repo root "
        "(e.g., /Users/acme/src/app). "
        "Authentication, Temporal connection details, and overrides are read from environment variables or .env."
    ),
)


def _build_workflow_args(
    *,
    defaults: CLISettings,
    repository_path: str,
    issue_url: str | None,
    task_text: str | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        repository=repository_path,
        issue_url=issue_url,
        task_text=task_text,
        reference=defaults.reference,
        address=defaults.address,
        namespace=defaults.namespace,
        task_queue=defaults.task_queue,
        model=defaults.model,
        branch_name=defaults.branch_name,
        coding_agent_provider=defaults.coding_agent_provider,
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
    args = _build_workflow_args(
        defaults=defaults,
        repository_path=repository_path,
        issue_url=issue_url,
        task_text=task_text,
    )

    target = f"issue {issue_url}" if issue_url else "ad-hoc task"
    await ctx.info(f"Submitting workflow for {target} against repository path {repository_path}.")

    handle = await _start_workflow_handle(args)

    payload = {
        "workflow_id": handle.id,
        "run_id": handle.run_id,
        "first_execution_run_id": handle.first_execution_run_id,
        "task_queue": args.task_queue,
        "namespace": args.namespace,
        "address": args.address,
        "issue_url": issue_url,
        "task_text": task_text,
        "repository_path": repository_path,
        "branch_name": args.branch_name,
        "coding_agent_provider": args.coding_agent_provider,
    }

    if remind_about_result:
        await ctx.info(
            "Workflow started. Call await_agentsflow_result with one or more workflow_ids to fetch the first change."
        )

    return payload


@mcp.tool
async def provide_agentsflow_clarification(
    workflow_id: str,
    answers: list[str],
    assumptions: list[str] | None = None,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Send clarification answers to an in-flight workflow."""

    defaults = CLISettings()
    client = await _create_temporal_client(defaults.address, defaults.namespace)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("provide_clarification", args=[answers, assumptions or []])
    await ctx.info("Clarification signal delivered.")
    return {"status": "clarification_delivered"}


@mcp.tool
async def start_agentsflow_process(
    repository_path: str,
    issue_url: str | None = None,
    task_text: str | None = None,
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
    workflow_ids: list[str],
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Return the first completion/clarification across the provided workflow_ids."""

    defaults = CLISettings()
    await ctx.info(f"Waiting for first change across {len(workflow_ids)} workflow(s).")
    event = await _await_first_change(
        defaults.address,
        defaults.namespace,
        workflow_ids,
        seen_event_ids=_LAST_SEEN_EVENT,
    )
    await ctx.info(
        f"Workflow {event['workflow_id']} reported {event['kind']}.",
    )
    if event.get("result"):
        # pydantic models -> dict for MCP transport
        event["result"] = event["result"].model_dump()
    if event.get("event_id") is not None:
        _LAST_SEEN_EVENT[event["workflow_id"]] = event["event_id"]
    return event


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    mcp.run()
