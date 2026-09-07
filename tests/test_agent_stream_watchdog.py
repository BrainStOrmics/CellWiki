"""流式活性看门狗（实测交接问题 C：取消/空闲永远落不定）。

以前：取消门与墙钟预算都只在**分段边界**检查，而边界要等模型调用返回才到得了一次。
SSE 连接挂起时（keepalive 会不断重置 httpx 的 read 超时）两者永远轮不到——实测一个
run 在 ``cancelling`` 上停了 8.5 小时，一直占着串行门禁，连 sidecar 都无法优雅关闭
（``close()`` 是 ``shutdown(wait=True)``）。

现在：一条 daemon 看门狗盯着流式增量。空闲界到期、或用户点了停止而宽限期内没落定，
就关掉模型的 HTTP client（照 ``adapters/openai_structured_output._watch_cancellation``
的既有做法）。httpcore 的连接池关闭**包含忙连接**，于是在飞的 socket 被关掉、阻塞读
抛错，生成器沿既有的 ``_iterate_safe`` finally 路径退栈：记账落盘、门禁释放。

这批用例只证明**本地可确定性验证**的那一半：界装上了、到期关掉了连接、退栈走了既有
收尾、三种入口都覆盖到、健康的静默工具不被误杀。关闭 ``root_client`` 是否真能打断
Windows/WebView2 上挂起的 qwen/glm SSE 读，需要按交接文档 §0 的配方用真实模型复现，
本地桩证明不了。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cellwiki.config import settings
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.questions import PendingQuestion
from cellwiki.domain.runs import (
    AgentErrorType,
    AgentRun,
    AgentRunStatus,
)
from cellwiki.services.agent_runtime import (
    AgentEventType,
    AgentRuntimeManager,
    RuntimeSignal,
    _StreamWatchdog,
    is_retryable_run,
)
from cellwiki.services.runtime_store import RuntimeStore

# 看门狗每 0.05s 轮询一次，所以亚秒级界是够用的；用例整体控制在 2s 量级。
WAIT_TIMEOUT = 10.0
# 替身流挂起时的最长等待：足够看门狗到期，又不会让用例在失败时挂住整个套件。
HANG_WAIT = 15.0


# ---------------------------------------------------------------------------
# 替身
# ---------------------------------------------------------------------------
class _RecordingClient:
    """模型 HTTP client 的最小形状：看门狗只会调它的 ``close()``。"""

    def __init__(self) -> None:
        self.closed = threading.Event()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class _WatchdogModel:
    """只暴露 ``root_client``——看门狗要的就是这一个句柄。"""

    def __init__(self, client: _RecordingClient) -> None:
        self.root_client = client


class _HangingAdapter:
    """协议型 adapter：吐一点增量后挂起，直到 client 被关掉或测试放行。

    协议型（有 ``execute``）是有意的：三个 ``_open_stream*`` 入口都接受它，于是
    ``start`` / ``resume`` / ``answer_question`` 三条路径都能用同一个替身驱动，
    证明界住在 ``_consume_stream`` 而不是某一个入口上。挂起之后抛的那一句，正是
    httpx 在 client 关闭后对阻塞读给出的错误。
    """

    def __init__(
        self, client: _RecordingClient, *, opens_tool: bool = False
    ) -> None:
        self.client = client
        self.opens_tool = opens_tool
        self.hanging = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []

    def execute(
        self,
        *,
        thread_id: str,
        message: Any = None,
        context: Any = None,
        resume: Any = None,
    ) -> Iterable[RuntimeSignal]:
        self.calls.append("answer" if resume is not None else "continue")
        if self.opens_tool:
            # 工具调用是静默之前的**最后**一条增量：``updates`` 把装配好的工具调用吐
            # 出来之后，工具节点就开始跑，几分钟内什么都不会有。多吐一条文本增量会把
            # "挂起空闲界"这件事掩盖掉——那正是误杀的窗口。
            yield RuntimeSignal(
                type=AgentEventType.TOOL_STARTED,
                message="ingest_sources · 3 个附件",
                data={"tool_name": "ingest_sources", "tool_call_id": "call_hang"},
                model_call_id="m1",
            )
        else:
            yield RuntimeSignal(
                type=AgentEventType.MESSAGE_DELTA,
                message="正在读",
                model_call_id="m1",
            )
        self.hanging.set()
        deadline = time.monotonic() + HANG_WAIT
        while time.monotonic() < deadline:
            if self.client.closed.is_set():
                raise RuntimeError(
                    "Cannot send a request, as the client has been closed."
                )
            if self.release.is_set():
                return
            time.sleep(0.02)
        raise AssertionError("the hanging adapter was never unblocked")

    def close(self) -> None:
        return None


class _ExpiryRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.fired = threading.Event()

    def __call__(self, run_id: str, escalated: bool) -> None:
        self.calls.append((run_id, escalated))
        self.fired.set()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
@contextmanager
def _watchdog(on_expire: Any) -> Iterable[_StreamWatchdog]:
    watchdog = _StreamWatchdog(on_expire)
    watchdog.start()
    try:
        yield watchdog
    finally:
        watchdog.stop()


def _manager(root: Path, adapter: _HangingAdapter) -> AgentRuntimeManager:
    """注入替身 adapter 的 manager，并补上模型句柄。

    生产路径上模型由 ``_build_agent()`` 建出来并记在 ``_agent_model`` 上，看门狗才有
    连接可断；注入 adapter 时那一步不会发生，所以这里手动挂上，形状与生产一致。
    """
    manager = AgentRuntimeManager(root, adapter=adapter)
    manager._agent_model = _WatchdogModel(adapter.client)
    return manager


def _context(thread_id: str) -> WikiAgentContext:
    return WikiAgentContext(project_id="cellwiki", thread_id=thread_id)


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


def _wait_for_close(adapter: _HangingAdapter, timeout: float = WAIT_TIMEOUT) -> None:
    if not adapter.client.closed.wait(timeout):
        raise AssertionError("the model connection was never force-closed")


def _wait_for_hang(adapter: _HangingAdapter, timeout: float = WAIT_TIMEOUT) -> None:
    if not adapter.hanging.wait(timeout):
        raise AssertionError("the adapter never reached its hanging model call")


def _wait_for_gate_release(
    manager: AgentRuntimeManager, timeout: float = WAIT_TIMEOUT
) -> None:
    """等串行门禁真的放开。

    终态是在 ``_execute_bound`` 的兜底 except 里落的，而 ``_running_run_id`` 要等到
    其后 ``_execute`` 的 finally（``_finish_run_segment``）才清；状态一变就断言会撞上
    这段窗口。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager._running_run_id is None:
            return
        time.sleep(0.02)
    raise AssertionError(f"the serial gate still holds {manager._running_run_id}")


def _start_hanging_run(
    manager: AgentRuntimeManager, thread_id: str, message: str = "读一下这个知识库"
) -> str:
    run = manager.start(
        thread_id=thread_id, message=message, context=_context(thread_id)
    )
    return run.run_id


def _park_unfinished(store: RuntimeStore, run_id: str, thread_id: str) -> None:
    """把一个 run 停在可续跑的 UNFINISHED 上（走 store 真正的迁移接口）。"""
    store.create_run(AgentRun(run_id=run_id, thread_id=thread_id, input_message="x"))
    store.transition(run_id, AgentRunStatus.RUNNING, message="Started.")
    store.transition(
        run_id,
        AgentRunStatus.UNFINISHED,
        error_type=AgentErrorType.TIMEOUT,
        error_message="budget exhausted",
        message="Paused.",
    )


def _park_on_question(store: RuntimeStore, run_id: str, thread_id: str) -> None:
    store.create_run(AgentRun(run_id=run_id, thread_id=thread_id, input_message="x"))
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
# 看门狗本身
# ===========================================================================
def test_watchdog_expires_when_the_stream_goes_idle():
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_idle", 0.2)
        assert recorder.fired.wait(WAIT_TIMEOUT)
    assert recorder.calls == [("run_idle", False)]


def test_watchdog_postpones_the_bound_while_items_keep_arriving():
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_live", 0.2)
        # 流一直有增量：界被不断顺延，不该到期。
        for _ in range(8):
            watchdog.touch(0.2)
            time.sleep(0.05)
        assert recorder.calls == []
        # 增量停了才到期。
        assert recorder.fired.wait(WAIT_TIMEOUT)
    assert recorder.calls == [("run_live", False)]


def test_watchdog_suspends_the_bound_while_a_tool_is_in_flight():
    """工具执行期间本来就产出不了任何增量，按空闲判定会误杀健康的 run。

    一次 ingest 可以合法地静默好几分钟，所以 ``touch(None)`` 必须真的把界挂起，
    而不是顺延。
    """
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_tool", 0.2)
        watchdog.touch(None)
        time.sleep(0.8)
        assert recorder.calls == []
        # 工具收工、增量恢复之后界要重新装上。
        watchdog.touch(0.2)
        assert recorder.fired.wait(WAIT_TIMEOUT)
    assert recorder.calls == [("run_tool", False)]


def test_watchdog_escalation_wins_over_later_stream_items():
    """用户点过停止之后，后到的增量不再顺延界——否则挂起的流永远等不到升级。"""
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_stop", 60.0)
        watchdog.escalate("run_stop", 0.2)
        for _ in range(6):
            watchdog.touch(60.0)
            time.sleep(0.05)
        assert recorder.fired.wait(WAIT_TIMEOUT)
    assert recorder.calls == [("run_stop", True)]


def test_watchdog_ignores_an_escalation_for_another_run():
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_a", 60.0)
        watchdog.escalate("run_b", 0.0)
        time.sleep(0.4)
        assert recorder.calls == []


def test_watchdog_disarm_stops_it_from_firing():
    recorder = _ExpiryRecorder()
    with _watchdog(recorder) as watchdog:
        watchdog.arm("run_done", 0.2)
        watchdog.disarm()
        time.sleep(0.6)
        assert recorder.calls == []


# ===========================================================================
# 空闲界：模型静默 -> 断开 -> 沿既有 finally 退栈
# ===========================================================================
def test_a_silent_model_call_is_force_closed_and_the_run_lands_unfinished(
    tmp_path: Path, monkeypatch
):
    """界到期时的四件事：断开连接、落 UNFINISHED/TIMEOUT、记账跑过、门禁释放。

    落 ``unfinished`` 而不是 ``failed``：图状态已按最后完成的超步落盘，这个 run 仍然
    可以续跑。记账那一条是退栈路径的证据——``_flush_accounting`` 挂在
    ``_iterate_safe`` 的 finally 上，只有沿既有路径退栈才会跑到。
    """
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 0.25)
    monkeypatch.setattr(settings, "agent_cancel_grace_seconds", 600)
    adapter = _HangingAdapter(_RecordingClient())
    manager = _manager(tmp_path, adapter)
    try:
        run_id = _start_hanging_run(manager, "thread_idle")
        _wait_for_hang(adapter)
        _wait_for_close(adapter)

        run = _wait_for_status(manager, run_id, {AgentRunStatus.UNFINISHED})
        assert run.error_type == AgentErrorType.TIMEOUT
        assert "force-closed" in (run.error_message or "")
        assert adapter.client.close_calls == 1
        # 退栈走的是既有 finally：spans 落盘了，串行门禁也放开了。
        assert any(span.kind == "model" for span in manager.store.list_spans(run_id))
        _wait_for_gate_release(manager)
        # 强制断开之后必须换掉懒建的 adapter 与模型：它们的连接已经关了，而编译图
        # 还持有那条进程级 SqliteSaver 连接。这是在不重新加锁的前提下维持 ADR-0010
        # 单写方不变量的方式。
        assert manager._built_adapter is None
        assert manager._agent_model is None
    finally:
        adapter.release.set()
        manager.close()


def test_a_cancel_that_never_lands_is_escalated_into_a_forced_close(
    tmp_path: Path, monkeypatch
):
    """裁定 2：停止键自动升级，而不是新增「强制终止」按钮。

    空闲界放到 600s，于是唯一可能到期的是取消宽限期——证明触发的是升级路径。
    必须收敛出 ``cancelling``：实测那 8.5 小时占住门禁的形状，就是 run 一直停在
    ``cancelling``（``_ensure_single_active_run`` 把它算作 active）。

    落点是 ``unfinished`` 而不是 ``cancelled``：用户按过停止，那是一次可续跑的暂停
    （ADR-0007 决策 10 的"用户停止后继续"）。所以门禁仍被这个 run 占着，要靠第二次
    取消（"放弃"）才放开——这一步也在这里钉住，否则两步语义会退化成新的死结。
    """
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 600)
    monkeypatch.setattr(settings, "agent_cancel_grace_seconds", 0.25)
    adapter = _HangingAdapter(_RecordingClient())
    manager = _manager(tmp_path, adapter)
    try:
        run_id = _start_hanging_run(manager, "thread_cancel")
        _wait_for_hang(adapter)

        cancelling = manager.cancel(run_id)
        assert cancelling.status == AgentRunStatus.CANCELLING
        _wait_for_close(adapter)

        run = _wait_for_status(manager, run_id, {AgentRunStatus.UNFINISHED})
        # 措辞落在 RUN_STATUS 事件上（run 行没有 message 字段）。
        assert any(
            event.type == AgentEventType.RUN_STATUS
            and "stopped by the user" in event.message
            for event in manager.store.list_events(run_id)
        )
        # 主动停止不是错误：error_type 为空 -> is_retryable_run 为假 -> 只给「继续」，
        # 不给「重试」（重试会删状态键从头重放，那不是按下停止的人想要的）。
        assert run.error_type is None
        assert is_retryable_run(run) is False

        # 暂停仍占着串行门禁；放弃（第二次取消）才放开。
        assert manager._ensure_single_active_run() is not None
        manager.cancel(run_id)
        abandoned = _wait_for_status(manager, run_id, {AgentRunStatus.CANCELLED})
        assert abandoned.status == AgentRunStatus.CANCELLED
        assert manager._ensure_single_active_run() is None
    finally:
        adapter.release.set()
        manager.close()


def test_a_silent_tool_does_not_trip_the_idle_bound(tmp_path: Path, monkeypatch):
    """误杀守卫：工具在飞时流本来就静默，空闲界必须挂起。

    后半段顺带证明挂起不是免死金牌——用户点停止仍然会升级并强制断开，run 落
    ``unfinished``（可续跑的暂停，门禁仍被占着），再取消一次才落 ``cancelled`` 放开。
    """
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 0.25)
    monkeypatch.setattr(settings, "agent_cancel_grace_seconds", 0.25)
    adapter = _HangingAdapter(_RecordingClient(), opens_tool=True)
    manager = _manager(tmp_path, adapter)
    try:
        run_id = _start_hanging_run(manager, "thread_tool")
        _wait_for_hang(adapter)
        # 3 倍空闲界内不得断开：工具还没收工，这是健康的静默。
        time.sleep(0.9)
        assert adapter.client.close_calls == 0
        assert manager.store.get_run(run_id).status == AgentRunStatus.RUNNING

        manager.cancel(run_id)
        _wait_for_close(adapter)
        _wait_for_status(manager, run_id, {AgentRunStatus.UNFINISHED})
        assert manager._ensure_single_active_run() is not None
        manager.cancel(run_id)
        _wait_for_status(manager, run_id, {AgentRunStatus.CANCELLED})
        assert manager._ensure_single_active_run() is None
    finally:
        adapter.release.set()
        manager.close()


# ===========================================================================
# 界住在 _consume_stream，三条入口都覆盖
# ===========================================================================
def test_the_resume_entry_point_is_bounded_too(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 0.25)
    store = RuntimeStore(tmp_path)
    _park_unfinished(store, "run_resume", "thread_resume")

    adapter = _HangingAdapter(_RecordingClient())
    manager = _manager(tmp_path, adapter)
    try:
        claimed = manager.resume("run_resume")
        assert claimed.status == AgentRunStatus.RUNNING
        _wait_for_hang(adapter)
        _wait_for_close(adapter)

        run = _wait_for_status(manager, "run_resume", {AgentRunStatus.UNFINISHED})
        assert run.error_type == AgentErrorType.TIMEOUT
        assert adapter.calls == ["continue"]
    finally:
        adapter.release.set()
        manager.close()


def test_the_answer_entry_point_is_bounded_too(tmp_path: Path, monkeypatch):
    """答题续跑段以前整段跑在 HTTP 线程上（阶段 E 已改到执行器），界同样要在。"""
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 0.25)
    store = RuntimeStore(tmp_path)
    _park_on_question(store, "run_answer", "thread_answer")

    adapter = _HangingAdapter(_RecordingClient())
    # 协议型 adapter 没有图状态，构造 manager 的启动收敛不动它的挂起态（决策 10）。
    manager = _manager(tmp_path, adapter)
    try:
        assert manager.store.get_run("run_answer").status == (
            AgentRunStatus.WAITING_CONFIRMATION
        )
        manager.answer_question("run_answer", ["是"])
        _wait_for_hang(adapter)
        _wait_for_close(adapter)

        run = _wait_for_status(manager, "run_answer", {AgentRunStatus.UNFINISHED})
        assert run.error_type == AgentErrorType.TIMEOUT
        assert adapter.calls == ["answer"]
    finally:
        adapter.release.set()
        manager.close()


def test_close_unblocks_a_hung_run_instead_of_waiting_forever(
    tmp_path: Path, monkeypatch
):
    """``close()`` 是 ``shutdown(wait=True)``，挂在 FastAPI 的 shutdown 事件上。

    模型挂起时它今天根本无法优雅关闭——实测那 8.5 小时最后只能靠强制重启恢复。
    关闭前先对正在跑的 run 升级看门狗（宽限期 0），于是退栈、收尾、shutdown 返回。
    """
    monkeypatch.setattr(settings, "agent_stream_idle_seconds", 600)
    monkeypatch.setattr(settings, "agent_cancel_grace_seconds", 600)
    adapter = _HangingAdapter(_RecordingClient())
    manager = _manager(tmp_path, adapter)
    run_id = _start_hanging_run(manager, "thread_shutdown")
    _wait_for_hang(adapter)

    started = time.monotonic()
    manager.close()
    assert time.monotonic() - started < HANG_WAIT
    assert adapter.client.close_calls == 1

    reopened = RuntimeStore(tmp_path)
    run = reopened.get_run(run_id)
    # 用户没点过停止，run 还在 RUNNING，而 RUNNING→CANCELLED 不是合法迁移：落
    # UNFINISHED/TIMEOUT（仍可续跑）。修复前这里会抛 InvalidRunTransitionError 出兜底
    # except，run 就永远停在 RUNNING 上。
    assert run.status == AgentRunStatus.UNFINISHED
    assert run.error_type == AgentErrorType.TIMEOUT
    assert "shutting down" in (run.error_message or "")
    adapter.release.set()
