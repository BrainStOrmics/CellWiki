# =============================================================================
# Run 作用域持久化 checkpoint —— ADR-0010 逐条决策的验收测试
# =============================================================================
# 每条决策配一个可失败的锁。另外两条是工作单阶段 C 的核心回归锁：
#   * 同线程连续多个 run 互不读取对方的图状态（决策 2/3/15）；
#   * 后一个 run 进入模型的 messages 不超过 ConversationContextView 上界（决策 15）。
# 真实图路径用假模型（BaseChatModel），不需要真实 provider，也不需要联网。
# =============================================================================

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from cellwiki.agent.app import build_wiki_agent
from cellwiki.api.app import create_app
from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentEventType,
    AgentRun,
    AgentRunStatus,
    RunBudget,
    RunUsage,
)
from cellwiki.services import agent_runtime as agent_runtime_module
from cellwiki.services.agent_runtime import (
    AgentRuntimeManager,
    RuntimeSignal,
    prompt_configuration_hash,
)
from cellwiki.services.checkpoints import (
    CheckpointMissingError,
    build_checkpointer,
    checkpoint_file_bytes,
    checkpoint_path,
    checkpoint_state_key,
    delete_run_checkpoints,
    delete_thread_checkpoints,
    has_run_checkpoint,
    latest_checkpoint_id,
    latest_run_checkpoint_id,
)
from cellwiki.services.conversation_context import ConversationContextView
from cellwiki.services.runtime_store import RuntimeStore, SerialGateViolationError


# 这些用例跨后台线程做真实的 git / SQLite / 图执行；与 test_agent_runtime 同源放宽。
WAIT_TIMEOUT = 20.0

TERMINAL = {
    AgentRunStatus.SUCCEEDED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.REJECTED,
}


# ---------------------------------------------------------------------------
# 替身
# ---------------------------------------------------------------------------
class _RecordingFakeModel(BaseChatModel):
    """真实图所用的假模型：记录每次进入模型的 messages，然后直接回答。"""

    seen: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def bind_tools(self, tools, **kwargs):
        return self

    def _bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        yield ChatGenerationChunk(message=AIMessageChunk(content="已回答"))


class _InterruptRecordingModel(BaseChatModel):
    """第一次只发 ask_user_question 工具调用（挂起），续跑后发最终回答；全程记录输入。"""

    seen: list[list[Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "interrupt-recording"

    def bind_tools(self, tools, **kwargs):
        return self

    def _bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        if len(self.seen) == 1:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_calls=[
                        {
                            "name": "ask_user_question",
                            "args": {"question": "继续吗？", "options": ["是", "否"]},
                            "id": "call_interrupt",
                            "type": "tool_call",
                        }
                    ],
                )
            )
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="已按你的选择完成"))


class _StubGraph:
    """图形状的最小替身：没有 ``execute``，也没有可读的 checkpointer。

    用来测决策 4 的拒绝路径——它必须在看不到 checkpoint 时明确失败，
    而不是打开一个空图。
    """

    checkpointer = None

    def stream(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("must not open a stream without a checkpoint")


class _PermissiveStubGraph:
    """图形状替身，但**允许**开流：用来验证闸门放行之后 ``resume`` 真的认领了 run。

    ``_StubGraph`` 是为拒绝路径准备的（它的 ``stream`` 直接断言失败），而修订后的
    决策 4 还要测放行路径。返回空流，执行器随即收尾，不影响用例的同步断言。
    """

    checkpointer = None

    def __init__(self) -> None:
        self.opened = 0

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        self.opened += 1
        return iter(())


class _RecordingProtocolAdapter:
    """协议型 adapter：记录收到的 thread_id，用于验证它仍走会话键（决策 2）。"""

    def __init__(self) -> None:
        self.thread_ids: list[str] = []

    def execute(self, *, thread_id: str, message: str, context: Any) -> Iterable[RuntimeSignal]:
        self.thread_ids.append(thread_id)
        yield RuntimeSignal(
            type=AgentEventType.FINAL_RESPONSE, message="ok", data={"answer": "ok"}
        )

    def close(self) -> None:
        return None


class _Carrier:
    """给 ``latest_checkpoint_id`` 用的最小 adapter 形状（只暴露 checkpointer）。"""

    def __init__(self, checkpointer: Any) -> None:
        self.checkpointer = checkpointer


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _wait_for_status(
    manager: AgentRuntimeManager,
    run_id: str,
    statuses: set[AgentRunStatus],
    timeout: float = WAIT_TIMEOUT,
) -> AgentRun:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.status in statuses:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach {statuses}")


def _wait_for_checkpoint(
    manager: AgentRuntimeManager, run_id: str, timeout: float = WAIT_TIMEOUT
) -> AgentRun:
    """等决策 4 的回写落库。

    run 是在流循环**里**转成 WAITING_CONFIRMATION 的，而 checkpoint 标识在流关闭
    时才写回；状态一变就读字段会撞上还没落盘的 NULL。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.store.get_run(run_id)
        if run.checkpoint_id:
            return run
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never recorded a checkpoint_id")


def _seed_workspace(root: Path) -> None:
    page = root / "wiki" / "cell_types" / "a.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    if not page.exists():
        page.write_text("# Alpha cell\n", encoding="utf-8")


def _graph_manager(root: Path, model: BaseChatModel | None = None) -> tuple[AgentRuntimeManager, BaseChatModel]:
    """真实产品图 + 假模型：这是 checkpoint 唯一真正的生产路径。"""
    _seed_workspace(root)
    active = model if model is not None else _RecordingFakeModel()
    graph = build_wiki_agent(root, model=active)
    return AgentRuntimeManager(root, adapter=graph), active


def _turn(manager: AgentRuntimeManager, thread_id: str, message: str) -> AgentRun:
    run = manager.start(
        thread_id=thread_id,
        message=message,
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    return _wait_for_status(manager, run.run_id, TERMINAL | {AgentRunStatus.UNFINISHED})


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return " ".join(str(part) for part in content)


def _count_occurrences(messages: list[Any], marker: str) -> int:
    """在**会话消息**里数 marker 出现次数。

    系统消息不算：Layer B 是运行时自己写的上下文快照，本来就会引用最近一轮
    输入（实测：4 轮后 run 的输入 = Layer A + Layer B + 7 条有界 transcript）。
    决策 2/3 要禁的是图状态叠在有界 transcript 之上，那只表现为会话消息重复。
    """
    return sum(
        1
        for message in messages
        if type(message).__name__ != "SystemMessage" and marker in _text(message)
    )


def _drive_to_unfinished(store: RuntimeStore, run_id: str) -> None:
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.transition(
        run_id,
        AgentRunStatus.UNFINISHED,
        error_type=AgentErrorType.TIMEOUT,
        error_message="budget exhausted",
        message="Paused.",
    )


def _park_on_question(store: RuntimeStore, run_id: str, thread_id: str) -> None:
    """把 run 停在一个未回答的问题上（走 store 真正的原子接口）。"""
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.save_pending_question_and_transition(
        PendingQuestion(
            question_id=f"q_{run_id}",
            run_id=run_id,
            thread_id=thread_id,
            question="继续吗？",
            options=["是", "否"],
            required=False,
        ),
        message="Run paused for a question.",
    )


# ===========================================================================
# 决策 1 / 14 / 15 —— 载体装配与回滚闸
# ===========================================================================
def test_default_carrier_is_sqlite_beside_the_runtime_db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "agent_checkpointer", "sqlite")

    saver = build_checkpointer(tmp_path)

    # 决策 15：装配回归锁——绝不能无声回落到进程内 saver。
    assert not isinstance(saver, InMemorySaver)
    # 决策 1：与 cellwiki.db 同目录、分文件，避免 WAL 与锁争用。
    assert checkpoint_path(tmp_path) == tmp_path / "data" / "runtime" / "checkpoints.sqlite"
    assert checkpoint_path(tmp_path).exists()
    assert checkpoint_path(tmp_path).parent == RuntimeStore(tmp_path).path.parent


def test_product_graph_is_assembled_with_the_persistent_carrier(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "agent_checkpointer", "sqlite")
    _seed_workspace(tmp_path)

    graph = build_wiki_agent(tmp_path, model=_RecordingFakeModel())

    assert graph.checkpointer is not None
    assert not isinstance(graph.checkpointer, InMemorySaver)


def test_rollback_gate_swaps_in_the_inmemory_checkpointer(tmp_path: Path, monkeypatch):
    """决策 14：``AGENT_CHECKPOINTER=inmemory`` 是短期回滚闸，必须真的能换掉载体。"""
    monkeypatch.setattr(settings, "agent_checkpointer", "inmemory")

    saver = build_checkpointer(tmp_path)

    assert isinstance(saver, InMemorySaver)
    assert not checkpoint_path(tmp_path).exists()
    # 闸打开时没有持久载体，"有没有 checkpoint"一律答否，续跑走显式失败。
    assert has_run_checkpoint(tmp_path, "thread_x", "run_x") is False


# ===========================================================================
# 决策 2 —— run 作用域状态键
# ===========================================================================
def test_state_key_is_run_scoped_not_session_scoped():
    assert checkpoint_state_key("thread_a", "run_1") == "thread_a::run_1"
    assert checkpoint_state_key("thread_a", "run_2") != checkpoint_state_key("thread_a", "run_1")


def test_protocol_adapter_keeps_the_session_key(tmp_path: Path):
    """决策 2：协议型 adapter 没有图状态，不套 run 作用域键。"""
    adapter = _RecordingProtocolAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        run = _turn(manager, "thread_proto", "hello")
        assert run.status == AgentRunStatus.SUCCEEDED
        assert adapter.thread_ids == ["thread_proto"]
        assert "::" not in adapter.thread_ids[0]
    finally:
        manager.close()


# ===========================================================================
# 决策 7 —— 幂等提交（内联守卫 ALTER，不走 Alembic）
# ===========================================================================
def test_direct_construct_db_gets_the_request_id_column(tmp_path: Path):
    """裁决 #13：直连建库路径（测试与 scripts/serve_e2e.py）不跑 Alembic，
    只有内联守卫 ALTER 才能让这些库也拿到 request_id 列，否则幂等门形同虚设。"""
    store = RuntimeStore(tmp_path)

    connection = sqlite3.connect(store.path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
        indexes = {
            row[1]: row for row in connection.execute("PRAGMA index_list(agent_runs)")
        }
    finally:
        connection.close()

    assert "request_id" in columns
    assert "ux_agent_runs_request_id" in indexes
    # 部分索引（WHERE request_id IS NOT NULL）：省略 request_id 的调用方不受唯一约束。
    assert indexes["ux_agent_runs_request_id"][4] == 1

    store.create_run(AgentRun(run_id="run_null_1", thread_id="t_null", input_message="a"))
    store.create_run(AgentRun(run_id="run_null_2", thread_id="t_null", input_message="b"))
    assert {run.run_id for run in store.list_runs(limit=10)} >= {"run_null_1", "run_null_2"}


def test_create_run_if_idle_replays_the_same_request_id(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    first_run = AgentRun(
        run_id="run_a", thread_id="t_idem", input_message="x", request_id="req-1"
    )

    created, replayed = store.create_run_if_idle(first_run, request_id="req-1")
    assert (created.run_id, replayed) == ("run_a", False)

    duplicate = AgentRun(
        run_id="run_b", thread_id="t_idem", input_message="x", request_id="req-1"
    )
    hit, hit_replayed = store.create_run_if_idle(duplicate, request_id="req-1")

    assert hit.run_id == "run_a"
    assert hit_replayed is True
    assert "run_b" not in {run.run_id for run in store.list_runs(limit=10)}


def test_create_run_if_idle_checks_the_serial_gate_in_the_same_transaction(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run_if_idle(
        AgentRun(run_id="run_active", thread_id="t_gate", input_message="x", request_id="req-1"),
        request_id="req-1",
    )

    other = AgentRun(
        run_id="run_second", thread_id="t_gate", input_message="y", request_id="req-2"
    )
    with pytest.raises(SerialGateViolationError):
        store.create_run_if_idle(other, request_id="req-2")

    assert "run_second" not in {run.run_id for run in store.list_runs(limit=10)}


def test_api_replays_a_double_submit_at_202(tmp_path: Path):
    """决策 7：重复提交命中既有 run，仍是 202，只多一个 replayed 标记。

    原 run 往往还是活动的——预检若先跑就会把幂等命中误判成 409，所以这里
    不做任何等待，直接连着提交两次。
    """
    manager = AgentRuntimeManager(tmp_path, adapter=_RecordingProtocolAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        body = {"message": "hello", "thread_id": "t_api", "request_id": "req-api"}

        first = client.post("/api/agent/runs", json=body)
        second = client.post("/api/agent/runs", json=body)

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert "replayed" not in first.json()
        assert second.json()["replayed"] is True
        assert second.json()["run_id"] == first.json()["run_id"]
    finally:
        manager.close()


# ===========================================================================
# 决策 8 —— 执行配置快照 + 墙钟跨段累计
# ===========================================================================
def test_prompt_hash_snapshots_layer_a_model_and_budget():
    baseline = prompt_configuration_hash(RunBudget())

    assert baseline == prompt_configuration_hash(RunBudget())
    assert len(baseline) == 16
    assert baseline != prompt_configuration_hash(RunBudget(max_runtime_seconds=999))


def test_started_run_records_its_prompt_hash(tmp_path: Path):
    adapter = _RecordingProtocolAdapter()
    manager = AgentRuntimeManager(tmp_path, adapter=adapter)
    try:
        run = _turn(manager, "t_hash", "hello")
        stored = manager.store.get_run(run.run_id)
        assert stored.prompt_hash == prompt_configuration_hash(stored.budget)
    finally:
        manager.close()


def test_usage_accumulates_across_segments_instead_of_overwriting(tmp_path: Path):
    """决策 8 的记账前提：每段只报自己的计数，累加才是 run 生命周期总量。"""
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_usage", thread_id="t_usage", input_message="x"))

    store.update_usage(
        "run_usage", RunUsage(model_calls=2, input_tokens=100, output_tokens=40, elapsed_seconds=3.0)
    )
    updated = store.update_usage(
        "run_usage",
        RunUsage(model_calls=1, input_tokens=50, output_tokens=10, elapsed_seconds=2.0),
        accumulate=True,
    )

    assert updated.usage.model_calls == 3
    assert updated.usage.input_tokens == 150
    assert updated.usage.output_tokens == 50
    assert updated.usage.elapsed_seconds == pytest.approx(5.0)


# ===========================================================================
# 决策 9 —— USAGE_UPDATED 事件
# ===========================================================================
def test_flush_accounting_emits_usage_updated_with_segment_and_cumulative(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, adapter=_RecordingProtocolAdapter())
    try:
        run = _turn(manager, "t_event", "hello")
        events = manager.store.list_events(run.run_id)
        usage_events = [
            event for event in events if event.type == AgentEventType.USAGE_UPDATED
        ]

        assert usage_events, "每段流结束都要投递一次用量事件"
        payload = usage_events[-1].data
        assert set(payload) >= {"segment", "cumulative"}
        assert payload["cumulative"]["model_calls"] >= payload["segment"]["model_calls"]
        assert payload["segment"]["elapsed_seconds"] >= 0
    finally:
        manager.close()


# ===========================================================================
# 决策 5 / 6 —— retry 清状态重放，resume 不清状态续跑
# ===========================================================================
def test_retry_deletes_the_run_state_key_before_replaying(tmp_path: Path, monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_runtime_module,
        "delete_run_checkpoints",
        lambda root, thread_id, run_id: calls.append((thread_id, run_id)),
    )
    manager = AgentRuntimeManager(tmp_path, adapter=_RecordingProtocolAdapter())
    try:
        store = manager.store
        store.create_run(AgentRun(run_id="run_retry", thread_id="t_retry", input_message="x"))
        store.transition("run_retry", AgentRunStatus.RUNNING, message="Started.")
        store.transition(
            "run_retry",
            AgentRunStatus.FAILED,
            error_type=AgentErrorType.SYSTEM,
            error_message="boom",
            message="Failed.",
        )

        manager.retry("run_retry")

        # 决策 5：删的是**该 run** 的状态键，不是整个线程。
        assert calls == [("t_retry", "run_retry")]
    finally:
        manager.close()


def test_delete_run_checkpoints_only_removes_that_run(tmp_path: Path):
    """决策 5 的机制侧：清状态必须精确到 run，兄弟 run 的状态不能一起没。"""
    _seed_workspace(tmp_path)
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    thread_id = "thread_scope"

    first = _turn(manager, thread_id, "first")
    second = _turn(manager, thread_id, "second")
    assert has_run_checkpoint(tmp_path, thread_id, first.run_id)
    assert has_run_checkpoint(tmp_path, thread_id, second.run_id)

    delete_run_checkpoints(tmp_path, thread_id, first.run_id)

    assert not has_run_checkpoint(tmp_path, thread_id, first.run_id)
    assert has_run_checkpoint(tmp_path, thread_id, second.run_id)


def test_resume_refuses_a_run_without_a_checkpoint(tmp_path: Path):
    """决策 4/6：升级前产生的 run 一律 checkpoint_id=NULL，续跑必须显式失败。"""
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_legacy", thread_id="t_legacy", input_message="x"))
    _drive_to_unfinished(store, "run_legacy")
    manager = AgentRuntimeManager(tmp_path, adapter=_StubGraph())
    try:
        with pytest.raises(CheckpointMissingError) as error:
            manager.resume("run_legacy")
        assert "resend" in str(error.value)
        # 拒绝发生在转 RUNNING 之前，run 不会停在 RUNNING 而没有执行者。
        assert store.get_run("run_legacy").status == AgentRunStatus.UNFINISHED
    finally:
        manager.close()


def test_answer_question_refuses_a_run_without_a_checkpoint(tmp_path: Path):
    # 先建 manager 再挂起问题：构造时的重启收敛（决策 10）会把"没有 checkpoint 的
    # WAITING_CONFIRMATION"降级掉，那正是本用例要手工摆出来的前置状态。
    manager = AgentRuntimeManager(tmp_path, adapter=_StubGraph())
    try:
        store = manager.store
        store.create_run(AgentRun(run_id="run_noq", thread_id="t_noq", input_message="x"))
        _park_on_question(store, "run_noq", "t_noq")

        with pytest.raises(CheckpointMissingError):
            manager.answer_question("run_noq", "是")

        # 拒绝发生在登记答案与转 RUNNING 之前：问题还开着，run 不会停在 RUNNING
        # 而没有执行者。
        assert store.get_run("run_noq").status == AgentRunStatus.WAITING_CONFIRMATION
        assert store.get_open_question("run_noq") is not None
    finally:
        manager.close()


# ===========================================================================
# 决策 10 —— 重启收敛覆盖 WAITING_CONFIRMATION
# ===========================================================================
def test_waiting_confirmation_survives_restart_when_its_checkpoint_is_durable(tmp_path: Path):
    """决策 10 的正例：图状态还在，重启后 run 仍挂在原问题上，用户直接作答即可续跑。"""
    _seed_workspace(tmp_path)
    model = _InterruptRecordingModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    run = manager.start(
        thread_id="thread_restart",
        message="分析后问我是否继续",
        context=WikiAgentContext(project_id="cellwiki", thread_id="thread_restart"),
    )
    _wait_for_status(manager, run.run_id, {AgentRunStatus.WAITING_CONFIRMATION})
    # 决策 4：挂起段结束就该把 checkpoint 标识回写成可查询字段。
    assert _wait_for_checkpoint(manager, run.run_id).checkpoint_id
    assert has_run_checkpoint(tmp_path, "thread_restart", run.run_id)
    manager.close()

    restarted = AgentRuntimeManager(
        tmp_path, adapter=build_wiki_agent(tmp_path, model=_InterruptRecordingModel())
    )
    try:
        recovered = restarted.store.get_run(run.run_id)

        assert recovered.status == AgentRunStatus.WAITING_CONFIRMATION
        question = restarted.store.get_open_question(run.run_id)
        assert question is not None and question["question"] == "继续吗？"
    finally:
        restarted.close()


@pytest.mark.parametrize("checkpoint_id", ["ckpt-from-a-lost-carrier", None])
def test_waiting_confirmation_degrades_when_its_checkpoint_is_gone(
    tmp_path: Path, checkpoint_id: str | None
):
    """决策 10 + 决策 4：图状态没了就关掉未回答的问题、落到 UNFINISHED，
    并让"继续"明确拒绝，而不是在空图上静默 Command(resume=...)。

    两种"没了"都要覆盖：载体里查不到状态（文件被清/换机器），以及升级前
    产生的 run 一律 ``checkpoint_id = NULL``。
    """
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(
            run_id="run_lost",
            thread_id="t_lost",
            input_message="x",
            checkpoint_id=checkpoint_id,
        )
    )
    _park_on_question(store, "run_lost", "t_lost")
    assert not has_run_checkpoint(tmp_path, "t_lost", "run_lost")

    # 构造 manager 就是"重启"：收敛在 __init__ 里跑。
    manager = AgentRuntimeManager(tmp_path, adapter=_StubGraph())
    try:
        recovered = manager.store.get_run("run_lost")

        assert recovered.status == AgentRunStatus.UNFINISHED
        assert "resend" in (recovered.error_message or "").lower()
        assert manager.store.get_open_question("run_lost") is None
        with pytest.raises(CheckpointMissingError):
            manager.resume("run_lost")
    finally:
        manager.close()


def _park_with_live_carrier(tmp_path: Path, thread_id: str) -> str:
    """用真实产品图跑出一个**活的**载体，返回 run_id（run 停在未回答的问题上）。

    真实图 + 假模型是 checkpoint 唯一真正的生产路径（见 ``_graph_manager``）；
    手工塞进 sqlite 的行代表不了 ``SqliteSaver`` 真正写下的形状。
    """
    _seed_workspace(tmp_path)
    manager = AgentRuntimeManager(
        tmp_path, adapter=build_wiki_agent(tmp_path, model=_InterruptRecordingModel())
    )
    try:
        run = manager.start(
            thread_id=thread_id,
            message="分析后问我是否继续",
            context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
        )
        _wait_for_status(manager, run.run_id, {AgentRunStatus.WAITING_CONFIRMATION})
        _wait_for_checkpoint(manager, run.run_id)
        assert has_run_checkpoint(tmp_path, thread_id, run.run_id)
        return run.run_id
    finally:
        manager.close()


def test_resume_admits_a_hard_killed_run_whose_checkpoint_id_is_null(tmp_path: Path):
    """决策 4（2026-09-07 修订）的 P0 回归：字段 NULL 不等于图状态不存在。

    复现桌面端实测问题 A：进程被硬杀时 ``checkpoint_id`` 的回写钩子没机会跑，字段
    停在 NULL 而载体完好。修订前 ``resume`` 直接判死回 409，UI 的「继续」于是成了
    死结——按钮不消失、发送键仍禁用，用户既不能继续也不能重发。
    """
    thread_id = "thread_hard_kill"
    run_id = _park_with_live_carrier(tmp_path, thread_id)

    store = RuntimeStore(tmp_path)
    store.answer_question(run_id, [], timed_out=True)
    _drive_to_unfinished(store, run_id)
    # 硬杀的效果：载体完好，run 行的字段没来得及回写。
    store.set_run_checkpoint(run_id, None)
    assert store.get_run(run_id).checkpoint_id is None
    assert has_run_checkpoint(tmp_path, thread_id, run_id)

    manager = AgentRuntimeManager(tmp_path, adapter=_PermissiveStubGraph())
    try:
        claimed = manager.resume(run_id)  # 修订前这里抛 CheckpointMissingError
        assert claimed.status == AgentRunStatus.RUNNING
    finally:
        manager.close()


def test_recover_stale_runs_backfills_the_checkpoint_id_of_a_hard_killed_run(tmp_path: Path):
    """决策 4（2026-09-07 修订）：启动收敛把标识回填成可查询字段。

    收敛是唯一无竞争的回填时机——manager 在构造执行器**之前**就调
    ``recover_stale_runs``，那时没有执行者会与段末回写争这一行。``resume`` 跑在
    HTTP 线程上，在那里回填会与该 run 自己的段末回写竞争。
    """
    thread_id = "thread_backfill"
    run_id = _park_with_live_carrier(tmp_path, thread_id)

    store = RuntimeStore(tmp_path)
    store.answer_question(run_id, [], timed_out=True)
    # 停在 RUNNING：这正是硬杀时 worker 的状态，收敛会把它落成 UNFINISHED。
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.set_run_checkpoint(run_id, None)
    assert store.get_run(run_id).checkpoint_id is None

    manager = AgentRuntimeManager(tmp_path, adapter=_PermissiveStubGraph())
    try:
        recovered = manager.store.get_run(run_id)
        assert recovered.status == AgentRunStatus.UNFINISHED
        assert recovered.checkpoint_id
        assert recovered.checkpoint_id == latest_run_checkpoint_id(
            tmp_path, thread_id, run_id
        )
    finally:
        manager.close()


def test_waiting_confirmation_survives_restart_even_when_its_field_is_null(tmp_path: Path):
    """决策 10 + 决策 4（2026-09-07 修订）：不以字段为空短路载体复核。

    修订前是 ``if run.checkpoint_id and has_run_checkpoint(...)``，字段 NULL 时直接
    走降级分支——关掉一个其实还能作答的问题、把 run 打成 UNFINISHED。这条同时
    关闭交接文档 §4 标注的"WAITING_CONFIRMATION 中重启后端"未实测缺口。
    """
    thread_id = "thread_question_null"
    run_id = _park_with_live_carrier(tmp_path, thread_id)

    store = RuntimeStore(tmp_path)
    store.set_run_checkpoint(run_id, None)
    assert store.get_run(run_id).status == AgentRunStatus.WAITING_CONFIRMATION

    manager = AgentRuntimeManager(tmp_path, adapter=_PermissiveStubGraph())
    try:
        recovered = manager.store.get_run(run_id)
        assert recovered.status == AgentRunStatus.WAITING_CONFIRMATION
        question = manager.store.get_open_question(run_id)
        assert question is not None and question["question"] == "继续吗？"
        assert recovered.checkpoint_id
        assert recovered.checkpoint_id == latest_run_checkpoint_id(
            tmp_path, thread_id, run_id
        )
    finally:
        manager.close()


def test_latest_run_checkpoint_id_reads_the_root_namespace_only(tmp_path: Path):
    """子图行不能冒充最新标识：``subgraphs=True`` 会写子图命名空间的行。

    SQL 逐字镜像 ``SqliteSaver.get_tuple`` 对"最新"的定义（根命名空间 +
    ``checkpoint_id`` 降序取一条），否则回填可能把一个子图标识写进 run 行。
    """
    saver = build_checkpointer(tmp_path)
    key = checkpoint_state_key("thread_ns", "run_ns")

    def put(namespace: str, checkpoint_id: str) -> None:
        saver.conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id,"
            " parent_checkpoint_id, type, checkpoint, metadata)"
            " VALUES (?, ?, ?, NULL, 'msgpack', x'00', x'00')",
            (key, namespace, checkpoint_id),
        )
        saver.conn.commit()

    put("sub:0", "ffff0000-0000-0000-0000-000000000000")
    assert latest_run_checkpoint_id(tmp_path, "thread_ns", "run_ns") is None
    # has_run_checkpoint 不过滤命名空间，所以这个组合是"存在但取不到标识"。
    # 该不对称是承重的：续跑闸门只问存在性，字段留空也安全。
    assert has_run_checkpoint(tmp_path, "thread_ns", "run_ns")

    put("", "1f1aa5d8-55f8-6780-8021-c170ea10bc03")
    put("", "1f1aa5da-535b-6c60-8022-4d3c37d67985")
    put("sub:0", "ffffffff-ffff-ffff-ffff-ffffffffffff")
    assert latest_run_checkpoint_id(tmp_path, "thread_ns", "run_ns") == (
        "1f1aa5da-535b-6c60-8022-4d3c37d67985"
    )


def test_protocol_adapter_question_is_left_alone_on_restart(tmp_path: Path):
    """决策 10 的边界：协议型 adapter 没有图状态，挂起态归外部服务，不参与收敛。"""
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_proto", thread_id="t_proto", input_message="x"))
    _park_on_question(store, "run_proto", "t_proto")

    recovered = store.recover_stale_runs(graph_state_durable=False)

    assert store.get_run("run_proto").status == AgentRunStatus.WAITING_CONFIRMATION
    assert store.get_open_question("run_proto") is not None
    assert all(run.run_id != "run_proto" for run in recovered)


# ===========================================================================
# 决策 11 / 12 —— 线程级联与体积指标
# ===========================================================================
def test_delete_thread_cascades_run_scoped_checkpoints(tmp_path: Path):
    _seed_workspace(tmp_path)
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    doomed_run = _turn(manager, "thread_doomed", "first")
    _turn(manager, "thread_doomed", "second")
    survivor_run = _turn(manager, "thread_survivor", "keep me")
    assert has_run_checkpoint(tmp_path, "thread_doomed", doomed_run.run_id)
    assert has_run_checkpoint(tmp_path, "thread_survivor", survivor_run.run_id)

    manager.store.delete_thread("thread_doomed")

    # 决策 11：该线程**全部** run 作用域键都要删掉，兄弟线程一个不动。
    assert not has_run_checkpoint(tmp_path, "thread_doomed", doomed_run.run_id)
    assert has_run_checkpoint(tmp_path, "thread_survivor", survivor_run.run_id)
    # 再删一次必须是无操作：键已经不在了，不能因此抛错。
    delete_thread_checkpoints(tmp_path, "thread_doomed")
    assert not has_run_checkpoint(tmp_path, "thread_doomed", doomed_run.run_id)


def test_diagnostics_reports_the_checkpoint_carrier_size(tmp_path: Path):
    """决策 12：载体不设 TTL/上限，膨胀只由删会话治理，所以体积必须可观测。"""
    manager = AgentRuntimeManager(tmp_path, adapter=_RecordingProtocolAdapter())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))
        started = client.post("/api/agent/runs", json={"message": "hello", "thread_id": "t_diag"})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]

        response = client.get(f"/api/agent/runs/{run_id}/diagnostics")

        assert response.status_code == 200, response.text
        checkpoint = response.json()["checkpoint"]
        assert checkpoint["backend"] == settings.agent_checkpointer
        assert checkpoint["file_bytes"] == checkpoint_file_bytes(tmp_path)
        assert checkpoint["file_bytes"] >= 0
    finally:
        manager.close()


def test_resume_and_answer_map_a_missing_checkpoint_to_409(tmp_path: Path):
    """决策 4 的 API 边界：CheckpointMissingError 继承 RuntimeError，
    漏掉映射就是 500。"""
    store = RuntimeStore(tmp_path)
    store.create_run(AgentRun(run_id="run_409", thread_id="t_409", input_message="x"))
    _drive_to_unfinished(store, "run_409")
    manager = AgentRuntimeManager(tmp_path, adapter=_StubGraph())
    try:
        client = TestClient(create_app(tmp_path, agent_runtime=manager))

        response = client.post("/api/agent/runs/run_409/resume")

        assert response.status_code == 409, response.text
        assert "resend" in response.json()["detail"]
    finally:
        manager.close()


# ===========================================================================
# 决策 13 —— 并发不变量（阶段 E 删掉临时写锁后本测试仍须绿）
# ===========================================================================
def test_checkpoint_carrier_tolerates_concurrent_readers(tmp_path: Path):
    """锁的是不变量而不是机制：多线程同时读同一个载体不许炸，也不许读到别的 id。"""
    _seed_workspace(tmp_path)
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    run = _turn(manager, "thread_concurrent", "hello")
    expected = latest_checkpoint_id(_Carrier(manager.adapter.checkpointer), "thread_concurrent", run.run_id)
    assert expected

    errors: list[BaseException] = []
    observed: list[str | None] = []
    lock = threading.Lock()

    def reader() -> None:
        # 每线程一条连接：并发访问同一个载体文件，但不泄漏上百个句柄。
        carrier = _Carrier(build_checkpointer(tmp_path))
        try:
            for _ in range(25):
                value = latest_checkpoint_id(carrier, "thread_concurrent", run.run_id)
                with lock:
                    observed.append(value)
        except BaseException as error:  # noqa: BLE001 - 测试要把任何异常都收上来
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=WAIT_TIMEOUT)

    assert not errors, errors
    assert observed and set(observed) == {expected}


# ===========================================================================
# 核心回归锁 —— 同线程连续 run 互不读取对方状态（决策 2/3/15）
# ===========================================================================
def test_consecutive_runs_in_one_thread_do_not_read_each_other_state(tmp_path: Path):
    """会话级状态键会让第 N 个 run 把前 N-1 轮已被图记住的内容重复注入，
    模型输入随轮次单调增长——这就是"多轮之后越来越乱"的机制来源。"""
    _seed_workspace(tmp_path)
    model = _RecordingFakeModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    thread_id = "thread_isolation"
    markers: list[str] = []
    runs: list[AgentRun] = []

    for index in range(4):
        marker = f"marker-{index}-{uuid.uuid4().hex[:8]}"
        markers.append(marker)
        run = _turn(manager, thread_id, f"{marker} 请简单回答")
        assert run.status == AgentRunStatus.SUCCEEDED, run.error_message
        runs.append(run)

    # 决策 2：每个 run 只有自己的 run 作用域键。
    for run in runs:
        assert has_run_checkpoint(tmp_path, thread_id, run.run_id), run.run_id

    last_input = model.seen[-1]
    # 核心锁：前面每一轮的输入在最后一个 run 里只出现一次（只经有界 transcript 进来）。
    for index, marker in enumerate(markers[:-1]):
        assert _count_occurrences(last_input, marker) == 1, (
            f"第 {index} 轮的输入被重复注入：{_count_occurrences(last_input, marker)} 次"
        )

    # 决策 15：进入模型的 messages 不超过 ConversationContextView 上界
    # （余量给系统提示、Layer B 与当前输入）。
    bound = ConversationContextView.MAX_MESSAGES + 4
    assert len(last_input) <= bound, f"{len(last_input)} 条消息超过上界 {bound}"


def test_resumed_segment_continues_from_checkpoint_without_replaying_transcript(tmp_path: Path):
    """决策 3 + 决策 4 + 决策 8：续跑段从该 run 自己的 checkpoint 继续，
    不重放 transcript；checkpoint 标识落库；墙钟跨段累计。"""
    _seed_workspace(tmp_path)
    model = _InterruptRecordingModel()
    manager = AgentRuntimeManager(tmp_path, adapter=build_wiki_agent(tmp_path, model=model))
    thread_id = "thread_resume"
    marker = f"marker-{uuid.uuid4().hex[:8]}"

    run = manager.start(
        thread_id=thread_id,
        message=f"{marker} 分析后问我是否继续",
        context=WikiAgentContext(project_id="cellwiki", thread_id=thread_id),
    )
    paused = _wait_for_status(manager, run.run_id, {AgentRunStatus.WAITING_CONFIRMATION})
    assert paused.status == AgentRunStatus.WAITING_CONFIRMATION
    paused = _wait_for_checkpoint(manager, run.run_id)
    assert has_run_checkpoint(tmp_path, thread_id, run.run_id)
    elapsed_before = paused.usage.elapsed_seconds

    result = manager.answer_question(run.run_id, "是")

    # 阶段 E：答题立即返回，续跑段在执行器线程上跑完。
    assert result["status"] == AgentRunStatus.RUNNING.value, result
    resumed = _wait_for_status(manager, run.run_id, {AgentRunStatus.SUCCEEDED})
    assert resumed.status == AgentRunStatus.SUCCEEDED
    assert len(model.seen) == 2
    # 决策 3：续跑段里首段的输入只出现一次——checkpoint 里那一份，没有再注入一遍。
    assert _count_occurrences(model.seen[1], marker) == 1
    # 决策 6：resume 不清状态，该 run 的状态键续跑之后仍在。
    assert has_run_checkpoint(tmp_path, thread_id, run.run_id)
    # 决策 8：墙钟继承已消耗时间，而不是从 0 重新计时。
    finished = manager.store.get_run(run.run_id)
    assert finished.usage.elapsed_seconds >= elapsed_before
    messages = manager.store.list_context_messages(thread_id)
    assert any("已按你的选择完成" in item["content"] for item in messages)
