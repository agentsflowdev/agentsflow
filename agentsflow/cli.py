"""Command-line utility to kick off the process Temporal workflow."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import uuid
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter

from agentsflow.logging_utils import (
    DEFAULT_LOG_LEVEL,
    configure_logging,
)
from agentsflow.workflows import ProcessWorkflow, ProcessWorkflowInput, ProcessWorkflowOutput

STATUS_POLL_INTERVAL_SECONDS = 2


class ClarificationPending(Exception):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("clarification_required")
        self.payload = payload


class CLISettings(BaseSettings):
    """Settings source for CLI defaults populated from environment or .env files."""

    repository: str | None = None
    reference: str | None = None
    issue_url: str | None = None
    task_text: str | None = None
    address: str = Field(default="127.0.0.1:7233", alias="TEMPORAL_ADDRESS")
    namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    task_queue: str = Field(default="process-workflow", alias="PROCESS_TASK_QUEUE")
    coding_agent_provider: str = Field(default="claude", alias="PROCESS_CODING_AGENT_PROVIDER")
    model: str | None = Field(default=None, alias="PROCESS_AGENT_MODEL")
    branch_name: str | None = None
    json_output: bool = Field(default=False, alias="PROCESS_JSON_OUTPUT")
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, alias="AGENTSFLOW_LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


def _parse_args(argv: list[str], defaults: CLISettings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the process workflow.")

    parser.add_argument(
        "--repository",
        default=defaults.repository,
        required=defaults.repository is None,
        help="Local path or remote URL to the git repository.",
    )
    source_group = parser.add_mutually_exclusive_group(
        required=defaults.issue_url is None and defaults.task_text is None
    )
    source_group.add_argument(
        "--issue-url",
        dest="issue_url",
        default=defaults.issue_url,
        help="URL of the issue to process.",
    )
    source_group.add_argument(
        "--task-text",
        dest="task_text",
        default=defaults.task_text,
        help="Free-text task description when no issue URL is available.",
    )
    parser.add_argument(
        "--reference",
        default=defaults.reference,
        help="Optional git reference (branch, tag, or commit).",
    )
    parser.add_argument(
        "--address",
        default=defaults.address,
        help="Temporal frontend address (env: TEMPORAL_ADDRESS).",
    )
    parser.add_argument(
        "--namespace",
        default=defaults.namespace,
        help="Temporal namespace to target (env: TEMPORAL_NAMESPACE).",
    )
    parser.add_argument(
        "--task-queue",
        dest="task_queue",
        default=defaults.task_queue,
        help="Task queue that the worker listens on (env: PROCESS_TASK_QUEUE).",
    )
    parser.add_argument(
        "--coding-agent-provider",
        default=defaults.coding_agent_provider,
        choices=["claude", "gemini", "codex"],
        help="Coding agent provider to use (env: PROCESS_CODING_AGENT_PROVIDER).",
    )
    parser.add_argument(
        "--model",
        default=defaults.model,
        help="Override chat model used by the process agents (env: PROCESS_AGENT_MODEL).",
    )
    parser.add_argument(
        "--branch",
        dest="branch_name",
        default=defaults.branch_name,
        help="Optional branch name to commit workflow changes into.",
    )
    parser.set_defaults(json=defaults.json_output)
    parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Print the workflow result as pretty-printed JSON (env: PROCESS_JSON_OUTPUT).",
    )
    parser.add_argument(
        "--no-json",
        dest="json",
        action="store_false",
        help="Disable JSON output even if PROCESS_JSON_OUTPUT is set.",
    )
    return parser.parse_args(argv)


def _generate_workflow_id() -> str:
    return f"process-{uuid.uuid4().hex[:8]}"


async def _create_temporal_client(address: str, namespace: str) -> Client:
    """Create a Temporal client with the standard AgentsFlow configuration."""

    return await Client.connect(
        address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )


async def _start_workflow_handle(
    args: argparse.Namespace,
) -> WorkflowHandle[ProcessWorkflowOutput, Any]:
    """Start the process workflow and return the Temporal workflow handle."""

    client = await _create_temporal_client(args.address, args.namespace)

    if args.model:
        os.environ["PROCESS_AGENT_MODEL"] = args.model

    input_payload = ProcessWorkflowInput(
        repository=args.repository,
        reference=args.reference,
        issue_url=args.issue_url,
        task_text=getattr(args, "task_text", None),
        branch_name=args.branch_name,
        coding_agent_provider=args.coding_agent_provider,
    )

    return await client.start_workflow(  # type: ignore[no-any-return]
        ProcessWorkflow.run,
        input_payload,
        id=_generate_workflow_id(),
        task_queue=args.task_queue,
    )  # type: ignore[call-overload]


async def _await_workflow_result(
    address: str,
    namespace: str,
    workflow_id: str,
    *,
    run_id: str | None = None,
) -> ProcessWorkflowOutput:
    """Await the result for an existing workflow execution."""

    client = await _create_temporal_client(address, namespace)
    handle: WorkflowHandle[ProcessWorkflowOutput, Any] = client.get_workflow_handle(
        workflow_id,
        run_id=run_id,
        result_type=ProcessWorkflowOutput,
    )
    return await _wait_for_completion(handle)


async def _run_workflow(args: argparse.Namespace) -> ProcessWorkflowOutput:
    handle = await _start_workflow_handle(args)
    return await _wait_for_completion(handle)


async def _wait_for_completion(handle: WorkflowHandle[ProcessWorkflowOutput, Any]) -> ProcessWorkflowOutput:
    result_task = asyncio.create_task(handle.result())
    try:
        while True:
            if result_task.done():
                return result_task.result()  # type: ignore[no-any-return]
            status: dict[str, Any] = await handle.query("clarification_status")
            if status.get("status") == "clarification_required":
                raise ClarificationPending(status)
            await asyncio.sleep(STATUS_POLL_INTERVAL_SECONDS)
    finally:
        if not result_task.done():
            result_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await result_task


def _print_result(result: ProcessWorkflowOutput, as_json: bool) -> None:
    data = result.model_dump()
    if as_json:
        print(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        print(f"{key}: {value}")


def _print_clarification(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2))
        return
    print("Workflow paused: clarification required.")
    if payload["questions"]:
        print("Questions to resolve:")
        for question in payload["questions"]:
            print(f"- {question}")
    else:
        print("No specific questions were returned.")
    if payload["assumptions"]:
        print("Assumptions to confirm:")
        for assumption in payload["assumptions"]:
            print(f"- {assumption}")


def main(argv: list[str] | None = None) -> int:
    defaults = CLISettings()
    configure_logging(defaults.log_level)
    args = _parse_args(argv or sys.argv[1:], defaults)
    try:
        result = asyncio.run(_run_workflow(args))
    except ClarificationPending as pending:
        _print_clarification(pending.payload, args.json)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
