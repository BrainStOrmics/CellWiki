"""Contract tests for the standalone annotation client and smoke check."""

from __future__ import annotations

import email.message
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import annotation_client  # noqa: E402
import annotation_smoke  # noqa: E402


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def http_error(status: int, code: str, message: str, *, retry_after: str | None = None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    body = json.dumps(
        {"request_id": None, "error": {"code": code, "message": message, "retryable": status >= 500}}
    ).encode("utf-8")
    return urllib.error.HTTPError(
        "http://127.0.0.1/api/v1/annotation-support", status, message, headers, io.BytesIO(body)
    )


def response_body() -> dict[str, Any]:
    return {
        "request_id": "annotation-request",
        "status": "matched",
        "recommendation": {
            "candidate_id": "cd4_tcm_gpr183",
            "support_score": None,
            "support_level": "strong",
            "supporting_markers": ["CD4"],
            "contradictory_markers": [],
            "evidence_ids": ["E1"],
        },
        "alternative_candidates": [],
        "evidence": [
            {
                "evidence_id": "E1",
                "evidence_tier": 1,
                "claim": "CD4 is a positive marker.",
                "paper_id": "Chen_2024_CancerCell",
                "title": "A paper",
                "doi": "10.1016/j.ccell.2024.06.009",
                "url": "https://doi.org/10.1016/j.ccell.2024.06.009",
                "page_path": "wiki/cell_types/cd4_tcm_gpr183.md",
                "locator": "wiki/cell_types/cd4_tcm_gpr183.md:L25",
            }
        ],
        "warnings": [],
        "knowledge_version": "1ea9f0c0de6d4edde1a6e0009e8b2882484b04a6",
        "algorithm_version": "annotation-v1",
    }


def test_build_payload_enforces_documented_constraints():
    payload = annotation_client.build_payload(
        request_id="r1",
        species="Homo sapiens",
        tissue="blood",
        top_markers=["CD4", "cd4", " IL7R "],
        low_or_absent_markers=["FOXP3"],
    )
    assert payload["top_markers"] == ["CD4", "IL7R"]
    assert payload["low_or_absent_markers"] == ["FOXP3"]
    assert payload["cluster"] == {"id": "r1"}
    with pytest.raises(ValueError):
        annotation_client.build_payload(
            request_id="r1", species="Homo sapiens", tissue="blood", top_markers=[]
        )
    with pytest.raises(ValueError):
        annotation_client.build_payload(
            request_id="r1",
            species="Homo sapiens",
            tissue="blood",
            top_markers=["CD4"],
            low_or_absent_markers=["cd4"],
        )
    with pytest.raises(ValueError):
        annotation_client.build_payload(
            request_id="r1",
            species="Homo sapiens",
            tissue="blood",
            top_markers=["CD4"],
            max_candidates=9,
        )


def test_daemon_port_reads_the_running_daemon():
    def runner(command, **kwargs):
        assert command[-3:] == ["status", "--workspace", "kb"]
        return subprocess.CompletedProcess(
            command, 0, json.dumps({"state": "running", "port": 4242, "pid": 7}), ""
        )

    assert annotation_client.daemon_port("kb", runner=runner) == 4242


def test_daemon_port_reports_a_stopped_daemon():
    def runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, json.dumps({"state": "absent"}), "")

    with pytest.raises(annotation_client.AnnotationUnreachableError):
        annotation_client.daemon_port("kb", runner=runner)


def test_query_returns_the_parsed_response():
    def opener(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer token"
        return FakeResponse(200, json.dumps(response_body()).encode("utf-8"))

    result = annotation_client.query_evidence(
        "http://127.0.0.1:1234", "token", {"request_id": "r1"}, opener=opener
    )
    assert result["status"] == "matched"
    assert result["recommendation"]["candidate_id"] == "cd4_tcm_gpr183"


def test_query_retries_a_busy_knowledge_base():
    calls: list[int] = []
    delays: list[float] = []

    def opener(request, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(503, "KNOWLEDGE_BUSY", "busy", retry_after="5")
        return FakeResponse(200, json.dumps(response_body()).encode("utf-8"))

    result = annotation_client.query_evidence(
        "http://127.0.0.1:1234",
        "token",
        {"request_id": "r1"},
        opener=opener,
        sleeper=delays.append,
    )
    assert result["status"] == "matched"
    assert len(calls) == 2
    assert delays == [5.0]


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (400, "INVALID_REQUEST", annotation_client.AnnotationRequestError),
        (401, "UNAUTHORIZED", annotation_client.AnnotationUnauthorizedError),
        (503, "SERVICE_DISABLED", annotation_client.AnnotationServiceDisabledError),
    ],
)
def test_query_does_not_retry_terminal_failures(status, code, expected):
    calls: list[int] = []

    def opener(request, timeout=None):
        calls.append(1)
        raise http_error(status, code, code)

    with pytest.raises(expected):
        annotation_client.query_evidence(
            "http://127.0.0.1:1234",
            "token",
            {"request_id": "r1"},
            opener=opener,
            sleeper=lambda delay: None,
        )
    assert len(calls) == 1


def test_query_gives_up_after_the_attempt_budget():
    calls: list[int] = []

    def opener(request, timeout=None):
        calls.append(1)
        raise http_error(500, "INTERNAL_ERROR", "boom")

    with pytest.raises(annotation_client.AnnotationError) as failure:
        annotation_client.query_evidence(
            "http://127.0.0.1:1234",
            "token",
            {"request_id": "r1"},
            max_attempts=3,
            opener=opener,
            sleeper=lambda delay: None,
        )
    assert failure.value.code == "INTERNAL_ERROR"
    assert len(calls) == 3


def test_query_reports_an_unreachable_service():
    def opener(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(annotation_client.AnnotationUnreachableError):
        annotation_client.query_evidence(
            "http://127.0.0.1:1234", "token", {"request_id": "r1"}, opener=opener
        )


def test_query_requires_a_token(monkeypatch):
    monkeypatch.delenv(annotation_client.TOKEN_ENV, raising=False)
    with pytest.raises(annotation_client.AnnotationUnauthorizedError):
        annotation_client.cellwiki_query(
            species="Homo sapiens", tissue="blood", top_markers=["CD4"], base_url="http://x"
        )


def test_smoke_checks_catch_a_broken_contract():
    broken = response_body()
    broken["recommendation"]["evidence_ids"] = ["E9"]
    broken["recommendation"]["support_score"] = 0.9
    failed = {name for name, passed, _ in annotation_smoke.check_response(broken) if not passed}
    assert "every evidence_ids entry resolves" in failed
    assert "support_score stays null" in failed


def test_smoke_checks_accept_a_valid_response():
    assert all(passed for _, passed, _ in annotation_smoke.check_response(response_body()))


def test_summary_mentions_the_recommendation():
    text = annotation_client.summarize(response_body())
    assert "cd4_tcm_gpr183" in text
    assert "knowledge_version" in text
