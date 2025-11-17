"""Utility to run the AgentsFlow Temporal worker."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter
from agentsflow.activities import AgentsFlowActivities
from agentsflow.workflows import SDLCWorkflow
from agentsflow.logging_utils import (
    DEFAULT_LOG_LEVEL,
    LOG_LEVEL_ENV,
    configure_logging,
)


class WorkerSettings(BaseSettings):
    """Settings for the Temporal worker, sourced from environment or .env."""

    address: str = Field(default="127.0.0.1:7233", alias="TEMPORAL_ADDRESS")
    namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    task_queue: str = Field(default="agentsflow-sdlc", alias="SDLC_TASK_QUEUE")
    claude_binary: str | None = Field(default=None, alias="CLAUDE_CODE_BIN")
    claude_auto_approve: bool = Field(default=True, alias="CLAUDE_AUTO_APPROVE")
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, alias=LOG_LEVEL_ENV)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


def _parse_args(argv: list[str], defaults: WorkerSettings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the AgentsFlow Temporal worker."
    )
    parser.add_argument(
        "--address",
        default=defaults.address,
        help="Temporal frontend address (env: TEMPORAL_ADDRESS).",
    )
    parser.add_argument(
        "--namespace",
        default=defaults.namespace,
        help="Temporal namespace (env: TEMPORAL_NAMESPACE).",
    )
    parser.add_argument(
        "--task-queue",
        dest="task_queue",
        default=defaults.task_queue,
        help="Task queue the worker will poll (env: SDLC_TASK_QUEUE).",
    )
    parser.add_argument(
        "--claude-binary",
        dest="claude_binary",
        default=defaults.claude_binary,
        help="Path to claude-code-acp binary (env: CLAUDE_CODE_BIN).",
    )
    parser.add_argument(
        "--claude-auto-approve",
        dest="claude_auto_approve",
        action="store_true",
        default=defaults.claude_auto_approve,
        help="Auto-approve ACP permissions (env: CLAUDE_AUTO_APPROVE).",
    )
    parser.add_argument(
        "--claude-require-approval",
        dest="claude_auto_approve",
        action="store_false",
        help="Require ACP permissions instead of auto-approving.",
    )
    parser.set_defaults(claude_auto_approve=defaults.claude_auto_approve)
    return parser.parse_args(argv)


async def _run_worker(args: argparse.Namespace) -> None:
    client = await Client.connect(
        args.address,
        namespace=args.namespace,
        data_converter=pydantic_data_converter,
    )

    activities = AgentsFlowActivities(
        claude_binary=args.claude_binary,
        auto_approve=args.claude_auto_approve,
    )

    worker = Worker(
        client,
        task_queue=args.task_queue,
        workflows=[SDLCWorkflow],
        activities=activities.activities(),
    )

    print(
        f"Worker listening on {args.address} (namespace={args.namespace}, task_queue={args.task_queue}). "
        "Press Ctrl+C to stop."
    )

    async with worker:
        await asyncio.Future()  # Run forever until cancelled.


def main(argv: list[str] | None = None) -> int:
    defaults = WorkerSettings()
    configure_logging(defaults.log_level)
    args = _parse_args(argv or sys.argv[1:], defaults)
    try:
        asyncio.run(_run_worker(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - runtime error reporting
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
