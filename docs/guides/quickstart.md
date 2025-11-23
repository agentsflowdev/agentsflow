# Quickstart

Spin up the SDLC workflow locally and run it end-to-end. The recommended way to run AgentsFlow is as an MCP server using `uvx`.

## Prerequisites
- **uv**: Install via `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Temporal**: The stack will automatically start a local Temporal dev server if port 7233 is free.
- **Secrets**: `OPENAI_API_KEY` plus issue provider credentials (Jira or GitHub).

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

Once connected, you can use natural language to interact with the SDLC workflow.

**Example Prompts:**
- "Start the SDLC workflow for the current repository."
- "Create a feature branch for issue JIRA-123."
- "Check the status of workflow `sdlc-1a2b3c`."

## Manual Setup (Alternative)

If you prefer to run from source or manage the process manually:

1.  Clone the repository.
2.  Install dependencies: `uv sync --extra dev`.
3.  Run the dev stack: `python -m agentsflow.dev`.
