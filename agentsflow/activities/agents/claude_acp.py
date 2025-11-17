"""Temporal helper routines for Claude Code ACP interactions."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from acp import (
    Client,
    ClientSideConnection,
    PROTOCOL_VERSION,
    RequestError,
    text_block,
)
from acp.schema import (
    AgentMessageChunk,
    AllowedOutcome,
    ClientCapabilities,
    CreateTerminalRequest,
    CreateTerminalResponse,
    DeniedOutcome,
    EmbeddedResourceContentBlock,
    FileSystemCapability,
    InitializeRequest,
    KillTerminalCommandRequest,
    KillTerminalCommandResponse,
    NewSessionRequest,
    PermissionOption,
    PromptRequest,
    PromptResponse,
    ReadTextFileRequest,
    ReadTextFileResponse,
    ReleaseTerminalRequest,
    ReleaseTerminalResponse,
    RequestPermissionRequest,
    RequestPermissionResponse,
    ResourceContentBlock,
    SessionNotification,
    TextContentBlock,
    TerminalOutputRequest,
    TerminalOutputResponse,
    WaitForTerminalExitRequest,
    WaitForTerminalExitResponse,
    WriteTextFileRequest,
    WriteTextFileResponse,
)
from temporalio import activity


@dataclass
class ClaudeACPRequest:
    prompt: str
    session_id: str | None = None
    claude_binary: str | None = None
    workspace_dir: str | None = None
    auto_approve: bool | None = None


@dataclass
class ClaudeACPResponse:
    session_id: str
    message: str
    stop_reason: str | None


@dataclass
class _ClaudeSession:
    process: asyncio.subprocess.Process
    connection: ClientSideConnection
    client: "_ClaudeACPClient"
    session_id: str

    async def send_prompt(self, prompt: str) -> tuple[str, PromptResponse]:
        self.client.start_prompt()
        response = await self.connection.prompt(
            PromptRequest(sessionId=self.session_id, prompt=[text_block(prompt)])
        )
        message = await self.client.consume_message()
        return message, response

    def is_alive(self) -> bool:
        return self.process.returncode is None


class _SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _ClaudeSession] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str | None) -> _ClaudeSession | None:
        if session_id is None:
            return None
        async with self._lock:
            return self._sessions.get(session_id)

    async def register(self, session: _ClaudeSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def create_session(
        self,
        *,
        claude_binary: str,
        workspace_dir: Path,
        auto_approve: bool,
    ) -> _ClaudeSession:
        process = await asyncio.create_subprocess_exec(
            claude_binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
        )

        if process.stdin is None or process.stdout is None:
            with contextlib.suppress(Exception):
                process.terminate()
            raise RuntimeError("claude-code-acp process does not expose stdio pipes.")

        client_impl = _ClaudeACPClient(auto_approve=auto_approve, workspace_dir=workspace_dir)
        connection = ClientSideConnection(lambda _agent: client_impl, process.stdin, process.stdout)

        try:
            await connection.initialize(
                InitializeRequest(
                    protocolVersion=PROTOCOL_VERSION,
                    clientCapabilities=ClientCapabilities(
                        fs=FileSystemCapability(readTextFile=True, writeTextFile=True),
                        terminal=True,
                    ),
                )
            )
            session_response = await connection.newSession(
                NewSessionRequest(
                    cwd=str(workspace_dir),
                    mcpServers=[],
                )
            )
        except Exception:
            await _shutdown_process(process, connection)
            raise

        client_impl.attach_session(session_response.sessionId)
        session = _ClaudeSession(
            process=process,
            connection=connection,
            client=client_impl,
            session_id=session_response.sessionId,
        )
        await self.register(session)
        return session


_session_registry = _SessionRegistry()


class _ClaudeACPClient(Client):
    def __init__(self, *, auto_approve: bool, workspace_dir: Path) -> None:
        self._auto_approve = auto_approve
        self._workspace_dir = workspace_dir
        self._session_id: str | None = None
        self._current_chunks: list[str] = []
        self._buffer_lock = asyncio.Lock()

    def attach_session(self, session_id: str) -> None:
        self._session_id = session_id

    def start_prompt(self) -> None:
        self._current_chunks = []

    async def consume_message(self) -> str:
        async with self._buffer_lock:
            message = "".join(self._current_chunks).strip()
            self._current_chunks = []
            return message

    async def requestPermission(  # type: ignore[override]
        self,
        params: RequestPermissionRequest,
    ) -> RequestPermissionResponse:
        if not self._auto_approve:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        option = _pick_preferred_option(params.options)
        if option is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(outcome=AllowedOutcome(optionId=option.optionId, outcome="selected"))

    async def writeTextFile(  # type: ignore[override]
        self,
        params: WriteTextFileRequest,
    ) -> WriteTextFileResponse:
        path = self._resolve_workspace_path(params.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(params.content)
        return WriteTextFileResponse()

    async def readTextFile(  # type: ignore[override]
        self,
        params: ReadTextFileRequest,
    ) -> ReadTextFileResponse:
        path = self._resolve_workspace_path(params.path)
        if not path.exists():
            raise RequestError.invalid_params({"path": params.path, "reason": "file does not exist"})
        text = path.read_text()
        return ReadTextFileResponse(content=text)

    async def createTerminal(  # type: ignore[override]
        self,
        params: CreateTerminalRequest,
    ) -> CreateTerminalResponse:
        return CreateTerminalResponse(terminalId="term-1")

    async def terminalOutput(  # type: ignore[override]
        self,
        params: TerminalOutputRequest,
    ) -> TerminalOutputResponse:
        return TerminalOutputResponse(output="", truncated=False)

    async def waitForTerminalExit(  # type: ignore[override]
        self,
        params: WaitForTerminalExitRequest,
    ) -> WaitForTerminalExitResponse:
        return WaitForTerminalExitResponse()

    async def releaseTerminal(  # type: ignore[override]
        self,
        params: ReleaseTerminalRequest,
    ) -> ReleaseTerminalResponse:
        return ReleaseTerminalResponse()

    async def killTerminal(  # type: ignore[override]
        self,
        params: KillTerminalCommandRequest,
    ) -> KillTerminalCommandResponse:
        return KillTerminalCommandResponse()

    async def sessionUpdate(  # type: ignore[override]
        self,
        params: SessionNotification,
    ) -> None:
        update = params.update
        if isinstance(update, AgentMessageChunk):
            text = _extract_text(update.content)
            if not text:
                return
            async with self._buffer_lock:
                self._current_chunks.append(text)

    def _resolve_workspace_path(self, requested: str) -> Path:
        path = Path(requested)
        if not path.is_absolute():
            path = (self._workspace_dir / path).resolve()
        else:
            path = path.resolve()
        if not _is_within_root(path, self._workspace_dir):
            raise RequestError.invalid_params({"path": requested, "reason": "path outside workspace"})
        return path


def _extract_text(content: object) -> str:
    if isinstance(content, TextContentBlock):
        return content.text
    if isinstance(content, ResourceContentBlock):
        return content.uri or content.name or ""
    if isinstance(content, EmbeddedResourceContentBlock):
        resource = content.resource
        text = getattr(resource, "text", None)
        if text:
            return text
    if isinstance(content, dict):
        text = content.get("text")  # type: ignore[union-attr]
        if isinstance(text, str):
            return text
    if isinstance(content, list):
        parts = [_extract_text(item) for item in content]
        return "".join(part for part in parts if part)
    return ""


def _pick_preferred_option(options: Iterable[PermissionOption] | None) -> PermissionOption | None:
    if not options:
        return None
    best = None
    for option in options:
        if getattr(option, "kind", None) in {"allow_once", "allow_always"}:
            return option
        best = best or option
    return best


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


async def _shutdown_process(
    process: asyncio.subprocess.Process | None,
    connection: ClientSideConnection | None,
) -> None:
    if connection is not None:
        with contextlib.suppress(Exception):
            await connection.close()
    if process is None:
        return
    if process.returncode is not None:
        return
    process.terminate()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)
    if process.returncode is None:
        process.kill()
        await process.wait()


def _resolve_claude_binary(binary: str | None) -> str:
    if binary:
        return binary
    env_value = os.getenv("ACP_CLAUDE_BIN")
    if env_value:
        return env_value
    resolved = shutil.which("claude-code-acp")
    if resolved:
        return resolved
    raise FileNotFoundError("Unable to locate `claude-code-acp` binary. Set ACP_CLAUDE_BIN or provide a path.")


async def run_claude_code(request: ClaudeACPRequest) -> ClaudeACPResponse:
    if not request.prompt:
        raise ValueError("Prompt is required.")

    workspace_input = request.workspace_dir or "."
    workspace_dir = Path(workspace_input).expanduser().resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    activity.logger.debug(
        "Received Claude ACP request",
        extra={
            "has_session": bool(request.session_id),
            "workspace_dir": str(workspace_dir),
            "prompt_chars": len(request.prompt),
        },
    )

    session: _ClaudeSession | None = None

    if request.session_id:
        activity.logger.debug(
            "Attempting to reuse existing Claude session",
            extra={"session_id": request.session_id},
        )
        session = await _session_registry.get(request.session_id)
        if session is not None and not session.is_alive():
            activity.logger.debug(
                "Stale Claude session detected; creating new session",
                extra={"session_id": session.session_id},
            )
            await _session_registry.remove(session.session_id)
            session = None

    if session is None:
        resolved_binary = _resolve_claude_binary(request.claude_binary)
        auto_approve = request.auto_approve if request.auto_approve is not None else True
        activity.logger.debug(
            "Launching Claude ACP session",
            extra={
                "claude_binary": resolved_binary,
                "workspace_dir": str(workspace_dir),
                "auto_approve": auto_approve,
            },
        )
        session = await _session_registry.create_session(
            claude_binary=resolved_binary,
            workspace_dir=workspace_dir,
            auto_approve=auto_approve,
        )

    message, response = await session.send_prompt(request.prompt)

    activity.logger.debug(
        "Claude ACP prompt completed",
        extra={
            "session_id": session.session_id,
            "response_stop_reason": response.stopReason,
            "response_chars": len(message),
        },
    )
    activity.logger.info(
        "Claude Code ACP prompt executed",
        extra={"session_id": session.session_id, "stop_reason": response.stopReason},
    )

    return ClaudeACPResponse(
        session_id=session.session_id,
        message=message,
        stop_reason=response.stopReason,
    )


async def close_session(session_id: str) -> None:
    session = await _session_registry.get(session_id)
    activity.logger.debug(
        "Closing Claude session",
        extra={"session_id": session_id, "found": session is not None},
    )
    if session is None:
        return
    await _shutdown_process(session.process, session.connection)
    await _session_registry.remove(session_id)
