import re
from random import Random

import pytest
from pydantic import ValidationError

from agentsflow.activities.issues.models import IssueComment, IssueDetails
from agentsflow.workflows.process import (
    ProcessWorkflowInput,
    _build_task_payload,
    _issue_details_from_task_text,
)


def test_build_task_payload_filters_empty_comments() -> None:
    details = IssueDetails(
        issue_key="ABC-123",
        issue_url="https://example.atlassian.net/browse/ABC-123",
        summary="Short summary",
        description="Detailed description",
        status="To Do",
        comments=[
            IssueComment(id="1", author="alice", created=None, updated=None, body=" Looks good "),
            IssueComment(id="2", author="bob", created=None, updated=None, body=""),
            IssueComment(id="3", author="carol", created=None, updated=None, body=None),
        ],
    )

    payload = _build_task_payload(details)

    assert payload.comments == ["alice: Looks good"]


def test_issue_details_from_task_text_splits_summary_and_description() -> None:
    details = _issue_details_from_task_text("Fix login\n\nHandle missing cookie", rng=Random(0))

    assert details.summary == "Fix login"
    assert details.description == "Handle missing cookie"
    assert details.issue_url == "adhoc://task"
    assert re.match(r"TASK-[A-Z0-9]{8}", details.issue_key)


def test_process_workflow_input_requires_single_source() -> None:
    with pytest.raises(ValidationError):
        ProcessWorkflowInput(
            repository="/tmp/repo",
            issue_url=None,
            task_text=None,
        )

    with pytest.raises(ValidationError):
        ProcessWorkflowInput(
            repository="/tmp/repo",
            issue_url="https://example.com/1",
            task_text="Do something",
        )

    parsed = ProcessWorkflowInput(
        repository="/tmp/repo",
        issue_url="https://example.com/1",
    )
    assert parsed.issue_url == "https://example.com/1"
    assert parsed.task_text is None
