"""Command-line utility to kick off the SDLC Temporal workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_ai.durable_exec.temporal import PydanticAIPlugin
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from agentsflow.workflows import SDLCWorkflow, SDLCWorkflowInput, SDLCWorkflowOutput


class CLISettings(BaseSettings):
    """Settings source for CLI defaults populated from environment or .env files."""

    repository: str | None = Field(default=None, alias="SDLC_REPOSITORY")
    reference: str | None = Field(default=None, alias="SDLC_REFERENCE")
    jira_url: str | None = Field(default=None, alias="SDLC_JIRA_URL")
    jira_email: str | None = Field(default=None, alias="JIRA_EMAIL")
    jira_token: str | None = Field(default=None, alias="JIRA_API_TOKEN")
    address: str = Field(default="127.0.0.1:7233", alias="TEMPORAL_ADDRESS")
    namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    task_queue: str = Field(default="agentsflow-sdlc", alias="SDLC_TASK_QUEUE")
    workflow_id: str | None = Field(default=None, alias="SDLC_WORKFLOW_ID")
    model: str | None = Field(default=None, alias="SDLC_AGENT_MODEL")
    json_output: bool = Field(default=False, alias="SDLC_JSON_OUTPUT")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True, extra="ignore")


def _parse_args(argv: list[str], defaults: CLISettings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AgentsFlow SDLC workflow.")

    parser.add_argument(
        "--repository",
        default=defaults.repository,
        required=defaults.repository is None,
        help="Local path or remote URL to the git repository (env: SDLC_REPOSITORY).",
    )
    parser.add_argument(
        "--jira-url",
        dest="jira_url",
        default=defaults.jira_url,
        required=defaults.jira_url is None,
        help="URL of the Jira issue to process (env: SDLC_JIRA_URL).",
    )
    parser.add_argument(
        "--jira-email",
        dest="jira_email",
        default=defaults.jira_email,
        required=defaults.jira_email is None,
        help="Jira account email used for authentication (env: JIRA_EMAIL).",
    )
    parser.add_argument(
        "--jira-token",
        dest="jira_token",
        default=defaults.jira_token,
        required=defaults.jira_token is None,
        help="Jira API token or password (env: JIRA_API_TOKEN).",
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


def _derive_workflow_id(jira_url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", jira_url.lower()).strip("-")
    slug = slug or "sdlc"
    return f"sdlc-{slug}"[:200]


async def _run_workflow(args: argparse.Namespace) -> SDLCWorkflowOutput:
    client = await Client.connect(
        args.address,
        namespace=args.namespace,
        data_converter=pydantic_data_converter,
        plugins=[PydanticAIPlugin()],
    )

    if args.model:
        os.environ["SDLC_AGENT_MODEL"] = args.model

    input_payload = SDLCWorkflowInput(
        repository=args.repository,
        reference=args.reference,
        jira_task_url=args.jira_url,
        jira_email=args.jira_email,
        jira_api_token=args.jira_token,
    )

    workflow_id = args.workflow_id or _derive_workflow_id(args.jira_url)

    handle = await client.start_workflow(
        SDLCWorkflow.run,
        input_payload,
        id=workflow_id,
        task_queue=args.task_queue,
    )

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
