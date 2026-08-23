# =============================================================================
# 产品 API 测试 —— 工作区版 FastAPI 端点契约
# =============================================================================

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.runs import AgentEventType, AgentRunStatus
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal


class _ApiAgentAdapter:
    """Keep Product API streaming tests independent from an external model provider."""

    def __init__(self, scripts: list[list[RuntimeSignal] | Exception] | None = None):
        self.scripts = scripts or []
        self.calls = 0

    def execute(self, *, thread_id: str, message, context) -> Iterable[RuntimeSignal]:
        self.calls += 1
        if self.scripts:
            script = self.scripts.pop(0)
            if isinstance(script, Exception):
                raise script
            yield from script
            return
        yield RuntimeSignal(type=AgentEventType.MESSAGE_DELTA, message="live ")
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE,
            message="answer",
            data={"answer": "answer", "file_paths": ["wiki/cell_types/alpha.md"]},
        )

    def close(self) -> None:
        return None


def _write_workspace(root: Path) -> None:
    wiki = root / "wiki" / "cell_types"
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / "alpha.md").write_text(
        "# Alpha\n\nFOXP3 marks Tregs.\n",
        encoding="utf-8",
    )


def _wait_for_run(client: TestClient, run_id: str, statuses: set[AgentRunStatus]):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/agent/runs/{run_id}")
        assert response.status_code == 200
        run = response.json()
        if run["status"] in {s.value for s in statuses}:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def test_health_and_system_info(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}
    info = client.get("/api/system/info").json()
    assert info["status"] == "ok"
    assert info["project_root"] == str(tmp_path.resolve())


def test_project_tree_and_page_reading(tmp_path: Path):
    _write_workspace(tmp_path)
    client = TestClient(create_app(tmp_path))
    tree = client.get("/api/projects/cellwiki/tree")
    assert tree.status_code == 200
    page = client.get("/api/pages/alpha")
    assert page.status_code == 200
    assert "FOXP3" in page.json().get("markdown", "")


def test_settings_roundtrip_and_test(tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    current = client.get("/api/settings")
    assert current.status_code == 200
    assert "openai_model" in current.json()
    probe = client.post(
        "/api/settings/test",
        json={
            "openai_base_url": "http://127.0.0.1:1",
            "openai_model": "test-model",
            "openai_api_key": "invalid-key-that-must-not-leak",
        },
    )
    assert probe.status_code == 200
    assert probe.json()["ok"] is False


def test_agent_thread_and_run_lifecycle(tmp_path: Path):
    adapter = _ApiAgentAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        thread = client.post("/api/agent/threads")
        assert thread.status_code == 201
        thread_id = thread.json()["thread_id"]

        started = client.post(
            "/api/agent/runs",
            json={"message": "总结细胞类型", "thread_id": thread_id},
        )
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        _wait_for_run(client, run_id, {AgentRunStatus.SUCCEEDED})

        runs = client.get("/api/agent/runs", params={"thread_id": thread_id})
        assert any(item["run_id"] == run_id for item in runs.json())
        detail = client.get(f"/api/agent/runs/{run_id}")
        assert detail.json()["status"] == "succeeded"
        events = client.get(f"/api/agent/runs/{run_id}/events")
        assert events.status_code == 200
        types = [event["type"] for event in events.json()]
        assert AgentEventType.FINAL_RESPONSE.value in types
        messages = client.get(f"/api/agent/threads/{thread_id}/messages")
        assert any(item["role"] == "assistant" for item in messages.json())
        diagnostics = client.get(f"/api/agent/runs/{run_id}/diagnostics")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["run_id"] == run_id

        deleted = client.delete(f"/api/agent/threads/{thread_id}")
        assert deleted.status_code == 200
    finally:
        manager.close()


def test_thread_attachments_upload_and_run_scope(tmp_path: Path):
    # 阶段 6：线程附件 = 临时 Agent 上下文；上传、线程归属校验、随线程删除
    from cellwiki.services.attachment_store import AttachmentFileStore

    client = TestClient(create_app(tmp_path))
    thread = client.post("/api/agent/threads")
    assert thread.status_code == 201
    thread_id = thread.json()["thread_id"]

    uploaded = client.post(
        f"/api/agent/threads/{thread_id}/attachments",
        files={"files": ("note.md", b"# Attachment\n\nFOXP3 marker", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    records = uploaded.json()
    assert len(records) == 1
    record = records[0]
    assert record["thread_id"] == thread_id
    assert record["original_name"] == "note.md"
    assert record["content_hash"]

    listed = client.get(f"/api/agent/threads/{thread_id}/attachments")
    assert [item["attachment_id"] for item in listed.json()] == [record["attachment_id"]]

    # 线程附件可以随 run 传递
    started = client.post(
        "/api/agent/runs",
        json={
            "message": "读一下附件",
            "thread_id": thread_id,
            "attachment_ids": [record["attachment_id"]],
        },
    )
    assert started.status_code == 202, started.text
    run = client.get(f"/api/agent/runs/{started.json()['run_id']}").json()
    assert run["attachment_ids"] == [record["attachment_id"]]

    # 不属于该线程的 attachment_id 必须被拒绝
    foreign = client.post(
        "/api/agent/runs",
        json={
            "message": "x",
            "thread_id": thread_id,
            "attachment_ids": ["att_does_not_exist"],
        },
    )
    assert foreign.status_code == 422

    # 不存在的线程不能上传
    missing = client.post(
        "/api/agent/threads/thread_none/attachments",
        files={"files": ("a.txt", b"x", "text/plain")},
    )
    assert missing.status_code == 404

    # 删除线程时文件与记录一并清理
    store = get_runtime_store(tmp_path)
    assert store.get_attachment(thread_id, record["attachment_id"]) is not None
    deleted = client.delete(f"/api/agent/threads/{thread_id}")
    assert deleted.status_code == 200
    assert store.get_attachment(thread_id, record["attachment_id"]) is None
    assert AttachmentFileStore(tmp_path).path_for(thread_id, record["attachment_id"]) is None


def get_runtime_store(project_root: Path):
    from cellwiki.services.runtime_store import RuntimeStore

    return RuntimeStore(project_root)


def test_agent_run_retry_via_api(tmp_path: Path):
    adapter = _ApiAgentAdapter(
        scripts=[
            RuntimeError("provider exploded"),
            [RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE,
                message="retried answer",
                data={"answer": "retried answer", "file_paths": []},
            )],
        ]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        started = client.post("/api/agent/runs", json={"message": "会失败"})
        run_id = started.json()["run_id"]
        failed = _wait_for_run(client, run_id, {AgentRunStatus.FAILED})
        assert failed["retryable"] is True
        retried = client.post(f"/api/agent/runs/{run_id}/retry")
        assert retried.status_code == 202
        _wait_for_run(client, run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        manager.close()


def test_consumer_endpoints_restored_or_removed(tmp_path: Path):
    # 阶段 5：审批队列/质量/来源接口恢复（前端 workspace 加载依赖），管线配置已并入 settings
    _write_workspace(tmp_path)
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/changesets")
    assert response.status_code == 200 and response.json() == []
    assert client.get("/api/quality").status_code == 200
    assert client.get("/api/sources").json() == []
    assert client.get("/api/pipeline/status").status_code == 404
    assert client.post("/api/sources", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code in {404, 405}
    # 全局搜索（阶段 6 前端 CommandPalette 依赖）：按内容命中页面
    hits = client.get("/api/search", params={"q": "FOXP3"}).json()
    assert any(hit["document_id"] == "alpha" and hit["type"] == "page" for hit in hits)

def test_agent_run_resume_via_api(tmp_path: Path):
    # 预算耗尽 -> unfinished -> 继续/恢复 -> succeeded（阶段 4）
    from cellwiki.services.agent_runtime import RuntimeSignal

    signals = [
        RuntimeSignal(
            type=AgentEventType.MESSAGE_DELTA, message="token", data={}
        )
        for _ in range(6)
    ]
    adapter = _ApiAgentAdapter(
        scripts=[
            signals,
            [RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="resumed", data={})],
        ]
    )
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        started = client.post(
            "/api/agent/runs",
            json={"message": "长任务", "budget": {"max_model_calls": 3}},
        )
        run_id = started.json()["run_id"]
        unfinished = _wait_for_run(client, run_id, {AgentRunStatus.UNFINISHED})
        assert unfinished["status"] == "unfinished"
        assert unfinished["resumable"] is True
        assert unfinished["cancellable"] is True
        resumed = client.post(f"/api/agent/runs/{run_id}/resume")
        assert resumed.status_code == 202, resumed.text
        completed = _wait_for_run(client, run_id, {AgentRunStatus.SUCCEEDED})
        assert completed["status"] == "succeeded"
        assert completed["resumable"] is False
    finally:
        manager.close()


def test_agent_run_strict_serial_gate_returns_409(tmp_path: Path):
    from threading import Event

    from cellwiki.services.agent_runtime import RuntimeSignal

    release = Event()

    class BlockingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            release.wait(timeout=8)
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="blocked answer", data={}
            )

    manager = AgentRuntimeManager(tmp_path, adapter=BlockingAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        first = client.post("/api/agent/runs", json={"message": "阻塞运行"})
        run_id = first.json()["run_id"]
        _wait_for_run(client, run_id, {AgentRunStatus.RUNNING})
        second = client.post("/api/agent/runs", json={"message": "第二个运行"})
        assert second.status_code == 409, second.text
        assert "another agent run is active" in second.json()["detail"]
        release.set()
        _wait_for_run(client, run_id, {AgentRunStatus.SUCCEEDED})
    finally:
        release.set()
        manager.close()


def test_pending_diff_endpoints_accept_reject_reopen(tmp_path: Path):
    import subprocess

    from cellwiki.services.agent_runtime import RuntimeSignal
    from cellwiki.services.git_executor import GitExecutor

    subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@cellwiki.local"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"],
        check=True,
        capture_output=True,
    )
    (tmp_path / "readme.md").write_text("base", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "readme.md"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )

    class WritingAdapter:
        def execute(self, *, thread_id, message, context) -> Any:
            (tmp_path / "note.md").write_text("agent note", encoding="utf-8")
            git = GitExecutor(tmp_path)
            git.run("add", "note.md")
            git.run("commit", "-m", "agent change 1")
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE, message="done", data={}
            )

    manager = AgentRuntimeManager(tmp_path, adapter=WritingAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        started = client.post("/api/agent/runs", json={"message": "写笔记"})
        run_id = started.json()["run_id"]
        _wait_for_run(client, run_id, {AgentRunStatus.SUCCEEDED})
        diffs: list = []
        for _ in range(100):
            diffs = client.get(f"/api/pending-diffs?run_id={run_id}").json()["pending_diffs"]
            if diffs:
                break
            time.sleep(0.02)
        assert len(diffs) == 1, diffs
        diff_id = diffs[0]["diff_id"]
        assert diffs[0]["status"] == "pending"
        assert (tmp_path / "note.md").exists()
        # reopen（pending -> pending，幂等语义）
        reopened = client.post(f"/api/pending-diffs/{diff_id}/reopen")
        assert reopened.status_code == 200
        # reject：revert run 内 commit
        rejected = client.post(f"/api/pending-diffs/{diff_id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert not (tmp_path / "note.md").exists(), "note.md 应被回滚"
        # 再次 reject 已解决 diff -> 409
        again = client.post(f"/api/pending-diffs/{diff_id}/reject")
        assert again.status_code == 409, again.text
    finally:
        manager.close()


class _QuestionCapableApiAdapter:
    """API 级协议适配器：初始 run 抛出一个挂起问题，回复后继续到成功。"""

    def __init__(self) -> None:
        self.resumed_with: object | None = None

    def execute(self, *, thread_id: str, message, context, resume: object | None = None):
        self.resumed_with = resume
        signal_question = RuntimeSignal(
            type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
            message="Waiting for the user: 是否将结果写入 wiki？",
            data={
                "interrupt": {
                    "question": "是否将结果写入 wiki？",
                    "options": ["写入", "仅回答", "放弃"],
                    "required": True,
                }
            },
        )
        if resume is None:
            yield signal_question
            return
        yield RuntimeSignal(type=AgentEventType.FINAL_RESPONSE, message="已按你的选择完成")

    def close(self) -> None:
        return None


def test_agent_question_flow_via_api(tmp_path: Path):
    # 阶段 4/6：ask_user_question 5+1 —— 挂起 -> GET question -> POST 回复 -> 续跑
    adapter = _QuestionCapableApiAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    client = TestClient(create_app(tmp_path, agent_runtime=manager))
    thread = client.post("/api/agent/threads").json()["thread_id"]

    started = client.post(
        "/api/agent/runs",
        json={"message": "分析 FOXP3", "thread_id": thread},
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        questioning = client.get(f"/api/agent/runs/{run_id}/question")
        if questioning.status_code == 200:
            break
        time.sleep(0.02)
    assert questioning.status_code == 200, questioning.text
    question = questioning.json()
    assert question["run_id"] == run_id
    assert question["question"] == "是否将结果写入 wiki？"
    assert question["options"] == ["写入", "仅回答", "放弃"]

    run_before = client.get(f"/api/agent/runs/{run_id}").json()
    assert run_before["status"] == "waiting_confirmation"

    # 空回复（必答）被拒绝
    rejected = client.post(
        f"/api/agent/runs/{run_id}/question",
        json={"answers": []},
    )
    assert rejected.status_code == 422

    answered = client.post(
        f"/api/agent/runs/{run_id}/question",
        json={"answers": "仅回答"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "succeeded"
    assert adapter.resumed_with == ["仅回答"]

    # 已回复后 GET question -> 404
    assert client.get(f"/api/agent/runs/{run_id}/question").status_code == 404
    # 已终态 run 再次回复 -> 409
    again = client.post(
        f"/api/agent/runs/{run_id}/question",
        json={"answers": "写入"},
    )
    assert again.status_code == 409
