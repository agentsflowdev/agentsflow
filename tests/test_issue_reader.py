from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from agentsflow.activities.issues import IssueRequest, read_issue
from agentsflow.activities.issues.github import GitHubIssueProvider
from agentsflow.activities.issues.jira import JiraTaskRequest
from agentsflow.activities.issues.models import IssueComment, IssueDetails


@pytest.mark.asyncio
async def test_read_issue_routes_to_jira(monkeypatch):
    captured: dict[str, JiraTaskRequest] = {}
    expected = IssueDetails(
        issue_key="ABC-123",
        issue_url="https://example.atlassian.net/browse/ABC-123",
        summary="Summary",
        description="Body",
        status="To Do",
        comments=[IssueComment(id="1", author="alice", created=None, updated=None, body="hi")],
    )

    async def fake_fetch(request: JiraTaskRequest) -> IssueDetails:
        captured["request"] = request
        return expected

    monkeypatch.setattr("agentsflow.activities.issues.jira.fetch_jira_task", fake_fetch)

    monkeypatch.setenv("JIRA_EMAIL", "dev@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")

    result = await read_issue(IssueRequest(issue_url="https://example.atlassian.net/browse/ABC-123"))

    assert result == expected
    assert captured["request"].task_url == "https://example.atlassian.net/browse/ABC-123"


@pytest.mark.asyncio
async def test_read_issue_skips_unconfigured_providers(monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    expected = IssueDetails(
        issue_key="octo/widgets#99",
        issue_url="https://github.com/octo/widgets/issues/99",
        summary="Fallback",
        description="",
        status="open",
        comments=[],
    )
    captured: dict[str, IssueRequest] = {}

    async def fake_github_read(self, request: IssueRequest) -> IssueDetails:
        captured["request"] = request
        return expected

    monkeypatch.setattr(
        "agentsflow.activities.issues.github.GitHubIssueProvider.read",
        fake_github_read,
        raising=False,
    )

    result = await read_issue(IssueRequest(issue_url="https://github.com/octo/widgets/issues/99"))

    assert result == expected
    assert captured["request"].issue_url.endswith("/99")


@pytest.mark.asyncio
async def test_github_issue_provider_fetches_issue(monkeypatch):
    class FakeComment:
        def __init__(self) -> None:
            self.id = 101
            self.body = "Thanks for the fix!"
            self.created_at = datetime(2025, 1, 1, 12, 0, 0)
            self.updated_at = None
            self.user = SimpleNamespace(login="octocat", name="Octo Cat")

    class FakeIssue:
        def __init__(self) -> None:
            self.title = "Fix race condition"
            self.body = "Detailed description"
            self.state = "open"

        def get_comments(self):
            return [FakeComment()]

    class FakeRepo:
        def get_issue(self, number: int) -> FakeIssue:
            assert number == 42
            return FakeIssue()

    class FakeGithub:
        def __init__(self, login_or_token=None, timeout=None):
            self.token = login_or_token
            self.timeout = timeout

        def get_repo(self, full_name: str) -> FakeRepo:
            assert full_name == "octo/widgets"
            return FakeRepo()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("agentsflow.activities.issues.github.Github", FakeGithub)
    monkeypatch.setattr("agentsflow.activities.issues.github.asyncio.to_thread", immediate_to_thread)

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")

    provider = GitHubIssueProvider()
    request = IssueRequest(issue_url="https://github.com/octo/widgets/issues/42")

    result = await provider.read(request)

    assert result.issue_key == "octo/widgets#42"
    assert result.summary == "Fix race condition"
    assert result.status == "open"
    assert result.comments[0].author == "Octo Cat"


@pytest.mark.asyncio
async def test_read_issue_errors_when_no_provider():
    with pytest.raises(ValueError):
        await read_issue(IssueRequest(issue_url="https://example.com/issues/1"))


@pytest.mark.asyncio
async def test_read_issue_reports_unconfigured_provider(monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    with pytest.raises(ValueError) as excinfo:
        await read_issue(IssueRequest(issue_url="https://example.atlassian.net/browse/ABC-123"))

    assert "not configured" in str(excinfo.value)
