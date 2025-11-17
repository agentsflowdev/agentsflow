from __future__ import annotations

import pytest

from agentsflow.activities.issues import jira


@pytest.mark.asyncio
async def test_fetch_jira_task_success(monkeypatch):
    expected = jira.JiraTaskDetails(
        issue_key="ABC-123",
        issue_url="https://example.atlassian.net/browse/ABC-123",
        summary="Test issue",
        description="Details",
        status="In Progress",
        comments=[
            jira.JiraComment(
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

    request = jira.JiraTaskRequest(
        task_url="https://example.atlassian.net/browse/ABC-123",
        jira_email="user@example.com",
        jira_api_token="token",
    )

    result = await jira.fetch_jira_task(request)

    assert result == expected


@pytest.mark.asyncio
async def test_fetch_jira_task_requires_credentials():
    request = jira.JiraTaskRequest(
        task_url="https://example.atlassian.net/browse/ABC-123",
        jira_email="",
        jira_api_token="",
    )

    with pytest.raises(ValueError):
        await jira.fetch_jira_task(request)
