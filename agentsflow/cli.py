"""Command-line utility to kick off the SDLC Temporal workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter

from agentsflow.workflows import SDLCWorkflow, SDLCWorkflowInput, SDLCWorkflowOutput
from agentsflow.logging_utils import (
    DEFAULT_LOG_LEVEL,
    LOG_LEVEL_ENV,
    configure_logging,
)


class CLISettings(BaseSettings):
    """Settings source for CLI defaults populated from environment or .env files."""

    repository: str | None = Field(default=None, alias="SDLC_REPOSITORY")
    reference: str | None = Field(default=None, alias="SDLC_REFERENCE")
    issue_url: str | None = Field(default=None, alias="SDLC_ISSUE_URL")
    jira_url: str | None = Field(default=None, alias="SDLC_JIRA_URL")
    address: str = Field(default="127.0.0.1:7233", alias="TEMPORAL_ADDRESS")
    namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    task_queue: str = Field(default="agentsflow-sdlc", alias="SDLC_TASK_QUEUE")
    workflow_id: str | None = Field(default=None, alias="SDLC_WORKFLOW_ID")
    model: str | None = Field(default=None, alias="SDLC_AGENT_MODEL")
    branch_name: str | None = Field(default=None, alias="SDLC_BRANCH_NAME")
    json_output: bool = Field(default=False, alias="SDLC_JSON_OUTPUT")
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, alias=LOG_LEVEL_ENV)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


def _parse_args(argv: list[str], defaults: CLISettings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AgentsFlow SDLC workflow.")

    parser.add_argument(
        "--repository",
        default=defaults.repository,
        required=defaults.repository is None,
        help="Local path or remote URL to the git repository (env: SDLC_REPOSITORY).",
    )
    issue_url_default = defaults.issue_url or defaults.jira_url
    parser.add_argument(
        "--issue-url",
        "--jira-url",
        dest="issue_url",
        default=issue_url_default,
        required=issue_url_default is None,
        help="URL of the issue to process (env: SDLC_ISSUE_URL or SDLC_JIRA_URL).",
    )
    parser.add_argument(
        "--reference",
        default=defaults.reference,
        help="Optional git reference (branch, tag, or commit) (env: SDLC_REFERENCE).",
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
        help="Task queue that the SDLC worker listens on (env: SDLC_TASK_QUEUE).",
    )
    parser.add_argument(
        "--workflow-id",
        dest="workflow_id",
        default=defaults.workflow_id,
        help="Optional workflow ID (default derived from Jira URL) (env: SDLC_WORKFLOW_ID).",
    )
    parser.add_argument(
        "--model",
        default=defaults.model,
        help="Override chat model used by the SDLC agents (env: SDLC_AGENT_MODEL).",
    )
    parser.add_argument(
        "--branch",
        dest="branch_name",
        default=defaults.branch_name,
        help="Optional branch name to commit workflow changes into (env: SDLC_BRANCH_NAME).",
    )
    parser.set_defaults(json=defaults.json_output)
    parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Print the workflow result as pretty-printed JSON (env: SDLC_JSON_OUTPUT).",
    )
    parser.add_argument(
        "--no-json",
        dest="json",
        action="store_false",
        help="Disable JSON output even if SDLC_JSON_OUTPUT is set.",
    )
    return parser.parse_args(argv)


def _derive_workflow_id(issue_url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", issue_url.lower()).strip("-")
    slug = slug or "sdlc"
    return f"sdlc-{slug}"[:200]


async def _create_temporal_client(address: str, namespace: str) -> Client:
    """Create a Temporal client with the standard AgentsFlow configuration."""

    return await Client.connect(
        address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
        plugins=[PydanticAIPlugin()],
    )


async def _start_workflow_handle(
    args: argparse.Namespace,
) -> WorkflowHandle[SDLCWorkflowOutput, Any]:
    """Start the SDLC workflow and return the Temporal workflow handle."""

    client = await _create_temporal_client(args.address, args.namespace)

    if args.model:
        os.environ["SDLC_AGENT_MODEL"] = args.model

    input_payload = SDLCWorkflowInput(
        repository=args.repository,
        reference=args.reference,
        issue_url=args.issue_url,
        branch_name=args.branch_name,
    )

    workflow_id = args.workflow_id or _derive_workflow_id(args.issue_url)

    return await client.start_workflow(
        SDLCWorkflow.run,
        input_payload,
        id=workflow_id,
        task_queue=args.task_queue,
    )


async def _await_workflow_result(
    address: str,
    namespace: str,
    workflow_id: str,
    *,
    run_id: str | None = None,
) -> SDLCWorkflowOutput:
    """Await the result for an existing workflow execution."""

    client = await _create_temporal_client(address, namespace)
    handle: WorkflowHandle[SDLCWorkflowOutput, Any] = client.get_workflow_handle(
        workflow_id,
        run_id=run_id,
        result_type=SDLCWorkflowOutput,
    )
    return await handle.result()


async def _run_workflow(args: argparse.Namespace) -> SDLCWorkflowOutput:
    handle = await _start_workflow_handle(args)
    return await handle.result()


def _print_result(result: SDLCWorkflowOutput, as_json: bool) -> None:
    data = result.model_dump()
    if as_json:
        print(json.dumps(data, indent=2))
        return
    for key, value in data.items():
        print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    defaults = CLISettings()
    configure_logging(defaults.log_level)
    args = _parse_args(argv or sys.argv[1:], defaults)
    try:
        result = asyncio.run(_run_workflow(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_result(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
