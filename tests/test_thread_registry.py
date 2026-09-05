# =============================================================================
# 会话登记测试 —— agent_threads 作为历史下拉唯一真相的存储契约
# =============================================================================
# 覆盖：零 run 会话可见性与排序、run 活动驱动会话活动时间、旧库列级升级与登记
# 回填、空槽位删除。历史下拉曾由 run 分组派生，导致 `+` 新建的会话不可见也
# 不可回访；这里锁定"会话登记"这一层的合同。
# =============================================================================

from __future__ import annotations

import sqlite3
from pathlib import Path

from cellwiki.domain.runs import AgentRun, AgentRunStatus
from cellwiki.services.runtime_store import RuntimeStore


def _run(run_id: str, thread_id: str) -> AgentRun:
    return AgentRun(run_id=run_id, thread_id=thread_id, input_message="inspect")


def test_list_threads_includes_zero_run_sessions(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_thread("thread_placeholder")
    store.create_run(_run("run_active", "thread_active"))
    store.create_thread("thread_active")

    threads = store.list_threads()
    by_id = {item["thread_id"]: item for item in threads}

    assert set(by_id) == {"thread_placeholder", "thread_active"}
    assert by_id["thread_placeholder"]["run_count"] == 0
    assert by_id["thread_placeholder"]["latest_run_id"] is None
    assert by_id["thread_placeholder"]["title"] is None
    assert by_id["thread_active"]["run_count"] == 1
    assert by_id["thread_active"]["latest_run_id"] == "run_active"
    assert by_id["thread_active"]["latest_status"] == AgentRunStatus.QUEUED.value


def test_thread_recency_follows_latest_run_activity(tmp_path: Path):
    # 会话活动时间从 run 派生，而不是注册表计数器：run 写入路径无需维护会话字段。
    store = RuntimeStore(tmp_path)
    store.create_thread("thread_old")
    store.create_run(_run("run_old", "thread_old"))
    store.create_thread("thread_new")

    assert [item["thread_id"] for item in store.list_threads()] == [
        "thread_new",
        "thread_old",
    ]

    store.transition("run_old", AgentRunStatus.RUNNING)
    assert [item["thread_id"] for item in store.list_threads()] == [
        "thread_old",
        "thread_new",
    ]


def test_registry_upgrade_adds_title_and_backfills_missing_rows(tmp_path: Path):
    database = tmp_path / "data" / "runtime" / "cellwiki.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        # 模拟注册表引入前的旧库：两列 agent_threads + 一条无登记行的 run。
        connection.execute(
            "CREATE TABLE agent_threads (thread_id TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
        )
        connection.execute(
            """
            CREATE TABLE agent_runs (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO agent_threads(thread_id, created_at) VALUES (?, ?)",
            ("thread_known", "2026-08-20T00:00:00+00:00"),
        )
        legacy = AgentRun(
            run_id="run_legacy",
            thread_id="thread_legacy",
            input_message="hello",
            created_at="2026-08-21T00:00:00+00:00",  # type: ignore[arg-type]
        )
        connection.execute(
            "INSERT INTO agent_runs(run_id, thread_id, status, payload, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                legacy.run_id,
                legacy.thread_id,
                legacy.status.value,
                legacy.model_dump_json(),
                "2026-08-21T00:05:00+00:00",
            ),
        )

    store = RuntimeStore(tmp_path)
    columns = {
        row[1] for row in sqlite3.connect(database).execute("PRAGMA table_info(agent_threads)")
    }
    assert columns == {"thread_id", "created_at", "title"}

    by_id = {item["thread_id"]: item for item in store.list_threads()}
    assert set(by_id) == {"thread_known", "thread_legacy"}
    assert by_id["thread_legacy"]["run_count"] == 1
    assert by_id["thread_known"]["run_count"] == 0

    # 重复启动必须幂等：既不报列已存在，也不产生重复登记行。
    RuntimeStore(tmp_path)
    assert len({item["thread_id"] for item in store.list_threads()}) == 2


def test_create_run_registers_its_thread_without_explicit_allocation(tmp_path: Path):
    # 直接写库的路径（夹具、恢复逻辑）可能不经过 POST /api/agent/threads；
    # 注册不变式必须在存储边界成立，否则该会话再次变成不可见、不可回访。
    store = RuntimeStore(tmp_path)
    store.create_run(_run("run_unregistered", "thread_unregistered"))

    entries = {item["thread_id"]: item for item in store.list_threads()}
    assert entries["thread_unregistered"]["run_count"] == 1
    assert entries["thread_unregistered"]["latest_run_id"] == "run_unregistered"


def test_thread_title_is_derived_from_the_first_user_message(tmp_path: Path):
    # 会话标题确定性派生（不接 LLM）：历史列表不能一直显示 ID 后缀占位。
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(
            run_id="run_titled",
            thread_id="thread_titled",
            input_message="总结 CD8 T 细胞的标记基因",
        )
    )

    entries = {item["thread_id"]: item for item in store.list_threads()}
    assert entries["thread_titled"]["title"] == "总结 CD8 T 细胞的标记基因"


def test_thread_title_collapses_whitespace_and_truncates_to_40_chars(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    long_message = "第一段\n\n  换行与多余空白   应该被折叠 " + "长" * 60
    store.create_run(
        AgentRun(run_id="run_long", thread_id="thread_long", input_message=long_message)
    )

    title = {item["thread_id"]: item for item in store.list_threads()}["thread_long"]["title"]
    assert title is not None
    assert len(title) == 40
    assert "\n" not in title
    assert "  " not in title
    assert title.startswith("第一段 换行与多余空白 应该被折叠")


def test_thread_title_falls_back_to_the_placeholder_for_a_blank_message(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_blank", thread_id="thread_blank", input_message="   \n ")
    )

    entries = {item["thread_id"]: item for item in store.list_threads()}
    assert entries["thread_blank"]["title"] == "新会话"


def test_thread_title_is_written_once_and_never_renamed(tmp_path: Path):
    # 标题取首条用户消息；后续消息不得改写它（否则历史列表会随对话漂移）。
    store = RuntimeStore(tmp_path)
    store.create_run(
        AgentRun(run_id="run_first", thread_id="thread_stable", input_message="第一个问题")
    )
    store.create_run(
        AgentRun(run_id="run_second", thread_id="thread_stable", input_message="第二个问题")
    )
    store.append_message(
        thread_id="thread_stable",
        run_id="run_first",
        role="user",
        content="被改写的第一条",
    )

    entries = {item["thread_id"]: item for item in store.list_threads()}
    assert entries["thread_stable"]["title"] == "第一个问题"


def test_zero_run_thread_keeps_a_null_title(tmp_path: Path):
    # 尚未开始的会话不派生标题：前端显示"新会话"占位，不是空串。
    store = RuntimeStore(tmp_path)
    store.create_thread("thread_empty")

    assert {item["thread_id"]: item for item in store.list_threads()}["thread_empty"][
        "title"
    ] is None


def test_delete_thread_removes_zero_run_placeholder(tmp_path: Path):
    store = RuntimeStore(tmp_path)
    store.create_thread("thread_disposable")

    assert store.delete_thread("thread_disposable") == 0
    assert store.list_threads() == []
    assert store.thread_exists("thread_disposable") is False
