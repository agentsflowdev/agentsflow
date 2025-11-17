# Repository Guidelines

## Project Structure & Module Organization
Temporal activities live in `agentsflow/activities/` (git worktree, issue ingestion, Claude ACP). Workflows reside in `agentsflow/workflows/`; entry points are `agentsflow/worker.py` and `agentsflow/cli.py`. Shared agent utilities (`agentsflow/agents/`, `agentsflow/issues/`) feed both the CLI and the FastMCP server (`agentsflow/mcp_server.py`). Tests in `tests/` mirror module names (e.g., `test_sdlc_workflow.py`), and SDLC fixtures live in `SDLC.json`.

## Build, Test & Development Commands
- `uv sync --extra dev` – install pinned deps for Python 3.12+ plus dev extras.
- `uv run --extra dev pytest` – run the async pytest suite; append `tests/test_git_worktree.py` to scope it.
- `python -m agentsflow.worker` – start the Temporal worker; reads `.env` for `TEMPORAL_ADDRESS`, `SDLC_TASK_QUEUE`, credentials.
- `python -m agentsflow.cli --issue-url … --repository … --json` – kick off the SDLC workflow locally with optional overrides.
- `uv run fastmcp run agentsflow/mcp_server.py` – expose the same workflow over MCP for agent clients.

## Coding Style & Naming Conventions
Stick to PEP 8, four-space indentation, and type hints on every public function. Keep orchestration lightweight in `agentsflow/activities/__init__.py`; push filesystem or API logic into dedicated modules and return typed dataclasses (`GitWorktreeResult`). Use snake_case for callables, PascalCase for models, ALL_CAPS for env vars, and structured `activity.logger` messages.

## Testing Guidelines
Pytest plus `pytest-asyncio` cover activities and workflows; place new async tests in `tests/test_<module>.py` beside existing fixtures and stub Temporal or ACP calls instead of hitting real services. Run `uv run --extra dev pytest -k <feature>` before pushing and keep coverage on par with modified modules.

## Commit & Pull Request Guidelines
Recent history favors short, imperative summaries (`Add branch override flag`), so mirror that style and keep the subject under ~70 characters. Each PR should link the Jira/GitHub issue, describe workflow or activity impacts, list new env vars, and paste the relevant CLI/pytest output or Temporal screenshots. Call out migration steps (schema, credentials, worktree paths) so downstream agents can replay them.

## Security & Configuration Tips
Never commit `.env`; instead export secrets such as `JIRA_API_TOKEN`, `OPENAI_API_KEY`, `CLAUDE_CODE_BIN`, and repo-specific tokens locally. Scrub logs and CLI output before sharing because activity traces often include issue descriptions, file paths, and credentials, and prefer isolated worktrees created by `create_git_worktree` when testing untrusted changes.
