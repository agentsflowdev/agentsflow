"""GitHub Issue provider implementation backed by PyGithub."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from urllib.parse import urlparse

from github import Github
from github.GithubException import (
    BadCredentialsException,
    GithubException,
    UnknownObjectException,
)

from .models import IssueComment, IssueDetails
from .reader import IssueProvider, IssueRequest, register_issue_provider

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_TIMEOUT_ENV = "GITHUB_TIMEOUT_SECONDS"


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def _normalize_author(user) -> str:
    if user is None:
        return ""
    name = getattr(user, "name", None) or ""
    login = getattr(user, "login", None) or ""
    return name or login or ""


def _parse_issue_segments(issue_url: str) -> tuple[str, str, int]:
    parsed = urlparse(issue_url)
    host = parsed.netloc.lower()
    if not host.endswith("github.com"):
        raise ValueError(
            "Only github.com issue URLs are supported by the GitHub provider."
        )
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 4:
        raise ValueError("GitHub issue URL must include owner, repo, and issue number.")
    owner, repo = segments[0], segments[1]
    try:
        issues_index = segments.index("issues")
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError("GitHub issue URL must contain the 'issues' segment.") from exc
    try:
        number = int(segments[issues_index + 1])
    except (IndexError, ValueError) as exc:
        raise ValueError(
            "GitHub issue URL must end with the numeric issue identifier."
        ) from exc
    return owner, repo, number


def _fetch_github_issue(
    *,
    owner: str,
    repo: str,
    issue_number: int,
    issue_url: str,
    token: str | None,
    timeout_seconds: float,
) -> IssueDetails:
    github = Github(login_or_token=token, timeout=timeout_seconds)
    try:
        repository = github.get_repo(f"{owner}/{repo}")
        issue = repository.get_issue(number=issue_number)
        comments = list(issue.get_comments())
    except BadCredentialsException as exc:
        raise PermissionError(
            "GitHub authentication failed; please check the token provided."
        ) from exc
    except UnknownObjectException as exc:
        raise ValueError(
            f"GitHub issue {owner}/{repo}#{issue_number} could not be found or you lack access."
        ) from exc
    except GithubException as exc:  # pragma: no cover - PyGithub error wrapper
        raise RuntimeError(
            f"GitHub API error while fetching issue: {exc.data or exc}"
        ) from exc

    parsed_comments: list[IssueComment] = []
    for comment in comments:
        parsed_comments.append(
            IssueComment(
                id=str(getattr(comment, "id", "") or "") or None,
                author=_normalize_author(getattr(comment, "user", None)),
                created=_isoformat(getattr(comment, "created_at", None)),
                updated=_isoformat(getattr(comment, "updated_at", None)),
                body=getattr(comment, "body", "") or "",
            )
        )

    description = getattr(issue, "body", "") or ""
    summary = getattr(issue, "title", "") or ""
    status = getattr(issue, "state", None)

    return IssueDetails(
        issue_key=f"{owner}/{repo}#{issue_number}",
        issue_url=issue_url,
        summary=summary,
        description=description,
        status=status,
        comments=parsed_comments,
    )


class GitHubIssueProvider(IssueProvider):
    name = "github"

    def supports(self, issue_url: str) -> bool:
        host = urlparse(issue_url).netloc.lower()
        return host.endswith("github.com")

    async def read(self, request: IssueRequest) -> IssueDetails:
        owner, repo, number = _parse_issue_segments(request.issue_url)
        token = os.environ.get(GITHUB_TOKEN_ENV)
        timeout_override = os.environ.get(GITHUB_TIMEOUT_ENV)
        timeout_seconds = _coerce_timeout(timeout_override, request.timeout_seconds)
        return await asyncio.to_thread(
            _fetch_github_issue,
            owner=owner,
            repo=repo,
            issue_number=number,
            issue_url=request.issue_url,
            token=token,
            timeout_seconds=timeout_seconds,
        )


def _coerce_timeout(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"{GITHUB_TIMEOUT_ENV} must be numeric when set.") from exc
    if parsed <= 0:
        raise ValueError(f"{GITHUB_TIMEOUT_ENV} must be greater than zero when set.")
    return parsed


register_issue_provider(GitHubIssueProvider())


__all__ = ["GitHubIssueProvider"]
