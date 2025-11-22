from typing import Any

from agentsflow.cli import ClarificationPending, _print_clarification


def test_clarification_pending_payload_roundtrip() -> None:
    payload: dict[str, Any] = {
        "status": "clarification_required",
        "questions": ["Confirm deployment target"],
        "assumptions": ["Staging credentials available"],
    }

    exc = ClarificationPending(payload)

    assert exc.payload == payload


def test_print_clarification_plain(capsys) -> None:  # type: ignore[no-redef]
    payload = {
        "status": "clarification_required",
        "questions": ["Need API endpoint"],
        "assumptions": [],
    }

    _print_clarification(payload, as_json=False)
    out = capsys.readouterr().out

    assert "Workflow paused" in out
    assert "Need API endpoint" in out


def test_print_clarification_json(capsys) -> None:  # type: ignore[no-redef]
    payload = {
        "status": "clarification_required",
        "questions": [],
        "assumptions": ["Use new staging cluster"],
    }

    _print_clarification(payload, as_json=True)
    out = capsys.readouterr().out

    assert "clarification_required" in out
    assert "Use new staging cluster" in out
