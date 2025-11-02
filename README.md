AgentsFlow Temporal Activities
==============================

A lightweight Python package that bundles reusable Temporal activities for the
AgentsFlow SDLC automation pipeline. The activities encapsulate common
infrastructure steps—provisioning Git worktrees, pulling Jira issue metadata,
and interacting with Claude Code via the Agent Client Protocol (ACP)—so they
can be orchestrated inside Temporal workflows.

Contents
--------
- **Git Worktree**: creates an isolated worktree from a local repository or
  remote URL, returning the filesystem path for downstream tasks.
- **Jira Task Fetch**: retrieves issue summary, description, and comments using
  Jira REST APIs with sensible error handling and ADF-to-text conversion.
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
        activities.fetch_jira_task,
        activities.run_claude_code,
        activities.close_claude_session,
    ],
)

# Inside workflows, call the activities via the Temporal SDK APIs.
```

Each activity accepts and returns typed dataclasses defined in the `agentsflow`
package. Consult the docstrings in `agentsflow/activities/*.py` for parameter
details and payload structures.

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
