"""Command-line utility to kick off the process Temporal workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from agentsflow.logging_utils import configure_logging
from agentsflow.settings import CLISettings
from agentsflow.workflow_client import (
    ClarificationPending,
    start_process_workflow,
    wait_for_completion,
)
from agentsflow.workflows import ProcessWorkflowOutput


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


async def _run_workflow(args: argparse.Namespace) -> ProcessWorkflowOutput:
    handle = await start_process_workflow(
        address=args.address,
        namespace=args.namespace,
        task_queue=args.task_queue,
        repository=args.repository,
        reference=args.reference,
        issue_url=args.issue_url,
        task_text=args.task_text,
        branch_name=args.branch_name,
        coding_agent_provider=args.coding_agent_provider,
        model=args.model,
    )
    return await wait_for_completion(handle)


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
