# MCP Server

The FastMCP bridge exposes the process workflow to MCP-compatible clients using the same settings as the CLI.

## Run the server
```bash
uv run fastmcp run agentsflow/mcp_server.py
```
Environment variables configure Temporal (`TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`), workflow defaults (`PROCESS_TASK_QUEUE`, `PROCESS_AGENT_MODEL`), and credentials (`OPENAI_API_KEY`, Jira/GitHub tokens). Load them however you prefer (shell export, direnv, uv --env-file, etc.).

## Tools
- `start_agentsflow_process(issue_url=None, task_text=None, repository_path)` – Starts the workflow asynchronously and returns `workflow_id`, `run_id`, `task_queue`, and connection metadata. Provide exactly one of `issue_url` (Jira/GitHub/etc.) **or** `task_text` (free-form description). `repository_path` must be an absolute path reachable by the worker host.
- `await_agentsflow_result(workflow_ids)` – Accepts a list of workflow IDs, returns after the *first* workflow finishes or pauses, and includes only that workflow's payload. Call again with the remaining IDs to drain the rest. Payload shape: `{status: "completed", result: ProcessWorkflowOutput}` or `{status: "clarification_required", ...}`.
- `provide_agentsflow_clarification(workflow_id, answers, assumptions=None)` – Signals the workflow to resume after a clarification pause.

## Operational tips
- Run the MCP server near the worker to avoid network egress on repository paths and Temporal traffic.
- Clarification flows mirror the CLI: call `start`, then `await`, respond with `provide_agentsflow_clarification` if needed, and `await` again.
