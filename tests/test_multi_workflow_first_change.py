from __future__ import annotations

from datetime import timedelta

import pytest
from temporalio import workflow
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from agentsflow.workflow_client import _await_first_change


@workflow.defn(sandboxed=False)
class ClarificationWorkflow:
    def __init__(self) -> None:
        self._resolved = False

    @workflow.signal
    async def clarification_requested(self, payload: dict):
        return None

    @workflow.signal
    async def answer(self):
        self._resolved = True

    @workflow.query
    def clarification_status(self) -> dict:
        if not self._resolved:
            return {
                "status": "clarification_required",
                "questions": ["Need input"],
                "assumptions": [],
            }
        return {"status": "running"}

    @workflow.run
    async def run(self):
        info = workflow.info()
        self_handle = workflow.get_external_workflow_handle(info.workflow_id, run_id=info.run_id)
        await self_handle.signal("clarification_requested", {"questions": ["Need input"], "assumptions": []})
        await workflow.wait_condition(lambda: self._resolved)
        return "clarified"


@workflow.defn(sandboxed=False)
class SlowCompletionWorkflow:
    @workflow.run
    async def run(self):
        await workflow.sleep(timedelta(seconds=5))
        return "done"


@pytest.mark.asyncio
async def test_first_change_returns_clarification_then_completion():
    env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)

    async with env:
        async with Worker(
            env.client,
            task_queue="test-first-change",
            workflows=[ClarificationWorkflow, SlowCompletionWorkflow],
        ):
            clarify_handle = await env.client.start_workflow(
                ClarificationWorkflow.run,
                id="clarify-1",
                task_queue="test-first-change",
            )
            slow_handle = await env.client.start_workflow(
                SlowCompletionWorkflow.run,
                id="slow-1",
                task_queue="test-first-change",
            )

            first = await _await_first_change(
                env.client.service_client.config.target_host,
                env.client.namespace,
                [clarify_handle.id, slow_handle.id],
                client=env.client,
            )

            assert first["kind"] == "clarification_required"
            assert first["workflow_id"] == clarify_handle.id
            assert first["payload"]["questions"] == ["Need input"]

            # Now resolve the clarification and expect the slow workflow to complete next.
            await clarify_handle.signal(ClarificationWorkflow.answer)

            second = await _await_first_change(
                env.client.service_client.config.target_host,
                env.client.namespace,
                [clarify_handle.id, slow_handle.id],
                client=env.client,
            )

            assert second["kind"] == "completed"
            assert second["workflow_id"] == clarify_handle.id
            assert second["result"] == "clarified"

            # Slow workflow should complete next.
            third = await _await_first_change(
                env.client.service_client.config.target_host,
                env.client.namespace,
                [slow_handle.id],
                client=env.client,
            )

            assert third["kind"] == "completed"
            assert third["workflow_id"] == slow_handle.id
            assert third["result"] == "done"
