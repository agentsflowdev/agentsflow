from agentsflow.activities.issues.models import IssueComment, IssueDetails
from agentsflow.workflows.sdlc import _build_task_payload


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
