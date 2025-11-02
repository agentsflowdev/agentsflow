"""FastMCP server exposing the AgentsFlow SDLC workflow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastmcp import Context, FastMCP

from agentsflow.cli import CLISettings, _run_workflow

mcp = FastMCP(
    "AgentsFlow SDLC",
    instructions=(
        "Run the AgentsFlow SDLC Temporal workflow. Provide a Jira issue URL and "
        "a git repository path. Jira authentication, Temporal connection details, "
        "and optional overrides are read from environment variables or the project's .env file."
    ),
)


@mcp.tool
async def run_sdlc_workflow(
    jira_url: str,
    repository: str,
    *,
    ctx: Context,
) -> dict[str, Any]:
    """Start the SDLC workflow and return the structured result."""
    defaults = CLISettings()

    if defaults.jira_email is None or defaults.jira_token is None:
        raise RuntimeError(
            "Jira credentials are missing. Set JIRA_EMAIL and JIRA_API_TOKEN in the environment or .env file."
        )

    args = SimpleNamespace(
        repository=repository,
        jira_url=jira_url,
        jira_email=defaults.jira_email,
        jira_token=defaults.jira_token,
        reference=defaults.reference,
        address=defaults.address,
        namespace=defaults.namespace,
        task_queue=defaults.task_queue,
        workflow_id=defaults.workflow_id,
        model=defaults.model,
    )

    await ctx.info(
        f"Starting SDLC workflow for Jira issue {jira_url} against repository {repository}."
    )

    result = await _run_workflow(args)

    await ctx.info("Workflow completed successfully.")

    return result.model_dump()


if __name__ == "__main__":  # pragma: no cover - manual execution helper
    mcp.run()
