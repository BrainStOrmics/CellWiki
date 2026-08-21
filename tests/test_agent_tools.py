# =============================================================================
# 智能体工具测试 —— 验证智能体工具函数的正确性
# =============================================================================

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langchain_openai import ChatOpenAI

from cellwiki.agent.app import (
    SYSTEM_PROMPT,
    _CellWikiToolBoundaryMiddleware,
    build_model,
    build_subagent_specs,
    build_wiki_agent,
)
from cellwiki.agent.tools import (
    build_attachment_tools,
    build_final_answer_tool,
    build_rebase_tool,
    build_ingest_tools,
    build_lint_tools,
    build_memory_tools,
    build_read_tools,
)
from cellwiki.config import Settings
from cellwiki.services.operations import bind_agent_run
from cellwiki.domain.contracts import ApprovalPolicy, PipelineTaskType, WikiAgentContext
from cellwiki.services.attachments import (
    MAX_ATTACHMENT_SEARCHES_PER_RUN,
    AttachmentService,
    clear_attachment_read_ledger,
    record_attachment_read,
)
from cellwiki.services.pipeline import KnowledgePipelineHarness
from cellwiki.services.sources import SourceRegistry


def test_read_tools_use_page_ids_and_return_search_results(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "t_cell.md").write_text("# T Cell\n\nCD3D marker", encoding="utf-8")
    tools = {tool.name: tool for tool in build_read_tools(tmp_path)}

    result = tools["search_wiki"].invoke({"query": "CD3D", "limit": 5})
    missing = json.loads(tools["read_wiki_page"].invoke({"page_id": "does_not_exist"}))
    status = json.loads(tools["get_project_status"].invoke({}))

    assert "t_cell" in result
    assert "CD3D" in result
    assert missing == {"error": "page_not_found", "page_id": "does_not_exist"}
    assert status["knowledge_version"].startswith("sha256:")
    assert status["approval_policy"] == "auto_low_risk"


def test_attachment_tools_read_search_and_promote_thread_scoped_uploads(tmp_path: Path):
    thread_id = "thread_" + "a" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 attachment evidence for Treg curation.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(
        context={
            "thread_id": thread_id,
            "attachment_ids": [attachment.attachment_id],
            "allow_attachment_promotion": True,
        }
    )

    listed = json.loads(tools["list_thread_attachments"].func(runtime=runtime))
    excerpt = json.loads(
        tools["read_attachment_excerpt"].func(
            runtime=runtime,
            attachment_id=attachment.attachment_id,
        )
    )
    matches = json.loads(
        tools["search_attachment_text"].func(runtime=runtime, query="FOXP3")
    )
    promoted = json.loads(
        tools["register_attachment_as_source"].func(
            runtime=runtime,
            attachment_id=attachment.attachment_id,
        )
    )
    promoted_again = json.loads(
        tools["register_attachment_as_source"].func(
            runtime=runtime,
            attachment_id=attachment.attachment_id,
        )
    )

    assert listed["attachments"][0]["attachment_id"] == attachment.attachment_id
    assert "stored_path" not in listed["attachments"][0]
    assert excerpt["chunk_id"] == f"{attachment.attachment_id}:text:0"
    assert "FOXP3 attachment evidence" in excerpt["excerpt"]
    assert matches["matches"][0]["attachment_id"] == attachment.attachment_id
    assert matches["matches"][0]["chunk_id"].startswith(f"{attachment.attachment_id}:")
    assert promoted["source"]["source_id"].startswith("src_")
    assert promoted_again["source"]["source_id"] == promoted["source"]["source_id"]
    assert promoted_again["already_promoted"] is True


def test_attachment_search_is_cached_and_bounded_per_run(tmp_path: Path):
    thread_id = "thread_" + "d" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 attachment evidence for Treg curation.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(
        context={
            "thread_id": thread_id,
            "attachment_ids": [attachment.attachment_id],
            "run_id": "run_attachment_search_budget",
        }
    )

    try:
        first = json.loads(
            tools["search_attachment_text"].func(runtime=runtime, query="FOXP3")
        )
        repeated = json.loads(
            tools["search_attachment_text"].func(runtime=runtime, query="  foxp3  ")
        )

        assert first["matches"]
        assert repeated["cached"] is True
        assert repeated["matches"][0]["attachment_id"] == attachment.attachment_id
        assert "excerpt" not in repeated["matches"][0]

        for index in range(MAX_ATTACHMENT_SEARCHES_PER_RUN - 1):
            json.loads(
                tools["search_attachment_text"].func(
                    runtime=runtime,
                    query=f"unseen query {index}",
                )
            )
        exhausted = json.loads(
            tools["search_attachment_text"].func(
                runtime=runtime,
                query="one more query",
            )
        )
        assert exhausted["error"] == "attachment_search_budget_exhausted"

        other_runtime = SimpleNamespace(
            context={
                "thread_id": thread_id,
                "attachment_ids": [attachment.attachment_id],
                "run_id": "run_attachment_search_other",
            }
        )
        other_run = json.loads(
            tools["search_attachment_text"].func(
                runtime=other_runtime,
                query="FOXP3",
            )
        )
        assert other_run.get("cached") is not True
    finally:
        clear_attachment_read_ledger("run_attachment_search_budget")
        clear_attachment_read_ledger("run_attachment_search_other")


def test_attachment_promotion_requires_runtime_write_intent(tmp_path: Path):
    thread_id = "thread_" + "f" * 32
    source = tmp_path / "notes.txt"
    source.write_text("This paper mentions T cells only.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(
        context={"thread_id": thread_id, "attachment_ids": [attachment.attachment_id]}
    )

    blocked = json.loads(
        tools["register_attachment_as_source"].func(
            runtime=runtime,
            attachment_id=attachment.attachment_id,
        )
    )

    assert blocked["error"] == "attachment_promotion_not_allowed"
    assert AttachmentService(tmp_path).get(thread_id, attachment.attachment_id).promoted_source_id is None
    assert SourceRegistry(tmp_path).list_sources() == []


def test_attachment_tools_bind_the_current_thread_from_runtime_context(tmp_path: Path):
    thread_id = "thread_" + "b" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 is a regulatory T-cell marker.", encoding="utf-8")
    attachment = AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(
        context={
            "thread_id": thread_id,
            "attachment_ids": [attachment.attachment_id],
        }
    )

    assert "thread_id" not in tools["list_thread_attachments"].tool_call_schema.model_fields
    listed = json.loads(tools["list_thread_attachments"].func(runtime=runtime))
    excerpt = json.loads(
        tools["read_attachment_excerpt"].func(
            attachment_id=attachment.attachment_id,
            runtime=runtime,
        )
    )

    assert listed["attachments"][0]["attachment_id"] == attachment.attachment_id
    assert "FOXP3" in excerpt["excerpt"]


def test_attachment_tools_only_expose_currently_referenced_attachments(tmp_path: Path):
    thread_id = "thread_" + "e" * 32
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("FOXP3 is a regulatory T-cell marker.", encoding="utf-8")
    second_source.write_text("SPP1 marks tumor-associated macrophages.", encoding="utf-8")
    first = AttachmentService(tmp_path).create(
        thread_id,
        first_source,
        original_name="first.txt",
        media_type="text/plain",
    )
    second = AttachmentService(tmp_path).create(
        thread_id,
        second_source,
        original_name="second.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(context={"thread_id": thread_id, "attachment_ids": [first.attachment_id]})

    listed = json.loads(tools["list_thread_attachments"].func(runtime=runtime))
    unselected_read = json.loads(
        tools["read_attachment_excerpt"].func(runtime=runtime, attachment_id=second.attachment_id)
    )
    unselected_search = json.loads(
        tools["search_attachment_text"].func(runtime=runtime, query="SPP1")
    )

    assert [item["attachment_id"] for item in listed["attachments"]] == [first.attachment_id]
    assert unselected_read["error"] == "attachment_not_selected"
    assert unselected_search["matches"] == []


def test_attachment_tools_with_no_references_do_not_fall_back_to_the_thread_archive(tmp_path: Path):
    thread_id = "thread_" + "f" * 32
    source = tmp_path / "notes.txt"
    source.write_text("FOXP3 evidence", encoding="utf-8")
    AttachmentService(tmp_path).create(
        thread_id,
        source,
        original_name="notes.txt",
        media_type="text/plain",
    )
    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(context={"thread_id": thread_id, "attachment_ids": []})

    listed = json.loads(tools["list_thread_attachments"].func(runtime=runtime))
    search = json.loads(tools["search_attachment_text"].func(runtime=runtime, query="FOXP3"))

    assert listed["attachments"] == []
    assert search["matches"] == []


def test_attachment_upload_defers_pdf_extraction_until_agent_read(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    source.write_bytes((Path(__file__).parent / "fixtures" / "page_aware_source.pdf").read_bytes())

    attachment = AttachmentService(tmp_path).create(
        "thread_" + "c" * 32,
        source,
        original_name="paper.pdf",
        media_type="application/pdf",
    )

    assert attachment.text_path is None
    assert not (Path(attachment.stored_path).parent / "text.txt").exists()
    assert "FOXP3" in AttachmentService(tmp_path).read_text(
        attachment.thread_id,
        attachment.attachment_id,
    )
    assert AttachmentService(tmp_path).get(
        attachment.thread_id,
        attachment.attachment_id,
    ).text_path is not None


def test_attachment_service_deletes_an_uncommitted_attachment(tmp_path: Path):
    source = tmp_path / "pending.txt"
    source.write_text("pending attachment", encoding="utf-8")
    service = AttachmentService(tmp_path)
    attachment = service.create(
        "thread_" + "f" * 32,
        source,
        original_name="pending.txt",
        media_type="text/plain",
    )
    stored_dir = Path(attachment.stored_path).parent

    deleted = service.delete(attachment.thread_id, attachment.attachment_id)

    assert deleted.attachment_id == attachment.attachment_id
    assert not stored_dir.exists()
    assert service.list(attachment.thread_id) == []


def test_attachment_service_lazily_extracts_text_from_legacy_pdf_uploads(tmp_path: Path):
    source = tmp_path / "legacy-paper.pdf"
    source.write_bytes((Path(__file__).parent / "fixtures" / "page_aware_source.pdf").read_bytes())
    service = AttachmentService(tmp_path)
    attachment = service.create(
        "thread_" + "d" * 32,
        source,
        original_name="legacy-paper.pdf",
        media_type="application/pdf",
    )

    # Simulate an upload created before PDF extraction was supported.
    attachment_dir = Path(attachment.stored_path).parent
    text_path = attachment_dir / "text.txt"
    text_path.unlink(missing_ok=True)
    metadata_path = attachment_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["text_path"] = None
    metadata["text_hash"] = None
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    text = service.read_text(attachment.thread_id, attachment.attachment_id)

    assert "FOXP3" in text
    refreshed = service.get(attachment.thread_id, attachment.attachment_id)
    assert refreshed.text_path is not None


def test_attachment_service_concurrent_metadata_writes_use_unique_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "concurrent-paper.pdf"
    source.write_bytes((Path(__file__).parent / "fixtures" / "page_aware_source.pdf").read_bytes())
    service = AttachmentService(tmp_path)
    attachment = service.create(
        "thread_" + "7" * 32,
        source,
        original_name="concurrent-paper.pdf",
        media_type="application/pdf",
    )

    # Separate service instances model independent tool/API callers. Force both
    # writers to finish before either replaces metadata.json. The old fixed
    # metadata.json.tmp path then fails deterministically on Windows.
    service_a = AttachmentService(tmp_path)
    service_b = AttachmentService(tmp_path)
    record_a = attachment.model_copy(update={"text_hash": "sha256:a"})
    record_b = attachment.model_copy(update={"text_hash": "sha256:b"})
    write_barrier = threading.Barrier(2)
    temporary_paths: list[str] = []
    temporary_paths_lock = threading.Lock()
    original_write_text = Path.write_text

    def synchronized_write_text(path: Path, *args, **kwargs):
        result = original_write_text(path, *args, **kwargs)
        if path.name.startswith("metadata.") and path.name.endswith(".json.tmp"):
            with temporary_paths_lock:
                temporary_paths.append(str(path.resolve()))
            write_barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(Path, "write_text", synchronized_write_text)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                reader._write_record,
                record,
            )
            for reader, record in ((service_a, record_a), (service_b, record_b))
        ]
        errors = []
        for future in futures:
            try:
                future.result()
            except Exception as error:  # pragma: no cover - assertion below reports it
                errors.append(error)

    assert not errors
    assert len(temporary_paths) == 2
    assert len(set(temporary_paths)) == 2


def test_attachment_service_concurrent_lazy_reads_share_projection_safely(tmp_path: Path):
    source = tmp_path / "concurrent-paper.pdf"
    source.write_bytes((Path(__file__).parent / "fixtures" / "page_aware_source.pdf").read_bytes())
    service = AttachmentService(tmp_path)
    attachment = service.create(
        "thread_" + "8" * 32,
        source,
        original_name="concurrent-paper.pdf",
        media_type="application/pdf",
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(service.read_text, attachment.thread_id, attachment.attachment_id)
            for _ in range(8)
        ]
        texts = [future.result() for future in futures]

    assert all("FOXP3" in text for text in texts)
    refreshed = service.get(attachment.thread_id, attachment.attachment_id)
    assert refreshed.text_path is not None


def test_attachment_tool_reads_legacy_pdf_after_lazy_extraction(tmp_path: Path):
    source = tmp_path / "legacy-paper.pdf"
    source.write_bytes((Path(__file__).parent / "fixtures" / "page_aware_source.pdf").read_bytes())
    service = AttachmentService(tmp_path)
    attachment = service.create(
        "thread_" + "e" * 32,
        source,
        original_name="legacy-paper.pdf",
        media_type="application/pdf",
    )

    # Simulate metadata written before PDF extraction was supported.
    attachment_dir = Path(attachment.stored_path).parent
    text_path = attachment_dir / "text.txt"
    text_path.unlink(missing_ok=True)
    metadata_path = attachment_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["text_path"] = None
    metadata["text_hash"] = None
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    tools = {tool.name: tool for tool in build_attachment_tools(tmp_path)}
    runtime = SimpleNamespace(
        context={
            "thread_id": attachment.thread_id,
            "attachment_ids": [attachment.attachment_id],
        }
    )

    result = json.loads(
        tools["read_attachment_excerpt"].func(
            runtime=runtime,
            attachment_id=attachment.attachment_id,
        )
    )

    assert "error" not in result
    assert "FOXP3" in result["excerpt"]


def test_rebase_tool_returns_an_explicit_current_or_conflict_result(tmp_path: Path):
    from cellwiki.services.changesets import ChangeSetRepository
    from cellwiki.domain.contracts import ChangeOperation, ChangeOperationType, RiskLevel
    from cellwiki.domain.pipeline import PipelineTaskType

    change_set = ChangeSetRepository(tmp_path).create_proposal(
        run_id="run_rebase_tool",
        task_type=PipelineTaskType.INGEST,
        operations=[
            ChangeOperation(
                type=ChangeOperationType.UPDATE_CURATION,
                target_id="cell_a",
                payload={"content": "Evidence"},
            )
        ],
        reason="Test rebase tool.",
        risk=RiskLevel.LOW,
    )
    payload = json.loads(
        build_rebase_tool(tmp_path).invoke({"change_set_id": change_set.change_set_id})
    )

    assert payload["original_change_set_id"] == change_set.change_set_id
    assert payload["status"] == "current"


def test_conversation_subagent_is_read_only(tmp_path: Path):
    read_tools = build_read_tools(tmp_path)
    specs = build_subagent_specs(
        "openai:test-model",
        read_tools,
    )

    assert {spec["name"] for spec in specs} == {"query-agent"}
    tool_names = {tool.name for tool in specs[0]["tools"]}
    assert "list_change_sets" in tool_names
    assert "commit_change_set" not in tool_names
    assert "prepare_ingest_change_set" not in tool_names
    assert "propose_lint_fix" not in tool_names


def test_lint_tools_return_the_report_with_a_whole_project_snapshot(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "broken.md").write_text("# Missing frontmatter", encoding="utf-8")
    tools = {tool.name: tool for tool in build_lint_tools(tmp_path)}

    payload = json.loads(tools["inspect_knowledge_quality"].invoke({}))

    assert payload["snapshot"]["task_type"] == "lint"
    assert payload["snapshot"]["inventory"]["formal"]["wiki_pages"] == 1
    assert payload["report"]["issue_count"] >= 1


def test_lint_tools_report_pipeline_busy_without_failing_the_agent_run(tmp_path: Path):
    harness = KnowledgePipelineHarness(tmp_path)
    tools = {tool.name: tool for tool in build_lint_tools(tmp_path)}

    with harness.acquire(task_type=PipelineTaskType.INGEST, run_id="run_writer"):
        payload = json.loads(
            tools["run_broad_lint"].invoke({"run_id": "run_lint"})
        )

    assert payload["status"] == "pipeline_busy"
    assert payload["active_task"]["run_id"] == "run_writer"


def test_coordinator_is_model_led_and_governed():
    assert "Model-led CellWiki coordinator" in SYSTEM_PROMPT
    assert "Do not route the user to a separate typed-task" in SYSTEM_PROMPT
    assert "never launch" in SYSTEM_PROMPT
    assert "never modify files directly" in SYSTEM_PROMPT
    assert "treat that as a constraint on actions" in SYSTEM_PROMPT


def test_default_harness_exposes_only_read_only_conversation_capabilities(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def capture_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr("cellwiki.agent.app.create_deep_agent", capture_agent)

    build_wiki_agent(
        project_root=tmp_path,
        model="openai:broad-lint-route-test",
        checkpointer=False,
    )

    specs = captured["subagents"]
    names = {spec["name"] for spec in specs}
    assert names == {"query-agent", "ingest-agent"}
    top_level_tool_names = {tool.name for tool in captured["tools"]}
    assert "submit_agent_answer" in top_level_tool_names
    assert "list_thread_attachments" in top_level_tool_names
    assert "read_attachment_excerpt" in top_level_tool_names
    assert "search_attachment_text" in top_level_tool_names
    assert "register_attachment_as_source" in top_level_tool_names
    assert "commit_change_set" not in top_level_tool_names
    assert "rebase_change_set" not in top_level_tool_names
    assert {"read_file", "write_file", "edit_file", "glob", "grep", "ls"}.isdisjoint(
        top_level_tool_names
    )


def test_tool_boundary_rejects_generic_filesystem_calls():
    middleware = _CellWikiToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "call_blocked", "args": {"path": "secret"}}
    )

    result = middleware.wrap_tool_call(request, lambda _: pytest.fail("handler must not run"))

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "CellWiki tools" in result.content


def test_tool_boundary_hides_mutating_tools_for_read_only_attachment_context():
    class Request(SimpleNamespace):
        def override(self, **overrides):
            data = self.__dict__.copy()
            data.update(overrides)
            return Request(**data)

    middleware = _CellWikiToolBoundaryMiddleware()
    request = Request(
        tools=[
            SimpleNamespace(name="list_thread_attachments"),
            SimpleNamespace(name="read_attachment_excerpt"),
            SimpleNamespace(name="register_attachment_as_source"),
            SimpleNamespace(name="prepare_ingest_change_set"),
            SimpleNamespace(name="submit_agent_answer"),
        ],
        runtime=SimpleNamespace(
            context=WikiAgentContext(
                thread_id="thread_" + "1" * 32,
                attachment_ids=["att_" + "2" * 32],
            )
        ),
        system_message=None,
    )

    visible_tool_names = middleware.wrap_model_call(
        request,
        lambda filtered: [tool.name for tool in filtered.tools],
    )

    assert "list_thread_attachments" in visible_tool_names
    assert "read_attachment_excerpt" in visible_tool_names
    assert "submit_agent_answer" in visible_tool_names
    assert "register_attachment_as_source" not in visible_tool_names
    assert "prepare_ingest_change_set" not in visible_tool_names


def test_tool_boundary_keeps_mutating_tools_for_explicit_attachment_promotion():
    class Request(SimpleNamespace):
        def override(self, **overrides):
            data = self.__dict__.copy()
            data.update(overrides)
            return Request(**data)

    middleware = _CellWikiToolBoundaryMiddleware()
    request = Request(
        tools=[
            SimpleNamespace(name="register_attachment_as_source"),
            SimpleNamespace(name="prepare_ingest_change_set"),
        ],
        runtime=SimpleNamespace(
            context=WikiAgentContext(
                thread_id="thread_" + "1" * 32,
                attachment_ids=["att_" + "2" * 32],
                allow_attachment_promotion=True,
            )
        ),
        system_message=None,
    )

    visible_tool_names = middleware.wrap_model_call(
        request,
        lambda filtered: [tool.name for tool in filtered.tools],
    )

    assert "register_attachment_as_source" in visible_tool_names
    assert "prepare_ingest_change_set" in visible_tool_names


def test_broad_lint_tool_combines_local_quality_and_external_refresh(
    tmp_path: Path,
    monkeypatch,
):
    class FakeRefreshRun:
        def model_dump(self, mode="json"):
            return {
                "refresh_run_id": "refresh_broad",
                "status": "completed",
                "candidate_ids": ["research_candidate"],
                "snapshot_id": "snapshot_external",
                "knowledge_version": "sha256:external",
            }

    class FakeResearchService:
        def __init__(self, project_root):
            assert project_root == tmp_path.resolve()

        def refresh(self, query: str, *, project_id: str, limit: int, run_id: str, lease):
            assert query == "Treg FOXP3"
            assert project_id == "cellwiki"
            assert limit == 3
            assert run_id == "broad-run"
            assert lease.snapshot.run_id == "broad-run"
            active = KnowledgePipelineHarness(tmp_path).active_task()
            assert active is not None
            assert active["run_id"] == "broad-run"
            assert active["snapshot_id"] == lease.snapshot.snapshot_id
            return FakeRefreshRun()

    monkeypatch.setattr("cellwiki.agent.tools.ResearchService", FakeResearchService)
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "broken.md").write_text("# Missing frontmatter", encoding="utf-8")
    tools = {tool.name: tool for tool in build_lint_tools(tmp_path)}

    payload = json.loads(
        tools["run_broad_lint"].invoke(
            {
                "run_id": "broad-run",
                "external_query": "Treg FOXP3",
                "limit": 3,
            }
        )
    )

    assert payload["mode"] == "broad"
    assert payload["local_quality"]["issue_count"] >= 1
    assert payload["external_refresh"]["refresh_run_id"] == "refresh_broad"
    assert payload["snapshot"]["task_type"] == "lint"


def test_lint_fix_proposal_returns_the_full_pipeline_snapshot(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "repair_me.md").write_text(
        "---\nreferences: [paper_1]\n---\n\nBody without a title.",
        encoding="utf-8",
    )
    tools = {tool.name: tool for tool in build_lint_tools(tmp_path)}
    report = json.loads(tools["inspect_knowledge_quality"].invoke({}))["report"]
    finding_ids = [item["finding_id"] for item in report["issues"] if item["auto_fixable"]]

    payload = json.loads(
        tools["propose_lint_fix"].invoke(
            {"finding_ids": finding_ids, "run_id": "lint-snapshot-run"}
        )
    )

    assert payload["snapshot"]["task_type"] == "lint"
    assert payload["snapshot"]["run_id"] == "lint-snapshot-run"
    assert payload["snapshot"]["inventory"]["formal"]["wiki_pages"] == 1


def test_deep_agent_compiles_with_explicit_safe_subagents(tmp_path: Path):
    model = ChatOpenAI(model="gpt-4o-mini", api_key="test-key")

    agent = build_wiki_agent(project_root=tmp_path, model=model)

    assert agent.name == "cellwiki-agent"
    assert "tools" in agent.get_graph().nodes


def test_auto_approval_policy_removes_the_human_interrupt_from_agent_harness(
    tmp_path: Path,
    monkeypatch,
):
    KnowledgePipelineHarness(tmp_path).set_approval_policy(ApprovalPolicy.AUTO_ALL)
    captured: dict[str, object] = {}

    def capture_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr("cellwiki.agent.app.create_deep_agent", capture_agent)

    from cellwiki.agent.app import build_wiki_agent

    build_wiki_agent(project_root=tmp_path, model="openai:auto-policy-test", checkpointer=False)

    assert captured["interrupt_on"] == {}


@pytest.mark.parametrize("use_prebuilt_model", [False, True])
def test_configured_agent_hides_generic_harness_tools_from_first_request(
    tmp_path: Path,
    monkeypatch,
    use_prebuilt_model: bool,
):
    captured: dict[str, object] = {}

    class RequestCaptured(Exception):
        """Stop graph execution after recording the provider request."""

    def capture_request(self, messages, stop=None, run_manager=None, **kwargs):
        schemas = kwargs.get("tools", [])
        captured["message_chars"] = sum(
            len(str(getattr(message, "content", ""))) for message in messages
        )
        captured["tool_choice"] = kwargs.get("tool_choice")
        captured["tool_names"] = {
            schema.get("function", {}).get("name", "") for schema in schemas
        }
        captured["tool_schemas"] = json.dumps(
            schemas,
            ensure_ascii=False,
            default=str,
        )
        captured["tool_schema_chars"] = sum(
            len(json.dumps(schema, ensure_ascii=False, default=str))
            for schema in schemas
        )
        raise RequestCaptured

    if use_prebuilt_model:
        model = ChatOpenAI(
            api_key="test-key",
            model="cellwiki-unregistered-profile-test",
        )
    else:
        configuration = Settings(
            _env_file=None,
            openai_api_key="test-key",
            openai_model="cellwiki-profile-test",
        )
        model = build_model(configuration)
    agent = build_wiki_agent(
        project_root=tmp_path,
        model=model,
        checkpointer=False,
    )
    monkeypatch.setattr(ChatOpenAI, "_generate", capture_request)

    with pytest.raises(RequestCaptured):
        list(
            agent.stream(
                {"messages": [{"role": "user", "content": "Explain regulatory T cells."}]},
                context={
                    "project_id": "cellwiki",
                    "page_id": "regulatory_t_cell",
                    "thread_id": "profile-test",
                },
                stream_mode=["updates"],
            )
        )

    assert {
        "get_project_status",
        "search_wiki",
        "read_wiki_page",
        "list_change_sets",
        "get_change_set",
        "prepare_ingest_change_set",
        "request_ingest_revision",
        "run_broad_lint",
        "inspect_knowledge_quality",
        "propose_lint_fix",
        "submit_agent_answer",
        "task",
    } <= captured["tool_names"]
    assert "general-purpose" not in captured["tool_schemas"]
    assert captured["tool_choice"] in {None, "auto"}
    assert captured["message_chars"] < 12_000
    assert captured["tool_schema_chars"] < 12_000


def test_memory_tool_submits_validated_candidate_without_accepting_reasoning(tmp_path: Path):
    _, propose = build_memory_tools(tmp_path)

    record = propose.invoke({
        "content": "Prefer compact claim and evidence tables.",
        "kind": "stable",
        "key": "answer_format",
        "confidence": 0.8,
        "tags": ["preference"],
    })

    assert '"status":"active"' in record
    assert '"key":"answer_format"' in record


def test_final_answer_tool_ignores_display_only_citation_metadata(tmp_path: Path):
    tool = build_final_answer_tool(tmp_path)

    result = tool.invoke(
        {
            "answer": "The page contains the requested entry.",
            "citations": [
                {
                    "page_id": "regulatory_t_cell",
                    "source_id": "paper-1",
                    "title": "Regulatory T Cell",
                    "path": "wiki/cell_types/regulatory_t_cell.md",
                    "sections": ["## Markers"],
                }
            ],
        }
    )

    assert '"page_id":"regulatory_t_cell"' in result


def test_final_answer_tool_normalizes_formal_section_metadata(tmp_path: Path):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "Lint completed and found advisory issues.",
                "citations": [
                    {
                        "page_id": "regulatory_t_cell",
                        "section": "wiki/cell_types/regulatory_t_cell.md:81-90",
                        "note": "broken link finding",
                    }
                ],
                "confidence": "high",
                "knowledge_scope": "formal",
            }
        )
    )

    citation = result["citations"][0]
    assert citation["page_id"] == "regulatory_t_cell"
    assert citation["locator"] == "wiki/cell_types/regulatory_t_cell.md:81-90"
    assert "section" not in citation
    assert "note" not in citation


def test_final_answer_tool_accepts_attachment_grounding(tmp_path: Path):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "The attachment mentions regulatory T cells.",
                "citations": [
                    {
                        "attachment_id": "att_" + "a" * 32,
                        "original_name": "paper.pdf",
                        "section_locator": "Page 1",
                        "type": "thread_attachment",
                    }
                ],
                "confidence": "high",
                "knowledge_scope": "attachment",
            }
        )
    )

    assert result["knowledge_scope"] == "attachment"
    assert result["verification_level"] == "unvalidated"
    assert result["confidence"] == "low"
    assert result["citations"][0]["attachment_id"].startswith("att_")


def test_final_answer_tool_promotes_read_attachment_evidence(tmp_path: Path):
    tool = build_final_answer_tool(tmp_path)
    attachment_id = "att_" + "e" * 32
    record_attachment_read(attachment_id)

    result = json.loads(
        tool.invoke(
            {
                "answer": "The attachment mentions regulatory T cells.",
                "citations": [{"attachment_id": attachment_id, "locator": "Page 1"}],
                "confidence": "high",
                "knowledge_scope": "attachment",
            }
        )
    )

    assert result["verification_level"] == "evidence"
    assert result["confidence"] == "high"


def test_final_answer_tool_normalizes_provider_attachment_citations_with_omitted_ids(
    tmp_path: Path,
):
    """Provider display fields and omitted IDs must not abort an attachment answer."""

    tool = build_final_answer_tool(tmp_path)
    attachment_id = "att_" + "d" * 32

    result = json.loads(
        tool.invoke(
            {
                "answer": "The attachment describes several T-cell subsets.",
                "citations": [
                    {
                        "attachment_id": attachment_id,
                        "file": "paper.pdf",
                        "locator": "Page 1",
                        "quote": "T-cell subsets",
                    },
                    {"locator": "Page 2", "quote": "memory T cells"},
                    {"locator": "Page 3", "quote": "regulatory T cells"},
                ],
                "confidence": "high",
                "knowledge_scope": "attachment",
            }
        )
    )

    assert len(result["citations"]) == 3
    assert {citation["attachment_id"] for citation in result["citations"]} == {attachment_id}
    assert result["citations"][0]["section_locator"] == "Page 1"
    assert result["citations"][1]["section_locator"] == "Page 2"
    assert result["citations"][2]["section_locator"] == "Page 3"
    assert all("file" not in citation for citation in result["citations"])


def test_final_answer_tool_preserves_attachment_locator_as_section_locator(tmp_path: Path):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "The attachment mentions regulatory T cells.",
                "citations": [
                    {
                        "attachment_id": "att_" + "b" * 32,
                        "original_name": "paper.pdf",
                        "locator": "Page 2 (RESULTS)",
                    }
                ],
                "confidence": "high",
                "knowledge_scope": "attachment",
            }
        )
    )

    assert result["citations"][0]["section_locator"] == "Page 2 (RESULTS)"
    assert result["citations"][0]["type"] == "thread_attachment"


def test_final_answer_tool_normalizes_attachment_quote_without_leaking_extra_fields(
    tmp_path: Path,
):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "The attachment mentions regulatory T cells.",
                "citations": [
                    {
                        "attachment_id": "att_" + "c" * 32,
                        "original_name": "paper.pdf",
                        "quote": "Regulatory T cell identity was examined.",
                    }
                ],
                "confidence": "high",
                "knowledge_scope": "attachment",
            }
        )
    )

    citation = result["citations"][0]
    assert citation["section_locator"] == "Regulatory T cell identity was examined."
    assert citation["type"] == "thread_attachment"
    assert "quote" not in citation


def test_final_answer_tool_accepts_operational_lint_summary_without_citations(
    tmp_path: Path,
):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "Lint completed and reported project quality status.",
                "citations": [],
                "confidence": 0.82,
                "knowledge_scope": "lint",
            }
        )
    )

    assert result["confidence"] == "high"
    assert result["knowledge_scope"] == "general"
    assert result["verification_level"] == "unvalidated"
    assert result["validation_issues"] == []


def test_final_answer_tool_tolerates_unknown_operational_scope_and_confidence(
    tmp_path: Path,
):
    tool = build_final_answer_tool(tmp_path)

    result = json.loads(
        tool.invoke(
            {
                "answer": "The Agent completed an operational status check.",
                "citations": [],
                "confidence": "confident",
                "knowledge_scope": "project quality",
            }
        )
    )

    assert result["confidence"] == "medium"
    assert result["knowledge_scope"] == "general"


def test_ingest_tool_uses_durable_agent_run_as_cancellation_authority(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, str] = {}
    source_path = tmp_path / "source.txt"
    source_path.write_text("FOXP3 is a regulatory T-cell marker.", encoding="utf-8")
    source = SourceRegistry(tmp_path).register(source_path, source_type="paper")
    snapshot = KnowledgePipelineHarness(tmp_path).capture_snapshot(
        task_type=PipelineTaskType.INGEST,
        run_id="model-task-id",
    )

    class FakeIngestService:
        def __init__(self, project_root: Path):
            assert project_root == tmp_path.resolve()

        def prepare_change_set(
            self,
            source_id: str,
            run_id: str,
            *,
            cancellation_id: str,
            agent_draft_run_id: str,
            revision_id: str | None = None,
            parent_change_set_id: str | None = None,
            parent_revision_id: str | None = None,
        ):
            captured.update(
                source_id=source_id,
                run_id=run_id,
                cancellation_id=cancellation_id,
                agent_draft_run_id=agent_draft_run_id,
            )
            return SimpleNamespace(
                snapshot_id=snapshot.snapshot_id,
                model_dump_json=lambda: '{"change_set_id":"cs-test"}',
            )

    monkeypatch.setattr("cellwiki.agent.tools.IngestService", FakeIngestService)
    prepare = build_ingest_tools(tmp_path)[0]

    # The model controls run_id, so it must never be able to redirect the
    # cancellation token away from the durable runtime-owned Agent run.
    with bind_agent_run("agent-run-durable"):
        prepare.invoke(
            {
                "source_id": source.source_id,
                "run_id": "model-task-id",
                "agent_draft_run_id": "draft-test",
            }
        )

    assert captured == {
        "source_id": source.source_id,
        "run_id": "model-task-id",
        "cancellation_id": "agent-run-durable",
        "agent_draft_run_id": "draft-test",
    }


def test_ingest_tool_returns_the_full_pipeline_snapshot(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "source.txt"
    source_path.write_text("FOXP3 is a regulatory T-cell marker.", encoding="utf-8")
    source = SourceRegistry(tmp_path).register(source_path, source_type="paper")
    snapshot = KnowledgePipelineHarness(tmp_path).capture_snapshot(
        task_type=PipelineTaskType.INGEST,
        run_id="snapshot-ingest-run",
    )

    class FakeIngestService:
        def __init__(self, project_root: Path):
            assert project_root == tmp_path.resolve()

        def prepare_change_set(
            self,
            source_id,
            run_id,
            *,
            cancellation_id,
            agent_draft_run_id: str,
            revision_id: str | None = None,
            parent_change_set_id: str | None = None,
            parent_revision_id: str | None = None,
        ):
            return SimpleNamespace(
                snapshot_id=snapshot.snapshot_id,
                model_dump_json=lambda: '{"change_set_id":"cs-snapshot"}',
            )

    monkeypatch.setattr("cellwiki.agent.tools.IngestService", FakeIngestService)
    prepare = build_ingest_tools(tmp_path)[0]

    payload = json.loads(
        prepare.invoke(
            {
                "source_id": source.source_id,
                "run_id": "snapshot-ingest-run",
                "agent_draft_run_id": "draft-snapshot",
            }
        )
    )

    assert payload["source_id"] == source.source_id
    assert payload["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert payload["snapshot"]["task_type"] == "ingest"
    assert "formal" in payload["snapshot"]["inventory"]


def test_ingest_tool_resolves_full_content_hash_alias_to_canonical_source_id(
    tmp_path: Path,
    monkeypatch,
):
    source_path = tmp_path / "source.txt"
    source_path.write_text("FOXP3 is a regulatory T-cell marker.", encoding="utf-8")
    source = SourceRegistry(tmp_path).register(source_path, source_type="paper")
    snapshot = KnowledgePipelineHarness(tmp_path).capture_snapshot(
        task_type=PipelineTaskType.INGEST,
        run_id="hash-alias-run",
    )
    captured: dict[str, str] = {}

    class FakeIngestService:
        def __init__(self, project_root: Path):
            assert project_root == tmp_path.resolve()

        def prepare_change_set(
            self,
            source_id,
            run_id,
            *,
            cancellation_id,
            agent_draft_run_id: str,
            revision_id: str | None = None,
            parent_change_set_id: str | None = None,
            parent_revision_id: str | None = None,
        ):
            captured.update(
                source_id=source_id,
                run_id=run_id,
                cancellation_id=cancellation_id,
            )
            return SimpleNamespace(
                snapshot_id=snapshot.snapshot_id,
                model_dump_json=lambda: '{"change_set_id":"cs-hash-alias"}',
            )

    monkeypatch.setattr("cellwiki.agent.tools.IngestService", FakeIngestService)
    prepare = build_ingest_tools(tmp_path)[0]
    full_hash_alias = "src_" + source.content_hash.removeprefix("sha256:")

    payload = json.loads(
        prepare.invoke(
            {
                "source_id": full_hash_alias,
                "run_id": "hash-alias-run",
                "agent_draft_run_id": "draft-hash",
            }
        )
    )

    assert captured["source_id"] == source.source_id
    assert payload["source_id"] == source.source_id
    assert payload["change_set"]["change_set_id"] == "cs-hash-alias"


def test_revision_tool_records_feedback_and_guides_next_extraction_step(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    class FakeRevision:
        revision_id = "revision-test"

        def model_dump(self, mode="json"):
            return {"revision_id": self.revision_id, "status": "ready"}

    class FakeRevisionService:
        def __init__(self, project_root, *, ingest):
            assert project_root == tmp_path.resolve()
            captured["ingest"] = ingest

        def request_revision(self, change_set_id, *, reviewer, comments):
            captured.update(change_set_id=change_set_id, reviewer=reviewer, comments=comments)
            return FakeRevision()

        def get(self, revision_id):
            return FakeRevision()

    monkeypatch.setattr("cellwiki.agent.tools.IngestRevisionService", FakeRevisionService)
    tools = {tool.name: tool for tool in build_ingest_tools(tmp_path)}

    payload = json.loads(
        tools["request_ingest_revision"].invoke(
            {
                "change_set_id": "cs-parent",
                "comments": ["Add the evidence locator."],
                "reviewer": "default-reviewer",
            }
        )
    )

    assert payload["revision"]["revision_id"] == "revision-test"
    assert captured["comments"] == ["Add the evidence locator."]
    assert captured["reviewer"] == "default-reviewer"
    assert captured["change_set_id"] == "cs-parent"
    assert "revision_id=revision-test" in payload["next_step"]
    assert "prepare_ingest_change_set" in payload["next_step"]
