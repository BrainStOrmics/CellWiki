"""Memory summary injection tests (ADR-0016, slice 4)."""

from __future__ import annotations

from pathlib import Path

from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.domain.runs import AgentRun
from cellwiki.services.agent_memory import (
    MEMORY_SUMMARY_MAX_TOKENS,
    WorkspaceMemoryStore,
    render_summary,
)
from cellwiki.services.agent_runtime import AgentRuntimeManager
from cellwiki.services.prompt_layers import build_turn_context


def _enable(monkeypatch, *, use: bool = True) -> None:
    import cellwiki.config as config_module

    monkeypatch.setattr(config_module.settings, "agent_memory_enabled", True)
    monkeypatch.setattr(config_module.settings, "agent_memory_use", use)


def _summary() -> str:
    return render_summary(
        profile="在这个工作区里按证据与逐行审批推进。",
        preferences="- 评审时逐行判定 diff。",
        tips="- 门禁失败先读 gate_issues。",
        index="### run 与审批\n- 审批偏好: 逐行判定",
    )


def test_turn_context_carries_memory_summary():
    context = build_turn_context(
        current_message="继续",
        gate_issues=["missing Evidence on wiki/cell_types/alpha.md"],
        memory_summary="v1\n\n## User Profile\n工作区协作口径。",
    )

    assert "## Workspace memory summary" in context
    assert "工作区协作口径。" in context
    # 门禁修复清单必须仍在同一份上下文里，不能被记忆段挤掉。
    assert "missing Evidence" in context


def test_turn_context_truncates_memory_summary():
    huge = "v1\n\n## User Profile\n" + ("记忆内容。" * 4_000)

    context = build_turn_context(current_message="x", memory_summary=huge)

    assert "[memory summary truncated]" in context
    assert len(context) <= 8_000


def test_memory_disabled_injects_nothing(monkeypatch, tmp_path: Path):
    _enable(monkeypatch, use=False)
    manager = AgentRuntimeManager(tmp_path, model_catalog=_NullCatalog())
    memory = WorkspaceMemoryStore(tmp_path, manager.store.path)
    memory.write_summary(_summary())
    run = manager.store.create_run(
        AgentRun(run_id="run_1", thread_id="thread_1", input_message="继续")
    )

    messages, _prompt = manager._prepare_v2_transcript(  # noqa: SLF001
        run, "继续", WikiAgentContext(), adapter=None
    )

    assert "Workspace memory summary" not in str(messages)


def test_memory_disabled_keeps_stable_prefix_memory_free(monkeypatch):
    import cellwiki.config as config_module
    from cellwiki.agent.app import stable_system_prompt_text

    monkeypatch.setattr(config_module.settings, "agent_memory_enabled", False)

    prompt = stable_system_prompt_text(2, "hash")

    for tool_name in (
        "list_memory",
        "read_memory",
        "search_memory",
        "add_ad_hoc_note",
    ):
        assert tool_name not in prompt


def test_memory_summary_is_pinned_to_the_first_run_of_a_thread(
    monkeypatch, tmp_path: Path
):
    _enable(monkeypatch)
    manager = AgentRuntimeManager(tmp_path, model_catalog=_NullCatalog())
    memory = WorkspaceMemoryStore(tmp_path, manager.store.path)
    memory.write_summary(_summary())
    first = manager.store.create_run(
        AgentRun(run_id="run_1", thread_id="thread_1", input_message="记住：逐行判定")
    )

    messages, _prompt = manager._prepare_v2_transcript(  # noqa: SLF001
        first, first.input_message, WikiAgentContext(), adapter=None
    )
    assert "Workspace memory summary" in str(messages)
    assert str(messages).count("Workspace memory summary") == 1

    # 记忆库在两次 run 之间更新：同线程第二次 run 仍复用快照，不重新读取文件。
    memory.write_summary(
        render_summary(profile="更新后的工作区口径。", preferences="- 新偏好。")
    )
    second = manager.store.create_run(
        AgentRun(run_id="run_2", thread_id="thread_1", input_message="继续")
    )

    second_messages, _prompt = manager._prepare_v2_transcript(  # noqa: SLF001
        second, second.input_message, WikiAgentContext(), adapter=None
    )

    # 钉住的含义是"不重新注入"：第二次 run 的历史里仍是首次那份快照，没有重复，
    # 也没有带上更新后的内容。
    assert str(second_messages).count("Workspace memory summary") == 1
    assert "更新后的工作区口径。" not in str(second_messages)


def test_thread_has_run_context_detects_prior_injection(tmp_path: Path):
    manager = AgentRuntimeManager(tmp_path, model_catalog=_NullCatalog())
    store = manager.store
    run = store.create_run(
        AgentRun(run_id="run_1", thread_id="t1", input_message="x")
    )
    assert not store.thread_has_run_context("t1", exclude_run_id=run.run_id)

    store.append_model_message(
        thread_id="t1",
        run_id="run_1",
        kind="run_context",
        role="user",
        content={"text": "## Run context"},
        message_key="run_context",
    )

    assert store.thread_has_run_context("t1")
    assert not store.thread_has_run_context("t1", exclude_run_id="run_1")


def test_memory_summary_token_budget_is_codex_aligned():
    assert MEMORY_SUMMARY_MAX_TOKENS == 2_500


class _NullCatalog:
    """Migration-free catalog: these tests never build a real model."""

    def resolve(self):  # noqa: D102 - parity with ModelCatalogService
        return None
