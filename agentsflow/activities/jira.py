"""Temporal helper routines for fetching Jira task details."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from contextlib import suppress
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qs, urlparse

from jira import JIRA
from jira.exceptions import JIRAError
from temporalio import activity


ISSUE_KEY_RE = re.compile(r"([A-Z][A-Z0-9_]+-\d+)", re.IGNORECASE)
STOP_SEGMENTS = {
    "browse",
    "projects",
    "issues",
    "secure",
    "board",
    "boards",
    "rapidboard",
    "wiki",
    "page",
    "portal",
    "customer",
    "servicedesk",
    "ticket",
    "view",
}


@dataclass
class JiraComment:
    id: str | None
    author: str
    created: str | None
    updated: str | None
    body: str


@dataclass
class JiraTaskDetails:
    issue_key: str
    issue_url: str
    summary: str
    description: str
    status: str | None
    comments: list[JiraComment]


@dataclass
class JiraTaskRequest:
    task_url: str
    jira_email: str
    jira_api_token: str
    timeout_seconds: float = 15.0


def _iter_url_values(path: str) -> Iterable[str]:
    if not path:
        return []
    if "/" not in path:
        return [path]
    return [segment for segment in path.split("/") if segment]


def _candidate_base_urls(parsed_url, issue_key: str) -> list[str]:
    base = f"{parsed_url.scheme}://{parsed_url.netloc}".rstrip("/")
    candidates = [base]
    segments = [segment for segment in _iter_url_values(parsed_url.path) if segment]
    current = base

    for segment in segments:
        lowered = segment.lower()
        if lowered in STOP_SEGMENTS or segment.upper() == issue_key:
            break
        current = f"{current}/{segment}"
        candidates.append(current)

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered


def _extract_issue_key(task_url: str) -> tuple[str, list[str], str]:
    parsed_url = urlparse(task_url)

    for segment in _iter_url_values(parsed_url.path):
        match = ISSUE_KEY_RE.search(segment)
        if match:
            issue_key = match.group(1).upper()
            return issue_key, _candidate_base_urls(parsed_url, issue_key), parsed_url.geturl()

    for values in parse_qs(parsed_url.query, keep_blank_values=False).values():
        for value in values:
            match = ISSUE_KEY_RE.search(value)
            if match:
                issue_key = match.group(1).upper()
                return issue_key, _candidate_base_urls(parsed_url, issue_key), parsed_url.geturl()

    if parsed_url.fragment:
        match = ISSUE_KEY_RE.search(parsed_url.fragment)
        if match:
            issue_key = match.group(1).upper()
            return issue_key, _candidate_base_urls(parsed_url, issue_key), parsed_url.geturl()

    raise ValueError("Could not detect a Jira issue key in the provided URL.")


def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (_adf_to_text(child) for child in node) if part)
    if isinstance(node, dict):
        node_type = node.get("type")
        content = node.get("content") or []

        if node_type == "text":
            text = node.get("text", "")
            for mark in node.get("marks") or []:
                if mark.get("type") == "link":
                    href = (mark.get("attrs") or {}).get("href")
                    if href:
                        text = f"{text} ({href})" if text else href
            return text

        if node_type == "mention":
            attrs = node.get("attrs") or {}
            return attrs.get("text") or attrs.get("id") or ""

        if node_type == "emoji":
            attrs = node.get("attrs") or {}
            return attrs.get("text") or attrs.get("shortName") or ""

        if node_type == "hardBreak":
            return "\n"

        if node_type in {"paragraph", "blockCard", "inlineCard"}:
            return _collapse_lines(_adf_to_text(content))

        if node_type == "heading":
            text = _collapse_lines(_adf_to_text(content))
            return text.upper() if text else ""

        if node_type in {"bulletList", "orderedList"}:
            items: list[str] = []
            is_ordered = node_type == "orderedList"
            start = (node.get("attrs") or {}).get("order", 1)
            for index, item in enumerate(content or [], start=start):
                text = _collapse_lines(_adf_to_text(item)).strip()
                if not text:
                    continue
                prefix = f"{index}. " if is_ordered else "- "
                items.append(f"{prefix}{text}")
            return "\n".join(items)

        if node_type == "listItem":
            return _collapse_lines(_adf_to_text(content))

        if node_type == "table":
            rows = [_collapse_lines(_adf_to_text(row)) for row in content]
            return "\n".join(rows)

        if node_type == "tableRow":
            cells: list[str] = []
            for idx, cell in enumerate(content or [], start=1):
                text = _collapse_lines(_adf_to_text(cell)).strip()
                if text:
                    cells.append(f"{idx}. {text}")
            return " | ".join(cells)

        if node_type in {"tableCell", "tableHeader"}:
            return _collapse_lines(_adf_to_text(content))

        if node_type == "codeBlock":
            text = _collapse_lines(_adf_to_text(content))
            return f"\n{text}\n"

        if node_type == "panel":
            return _collapse_lines(_adf_to_text(content))

        if node_type == "doc":
            return _collapse_lines(_adf_to_text(content))

        return _collapse_lines(_adf_to_text(content))

    return str(node)


def _collapse_lines(text: str) -> str:
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return "\n".join(collapsed).strip("\n")


def _build_response(
    issue_data: dict[str, Any],
    comments: Sequence[dict[str, Any]],
    issue_key: str,
    original_url: str,
) -> JiraTaskDetails:
    fields = issue_data.get("fields", {})
    description_raw = fields.get("description")
    description = _adf_to_text(description_raw).strip()
    summary = fields.get("summary") or ""
    status_name = (fields.get("status") or {}).get("name")

    parsed_comments: list[JiraComment] = []
    for item in comments or []:
        body_text = _adf_to_text(item.get("body")).strip()
        author = item.get("author") or {}
        display_name = author.get("displayName") or author.get("emailAddress") or ""
        parsed_comments.append(
            JiraComment(
                id=item.get("id"),
                author=display_name,
                created=item.get("created"),
                updated=item.get("updated"),
                body=body_text,
            )
        )

    return JiraTaskDetails(
        issue_key=issue_key,
        issue_url=original_url,
        summary=summary,
        description=description,
        status=status_name,
        comments=parsed_comments,
    )


def _format_jira_error(exc: JIRAError, issue_key: str) -> str:
    status = getattr(exc, "status_code", None)
    text = (getattr(exc, "text", "") or str(exc)).strip()
    if status:
        base = f"Jira API returned status {status} while retrieving issue '{issue_key}'."
    else:
        base = f"Jira API error while retrieving issue '{issue_key}'."
    if text:
        return f"{base} Details: {text}"
    return base


def _fetch_issue_details(
    base_candidates: Sequence[str],
    issue_key: str,
    email: str,
    token: str,
    original_url: str,
    *,
    timeout_seconds: float,
) -> JiraTaskDetails:
    last_error: Exception | None = None

    for base_url in base_candidates:
        client: JIRA | None = None
        try:
            client = JIRA(server=base_url, basic_auth=(email, token), timeout=timeout_seconds)
            issue = client.issue(issue_key, expand="renderedFields,names")
            comments = client.comments(issue)

            raw_issue = issue.raw
            raw_comments: list[dict[str, Any]] = []
            for comment in comments or []:
                raw = getattr(comment, "raw", None)
                if isinstance(raw, dict):
                    raw_comments.append(raw)
                else:
                    author = getattr(comment, "author", None)
                    raw_comments.append(
                        {
                            "id": getattr(comment, "id", None),
                            "author": {
                                "displayName": getattr(author, "displayName", "") if author else "",
                                "emailAddress": getattr(author, "emailAddress", "") if author else "",
                            },
                            "created": getattr(comment, "created", None),
                            "updated": getattr(comment, "updated", None),
                            "body": getattr(comment, "body", ""),
                        }
                    )

            return _build_response(raw_issue, raw_comments, issue_key, original_url)
        except JIRAError as exc:
            if getattr(exc, "status_code", None) in {401, 403}:
                msg = "Jira authentication failed. Please verify the account email/username and API token."
                raise PermissionError(msg) from exc
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            if client is not None:
                with suppress(Exception):
                    client.close()

    if isinstance(last_error, JIRAError):
        raise last_error
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to retrieve Jira issue '{issue_key}' for unknown reasons.")


async def fetch_jira_task(request: JiraTaskRequest) -> JiraTaskDetails:
    task_url = (request.task_url or "").strip()
    email = (request.jira_email or "").strip()
    token = (request.jira_api_token or "").strip()

    if not task_url:
        raise ValueError("Task URL is required.")
    if not email or not token:
        raise ValueError("Both Jira account email/username and API token must be provided.")

    issue_key, base_candidates, original = _extract_issue_key(task_url)

    try:
        details = await asyncio.to_thread(
            _fetch_issue_details,
            base_candidates,
            issue_key,
            email,
            token,
            original,
            timeout_seconds=request.timeout_seconds,
        )
    except PermissionError:
        activity.logger.warning(
            "Jira authentication failed",
            extra={"issue_key": issue_key, "base_candidates": base_candidates},
        )
        raise
    except JIRAError as exc:
        message = _format_jira_error(exc, issue_key)
        activity.logger.error(
            "Jira API error",
            extra={"issue_key": issue_key, "message": message},
        )
        raise RuntimeError(message) from exc

    activity.logger.info(
        "Fetched Jira task",
        extra={"issue_key": details.issue_key, "status": details.status},
    )
    return details
