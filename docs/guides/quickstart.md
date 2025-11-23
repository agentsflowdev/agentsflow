# Quickstart

Spin up the SDLC workflow locally and run it end-to-end. These steps target new operators; see the deployment guide for containerised options.

## Prerequisites
- Python 3.12+, `uv`, and `git`
- A Temporal cluster (the launcher below will start `temporal server start-dev` when port 7233 is free, or you can point at your own cluster)
- Secrets: `OPENAI_API_KEY` plus issue provider credentials (choose Jira *or* GitHub below)
- Access to the target repository path on the worker host

## 1) Install dependencies
```bash
uv sync --extra dev
```

## 2) Configure environment
Create a `.env` alongside the repository or export the variables directly. Set the common values first, then only configure the issue provider you use (Jira or GitHub)—you do not need credentials for both.
```bash
OPENAI_API_KEY=sk-...
TEMPORAL_ADDRESS=127.0.0.1:7233
TEMPORAL_NAMESPACE=default
SDLC_TASK_QUEUE=agentsflow-sdlc

# Jira credentials (if using Jira)
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=atlassian-token

# GitHub credentials (if using GitHub Issues)
GITHUB_TOKEN=ghp_...
```
Set `AGENTSFLOW_LOG_LEVEL=DEBUG` if you want verbose logs, and use `ACP_AUTO_APPROVE=false` to require manual ACP confirmations.

## 3) Launch the stack (recommended)
Start everything—Temporal dev server, worker, and MCP server—with a single command and live logs:
```bash
python -m agentsflow.dev
```
By default it uses the `stdio` transport for MCP; override with `--transport http|sse|streamable-http` as needed. The launcher only starts Temporal if port 7233 is free; otherwise it reuses an existing cluster.

### Manual start (only if you need it)
- Start Temporal yourself: `temporal server start-dev` or `docker compose up temporal`
- Then run the worker: `uv run python -m agentsflow.worker --task-queue agentsflow-sdlc`
Keep the worker process running so activities stay registered.

## 4) Trigger the workflow
```bash
uv run python -m agentsflow.cli \
  --repository /path/to/repo \
  --issue-url https://example.atlassian.net/browse/ABC-123 \
  --json
```
Optional overrides: `--reference <branch|tag>`, `--model <chat-model>`, `--branch <target-branch>`, or `--coding-agent-provider claude|gemini|codex`. Each run auto-generates a workflow ID like `sdlc-1a2b3c4d`.

## 5) Validate the install
Run the existing tests to verify the environment and credentials:
```bash
uv run --extra dev pytest -k sdlc_workflow
```

## Next steps
- Deployment options: [Deployment](deployment.md)
- Provider specifics: [Providers](providers.md)
- Full workflow behaviour: [SDLC Workflow](../workflows/sdlc.md)
