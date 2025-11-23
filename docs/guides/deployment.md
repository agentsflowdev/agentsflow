# Deployment

Choose between local processes, Docker Compose, or the MCP server. All options rely on the same Temporal workflow and activities.

## Local processes (default)
1. Start Temporal (dev): `temporal server start-dev` or point `TEMPORAL_ADDRESS`/`TEMPORAL_NAMESPACE` at an existing cluster.
2. Export secrets (`OPENAI_API_KEY`, `JIRA_EMAIL`/`JIRA_API_TOKEN` or `GITHUB_TOKEN`) in `.env`.
3. Launch the worker:
   ```bash
   uv run python -m agentsflow.worker --task-queue process-workflow
   ```
4. Trigger workflows from another shell via the CLI or MCP (see reference pages). Keep the worker running so activities stay registered.

## Docker Compose
`docker compose up --build` starts three services:
- `temporal` – Temporal dev server (ports 7233 gRPC / 8233 Web UI).
- `worker` – AgentsFlow worker with hot-reloaded source mounted from the host.
- `mcp-server` – FastMCP bridge exposing the same workflow.

Pass credentials from the host environment (as shown in `docker-compose.yml`). Rebuild when dependencies change: `docker compose build --pull`.

## MCP server
Run the FastMCP bridge against an existing Temporal cluster:
```bash
uv run fastmcp run agentsflow/mcp_server.py
```
It reuses the CLI defaults for Temporal connection and environment variables. Ensure `repository_path` values passed to the tools are absolute paths visible to the worker host.

## Operational knobs
- `ACP_AUTO_APPROVE=false` to require ACP permission prompts instead of auto-approving.
- `PROCESS_CODING_AGENT_PROVIDER` selects `claude` (default), `gemini`, or `codex` ACP binaries; override binary paths with `ACP_CLAUDE_BIN`, `ACP_GEMINI_BIN`, or `ACP_CODEX_BIN`.
- `AGENTSFLOW_LOG_LEVEL=DEBUG` increases verbosity for both CLI and worker processes.
