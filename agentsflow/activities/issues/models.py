"""Shared dataclasses representing issues across providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IssueComment:
    """Normalized representation of an issue comment."""

    id: str | None
    author: str
    created: str | None
    updated: str | None
    body: str | None


@dataclass(slots=True)
class IssueDetails:
    """Normalized payload returned by issue providers."""

    issue_key: str
    issue_url: str
    summary: str
    description: str
    status: str | None
    comments: list[IssueComment]
