import asyncio

import pytest

from agentsflow.mcp_server import _await_workflow_tool_impl
from agentsflow.workflow_client import ClarificationPending


class DummyCtx:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def info(self, msg: str) -> None:
        self.messages.append(msg)


class FakeOutput:
    def __init__(self, value: str) -> None:
        self.value = value

    def model_dump(self) -> dict[str, str]:
        return {"value": self.value}


@pytest.mark.asyncio
async def test_await_workflow_returns_on_first_completion(monkeypatch):
    calls: list[str] = []

    async def fake_await(address: str, namespace: str, workflow_id: str):
        calls.append(workflow_id)
        # Make one workflow finish sooner than the other.
        if workflow_id == "fast":
            await asyncio.sleep(0.01)
        else:
            await asyncio.sleep(0.05)
        return FakeOutput(workflow_id)

    monkeypatch.setattr("agentsflow.mcp_server.await_workflow_result", fake_await)

    ctx = DummyCtx()
    result = await _await_workflow_tool_impl(workflow_ids=["fast", "slow"], ctx=ctx)

    # Should return only the first finished workflow.
    assert set(result.keys()) == {"fast"}
    assert result["fast"]["status"] == "completed"
    assert result["fast"]["result"] == {"value": "fast"}
    assert any("fast" in msg for msg in ctx.messages)


@pytest.mark.asyncio
async def test_await_workflow_handles_clarification(monkeypatch):
    async def fake_await(address: str, namespace: str, workflow_id: str):
        raise ClarificationPending({"status": "clarification_required", "questions": ["q"], "assumptions": []})

    monkeypatch.setattr("agentsflow.mcp_server.await_workflow_result", fake_await)

    ctx = DummyCtx()
    result = await _await_workflow_tool_impl(workflow_ids=["needs-clarification"], ctx=ctx)

    assert result["needs-clarification"]["status"] == "clarification_required"
    assert result["needs-clarification"]["questions"] == ["q"]
