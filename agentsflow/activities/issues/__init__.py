"""Issue tracker integrations (Jira, GitHub Issues, etc.)."""

from __future__ import annotations

from temporalio import activity

from .models import IssueComment, IssueDetails
from .reader import (
    IssueProvider,
    IssueRequest,
    list_issue_providers,
    read_issue as _read_issue,
    register_issue_provider,
)
from .jira import (
    JiraComment,
    JiraTaskDetails,
    JiraTaskRequest,
    fetch_jira_task as _fetch_jira_task,
)

# Import providers for their side-effect registrations.
from . import github as _github_provider  # noqa: F401
from . import jira as _jira_provider  # noqa: F401


class IssueActivities:
    """Bundle of issue-tracker activities (Jira fetch + generic reader)."""

    @activity.defn(name="fetch_jira_task")
    async def fetch_jira_task(self, request: JiraTaskRequest) -> IssueDetails:
        activity.logger.info(
            "Fetching Jira task",
            extra={"task_url": request.task_url, "timeout": request.timeout_seconds},
        )
        result = await _fetch_jira_task(request)
        activity.logger.info(
            "Fetched Jira task",
            extra={"task_url": request.task_url, "issue_key": result.issue_key},
        )
        return result

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

    def activities(self) -> list:
        return [self.fetch_jira_task, self.read_issue]


__all__ = [
    "IssueActivities",
    "IssueComment",
    "IssueDetails",
    "IssueProvider",
    "IssueRequest",
    "JiraComment",
    "JiraTaskDetails",
    "JiraTaskRequest",
    "fetch_jira_task",
    "list_issue_providers",
    "read_issue",
    "register_issue_provider",
]


fetch_jira_task = _fetch_jira_task
read_issue = _read_issue
