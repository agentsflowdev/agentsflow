from __future__ import annotations

import pytest

from agentsflow.activities.issues import jira
from agentsflow.activities.issues.models import IssueComment, IssueDetails


@pytest.mark.asyncio
async def test_fetch_jira_task_success(monkeypatch):
    expected = IssueDetails(
        issue_key="ABC-123",
        issue_url="https://example.atlassian.net/browse/ABC-123",
        summary="Test issue",
        description="Details",
        status="In Progress",
        comments=[
            IssueComment(
                id="1",
                author="Jane",
                created="2025-01-01",
                updated=None,
                body="Looks good",
            )
        ],
    )

    async def fake_to_thread(func, *args, **kwargs):
        assert func is jira._fetch_issue_details
        return expected

    monkeypatch.setattr(jira.asyncio, "to_thread", fake_to_thread)

    result = await jira._fetch_jira_issue(
        task_url="https://example.atlassian.net/browse/ABC-123",
        email="user@example.com",
        token="token",
    )

    assert result == expected


@pytest.mark.asyncio
async def test_fetch_jira_task_requires_credentials():
    with pytest.raises(ValueError):
        await jira._fetch_jira_issue(
            task_url="https://example.atlassian.net/browse/ABC-123",
            email="",
            token="",
        )
