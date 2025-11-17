from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentsflow.activities.agents import claude_acp


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

    async def create_session(self, *, claude_binary, workspace_dir, auto_approve):
        self.created_with = {
            "claude_binary": claude_binary,
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
async def test_run_claude_code_creates_session(monkeypatch, tmp_path):
    registry = DummyRegistry()
    monkeypatch.setattr(claude_acp, "_session_registry", registry)
    monkeypatch.setattr(claude_acp, "_resolve_claude_binary", lambda path: "/fake/claude")

    request = claude_acp.ClaudeACPRequest(prompt="Hello", workspace_dir=str(tmp_path))

    result = await claude_acp.run_claude_code(request)

    assert registry.created_with == {
        "claude_binary": "/fake/claude",
        "workspace_dir": str(tmp_path.resolve()),
        "auto_approve": True,
    }
    assert result.session_id == registry.session.session_id
    assert result.message == "response"
    assert registry.session.prompts == ["Hello"]


@pytest.mark.asyncio
async def test_run_claude_code_reuses_session(monkeypatch, tmp_path):
    existing = FakeSession(session_id="sess-existing")
    registry = DummyRegistry(session=existing)
    monkeypatch.setattr(claude_acp, "_session_registry", registry)
    monkeypatch.setattr(claude_acp, "_resolve_claude_binary", lambda path: "/fake/claude")

    request = claude_acp.ClaudeACPRequest(
        prompt="Hello again",
        session_id="sess-existing",
        workspace_dir=str(tmp_path),
    )

    result = await claude_acp.run_claude_code(request)

    assert registry.created_with is None
    assert result.session_id == "sess-existing"
    assert registry.session.prompts == ["Hello again"]


@pytest.mark.asyncio
async def test_close_claude_session(monkeypatch):
    session = FakeSession(session_id="sess-close")
    registry = DummyRegistry(session=session)
    monkeypatch.setattr(claude_acp, "_session_registry", registry)

    await claude_acp.close_session("sess-close")

    assert registry.removed == "sess-close"
