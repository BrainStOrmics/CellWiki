"""Run 作用域 checkpoint 载体（ADR-0010）。

产品图默认把 LangGraph 图状态落到 ``data/runtime/checkpoints.sqlite``，与
``cellwiki.db`` 分文件，避免 WAL 与锁争用。状态键是 run 作用域的
``f"{thread_id}::{run_id}"``，所以同一会话里连续两个 run 不会读到对方的图状态；
协议型 adapter 没有图状态，继续用会话键。

不设 TTL、不设体积上限：膨胀只由用户删除会话治理（决策 12），
``GET /api/agent/runs/{run_id}/diagnostics`` 暴露体积指标供后续按实测数据重新评估。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from cellwiki.config import settings

CHECKPOINT_FILE_NAME = "checkpoints.sqlite"


class CheckpointMissingError(RuntimeError):
    """决策 4：可恢复态的 run 没有 checkpoint 时显式失败。

    升级前产生的 run 一律 ``checkpoint_id = NULL``；在空图上静默
    ``Command(resume=...)`` 行为不可预测，因此拒绝续跑并要求重发消息。
    与 ``InvalidRunTransitionError`` 同族（RuntimeError），API 映射成 409。
    """


def checkpoint_state_key(thread_id: str, run_id: str) -> str:
    """决策 2：图状态按 run 作用域隔离，而不是按会话。"""
    return f"{thread_id}::{run_id}"


def checkpoint_path(project_root: Path | str) -> Path:
    return Path(project_root) / "data" / "runtime" / CHECKPOINT_FILE_NAME


def build_checkpointer(project_root: Path | str) -> Any:
    """决策 1/14：默认 SqliteSaver；``AGENT_CHECKPOINTER=inmemory`` 是短期回滚闸。

    决策 13 的权宜写锁已删：**写方唯一由串行门禁保证**，不再靠进程内锁。
    一段运行的图状态只由执行器线程写（提问续跑也在执行器里，见
    ``AgentRuntimeManager._execute_resume``）；retry 的 ``delete_run_checkpoints``
    与删线程的级联删除都要求当时没有活动 run；``answer_question`` 只在
    WAITING_CONFIRMATION 上读一次最新 checkpoint 标识，那时没有执行者在跑。
    """
    if settings.agent_checkpointer == "inmemory":
        return InMemorySaver()
    path = checkpoint_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：连接在执行器线程上使用，但载体是在别的线程构造的。
    connection = sqlite3.connect(path, check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    return saver


def checkpoint_file_bytes(project_root: Path | str) -> int:
    """决策 12：体积指标。文件还没建出来时按 0 报，不报错。"""
    try:
        return checkpoint_path(project_root).stat().st_size
    except OSError:
        return 0


def _with_saver(project_root: Path | str, action: Callable[[SqliteSaver], None]) -> None:
    """对持久载体做一次短连接操作；回滚闸打开或文件不存在时无操作。"""
    if settings.agent_checkpointer == "inmemory":
        return
    path = checkpoint_path(project_root)
    if not path.exists():
        return
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        saver = SqliteSaver(connection)
        action(saver)
        connection.commit()
    finally:
        connection.close()


def delete_run_checkpoints(project_root: Path | str, thread_id: str, run_id: str) -> None:
    """决策 5：retry 先删该 run 的状态键，再从有界 transcript 重跑。"""
    key = checkpoint_state_key(thread_id, run_id)
    _with_saver(project_root, lambda saver: saver.delete_thread(key))


def delete_thread_checkpoints(project_root: Path | str, thread_id: str) -> None:
    """决策 11：删线程时按 run 作用域键级联删掉该线程全部 checkpoint。

    状态键形如 ``{thread_id}::{run_id}``，线程 id 是 ``thread_<hex>``，
    不含 LIKE 通配符，因此前缀匹配不会越界到别的线程。
    """

    def _delete(saver: SqliteSaver) -> None:
        rows = saver.conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE ?",
            (f"{thread_id}::%",),
        ).fetchall()
        for row in rows:
            saver.delete_thread(str(row[0]))

    _with_saver(project_root, _delete)


def has_run_checkpoint(project_root: Path | str, thread_id: str, run_id: str) -> bool:
    """决策 4/10：续跑前判断该 run 的图状态是否真的还在。"""
    if settings.agent_checkpointer == "inmemory":
        return False
    path = checkpoint_path(project_root)
    if not path.exists():
        return False
    key = checkpoint_state_key(thread_id, run_id)
    connection = sqlite3.connect(path, check_same_thread=False)
    try:
        row = connection.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1", (key,)
        ).fetchone()
        return row is not None
    finally:
        connection.close()


def latest_checkpoint_id(adapter: Any, thread_id: str, run_id: str) -> str | None:
    """决策 4：每段流结束时取回最新 checkpoint 标识，写回 ``AgentRun.checkpoint_id``。

    从编译图自己持有的 checkpointer 读，而不是另开一条连接：这样持久载体与
    ``AGENT_CHECKPOINTER=inmemory`` 回滚闸走同一条路径。
    """
    checkpointer = getattr(adapter, "checkpointer", None)
    if checkpointer is None:
        return None
    key = checkpoint_state_key(thread_id, run_id)
    found = checkpointer.get_tuple({"configurable": {"thread_id": key}})
    if found is None:
        return None
    configurable = found.config.get("configurable") if isinstance(found.config, dict) else None
    checkpoint_id = (configurable or {}).get("checkpoint_id")
    return str(checkpoint_id) if checkpoint_id else None


__all__ = [
    "CHECKPOINT_FILE_NAME",
    "CheckpointMissingError",
    "build_checkpointer",
    "checkpoint_file_bytes",
    "checkpoint_path",
    "checkpoint_state_key",
    "delete_run_checkpoints",
    "delete_thread_checkpoints",
    "has_run_checkpoint",
    "latest_checkpoint_id",
]
