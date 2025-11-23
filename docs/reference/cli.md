# CLI & Worker Reference

## CLI (`python -m agentsflow.cli`)
- Required inputs: `--repository` (path or git URL) and `--issue-url`.
- Connection flags: `--address` (`TEMPORAL_ADDRESS`), `--namespace` (`TEMPORAL_NAMESPACE`), `--task-queue` (`PROCESS_TASK_QUEUE`).
- Workflow controls: `--reference`, `--coding-agent-provider {claude,gemini,codex}`, `--model` (`PROCESS_AGENT_MODEL`), `--branch`.
- Output: `--json` / `--no-json` (defaults to `PROCESS_JSON_OUTPUT`); prints the `ProcessWorkflowOutput` payload on success.
- Exit codes: `0` success, `2` clarification required (payload printed), `1` error, `130` interrupted.
- Workflow IDs are generated automatically as `process-<8 hex>` unless you wrap the CLI yourself.

Example run:
```bash
uv run python -m agentsflow.cli \
  --repository /repos/sample \
  --issue-url https://github.com/octo/widgets/issues/99 \
  --reference main \
  --json
```

## Worker (`python -m agentsflow.worker`)
- Flags mirror the CLI connection options plus `--auto-approve` / `--require-approval` (maps to `ACP_AUTO_APPROVE`).
- Registers `AgentsFlowActivities().activities()` and the `ProcessWorkflow`, listening on the configured task queue until stopped.
- Uses the Temporal Pydantic data converter to keep model serialization consistent with the workflow.

## Logging
Set `AGENTSFLOW_LOG_LEVEL` (`DEBUG`, `INFO`, etc.) to control verbosity for both CLI and worker entry points.
