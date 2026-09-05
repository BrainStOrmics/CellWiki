# =============================================================================
# Agent API 错误映射测试 —— 门禁冲突必须是 409，不是 500
# =============================================================================
# as-built：`cancel` 与 pending-diff `reopen` 已经捕获 InvalidRunTransitionError，
# 而 `retry` / `resume` 只捕获 KeyError / ValueError。两个异常类都继承
# RuntimeError（不是 ValueError），于是门禁冲突漏成 500。
# 本文件同时锁定阶段 A 的三项"顺带修"在 API 边界上的可见结果：
# composer 附件删除端点存在且语义正确（F2）、run 预算走 settings 回退、
# page_id / selected_text 落库（F8 记账侧），以及死枚举不再存在于事件合同。
# =============================================================================

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.config import settings
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.attachment_store import AttachmentFileStore


class _ScriptedAdapter:
    """Deterministic stand-in so no test here needs a real model provider."""

    def __init__(self, scripts: list[list[RuntimeSignal] | Exception] | None = None):
        self.scripts = scripts or []
        self.contexts: list[Any] = []

    def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
        self.contexts.append(context)
        if self.scripts:
            script = self.scripts.pop(0)
            if isinstance(script, Exception):
                raise script
            yield from script
            return
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE, message="answer", data={"answer": "answer"}
        )

    def close(self) -> None:
        return None


def _wait_for_run(client: TestClient, run_id: str, statuses: set[AgentRunStatus]) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {item.value for item in statuses}:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def _drive_to(manager: AgentRuntimeManager, run_id: str, status: AgentRunStatus) -> None:
    """Move one run to ``status`` through legal store transitions (no model)."""
    store = manager.store
    if status is AgentRunStatus.QUEUED:
        return
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    if status is AgentRunStatus.RUNNING:
        return
    if status is AgentRunStatus.SUCCEEDED:
        from cellwiki.domain.runs import AgentRunOutcome

        store.finalize_run(
            run_id, AgentRunOutcome(status=AgentRunStatus.SUCCEEDED, message="Done.")
        )
        return
    store.transition(run_id, status, message="Gated.")


# ---- retry / resume 的门禁冲突映射 ----


def test_retry_reports_a_gate_conflict_as_409_not_500(tmp_path: Path):
    """retry 一个非 failed 的 run 是门禁冲突，必须 409（抄 cancel 的写法）。"""
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        from cellwiki.domain.runs import AgentRun

        manager.store.create_run(
            AgentRun(run_id="run_retry", thread_id="thread_map", input_message="x")
        )
        _drive_to(manager, "run_retry", AgentRunStatus.SUCCEEDED)

        response = client.post("/api/agent/runs/run_retry/retry")

        assert response.status_code == 409, response.text
        assert "retry" in response.json()["detail"].lower()
    finally:
        manager.close()


def test_resume_reports_a_gate_conflict_as_409_not_500(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        from cellwiki.domain.runs import AgentRun

        manager.store.create_run(
            AgentRun(run_id="run_resume", thread_id="thread_map", input_message="x")
        )
        _drive_to(manager, "run_resume", AgentRunStatus.SUCCEEDED)

        response = client.post("/api/agent/runs/run_resume/resume")

        assert response.status_code == 409, response.text
    finally:
        manager.close()


def test_resume_cannot_pull_a_waiting_approval_run_back_over_http(tmp_path: Path):
    """端到端锁定审批绕过：待确认 diff 未判定时 resume 必须 409。"""
    from cellwiki.domain.pending_diff import PendingDiff, PendingDiffStatus
    from cellwiki.domain.runs import AgentRun

    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        store = manager.store
        store.create_run(
            AgentRun(run_id="run_approval", thread_id="thread_map", input_message="x")
        )
        _drive_to(manager, "run_approval", AgentRunStatus.WAITING_APPROVAL)
        store.save_pending_diff(
            PendingDiff(
                diff_id="diff_run_approval_1",
                run_id="run_approval",
                thread_id="thread_map",
                project_id="cellwiki",
                snapshot_commit="aaa1111",
                head_commit="bbb2222",
                commits=["bbb2222"],
                files=["wiki/x.md"],
                status=PendingDiffStatus.PENDING,
            )
        )

        response = client.post("/api/agent/runs/run_approval/resume")

        assert response.status_code == 409, response.text
        assert store.get_run("run_approval").status is AgentRunStatus.WAITING_APPROVAL
        assert (
            store.get_pending_diff("diff_run_approval_1").status
            is PendingDiffStatus.PENDING
        )
    finally:
        manager.close()


def test_retry_and_resume_report_the_serial_gate_as_409(tmp_path: Path):
    """严格串行门禁冲突（另一个 run 活动）同样不得漏成 500。"""
    from cellwiki.domain.runs import AgentRun

    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        store = manager.store
        store.create_run(
            AgentRun(run_id="run_blocker", thread_id="thread_map", input_message="x")
        )
        _drive_to(manager, "run_blocker", AgentRunStatus.RUNNING)
        store.create_run(
            AgentRun(run_id="run_victim", thread_id="thread_map", input_message="y")
        )
        from cellwiki.domain.runs import AgentErrorType, AgentRunOutcome

        store.transition("run_victim", AgentRunStatus.RUNNING, message="Started.")
        store.finalize_run(
            "run_victim",
            AgentRunOutcome(
                status=AgentRunStatus.FAILED,
                message="boom",
                error_type=AgentErrorType.SYSTEM,
                error_message="boom",
            ),
        )

        retried = client.post("/api/agent/runs/run_victim/retry")

        assert retried.status_code == 409, retried.text
        assert "another agent run is active" in retried.json()["detail"]
    finally:
        manager.close()


def test_retry_and_resume_keep_404_for_an_unknown_run(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        assert client.post("/api/agent/runs/run_missing/retry").status_code == 404
        assert client.post("/api/agent/runs/run_missing/resume").status_code == 404
    finally:
        manager.close()


# ---- F2：composer 附件删除端点 ----


def test_composer_attachment_delete_endpoint_removes_record_and_file(tmp_path: Path):
    """前端一直调用的 DELETE .../attachments/{id} 此前不存在 -> 删除必失败。"""
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        thread_id = client.post("/api/agent/threads").json()["thread_id"]
        uploaded = client.post(
            f"/api/agent/threads/{thread_id}/attachments",
            files={"files": ("note.txt", b"hello", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        record = uploaded.json()[0]
        attachment_id = record["attachment_id"]
        files = AttachmentFileStore(tmp_path)
        assert files.path_for(thread_id, attachment_id) is not None

        deleted = client.delete(f"/api/agent/threads/{thread_id}/attachments/{attachment_id}")

        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {"deleted": True}
        assert manager.store.get_attachment(thread_id, attachment_id) is None
        assert files.path_for(thread_id, attachment_id) is None
        assert client.get(f"/api/agent/threads/{thread_id}/attachments").json() == []
    finally:
        manager.close()


def test_composer_attachment_delete_is_404_for_an_unknown_attachment(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        thread_id = client.post("/api/agent/threads").json()["thread_id"]

        missing = client.delete(f"/api/agent/threads/{thread_id}/attachments/att_none")
        unknown_thread = client.delete("/api/agent/threads/thread_none/attachments/att_none")

        assert missing.status_code == 404
        assert unknown_thread.status_code == 404
    finally:
        manager.close()


def test_composer_attachment_delete_is_409_once_a_run_consumed_it(tmp_path: Path):
    """已随消息发出的附件不可"撤回"：409 让前端显示"已发送"而不是通用失败。"""
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        thread_id = client.post("/api/agent/threads").json()["thread_id"]
        record = client.post(
            f"/api/agent/threads/{thread_id}/attachments",
            files={"files": ("paper.txt", b"content", "text/plain")},
        ).json()[0]
        attachment_id = record["attachment_id"]
        started = client.post(
            "/api/agent/runs",
            json={
                "message": "read the attachment",
                "thread_id": thread_id,
                "attachment_ids": [attachment_id],
            },
        )
        assert started.status_code == 202, started.text
        _wait_for_run(client, started.json()["run_id"], {AgentRunStatus.SUCCEEDED})

        conflict = client.delete(
            f"/api/agent/threads/{thread_id}/attachments/{attachment_id}"
        )

        assert conflict.status_code == 409, conflict.text
        assert manager.store.get_attachment(thread_id, attachment_id) is not None
    finally:
        manager.close()


# ---- RunBudget 走 settings 回退（配置覆盖此前是死路径）----


def test_run_budget_falls_back_to_settings_when_the_request_omits_it(
    tmp_path: Path, monkeypatch
):
    """请求不带 budget 时必须读 settings；此前 default_factory=RunBudget 硬编码 100/7200。"""
    monkeypatch.setattr(settings, "agent_max_tool_steps", 7)
    monkeypatch.setattr(settings, "agent_run_max_seconds", 600)
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))

        started = client.post("/api/agent/runs", json={"message": "configured budget"})

        assert started.status_code == 202, started.text
        budget = started.json()["budget"]
        assert budget["max_model_calls"] == 7
        assert budget["max_runtime_seconds"] == 600
    finally:
        manager.close()


def test_run_budget_honours_an_explicit_request_override(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tool_steps", 7)
    manager = AgentRuntimeManager(tmp_path, adapter=_ScriptedAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))

        started = client.post(
            "/api/agent/runs",
            json={"message": "explicit budget", "budget": {"max_model_calls": 3}},
        )

        assert started.status_code == 202, started.text
        assert started.json()["budget"]["max_model_calls"] == 3
    finally:
        manager.close()


# ---- F8 记账侧：page_id / selected_text 落库 ----


def test_run_persists_page_and_selected_text_context(tmp_path: Path):
    """直播与回放读到同一份上下文：run 记录必须带上页面与选中文本。"""
    adapter = _ScriptedAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))

        started = client.post(
            "/api/agent/runs",
            json={
                "message": "explain this passage",
                "page_id": "cell_types/alpha",
                "selected_text": "FOXP3 marks Tregs.",
                "source_id": "src_1",
            },
        )

        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        detail = client.get(f"/api/agent/runs/{run_id}").json()
        assert detail["page_id"] == "cell_types/alpha"
        assert detail["selected_text"] == "FOXP3 marks Tregs."
        assert detail["source_id"] == "src_1"
        # 落库不是只给 API 看：持久化记录本身必须带这两个字段。
        persisted = manager.store.get_run(run_id)
        assert persisted.page_id == "cell_types/alpha"
        assert persisted.selected_text == "FOXP3 marks Tregs."
    finally:
        manager.close()


# ---- 死枚举：MEMORY_* 从未被发出 ----


def test_event_contract_has_no_never_emitted_memory_values():
    """两个 MEMORY_* 值在全仓无生产者，留着会让前端事件表以为需要处理它们。"""
    values = {item.value for item in AgentEventType}

    assert "memory_recalled" not in values
    assert "memory_candidate" not in values


def test_live_event_types_are_preserved():
    """别把活的枚举一起删掉：这三个各有 1 个生产者。"""
    values = {item.value for item in AgentEventType}

    assert {"review_required", "changeset_ready", "verification"} <= values
    assert "task_confirmation_required" in values
