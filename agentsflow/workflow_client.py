"""Shared helpers for interacting with the process workflow via Temporal."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Literal

from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter

from agentsflow.workflows import ProcessWorkflow, ProcessWorkflowInput, ProcessWorkflowOutput

STATUS_POLL_INTERVAL_SECONDS = 2


class ClarificationPending(Exception):
    """Raised when a workflow run pauses waiting for clarification."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("clarification_required")
        self.payload = payload


async def create_temporal_client(address: str, namespace: str) -> Client:
    """Create a Temporal client configured for AgentsFlow."""

    return await Client.connect(
        address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )


async def start_process_workflow(
    *,
    address: str,
    namespace: str,
    task_queue: str,
    repository: str,
    reference: str | None,
    issue_url: str | None,
    task_text: str | None,
    branch_name: str | None,
    coding_agent_provider: Literal["claude", "gemini", "codex"],
) -> WorkflowHandle[ProcessWorkflowOutput, Any]:
    """Start the process workflow and return its handle."""

    client = await create_temporal_client(address, namespace)

    input_payload = ProcessWorkflowInput(
        repository=repository,
        reference=reference,
        issue_url=issue_url,
        task_text=task_text,
        branch_name=branch_name,
        coding_agent_provider=coding_agent_provider,
    )

    return await client.start_workflow(  # type: ignore[no-any-return]
        ProcessWorkflow.run,
        input_payload,
        id=_generate_workflow_id(),
        task_queue=task_queue,
    )  # type: ignore[call-overload]


async def await_workflow_result(
    address: str,
    namespace: str,
    workflow_id: str,
    *,
    run_id: str | None = None,
) -> ProcessWorkflowOutput:
    """Await the result for an existing workflow execution."""

    client = await create_temporal_client(address, namespace)
    handle: WorkflowHandle[ProcessWorkflowOutput, Any] = client.get_workflow_handle(
        workflow_id,
        run_id=run_id,
        result_type=ProcessWorkflowOutput,
    )
    return await wait_for_completion(handle)


async def wait_for_completion(handle: WorkflowHandle[ProcessWorkflowOutput, Any]) -> ProcessWorkflowOutput:
    """Block until a workflow completes or requests clarification."""

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


def _generate_workflow_id() -> str:
    # Keep uuid4 without separators to preserve existing ID format.
    import uuid

    return f"process-{uuid.uuid4().hex[:8]}"
