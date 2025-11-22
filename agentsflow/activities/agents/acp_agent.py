"""Temporal helper routines for generic ACP (Agent Client Protocol) interactions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from acp import (
    PROTOCOL_VERSION,
    Client,
    ClientSideConnection,
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
    TerminalOutputRequest,
    TerminalOutputResponse,
    TextContentBlock,
    WaitForTerminalExitRequest,
    WaitForTerminalExitResponse,
    WriteTextFileRequest,
    WriteTextFileResponse,
)
from temporalio import activity

LOGGER = logging.getLogger(__name__)


def _debug(message: str, extra: dict[str, object] | None = None) -> None:
    """Log debug statements even when no activity context is active."""

    rendered = message
    if extra:
        try:
            rendered = f"{message} {json.dumps(extra, default=str, sort_keys=True)}"
        except Exception:
            rendered = f"{message} {extra}"

    try:
        activity.logger.debug(rendered, extra=extra)
    except RuntimeError:
        LOGGER.debug(rendered, extra=extra)


@dataclass
@dataclass
class ACPRequest:
    prompt: str
    agent_type: str = "claude"  # "claude" or "gemini"
    model: str | None = None
    session_id: str | None = None
    agent_binary: str | None = None
    workspace_dir: str | None = None
    auto_approve: bool | None = None


@dataclass
class ACPResponse:
    session_id: str
    message: str
    stop_reason: str | None


@dataclass
class _ACPSession:
    process: asyncio.subprocess.Process
    connection: ClientSideConnection
    client: _ACPClient
    session_id: str

    async def send_prompt(self, prompt: str) -> tuple[str, PromptResponse]:
        _debug(
            "Dispatching ACP prompt",
            {"session_id": self.session_id, "prompt_chars": len(prompt)},
        )
        self.client.start_prompt()
        response = await self.connection.prompt(PromptRequest(sessionId=self.session_id, prompt=[text_block(prompt)]))
        message = await self.client.consume_message()
        _debug(
            "ACP prompt response received",
            {
                "session_id": self.session_id,
                "response_chars": len(message),
                "stop_reason": getattr(response, "stopReason", None),
            },
        )
        return message, response

    def is_alive(self) -> bool:
        return self.process.returncode is None


class _SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, _ACPSession] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str | None) -> _ACPSession | None:
        if session_id is None:
            return None
        async with self._lock:
            session = self._sessions.get(session_id)
        _debug("ACP session lookup", {"session_id": session_id, "found": session is not None})
        return session

    async def register(self, session: _ACPSession) -> None:
        async with self._lock:
            self._sessions[session.session_id] = session
        _debug(
            "ACP session registered",
            {"session_id": session.session_id, "pid": session.process.pid},
        )

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            removed = self._sessions.pop(session_id, None)
        _debug("ACP session removed", {"session_id": session_id, "had_session": removed is not None})

    async def create_session(
        self,
        *,
        command: list[str],
        workspace_dir: Path,
        auto_approve: bool,
    ) -> _ACPSession:
        _debug(
            "Spawning ACP process",
            {
                "command": command,
                "workspace_dir": str(workspace_dir),
                "auto_approve": auto_approve,
            },
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
        )
        _debug("ACP process started", {"pid": process.pid})

        if process.stdin is None or process.stdout is None:
            with contextlib.suppress(Exception):
                process.terminate()
            raise RuntimeError("ACP agent process does not expose stdio pipes.")

        client_impl = _ACPClient(auto_approve=auto_approve, workspace_dir=workspace_dir)
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
        _debug(
            "ACP session established",
            {"session_id": session_response.sessionId, "workspace_dir": str(workspace_dir)},
        )
        session = _ACPSession(
            process=process,
            connection=connection,
            client=client_impl,
            session_id=session_response.sessionId,
        )
        await self.register(session)
        return session


_session_registry = _SessionRegistry()


class _ACPClient(Client):  # type: ignore[misc]
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

    async def requestPermission(
        self,
        params: RequestPermissionRequest,
    ) -> RequestPermissionResponse:
        option_count = len(params.options or [])
        _debug(
            "ACP permission requested",
            {
                "session_id": self._session_id,
                "auto_approve": self._auto_approve,
                "option_count": option_count,
                "resource": getattr(params, "resource", None),
            },
        )
        if not self._auto_approve:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        option = _pick_preferred_option(params.options)
        if option is None:
            _debug("ACP permission denied automatically", {"session_id": self._session_id})
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        _debug(
            "ACP permission auto-approved",
            {"session_id": self._session_id, "option_id": option.optionId},
        )
        return RequestPermissionResponse(outcome=AllowedOutcome(optionId=option.optionId, outcome="selected"))

    async def writeTextFile(
        self,
        params: WriteTextFileRequest,
    ) -> WriteTextFileResponse:
        path = self._resolve_workspace_path(params.path)
        _debug(
            "ACP write file request",
            {
                "session_id": self._session_id,
                "path": str(path),
                "content_chars": len(params.content),
            },
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(params.content)
        except (OSError, UnicodeError) as exc:
            raise RequestError.internal_error(
                {
                    "path": params.path,
                    "reason": "unable to write file",
                    "error": str(exc),
                }
            ) from exc
        return WriteTextFileResponse()

    async def readTextFile(
        self,
        params: ReadTextFileRequest,
    ) -> ReadTextFileResponse:
        path = self._resolve_workspace_path(params.path)
        _debug("ACP read file request", {"session_id": self._session_id, "path": str(path)})
        if not path.exists():
            raise RequestError.invalid_params({"path": params.path, "reason": "file does not exist"})
        try:
            text = path.read_text()
        except UnicodeDecodeError as exc:
            raise RequestError.invalid_params(
                {
                    "path": params.path,
                    "reason": "file is not UTF-8 encoded text",
                    "error": str(exc),
                }
            ) from exc
        except OSError as exc:
            raise RequestError.internal_error(
                {
                    "path": params.path,
                    "reason": "unable to read file",
                    "error": str(exc),
                }
            ) from exc
        return ReadTextFileResponse(content=text)

    async def createTerminal(
        self,
        params: CreateTerminalRequest,
    ) -> CreateTerminalResponse:
        _debug("ACP create terminal", {"session_id": self._session_id})
        return CreateTerminalResponse(terminalId="term-1")

    async def terminalOutput(
        self,
        params: TerminalOutputRequest,
    ) -> TerminalOutputResponse:
        _debug(
            "ACP terminal output request",
            {"session_id": self._session_id, "terminal_id": params.terminalId},
        )
        return TerminalOutputResponse(output="", truncated=False)

    async def waitForTerminalExit(
        self,
        params: WaitForTerminalExitRequest,
    ) -> WaitForTerminalExitResponse:
        _debug(
            "ACP wait for terminal exit",
            {"session_id": self._session_id, "terminal_id": params.terminalId},
        )
        return WaitForTerminalExitResponse()

    async def releaseTerminal(
        self,
        params: ReleaseTerminalRequest,
    ) -> ReleaseTerminalResponse:
        _debug(
            "ACP release terminal",
            {"session_id": self._session_id, "terminal_id": params.terminalId},
        )
        return ReleaseTerminalResponse()

    async def killTerminal(
        self,
        params: KillTerminalCommandRequest,
    ) -> KillTerminalCommandResponse:
        _debug(
            "ACP kill terminal",
            {"session_id": self._session_id, "terminal_id": params.terminalId},
        )
        return KillTerminalCommandResponse()

    async def sessionUpdate(
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
        return str(content.text)
    if isinstance(content, ResourceContentBlock):
        return content.uri or content.name or ""
    if isinstance(content, EmbeddedResourceContentBlock):
        resource = content.resource
        text = getattr(resource, "text", None)
        if text:
            return str(text)
    if isinstance(content, dict):
        return str(content.get("text", ""))
    if isinstance(content, list):
        parts = [_extract_text(item) for item in content]
        return "".join(part for part in parts if part)
    return ""


def _pick_preferred_option(
    options: Iterable[PermissionOption] | None,
) -> PermissionOption | None:
    if not options:
        return None
    best = None
    for option in options:
        if getattr(option, "kind", None) in {"allow_once", "allow_always"}:
            return option
        best = best or option
    return best


def _is_within_root(path: Path, root: Path) -> bool:
    # NOTE: Path.resolve() already normalises symlinks like /var -> /private/var on macOS.
    path_resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        return os.path.commonpath([path_resolved, root_resolved]) == str(root_resolved)
    except ValueError:
        # Different drives/platform-specific edge cases.
        return False


async def _shutdown_process(
    process: asyncio.subprocess.Process | None,
    connection: ClientSideConnection | None,
) -> None:
    if connection is not None:
        _debug("Closing ACP connection", None)
        with contextlib.suppress(Exception):
            await connection.close()
    if process is None:
        return
    if process.returncode is not None:
        return
    _debug("Terminating ACP process", {"pid": process.pid})
    process.terminate()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)
    if process.returncode is None:
        _debug("Killing ACP process", {"pid": process.pid})
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


def _resolve_gemini_binary(binary: str | None) -> str:
    if binary:
        return binary
    env_value = os.getenv("ACP_GEMINI_BIN")
    if env_value:
        return env_value
    resolved = shutil.which("gemini")
    if resolved:
        return resolved
    raise FileNotFoundError("Unable to locate `gemini` binary. Set ACP_GEMINI_BIN or provide a path.")


def _resolve_codex_binary(binary: str | None) -> str:
    if binary:
        return binary
    env_value = os.getenv("ACP_CODEX_BIN")
    if env_value:
        return env_value
    resolved = shutil.which("codex-acp")
    if resolved:
        return resolved
    raise FileNotFoundError("Unable to locate `codex-acp` binary. Set ACP_CODEX_BIN or provide a path.")


async def run_acp_agent(request: ACPRequest) -> ACPResponse:
    if not request.prompt:
        raise ValueError("Prompt is required.")

    workspace_input = request.workspace_dir or "."
    workspace_dir = Path(workspace_input).expanduser().resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    activity.logger.debug(
        "Received ACP request",
        extra={
            "agent_type": request.agent_type,
            "has_session": bool(request.session_id),
            "workspace_dir": str(workspace_dir),
            "prompt_chars": len(request.prompt),
        },
    )

    session: _ACPSession | None = None

    if request.session_id:
        activity.logger.debug(
            "Attempting to reuse existing ACP session",
            extra={"session_id": request.session_id},
        )
        session = await _session_registry.get(request.session_id)
        if session is not None and not session.is_alive():
            activity.logger.debug(
                "Stale ACP session detected; creating new session",
                extra={"session_id": session.session_id},
            )
            await _session_registry.remove(session.session_id)
            session = None

    if session is None:
        auto_approve = request.auto_approve if request.auto_approve is not None else True
        command: list[str] = []

        if request.agent_type == "gemini":
            resolved_binary = _resolve_gemini_binary(request.agent_binary)
            # Gemini CLI uses --experimental-acp flag
            command = [resolved_binary, "--experimental-acp"]
            # If a model is specified in env or elsewhere, we might want to pass it.
            # For now, we'll assume the user configures it via env or defaults.
            # But let's support an optional model arg if we had it in the request (we don't yet).
            # We can check for a model env var if needed, or just rely on gemini defaults.
            # However, the previous plan mentioned --model. Let's check if we have a way to pass it.
            # The ACPRequest doesn't have a model field yet. We might need to add it or rely on env.
            # For now, basic support:
            if request.model:
                command.extend(["--model", request.model])
        elif request.agent_type == "codex":
            resolved_binary = _resolve_codex_binary(request.agent_binary)
            # Codex ACP usually runs as the binary itself
            command = [resolved_binary]
        else:
            # Default to Claude if unknown or explicitly claude
            resolved_binary = _resolve_claude_binary(request.agent_binary)
            command = [resolved_binary]

        activity.logger.debug(
            "Launching ACP session",
            extra={
                "command": command,
                "workspace_dir": str(workspace_dir),
                "auto_approve": auto_approve,
            },
        )
        session = await _session_registry.create_session(
            command=command,
            workspace_dir=workspace_dir,
            auto_approve=auto_approve,
        )

    message, response = await session.send_prompt(request.prompt)

    activity.logger.debug(
        "ACP prompt completed",
        extra={
            "session_id": session.session_id,
            "response_stop_reason": response.stopReason,
            "response_chars": len(message),
        },
    )
    activity.logger.info(
        "ACP prompt executed",
        extra={"session_id": session.session_id, "stop_reason": response.stopReason},
    )

    return ACPResponse(
        session_id=session.session_id,
        message=message,
        stop_reason=response.stopReason,
    )


async def close_session(session_id: str) -> None:
    session = await _session_registry.get(session_id)
    activity.logger.debug(
        "Closing ACP session",
        extra={"session_id": session_id, "found": session is not None},
    )
    if session is None:
        return
    await _shutdown_process(session.process, session.connection)
    await _session_registry.remove(session_id)
