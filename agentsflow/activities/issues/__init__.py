"""Issue tracker integrations (Jira, GitHub Issues, etc.)."""

from __future__ import annotations

from typing import Any

from temporalio import activity

# Import providers for their side-effect registrations.
from . import github as _github_provider  # noqa: F401
from . import jira as _jira_provider  # noqa: F401
from .models import IssueComment, IssueDetails
from .reader import (
    IssueProvider,
    IssueRequest,
    list_issue_providers,
    register_issue_provider,
)
from .reader import (
    read_issue as _read_issue,
)


class IssueActivities:
    """Bundle of issue-tracker activities (Jira fetch + generic reader)."""

    @activity.defn(name="read_issue")
    async def read_issue(self, request: IssueRequest) -> IssueDetails:
        activity.logger.info(
            "Reading issue",
            extra={
                "issue_url": request.issue_url,
                "provider": request.provider,
                "timeout": request.timeout_seconds,
            },
        )
        result = await _read_issue(request)
        activity.logger.info(
            "Read issue",
            extra={
                "issue_url": request.issue_url,
                "provider": request.provider or "auto",
                "issue_key": result.issue_key,
            },
        )
        return result

    def activities(self) -> list[Any]:
        return [self.read_issue]


__all__ = [
    "IssueActivities",
    "IssueComment",
    "IssueDetails",
    "IssueProvider",
    "IssueRequest",
    "list_issue_providers",
    "read_issue",
    "register_issue_provider",
]
read_issue = _read_issue
