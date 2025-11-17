"""Issue provider registry and dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import IssueDetails

DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(slots=True)
class IssueRequest:
    """Parameters describing how to retrieve an issue from any provider."""

    issue_url: str
    provider: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class IssueProvider(Protocol):
    """Protocol implemented by provider modules capable of reading issues."""

    name: str

    def supports(self, issue_url: str) -> bool:
        """Return True when this provider can service the given URL."""

    async def read(self, request: IssueRequest) -> IssueDetails:
        """Fetch and normalize the issue details."""


_PROVIDERS: list[IssueProvider] = []


def _provider_is_configured(provider: IssueProvider) -> bool:
    """Return True when the provider declares itself as configured."""

    configured = getattr(provider, "is_configured", None)
    if callable(configured):
        return bool(configured())
    if configured is not None:
        return bool(configured)

    legacy_configured = getattr(provider, "configured", None)
    if callable(legacy_configured):
        return bool(legacy_configured())
    if legacy_configured is not None:
        return bool(legacy_configured)

    return True


def register_issue_provider(provider: IssueProvider) -> None:
    if provider in _PROVIDERS:
        return
    _PROVIDERS.append(provider)


def list_issue_providers() -> tuple[str, ...]:
    return tuple(
        provider.name for provider in _PROVIDERS if _provider_is_configured(provider)
    )


def _select_provider(issue_url: str, provider_name: str | None) -> IssueProvider:
    skipped_unconfigured: list[str] = []
    if provider_name:
        for provider in reversed(_PROVIDERS):
            if provider.name == provider_name:
                if not _provider_is_configured(provider):
                    raise ValueError(
                        f"Issue provider '{provider_name}' is not configured in this environment."
                    )
                return provider
        raise ValueError(f"No issue provider registered with name '{provider_name}'.")
    for provider in reversed(_PROVIDERS):
        if not provider.supports(issue_url):
            continue
        if not _provider_is_configured(provider):
            if provider.name not in skipped_unconfigured:
                skipped_unconfigured.append(provider.name)
            continue
        return provider
    if skipped_unconfigured:
        disabled = ", ".join(skipped_unconfigured)
        raise ValueError(
            "Unable to determine an issue provider for the supplied URL because "
            f"the following providers are not configured: {disabled}."
        )
    raise ValueError(
        "Unable to determine an issue provider for the supplied URL. "
        "Register a provider via register_issue_provider or supply provider explicitly."
    )


async def read_issue(request: IssueRequest) -> IssueDetails:
    """Read an issue using the best-matching registered provider."""

    provider = _select_provider(request.issue_url, request.provider)
    return await provider.read(request)


__all__ = [
    "IssueProvider",
    "IssueRequest",
    "list_issue_providers",
    "read_issue",
    "register_issue_provider",
]
