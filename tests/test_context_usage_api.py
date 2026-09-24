# =============================================================================
# 上下文容量浮层的数据面：线程级构成估算
# =============================================================================
# 浮层显示"已用/上限 + 分节占比 + 平均缓存命中率"。总量取 provider 实测的
# `last_prompt_tokens`，分节是字符估算（与压缩基线同口径）。这四条锁住：新会话不编
# 数字、注入块与对话消息分桶、实测总量与缓存命中率来自账本、未知会话 404。
# =============================================================================

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from cellwiki.api.app import create_app
from cellwiki.domain.runs import AgentRun, AgentSpan, RunUsage
from cellwiki.services.agent_runtime import AgentRuntimeManager

THREAD = "thread_context_usage"


def _client(tmp_path: Path) -> tuple[TestClient, AgentRuntimeManager]:
    manager = AgentRuntimeManager(tmp_path)
    return TestClient(create_app(tmp_path, agent_runtime=manager)), manager


def _seed_transcript(manager: AgentRuntimeManager) -> None:
    manager.store.create_thread(THREAD)
    manager.store.create_run(
        AgentRun(run_id="run_seed", thread_id=THREAD, input_message="问" * 400)
    )
    manager.store.append_model_message(
        thread_id=THREAD,
        run_id="run_seed",
        kind="user",
        role="user",
        content={"text": "问" * 400},
        message_key="user",
    )
    manager.store.append_model_message(
        thread_id=THREAD,
        run_id="run_seed",
        kind="run_context",
        role="user",
        content={"text": "## Run context\n" + "上下文" * 100},
        message_key="run_context",
    )


def test_context_usage_separates_messages_from_injection(tmp_path: Path):
    client, manager = _client(tmp_path)
    _seed_transcript(manager)

    payload = client.get(f"/api/agent/threads/{THREAD}/context-usage").json()

    assert payload["thread_id"] == THREAD
    sections = payload["sections"]
    assert set(sections) == {"messages", "injection", "tools", "system_prompt"}
    # 注入块与对话消息各归各的桶，互不吞并
    assert sections["messages"] >= len("问" * 400) // 4
    assert 0 < sections["injection"] < sections["messages"]
    # 工具定义与系统提示词是随图构建的常量，必须量到非零
    assert sections["tools"] > 0
    assert sections["system_prompt"] > 0
    assert payload["estimated_tokens"] == sum(sections.values())


def test_context_usage_has_no_measured_total_before_the_first_call(tmp_path: Path):
    client, manager = _client(tmp_path)
    _seed_transcript(manager)

    payload = client.get(f"/api/agent/threads/{THREAD}/context-usage").json()

    # 还没跑过模型：不编造"已用"，但估算仍在（前端据此显示 0%）
    assert payload["used_tokens"] == 0
    assert payload["avg_cache_hit_rate"] == 0.0


def test_context_usage_scales_sections_onto_the_measured_total(tmp_path: Path):
    client, manager = _client(tmp_path)
    _seed_transcript(manager)
    manager.store.record_prompt_tokens(THREAD, 5_000)
    manager.store.record_completion_tokens(THREAD, 800)
    manager.store.update_usage(
        "run_seed",
        RunUsage(input_tokens=5_000, output_tokens=800, cached_input_tokens=3_750),
    )

    payload = client.get(f"/api/agent/threads/{THREAD}/context-usage").json()

    # 占用总量 = 上次调用的输入 + 它的输出：那条回答下一轮会被重发
    assert payload["last_input_tokens"] == 5_000
    assert payload["last_output_tokens"] == 800
    assert payload["used_tokens"] == 5_800
    assert payload["avg_cache_hit_rate"] == 0.75
    # 中文密度让字符估算系统性偏低，分节必须按实测输入折上去；输出不进分节
    assert abs(payload["estimated_tokens"] - 5_000) <= 8
    assert payload["sections"]["messages"] > payload["sections"]["injection"]


def test_context_usage_falls_back_to_the_last_model_span_for_old_threads(tmp_path: Path):
    # 记录列是新增的，升级前的会话没有值；span 里有 per-call 输出，用它兜底
    client, manager = _client(tmp_path)
    _seed_transcript(manager)
    manager.store.record_prompt_tokens(THREAD, 5_000)
    manager.store.upsert_span(
        AgentSpan(
            span_id="span_seed",
            run_id="run_seed",
            kind="model",
            name="coordinator",
            status="succeeded",
            started_at=datetime(2026, 9, 24, 1, 0, tzinfo=UTC),
            input_tokens=5_000,
            output_tokens=640,
        )
    )

    payload = client.get(f"/api/agent/threads/{THREAD}/context-usage").json()

    assert payload["last_output_tokens"] == 640
    assert payload["used_tokens"] == 5_640


def test_context_usage_rejects_unknown_threads(tmp_path: Path):
    client, _ = _client(tmp_path)
    assert client.get("/api/agent/threads/thread_missing/context-usage").status_code == 404
