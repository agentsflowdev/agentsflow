"""Shared settings used by the CLI and MCP server."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentsflow.logging_utils import DEFAULT_LOG_LEVEL


class CLISettings(BaseSettings):
    """Settings source populated from environment variables."""

    repository: str | None = None
    reference: str | None = None
    issue_url: str | None = None
    task_text: str | None = None
    address: str = Field(default="127.0.0.1:7233", alias="TEMPORAL_ADDRESS")
    namespace: str = Field(default="default", alias="TEMPORAL_NAMESPACE")
    task_queue: str = Field(default="process-workflow", alias="PROCESS_TASK_QUEUE")
    coding_agent_provider: Literal["claude", "gemini", "codex"] = Field(
        default="claude", alias="PROCESS_CODING_AGENT_PROVIDER"
    )
    branch_name: str | None = None
    json_output: bool = Field(default=False, alias="PROCESS_JSON_OUTPUT")
    log_level: str = Field(default=DEFAULT_LOG_LEVEL, alias="AGENTSFLOW_LOG_LEVEL")

    model_config = SettingsConfigDict(
        populate_by_name=True,
        extra="ignore",
    )
