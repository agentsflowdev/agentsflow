# MCP Server

The FastMCP bridge exposes the SDLC workflow to MCP-compatible clients using the same settings as the CLI.

## Run the server
```bash
uv run fastmcp run agentsflow/mcp_server.py
```
It respects `.env` values for Temporal (`TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`), workflow defaults (`SDLC_*`), and credentials (`OPENAI_API_KEY`, Jira/GitHub tokens).

## Tools
- `start_sdlc_workflow(issue_url, repository_path)` – Starts the workflow asynchronously and returns `workflow_id`, `run_id`, `task_queue`, and connection metadata. `repository_path` must be an absolute path reachable by the worker host.
- `await_sdlc_workflow_result(workflow_id)` – Waits for the latest run of the workflow and returns the serialized `SDLCWorkflowOutput`. If the run paused for clarification, the payload contains the open questions/assumptions instead.
- `provide_sdlc_clarification(workflow_id, answers, assumptions=None)` – Signals the workflow to resume after a clarification pause.

## Operational tips
- Run the MCP server near the worker to avoid network egress on repository paths and Temporal traffic.
- Clarification flows mirror the CLI: call `start`, then `await`, respond with `provide_sdlc_clarification` if needed, and `await` again.
