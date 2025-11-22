# Upgrade Notes

Guidance for rolling AgentsFlow deployments forward while keeping docs and dependencies in sync.

## Updating local or server installs
1. Pull the latest code: `git pull`
2. Refresh dependencies (pinned via `uv.lock`):
   ```bash
   uv sync --extra dev --frozen
   ```
3. Re-run tests to confirm the environment:
   ```bash
   uv run --extra dev pytest
   ```
4. Restart long-running workers so Temporal loads the updated activities and workflow definitions.

## Containerised environments
- Rebuild images after dependency or Python changes: `docker compose build --pull`
- Restart the stack: `docker compose up -d`
- Verify the worker logs and Temporal UI (port 8233) for healthy task polling.

## Docs site (mike + MkDocs)
- Preview locally: `uv run mkdocs serve`
- Publish a new docs version (replace `vX.Y` with the release tag):
  ```bash
  uv run mike deploy vX.Y latest
  uv run mike set-default latest
  ```
- Commit the updated `gh-pages` branch per your release process.

## Tracking breaking changes
- New or renamed environment variables should be captured in the [Environment Variables](../configuration/env.md) reference and communicated to operators before rollout.
- Temporal workflow changes that alter inputs/outputs should be coordinated with MCP clients and any automation that parses `SDLCWorkflowOutput`.
