from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentsflow.activities.agents import acp_agent


class FakeSession:
    def __init__(self, session_id: str = "sess-1") -> None:
        self.session_id = session_id
        self.prompts: list[str] = []
        self.process = None
        self.connection = None

    def is_alive(self) -> bool:
        return True

    async def send_prompt(self, prompt: str):
        self.prompts.append(prompt)
        return "response", SimpleNamespace(stopReason="stop")


class DummyRegistry:
    def __init__(self, session: FakeSession | None = None) -> None:
        self.session = session
        self.created_with: dict | None = None
        self.removed: str | None = None

    async def get(self, session_id: str | None):
        if session_id is None:
            return None
        return self.session if self.session and self.session.session_id == session_id else None

    async def create_session(self, *, command, workspace_dir, auto_approve):
        self.created_with = {
            "command": command,
            "workspace_dir": str(workspace_dir),
            "auto_approve": auto_approve,
        }
        self.session = self.session or FakeSession()
        return self.session

    async def remove(self, session_id: str):
        self.removed = session_id
        if self.session and self.session.session_id == session_id:
            self.session = None


@pytest.mark.asyncio
async def test_run_acp_agent_creates_session(monkeypatch, tmp_path):
    registry = DummyRegistry()
    monkeypatch.setattr(acp_agent, "_session_registry", registry)
    monkeypatch.setattr(acp_agent, "_resolve_claude_binary", lambda path: "/fake/claude")

    request = acp_agent.ACPRequest(prompt="Hello", agent_type="claude", workspace_dir=str(tmp_path))

    result = await acp_agent.run_acp_agent(request)

    assert registry.created_with == {
        "command": ["/fake/claude"],
        "workspace_dir": str(tmp_path.resolve()),
        "auto_approve": True,
    }
    assert result.session_id == registry.session.session_id
    assert result.message == "response"
    assert registry.session.prompts == ["Hello"]


@pytest.mark.asyncio
async def test_run_acp_agent_reuses_session(monkeypatch, tmp_path):
    existing = FakeSession(session_id="sess-existing")
    registry = DummyRegistry(session=existing)
    monkeypatch.setattr(acp_agent, "_session_registry", registry)
    monkeypatch.setattr(acp_agent, "_resolve_claude_binary", lambda path: "/fake/claude")

    request = acp_agent.ACPRequest(
        prompt="Hello again",
        agent_type="claude",
        session_id="sess-existing",
        workspace_dir=str(tmp_path),
    )

    result = await acp_agent.run_acp_agent(request)

    assert registry.created_with is None
    assert result.session_id == "sess-existing"
    assert registry.session.prompts == ["Hello again"]


@pytest.mark.asyncio
async def test_close_acp_session(monkeypatch):
    session = FakeSession(session_id="sess-close")
    registry = DummyRegistry(session=session)
    monkeypatch.setattr(acp_agent, "_session_registry", registry)

    await acp_agent.close_session("sess-close")

    assert registry.removed == "sess-close"
