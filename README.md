AgentsFlow Temporal Activities
==============================

A lightweight Python package that bundles reusable Temporal activities for the
AgentsFlow SDLC automation pipeline. The activities encapsulate common
infrastructure steps—provisioning Git worktrees, pulling Jira or GitHub issue metadata,
and interacting with Claude Code via the Agent Client Protocol (ACP)—so they
can be orchestrated inside Temporal workflows.

Contents
--------
- **Git Worktree**: creates an isolated worktree from a local repository or
  remote URL, returning the filesystem path for downstream tasks.
- **Issue Reader**: dispatches to Jira or GitHub based on the issue URL, normalising
  summaries, descriptions, statuses, and comments for downstream agents.
- **Claude Code ACP**: manages ACP sessions, streams prompts to the
  `claude-code-acp` binary, and returns responses while supporting session
  reuse and cleanup.

Project Layout
--------------
- `agentsflow/activities/` – activity implementations and helpers.
- `agentsflow/__init__.py` – re-export convenience types and the
  `AgentsFlowActivities` bundle for worker registration.
- `tests/` – async pytest coverage for each activity module.
- `pyproject.toml` – package metadata managed by `uv`.

Getting Started
---------------
1. **Install dependencies** (Python 3.12+):

   ```bash
   uv sync --extra dev
   ```

2. **Run tests** to verify the environment:

   ```bash
   uv run --extra dev pytest
   ```

Using the Activities
--------------------
Register the provided activities with your Temporal worker:

```python
from temporalio.worker import Worker

from agentsflow import AgentsFlowActivities, GitWorktreeRequest

activities = AgentsFlowActivities(claude_binary="/usr/local/bin/claude-code-acp")

worker = Worker(
    client=temporal_client,
    task_queue="agentsflow-sdlc",
    activities=[
        activities.create_git_worktree,
        activities.read_issue,
        activities.run_claude_code,
        activities.close_claude_session,
    ],
)

# Inside workflows, call the activities via the Temporal SDK APIs.
```

Each activity accepts and returns typed dataclasses defined in the `agentsflow`
package. Consult the docstrings in `agentsflow/activities/*.py` for parameter
details and payload structures. Issue providers read their credentials directly
from the worker environment: export `JIRA_EMAIL`, `JIRA_API_TOKEN`, and
`GITHUB_TOKEN` (plus optional `JIRA_TIMEOUT_SECONDS` / `GITHUB_TIMEOUT_SECONDS`)
before starting the worker so every activity invocation can authenticate.

SDLC Workflow
-------------
The repository also ships with a high-level workflow that mirrors the Agentsflow
SDLC pipeline while relying on [PydanticAI's Temporal integration](https://ai.pydantic.dev/durable_execution/temporal/)
for LLM calls. Register it alongside the activities:

```python
import os

from temporalio.worker import Worker

from agentsflow import AgentsFlowActivities
from agentsflow.workflows import SDLCWorkflow, SDLCWorkflowInput

activities = AgentsFlowActivities()

worker = Worker(
    client=temporal_client,
    task_queue="agentsflow-sdlc",
    activities=[
        activities.create_git_worktree,
        activities.read_issue,
    ],
    workflows=[SDLCWorkflow],
)

execution = await temporal_client.start_workflow(
    SDLCWorkflow.run,
    SDLCWorkflowInput(
        repository="git@github.com:example/repo.git",
        reference="main",
        issue_url="https://example.atlassian.net/browse/ABC-123",
    ),
    id="abc-123",
    task_queue="agentsflow-sdlc",
)
result = await execution.result()
print(result.model_dump())
```

Set `SDLC_AGENT_MODEL` to override the default OpenAI chat model used by the
underlying agents when necessary.

Running the Workflow
--------------------
You can start the full SDLC flow using one of the following methods:

### Option 1: Docker Compose (Recommended)
Run the entire stack in containers:

```bash
docker-compose up
```

This starts Temporal, the Worker, and the MCP Server. The source code is mounted so changes are reflected immediately in the worker and MCP server.

### Option 2: Local Dev Script
If you prefer running natively, use the dev launcher script. This requires `temporal` CLI to be installed or running separately.

```bash
python -m agentsflow.dev
```

This script will:
1. Start Temporal (if not already running).
2. Start the Worker.
3. Start the MCP Server.
4. Stream logs to `logs/`.

### Option 3: Manual Startup
After configuring `.env` you can start the full SDLC flow with three steps:

1. **Start Temporal** – run the Temporal CLI or your own cluster (`temporal server start-dev`).
2. **Launch the worker** – from the project root, the worker reads `.env` for
   values like `TEMPORAL_ADDRESS`, `OPENAI_API_KEY`, `SDLC_TASK_QUEUE`,
   `CLAUDE_CODE_BIN`, and `CLAUDE_AUTO_APPROVE` and falls back to flags when
   provided:

   ```bash
   python -m agentsflow.worker
   ```

   The worker automatically registers the Pydantic v2 data converter so models are
   serialised/deserialised without warnings. It also exposes the Claude Code ACP
   activity plus TemporalAgent plugins used for verification. Use
   `python -m agentsflow.worker --help` to override defaults (e.g. task queue or server address).
3. **Trigger the workflow** – in another shell run the CLI. Any flag overrides
   the `.env` values; for a minimal run specify the issue URL and repository path
   if they are not already present as `SDLC_ISSUE_URL` / `SDLC_REPOSITORY` (or
   the legacy `SDLC_JIRA_URL`) in `.env`:

   ```bash
   python -m agentsflow.cli \
     --repository /path/to/checkout \
     --issue-url https://example.atlassian.net/browse/ABC-123 \
      --json
   ```

   Add `--reference` or `--model` when you need to deviate from the values stored in `.env`.
   Each CLI invocation now generates a random workflow ID shaped like `sdlc-1a2b3c4d`,
   ensuring every run is unique without any manual overrides.

FastMCP Server
--------------
You can invoke the same Temporal workflow through an [MCP](https://github.com/modelcontextprotocol/cli) server powered by
[FastMCP](https://github.com/jlowin/fastmcp). The server is defined in `agentsflow/mcp_server.py`
and now exposes asynchronous control via two tools:

1. `start_sdlc_workflow` – kicks off the workflow and returns the `workflow_id` / `run_id` so the client can poll later. Required params: `issue_url`, `repository_path`.
2. `await_sdlc_workflow_result` – waits for the latest execution of the specified workflow to finish. Required param: `workflow_id`.

All workflow settings are sourced from environment variables via `CLISettings`.
Ensure the following are exported or placed in `.env` before invoking a tool:

- `JIRA_EMAIL` – Jira username used for API authentication
- `JIRA_API_TOKEN` – Jira API token/password
- `GITHUB_TOKEN` – GitHub personal access token for GitHub issue reads
- `OPENAI_API_KEY` – used by the SDLC coding/verification agents
- Optional overrides: `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `SDLC_TASK_QUEUE`, `SDLC_AGENT_MODEL`, `SDLC_REFERENCE`

Run the server over stdio (ideal for MCP-compatible clients):

```bash
uv run fastmcp run agentsflow/mcp_server.py
```

Clients supply the Jira URL and absolute repository path when calling the tool. The returned payload is the structured
`SDLCWorkflowOutput` from Temporal, allowing downstream automations to inspect paths, Claude transcripts, and verification artefacts.

Workflow stages
---------------
1. **Git worktree & Jira fetch** – activities clone an isolated worktree and
   pull the Jira task metadata.
2. **Coding agent (Claude Code ACP)** – the workflow prompts the Claude ACP
   binary to implement the task directly inside the worktree. It loops through
   ACP sessions until the verification checks confirm the task is complete.
3. **Verification agents (PydanticAI)** – once a coding pass finishes, the
   verification agents summarise the transcript, evaluate task coverage, and
   decide whether automated tests exist. Failed checks push the workflow back to
   Claude Code ACP for another iteration (for example, a dedicated testing run).
   When everything passes, additional agents perform the review and outline the
   release plan. These agents never modify the repository—they only analyse the
   coding agent’s output.
4. **Structured result** – the workflow returns the repository path alongside the
   Claude transcript and all verification artefacts (`ImplementationOutput`,
   `EvaluationOutput`, `TestPlanOutput`, `ReviewOutput`, `ReleasePlanOutput`).

Development Notes
-----------------
- The project uses `uv` for dependency management; run `uv sync` whenever
  `pyproject.toml` changes.
- Activities use `asyncio.to_thread` to offload blocking I/O; no additional
  threading primitives are required when invoking them from workflows.
- When working on the Claude ACP activity, set the `ACP_CLAUDE_BIN` environment
  variable or supply `claude_binary` to `AgentsFlowActivities` to point at your
  local `claude-code-acp` binary.

License
-------
TBD – add project licensing information here.
