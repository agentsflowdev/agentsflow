# Operations & Runbooks

Operational procedures for the SDLC workflow and AgentsFlow worker.

## Worker lifecycle
- Start: `uv run python -m agentsflow.worker --task-queue agentsflow-sdlc`
- Stop: `Ctrl+C` (returns 130). Restart after config changes or upgrades so Temporal reloads activities.
- Logs: stdout/stderr; increase verbosity with `AGENTSFLOW_LOG_LEVEL=DEBUG`.

## Responding to clarifications
- When a run pauses for clarification, the CLI exits with status 2 and prints questions/assumptions.
- Provide answers via the MCP tool `provide_sdlc_clarification` or a Temporal signal named `provide_clarification` (args: lists of answers and assumptions).
- Re-run `await_sdlc_workflow_result` (MCP) or watch Temporal UI until the run resumes.

## Provider and auth issues
- Jira: ensure `JIRA_EMAIL`/`JIRA_API_TOKEN` are set and the issue host matches `atlassian.net`, contains `jira`, or is in `JIRA_HOST_ALLOWLIST`.
- GitHub: set `GITHUB_TOKEN` for private repos and to avoid anonymous rate limits.
- Timeouts: adjust `JIRA_TIMEOUT_SECONDS` or `GITHUB_TIMEOUT_SECONDS` when API latency is high.

## ACP agent troubleshooting
- Missing binaries raise `FileNotFoundError`; set `ACP_CLAUDE_BIN`, `ACP_GEMINI_BIN`, or `ACP_CODEX_BIN` or place the binaries on `PATH`.
- Disable auto-approval by exporting `ACP_AUTO_APPROVE=false` to require interactive confirmations in ACP sessions.

## Git hygiene
- Worktrees are cleaned up after `finalize_git_changes`, but interrupted runs may leave `temporal-worktree-*` directories. Remove them manually when safe.
- Commit and push errors are surfaced as workflow failures; rerun once repository permissions or remotes are fixed.

## Health checks
- Temporal Web UI (port 8233 in Docker Compose) shows workflow status, queries, and history.
- `temporal workflow list --namespace <ns>` confirms the worker is polling the expected task queue.
- Automated verification: `uv run --extra dev pytest -k sdlc_workflow` exercises the workflow entrypoints.
