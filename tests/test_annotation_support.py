"""Local contracts and evidence gates; no caller, provider or real workspace required."""

import json
import sqlite3
import subprocess
import socket
import threading
import time
from pathlib import Path
from shutil import copyfile

import pytest
import httpx
import uvicorn
from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.annotation import AnnotationRequest
from cellwiki.services.annotation_support import AnnotationSupportService, AnnotationUnavailable
from cellwiki.services.runtime_store import RuntimeStore

ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/v1/annotation-support"


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def page(identity: str = "cd4_cell", *, markers: str = "[CD4, IL7R]", title: bool = True) -> str:
    reference = "    title: Test paper\n    doi: 10.1234/test\n    url: https://doi.org/10.1234/test\n" if title else ""
    return (
        "---\n"
        f"standard_name: {identity}\ndisplay_name: CD4 cell\naliases: [CD4 T]\n"
        "cl_id: null\nparent_type: t_cell\nreferences:\n  - paper_id: paper_1\n"
        f"{reference}evidence_tier: 4\nsource_count: 1\npositive_markers: {markers}\n"
        "negative_markers: [FOXP3]\ntissues: [blood]\nspecies: [Homo sapiens]\nconflicts: []\n---\n"
        "# CD4 cell\n\n## Markers\n\n"
        "| Marker | Type | Evidence | Source |\n| --- | --- | --- | --- |\n"
        "| [[CD4]] | positive | Tier 2 | [paper_1](#references) |\n"
        "| [[IL7R]] | positive | Tier 3 | [paper_1](#references) |\n"
        "| [[FOXP3]] | negative | Tier 2 | [paper_1](#references) |\n\n"
        "## Contexts\n\n### Homo sapiens\n\n**Tissues:** [[blood]]\n\n"
        "**Diseases:** [[healthy]]\n\n**Source:** [paper_1](#references)\n\n"
        "## References\n\n- Unbound title [10.9999/wrong](https://doi.org/10.9999/wrong)\n"
    )


def payload(**changes) -> dict:
    result = {"request_id": "cluster-1", "species": "Homo sapiens", "tissue": "blood",
              "cluster": {"id": "cluster:1"}, "top_markers": ["CD4", "IL7R"]}
    result.update(changes)
    return result


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "wiki/cell_types").mkdir(parents=True)
    (tmp_path / "raw/paper_1").mkdir(parents=True)
    (tmp_path / "raw/paper_1/source.md").write_text("Test paper", encoding="utf-8")
    (tmp_path / "wiki/cell_types/cd4_cell.md").write_text(page(), encoding="utf-8")
    (tmp_path / ".gitignore").write_text("data/runtime/\n", encoding="utf-8")
    copyfile(ROOT / "schema.md", tmp_path / "schema.md")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "fixture")
    return tmp_path


def query(root: Path, **changes):
    return AnnotationSupportService(root).query(AnnotationRequest.model_validate(payload(**changes)))


def runtime_row(root: Path, *, run_status: str = "succeeded", verdict: str | None = None, maintenance: str = "ok"):
    store = RuntimeStore(root)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r1", "t1", run_status,
             json.dumps({"status": run_status, "snapshot_commit": git(root, "rev-parse", "HEAD")}), "2026-10-12"),
        )
        if verdict:
            connection.execute(
                "INSERT INTO pending_diffs (diff_id,run_id,thread_id,status,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                ("diff_r1_1", "r1", "t1", verdict, json.dumps({"data": {"maintenance": {"status": maintenance}}}), "2026-10-12", "2026-10-12"),
            )
    return store


def test_grounded_matching_and_stability(workspace):
    before = git(workspace, "status", "--porcelain")
    result = query(workspace)
    assert result == query(workspace)
    assert result.status == "matched"
    assert result.knowledge_version == git(workspace, "rev-parse", "HEAD")
    assert result.recommendation.support_score is None
    assert result.recommendation.support_level == "strong"
    assert result.recommendation.supporting_markers == ["CD4", "IL7R"]
    assert result.evidence[0].evidence_tier == 2
    assert result.evidence[1].evidence_tier == 3
    assert {item.evidence_id for item in result.evidence} == set(result.recommendation.evidence_ids)
    for evidence in result.evidence:
        line = int(evidence.locator.split(":L")[1])
        assert "Tier" in (workspace / evidence.page_path).read_text().splitlines()[line - 1]
    assert git(workspace, "status", "--porcelain") == before
    assert not (workspace / "data/runtime/cellwiki.db").exists()


@pytest.mark.parametrize("changes", [
    {"top_markers": []}, {"max_candidates": 0}, {"max_candidates": True},
    {"request_id": " "}, {"species": " "}, {"top_markers": [" "]},
    {"top_markers": ["CD4"] * 51}, {"low_or_absent_markers": ["FOXP3"] * 31},
    {"low_or_absent_markers": ["cd4"]}, {"top_markers": [1]},
    {"cluster": {"id": "x", "n_cells": 0}},
    {"cluster": {"id": "x", "current_confidence": 1.1}},
    {"cluster": {"id": "x", "fraction_in_dataset": -0.1}},
    {"author_cell_type": "forbidden"}, {"cluster": {"id": "x", "patient_id": "forbidden"}},
])
def test_bad_requests(workspace, changes):
    with TestClient(create_app(workspace, annotation_token="evidence")) as client:
        response = client.post(PATH, json=payload(**changes), headers={"Authorization": "Bearer evidence"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_deduplication_and_current_annotation_does_not_anchor(workspace):
    assert query(workspace, top_markers=["CD4", "cd4", "IL7R"]).recommendation.supporting_markers == ["cd4", "IL7R"]
    result = query(workspace, cluster={"id": "x", "current_cell_type": "B cell", "current_confidence": 0.99})
    assert result.recommendation.candidate_id == "cd4_cell"


def test_no_match(workspace):
    result = query(workspace, top_markers=["ZZZ"])
    assert result.status == "no_match"
    assert result.recommendation is None and not result.evidence


@pytest.mark.parametrize("changes", [
    {"top_markers": ["CD4", "FOXP3"]},
    {"top_markers": ["CD4"], "low_or_absent_markers": ["IL7R"]},
    {"tissue": "brain"}, {"species": "Mus musculus"}, {"disease": "cancer"},
])
def test_ambiguity_contradictions_context(workspace, changes):
    result = query(workspace, **changes)
    assert result.status == "ambiguous" and result.recommendation is None
    assert result.alternative_candidates
    if "low_or_absent_markers" in changes:
        assert result.alternative_candidates[0].contradictory_markers == ["IL7R"]
    if "tissue" in changes:
        assert result.alternative_candidates[0].context_match.tissue == "cross_context"
        assert result.warnings


def test_ties_detected_before_limit(workspace):
    (workspace / "wiki/cell_types/another.md").write_text(page("another"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "tie")
    result = query(workspace, max_candidates=1)
    assert result.status == "ambiguous"
    assert result.alternative_candidates[0].candidate_id == "another"


def test_worktree_and_index_are_not_knowledge(workspace):
    original = query(workspace)
    (workspace / "wiki/cell_types/cd4_cell.md").write_text("broken", encoding="utf-8")
    git(workspace, "add", "wiki")
    (workspace / "wiki/cell_types/untracked.md").write_text("broken", encoding="utf-8")
    (workspace / "schema.md").write_text("broken", encoding="utf-8")
    assert query(workspace) == original


def test_unbound_reference_metadata_never_uses_list_order(workspace):
    text = page(title=False).replace(
        "references:\n  - paper_id: paper_1\n",
        "references:\n  - paper_id: paper_1\n  - paper_id: paper_2\n",
    ).replace(
        "## References\n\n- Unbound title [10.9999/wrong](https://doi.org/10.9999/wrong)",
        "## References\n\n- First paper [10.9999/first](https://doi.org/10.9999/first)\n"
        "- Second paper [10.9999/second](https://doi.org/10.9999/second)",
    )
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(text, encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "missing metadata")
    result = query(workspace)
    assert all(item.title is None and item.doi is None and item.url is None for item in result.evidence)
    assert result.warnings


def test_single_reference_line_can_bind_metadata_without_guessing(workspace):
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(
        page(title=False).replace(
            "## References\n\n- Unbound title [10.9999/wrong](https://doi.org/10.9999/wrong)",
            "## References\n\n- Unique title [10.9999/unique](https://doi.org/10.9999/unique)",
        ),
        encoding="utf-8",
    )
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "bind unique reference")
    result = query(workspace)
    assert result.evidence[0].title == "Unique title"
    assert result.evidence[0].doi == "10.9999/unique"
    assert result.evidence[0].url == "https://doi.org/10.9999/unique"


@pytest.mark.parametrize("status", ["queued", "running", "unfinished", "waiting_confirmation", "cancelling", "retrying"])
def test_active_run_blocks(workspace, status):
    runtime_row(workspace, run_status=status)
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


@pytest.mark.parametrize("verdict,maintenance", [("pending", "ok"), ("accepted", "failed"), ("rejected", "failed")])
def test_pending_and_maintenance_block(workspace, verdict, maintenance):
    runtime_row(workspace, verdict=verdict, maintenance=maintenance)
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


@pytest.mark.parametrize("verdict", ["accepted", "rejected"])
def test_resolved_and_maintained_allows(workspace, verdict):
    runtime_row(workspace, verdict=verdict)
    assert query(workspace).status == "matched"


def test_failed_unapproved_commit_blocks(workspace):
    runtime_row(workspace, run_status="failed")
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "unapproved")
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_database_writer_blocks_capture(workspace):
    store = runtime_row(workspace)
    with sqlite3.connect(store.path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
            query(workspace)


def alembic_only_database(workspace: Path) -> Path:
    """A runtime database with only the Alembic baseline tables."""
    database = workspace / "data/runtime/cellwiki.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE agent_runs (run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, "
            "status TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE agent_events (run_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
            "event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, "
            "PRIMARY KEY(run_id, sequence))"
        )
    return database


def test_alembic_only_runtime_database_does_not_block(workspace):
    alembic_only_database(workspace)
    assert query(workspace).status == "matched"


def test_alembic_only_runtime_database_still_blocks_unapproved_leftovers(workspace):
    database = alembic_only_database(workspace)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r1", "t1", "failed",
             json.dumps({"status": "failed", "snapshot_commit": git(workspace, "rev-parse", "HEAD")}),
             "2026-10-12"),
        )
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "unapproved")
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_auth_is_separate_and_does_not_initialize_runtime(workspace, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Annotation must not construct AgentRuntimeManager")
    monkeypatch.setattr("cellwiki.api.app.AgentRuntimeManager", forbidden)
    with TestClient(create_app(workspace, local_token="desktop", annotation_token="evidence")) as client:
        assert client.post(PATH, json=payload()).status_code == 401
        assert client.post(PATH, json=payload(), headers={"Authorization": "Bearer desktop"}).status_code == 401
        assert client.post(PATH, json=payload(), headers={"Authorization": "Bearer evidence"}).status_code == 200
        assert client.post("/api/agent/threads", headers={"Authorization": "Bearer evidence"}).status_code == 401
        assert client.post(PATH + "/", json=payload(), headers={"Authorization": "Bearer evidence"}).status_code == 200


def test_disabled_and_malformed(workspace):
    with TestClient(create_app(workspace, annotation_token="")) as client:
        assert client.post(PATH, json=payload()).json()["error"]["code"] == "SERVICE_DISABLED"
    with TestClient(create_app(workspace, annotation_token="evidence")) as client:
        headers = {"Authorization": "Bearer evidence"}
        assert client.post(PATH, content="{", headers=headers).status_code == 400
        assert client.post(PATH, content="x" * 64001, headers=headers).status_code == 400


def test_unavailable_is_not_no_match(tmp_path):
    with TestClient(create_app(tmp_path, annotation_token="evidence")) as client:
        response = client.post(PATH, json=payload(), headers={"Authorization": "Bearer evidence"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "KNOWLEDGE_UNAVAILABLE"
    assert str(tmp_path) not in response.text


def test_only_grounded_markers_are_returned(workspace):
    text = page(markers="[CD4, IL7R, UNBOUND]").replace(
        "| [[IL7R]] | positive | Tier 3 | [paper_1](#references) |", ""
    )
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(text, encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "partial evidence")
    result = query(workspace, top_markers=["CD4", "IL7R", "UNBOUND"])
    assert result.recommendation.supporting_markers == ["CD4"]
    assert len(result.evidence) == 2
    assert all("IL7R" not in item.claim and "UNBOUND" not in item.claim for item in result.evidence)


def test_failed_run_preserves_previously_accepted_unit(workspace):
    store = runtime_row(workspace, run_status="failed", verdict="accepted")
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "approved unit")
    approved = git(workspace, "rev-parse", "HEAD")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE pending_diffs SET payload=?",
            (json.dumps({"head_commit": approved, "data": {"maintenance": {"status": "ok"}}}),),
        )
    assert query(workspace).recommendation.supporting_markers == ["CD4"]
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "unapproved tail")
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_older_failed_run_leftover_cannot_be_hidden_by_later_success(workspace):
    store = RuntimeStore(workspace)
    base = git(workspace, "rev-parse", "HEAD")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r_failed", "t1", "failed",
             json.dumps({"status": "failed", "snapshot_commit": base}), "2026-10-12"),
        )
    # 段尾发布被挡下时，失败 run 的提交不会生成任何 pending 单元
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "failed run leftover")
    leftover = git(workspace, "rev-parse", "HEAD")
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "later approved change")
    approved = git(workspace, "rev-parse", "HEAD")
    # 后续成功 run 的快照包含旧残留，它的审批单元只覆盖自己的提交
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r_ok", "t1", "succeeded",
             json.dumps({"status": "succeeded", "snapshot_commit": leftover}), "2026-10-13"),
        )
        connection.execute(
            "INSERT INTO pending_diffs (diff_id,run_id,thread_id,status,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("diff_r_ok_1", "r_ok", "t1", "accepted",
             json.dumps({"snapshot_commit": leftover, "head_commit": approved,
                         "data": {"maintenance": {"status": "ok"}}}),
             "2026-10-13", "2026-10-13"),
        )
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_older_failed_run_tail_after_accepted_unit_blocks(workspace):
    store = RuntimeStore(workspace)
    base = git(workspace, "rev-parse", "HEAD")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r_failed", "t1", "failed",
             json.dumps({"status": "failed", "snapshot_commit": base}), "2026-10-12"),
        )
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "reviewed unit")
    reviewed = git(workspace, "rev-parse", "HEAD")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO pending_diffs (diff_id,run_id,thread_id,status,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("diff_r_failed_1", "r_failed", "t1", "accepted",
             json.dumps({"snapshot_commit": base, "head_commit": reviewed,
                         "data": {"maintenance": {"status": "ok"}}}),
             "2026-10-12", "2026-10-12"),
        )
    # 单元判定后同一失败 run 又有未发布提交，随后被成功 run 的快照吸收
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(markers="[CD4, IL7R, GPR183]"), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "unpublished tail")
    tail = git(workspace, "rev-parse", "HEAD")
    (workspace / "wiki/cell_types/cd4_cell.md").write_text(page(), encoding="utf-8")
    git(workspace, "add", "wiki")
    git(workspace, "commit", "-m", "later approved change")
    approved = git(workspace, "rev-parse", "HEAD")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO agent_runs (run_id,thread_id,status,payload,updated_at) VALUES (?,?,?,?,?)",
            ("r_ok", "t1", "succeeded",
             json.dumps({"status": "succeeded", "snapshot_commit": tail}), "2026-10-13"),
        )
        connection.execute(
            "INSERT INTO pending_diffs (diff_id,run_id,thread_id,status,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("diff_r_ok_1", "r_ok", "t1", "accepted",
             json.dumps({"snapshot_commit": tail, "head_commit": approved,
                         "data": {"maintenance": {"status": "ok"}}}),
             "2026-10-13", "2026-10-13"),
        )
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_older_failed_maintenance_cannot_be_hidden(workspace):
    store = runtime_row(workspace, verdict="accepted", maintenance="failed")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "INSERT INTO pending_diffs (diff_id,run_id,thread_id,status,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            ("diff_r1_2", "r1", "t1", "accepted", json.dumps({"data": {"maintenance": {"status": "ok"}}}), "2026-10-13", "2026-10-13"),
        )
    with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
        query(workspace)


def test_runtime_maintenance_guard_blocks(workspace):
    from cellwiki.services.agent_runtime import AgentRuntimeManager

    runtime = object.__new__(AgentRuntimeManager)
    runtime._maintenance_lock = threading.RLock()
    ready = threading.Event()
    release = threading.Event()

    def maintain():
        with runtime._maintenance_lock:
            ready.set()
            release.wait(10)

    worker = threading.Thread(target=maintain)
    worker.start()
    assert ready.wait(5)
    try:
        with pytest.raises(AnnotationUnavailable, match="KNOWLEDGE_BUSY"):
            with runtime.annotation_read_guard():
                pytest.fail("maintenance must block capture")
    finally:
        release.set()
        worker.join(5)


def test_real_http_smoke(workspace):
    before = git(workspace, "status", "--porcelain")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        create_app(workspace, local_token="desktop", annotation_token="evidence"),
        log_level="error",
    ))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
            assert client.post(PATH, json=payload()).status_code == 401
            response = client.post(PATH, json=payload(), headers={"Authorization": "Bearer evidence"})
            assert response.status_code == 200
            assert response.json()["recommendation"]["candidate_id"] == "cd4_cell"
            assert response.json()["knowledge_version"] == git(workspace, "rev-parse", "HEAD")
        assert git(workspace, "status", "--porcelain") == before
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
    assert not worker.is_alive()
