"""Shared Temporal client helpers for CLI and MCP tools."""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, cast

from aiostream import stream
from temporalio.client import Client, WorkflowHandle
from temporalio.contrib.pydantic import pydantic_data_converter

from agentsflow.workflows.process import (
    ProcessWorkflow,
    ProcessWorkflowInput,
    ProcessWorkflowOutput,
)


async def _create_temporal_client(address: str, namespace: str, *, existing: Client | None = None) -> Client:
    """Create (or reuse) a Temporal client with the standard configuration."""

    if existing is not None:
        return existing
    return await Client.connect(address, namespace=namespace, data_converter=pydantic_data_converter)


async def _start_workflow_handle(
    args: argparse.Namespace,
    *,
    client: Client | None = None,
) -> WorkflowHandle[ProcessWorkflowOutput, Any]:
    """Start the process workflow and return its handle."""

    client = await _create_temporal_client(args.address, args.namespace, existing=client)

    if args.model:
        # Allow model override per invocation.
        import os

        os.environ["PROCESS_AGENT_MODEL"] = args.model

    input_payload = ProcessWorkflowInput(
        repository=args.repository,
        reference=args.reference,
        issue_url=args.issue_url,
        task_text=args.task_text,
        branch_name=args.branch_name,
        coding_agent_provider=args.coding_agent_provider,
    )

    return await client.start_workflow(  # type: ignore[no-any-return]
        ProcessWorkflow.run,
        input_payload,
        id=_generate_workflow_id(),
        task_queue=args.task_queue,
    )  # type: ignore[call-overload]


def _generate_workflow_id() -> str:
    import uuid

    return f"process-{uuid.uuid4().hex[:8]}"


async def _await_workflow_result(
    address: str,
    namespace: str,
    workflow_id: str,
    *,
    run_id: str | None = None,
    client: Client | None = None,
) -> ProcessWorkflowOutput:
    client = await _create_temporal_client(address, namespace, existing=client)
    handle: WorkflowHandle[ProcessWorkflowOutput, Any] = client.get_workflow_handle(
        workflow_id,
        run_id=run_id,
        result_type=ProcessWorkflowOutput,
    )
    result = await handle.result()
    return cast(ProcessWorkflowOutput, result)


async def _await_first_change(
    address: str,
    namespace: str,
    workflow_ids: Sequence[str],
    *,
    client: Client | None = None,
    seen_event_ids: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return the first completion/clarification event across the given workflows.

    Uses history long-polling plus result futures; no explicit sleep-based polling.
    """

    client = await _create_temporal_client(address, namespace, existing=client)

    # Resolve handles and run_ids up front for diagnostics.
    handles: list[WorkflowHandle[Any, Any]] = []
    for wid in workflow_ids:
        handles.append(client.get_workflow_handle(wid))

    seen_event_ids = seen_event_ids or {}

    # Immediate clarification check (no polling loop).
    for handle in handles:
        try:
            status = await handle.query("clarification_status")
        except Exception:
            continue
        if status.get("status") == "clarification_required":
            return {
                "kind": "clarification_required",
                "workflow_id": handle.id,
                "run_id": handle.run_id,
                "payload": {
                    "questions": status.get("questions", []),
                    "assumptions": status.get("assumptions", []),
                },
            }

    async def _decode_details(details: Mapping[str, Any]) -> dict[str, Any]:
        decoded: dict[str, Any] = {}
        for key, payload in details.items():
            decoded[key] = (await client.data_converter.decode([payload]))[0]
        return decoded

    async def _clarification_events(handle: WorkflowHandle[Any, Any]) -> AsyncIterator[dict[str, Any]]:
        async for hist in handle.fetch_history_events(wait_new_event=True):
            if hist.event_id <= seen_event_ids.get(handle.id, 0):
                continue
            attrs = hist.workflow_execution_signaled_event_attributes
            if not attrs or attrs.signal_name != "clarification_requested":
                continue
            decoded = (await client.data_converter.decode(attrs.input.payloads, [dict]))[0]
            yield {
                "kind": "clarification_required",
                "workflow_id": handle.id,
                "run_id": handle.run_id,
                "payload": decoded,
                "event_id": hist.event_id,
            }

    async def _completion_event(handle: WorkflowHandle[Any, Any]) -> AsyncIterator[dict[str, Any]]:
        try:
            result = await handle.result()
            yield {
                "kind": "completed",
                "workflow_id": handle.id,
                "run_id": handle.run_id,
                "result": result,
                "event_id": None,
            }
        except Exception as exc:  # pragma: no cover - defensive
            yield {
                "kind": "failed",
                "workflow_id": handle.id,
                "run_id": handle.run_id,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
                "event_id": None,
            }

    # Build one merged stream per workflow, then merge those.
    per_workflow_streams = []
    for handle in handles:
        per_workflow_streams.append(
            stream.merge(
                _clarification_events(handle),
                _completion_event(handle),
            )
        )

    merged = stream.merge(*per_workflow_streams)

    async with merged.stream() as streamer:
        async for event in streamer:
            # First event wins; close everything else.
            if event.get("event_id") is not None:
                seen_event_ids[event["workflow_id"]] = event["event_id"]
            await streamer.aclose()
            return event

    # Should be unreachable because at least one stream will finish.
    raise RuntimeError("No workflow events observed")
