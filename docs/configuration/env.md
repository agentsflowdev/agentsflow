# Environment Variables

AgentsFlow entry points load configuration from environment variables. If you prefer `.env` files, load them yourself (e.g., `direnv`, `uv run --env-file`, or your process manager) before starting the CLI, MCP server, or worker. Defaults are chosen for local development; production deployments should supply explicit values.

## Temporal connection & workflow routing
- `TEMPORAL_ADDRESS` (default `127.0.0.1:7233`) – Temporal frontend address for CLI, worker, and MCP.
- `TEMPORAL_NAMESPACE` (default `default`) – Temporal namespace to target.
- `PROCESS_TASK_QUEUE` (default `process-workflow`) – Task queue polled by the worker and targeted by the CLI/MCP.

## Workflow inputs & agent overrides
- `PROCESS_CODING_AGENT_PROVIDER` (default `claude`) – ACP binary to use: `claude`, `gemini`, or `codex`.
- `PROCESS_AGENT_MODEL` – Overrides the OpenAI chat model used by the Pydantic AI agents.
- `PROCESS_JSON_OUTPUT` – Set to `true` to default the CLI to JSON output.

## Authentication & provider settings
- `OPENAI_API_KEY` (required) – Used by the Pydantic AI agents inside the workflow activities.
- `JIRA_EMAIL` / `JIRA_API_TOKEN` (required for Jira) – Credentials for Jira issue reads.
- `JIRA_HOST_ALLOWLIST` – Comma-separated hostnames to treat as Jira instances even without `jira` in the domain.
- `JIRA_TIMEOUT_SECONDS` – Override the default Jira request timeout (must be > 0).
- `GITHUB_TOKEN` – Token for GitHub issue reads (optional but recommended for private repos and higher rate limits).
- `GITHUB_TIMEOUT_SECONDS` – Override the GitHub request timeout (must be > 0).

## ACP binaries & permissions
- `ACP_AUTO_APPROVE` (default `true`) – Auto-approve ACP permissions; set `false` to prompt for approvals.
- `ACP_CLAUDE_BIN` / `ACP_GEMINI_BIN` / `ACP_CODEX_BIN` – Custom paths to ACP binaries; otherwise the worker searches `PATH`.
- `ACP_STREAM_READER_LIMIT` (default `8388608`) – Maximum bytes read from ACP streaming responses; increase for very large transcripts.
- `PROCESS_ACP_ACTIVITY_TIMEOUT_MINUTES` (default `60`) – Start-to-close timeout in minutes for ACP activity invocations; must be greater than zero.

## Logging & diagnostics
- `AGENTSFLOW_LOG_LEVEL` (default `INFO`) – Controls verbosity for CLI, worker, and MCP logs.

Store secrets outside version control; if you keep a local `.env`, ensure it is never committed and is loaded by your shell/process manager before running AgentsFlow.
