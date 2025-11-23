# Quickstart

Spin up the process workflow locally and run it end-to-end. The recommended way to run AgentsFlow is as an MCP server using `uvx`.

## Prerequisites

- **uvx** (from [uv](https://github.com/astral-sh/uv#installation))
- **Temporal CLI/dev server**: install and run via https://docs.temporal.io/cli (the stack will auto-start a local dev server if port 7233 is free)
- **Secrets**: `OPENAI_API_KEY` plus issue provider credentials (Jira or GitHub)

## 1) Option 1: Use with AI Assistant (Recommended)

To use AgentsFlow with your AI assistant, configure it as an MCP server.

### Claude Code
```bash
claude mcp add agentsflow --scope user --env OPENAI_API_KEY=sk-... -- uvx agentsflow
```

### Gemini CLI
```bash
gemini mcp add agentsflow --scope user --env OPENAI_API_KEY=sk-... -- uvx agentsflow
```

### Codex CLI
```bash
codex mcp add agentsflow --env OPENAI_API_KEY=sk-... -- uvx agentsflow
```

### Cursor
Add to `.cursor/mcp.json` or configure via **Settings > MCP**:

```json
{
  "mcpServers": {
    "agentsflow": {
      "command": "uvx",
      "args": ["agentsflow"],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

## 2) Option 2: Standalone HTTP Server

If you want to run the stack independently (e.g. for debugging or remote access via SSE/HTTP):

```bash
uvx agentsflow --transport streamable-http
```

## 3) Tracking Progress

Regardless of which option you choose, you can track workflow execution, history, and status in the Temporal Web UI.

- **URL**: http://localhost:8233
- **Namespace**: `default`

## 3) Using AgentsFlow

Once connected, you can use natural language to interact with the process workflow. A few concrete prompts:

- "Call `start_agentsflow_process` on this repo with issue https://jira.example.com/browse/TEAM-123."
- "Kick off `start_agentsflow_process` with task text 'Fix 500 error when cookie is missing' for the current repo."
- "The workflow paused; send these answers via `provide_agentsflow_clarification` and then `await_agentsflow_result`."
- "Check the latest status for workflow `process-1a2b3c` using `await_agentsflow_result`."

You can supply either an issue URL or a free-text task when calling `start_agentsflow_process`, but not both.

## Manual Setup (Alternative)

If you prefer to run from source or manage the process manually:

1.  Clone the repository.
2.  Install dependencies: `uv sync --extra dev`.
3.  Run the dev stack: `python -m agentsflow.dev`.
