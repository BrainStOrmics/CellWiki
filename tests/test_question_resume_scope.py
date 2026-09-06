# =============================================================================
# 阶段 E：提问续跑段的作用域与"checkpoint 写方唯一"
# =============================================================================
# 续跑段此前跑在 HTTP 请求线程上，而且只装了 attachment resolver、没装 scope：
# workspace_root / thread_dir / 读预算全是空的。这里锁三件事——
#   1. 答题接口登记完答案就返回，续跑在执行器线程上（HTTP 线程不被占住）；
#   2. 续跑段读附件成功，且落在真正的工作区作用域里；
#   3. 续跑段的读预算真实生效（不是"预算 0 = 无限"）。
# 另加裁决 #5 的验收条件：阶段 C 的临时进程内写锁已删除，写方唯一由串行门禁保证。
# 全程用替身 adapter，不需要真实 provider，也不需要联网。
# =============================================================================

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from cellwiki.agent.executor import build_attachment_tools, get_attachment_scope
from cellwiki.config import settings
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import AgentEventType, AgentRun, AgentRunStatus
from cellwiki.services import checkpoints as checkpoints_module
from cellwiki.services.agent_runtime import AgentRuntimeManager, RuntimeSignal
from cellwiki.services.checkpoints import build_checkpointer

WAIT_TIMEOUT = 20.0

ATTACHMENT_TEXT = "# Attachment\n\nFOXP3 marks regulatory T cells."


class _ProbeCheckpointer:
    """只回答"最新 checkpoint 标识"，让决策 4 的显式拒绝不误伤本用例。"""

    def get_tuple(self, config: Any) -> Any:
        return SimpleNamespace(config={"configurable": {"checkpoint_id": "cp_probe"}})


class _ResumeProbingGraph:
    """图形状替身：没有 ``execute``，因此走 ``_open_stream_resume`` 的编译图分支。

    流一打开就在**续跑段的线程里**探针附件作用域并真的调用 ``read_attachment``。
    """

    def __init__(self, attachment_id: str) -> None:
        self.attachment_id = attachment_id
        self.checkpointer = _ProbeCheckpointer()
        self.probe: dict[str, Any] | None = None
        self.stream_kwargs: dict[str, Any] = {}

    def stream(self, payload: Any, config: Any = None, **kwargs: Any) -> Any:
        self.stream_kwargs = {"payload": payload, "config": config, **kwargs}
        resolver, workspace_root, thread_dir = get_attachment_scope()
        tools = {tool.name: tool for tool in build_attachment_tools()}
        raw = tools["read_attachment"].invoke({"attachment_id": self.attachment_id})
        self.probe = {
            "thread_ident": threading.get_ident(),
            "has_resolver": resolver is not None,
            "workspace_root": workspace_root,
            "thread_dir": thread_dir,
            "read": json.loads(raw),
        }
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE, message="ok", data={"answer": "ok"}
        )


def _wait_for_status(
    manager: AgentRuntimeManager, run_id: str, statuses: set[AgentRunStatus]
) -> AgentRun:
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def _parked_run_with_attachment(
    tmp_path: Path, monkeypatch, *, budget_chars: int | None = None
) -> tuple[AgentRuntimeManager, _ResumeProbingGraph, str]:
    """装好一个停在问题上的 run，其线程里已经有一份真实上传的附件。"""
    from fastapi.testclient import TestClient

    from cellwiki.api.app import create_app

    monkeypatch.setattr(settings, "agent_checkpointer", "sqlite")
    if budget_chars is not None:
        monkeypatch.setattr(settings, "agent_attachment_read_budget_chars", budget_chars)
    page = tmp_path / "wiki" / "cell_types" / "a.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# Alpha cell\n", encoding="utf-8")

    # 附件要走真实上传路径，作用域探针读的才是产品那份登记与落盘布局。
    placeholder = _ResumeProbingGraph("att_placeholder")
    manager = AgentRuntimeManager(tmp_path, adapter=placeholder)
    client = TestClient(create_app(tmp_path, agent_runtime=manager))
    thread_id = client.post("/api/agent/threads").json()["thread_id"]
    uploaded = client.post(
        f"/api/agent/threads/{thread_id}/attachments",
        files={"files": ("note.md", ATTACHMENT_TEXT.encode("utf-8"), "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()[0]["attachment_id"]

    graph = _ResumeProbingGraph(attachment_id)
    manager.adapter = graph
    run = AgentRun(
        run_id="run_resume_scope",
        thread_id=thread_id,
        input_message="读一下附件",
        attachment_ids=[attachment_id],
    )
    manager.store.create_run(run)
    manager.store.transition(run.run_id, AgentRunStatus.RUNNING, message="Started.")
    manager.store.save_pending_question_and_transition(
        PendingQuestion(
            question_id=f"q_{run.run_id}",
            run_id=run.run_id,
            thread_id=thread_id,
            question="继续吗？",
            options=["是", "否"],
            required=False,
        ),
        message="Run paused for a question.",
    )
    return manager, graph, run.run_id


def test_answer_question_returns_while_the_resume_runs_on_the_executor(
    tmp_path: Path, monkeypatch
):
    manager, graph, run_id = _parked_run_with_attachment(tmp_path, monkeypatch)
    caller = threading.get_ident()
    try:
        payload = manager.answer_question(run_id, ["是"])
        # 接口立刻拿到 run，且续跑段还没跑完：状态是 RUNNING，不是终态。
        assert payload["status"] == AgentRunStatus.RUNNING.value
        assert graph.probe is None or graph.probe["thread_ident"] != caller

        finished = _wait_for_status(
            manager,
            run_id,
            {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED},
        )
        assert finished.status == AgentRunStatus.SUCCEEDED
        # 续跑段确实跑在另一个线程上——这正是"checkpoint 写方唯一"的前提。
        assert graph.probe is not None
        assert graph.probe["thread_ident"] != caller
    finally:
        manager.close()


def test_the_resume_segment_reads_the_attachment_inside_the_workspace_scope(
    tmp_path: Path, monkeypatch
):
    manager, graph, run_id = _parked_run_with_attachment(tmp_path, monkeypatch)
    try:
        manager.answer_question(run_id, ["是"])
        _wait_for_status(manager, run_id, {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED})

        assert graph.probe is not None
        probe = graph.probe
        assert probe["has_resolver"] is True
        # 只装 resolver 时这两个都是 None：附件路径无法相对工作区表达。
        assert probe["workspace_root"] == manager.project_root
        assert probe["thread_dir"] is not None
        assert Path(str(probe["thread_dir"])).is_dir()
        assert probe["read"].get("content") == ATTACHMENT_TEXT
        assert probe["read"].get("error") is None
    finally:
        manager.close()


def test_the_resume_segment_enforces_the_attachment_read_budget(
    tmp_path: Path, monkeypatch
):
    budget = 12
    assert len(ATTACHMENT_TEXT) > budget
    manager, graph, run_id = _parked_run_with_attachment(
        tmp_path, monkeypatch, budget_chars=budget
    )
    try:
        manager.answer_question(run_id, ["是"])
        _wait_for_status(manager, run_id, {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED})

        assert graph.probe is not None
        read = graph.probe["read"]
        # 预算未装时 read 会返回全文（预算 0 = 无限），这条因此是红→绿锁。
        assert read.get("error") is None
        assert len(read["content"]) == budget
        assert read["next_offset"] == budget
    finally:
        manager.close()


def test_the_stage_c_checkpoint_write_lock_is_deleted(tmp_path: Path, monkeypatch):
    """裁决 #5 的验收条件：临时写锁与它的载体子类都不许再存在。"""
    monkeypatch.setattr(settings, "agent_checkpointer", "sqlite")

    assert not hasattr(checkpoints_module, "checkpoint_write_lock")
    assert not hasattr(checkpoints_module, "_ThreadSafeSqliteSaver")
    assert not hasattr(checkpoints_module, "_checkpoint_write_lock")
    source = Path(checkpoints_module.__file__).read_text(encoding="utf-8")
    assert "_checkpoint_write_lock" not in source

    # 载体就是 LangGraph 自己的 SqliteSaver，没有被包一层。
    assert type(build_checkpointer(tmp_path)) is SqliteSaver
