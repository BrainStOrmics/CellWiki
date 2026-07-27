# =============================================================================
# 智能体工具测试 —— 验证智能体工具函数的正确性
# =============================================================================

import json
from pathlib import Path
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
    build_rebase_tool,
    build_ingest_tools,
    build_lint_tools,
    build_memory_tools,
    build_read_tools,
)
from cellwiki.config import Settings
from cellwiki.services.operations import bind_agent_run
from cellwiki.domain.contracts import ApprovalPolicy, PipelineTaskType
from cellwiki.services.pipeline import KnowledgePipelineHarness


def test_read_tools_use_page_ids_and_return_search_results(tmp_path: Path):
    pages = tmp_path / "wiki" / "cell_types"
    pages.mkdir(parents=True)
    (pages / "t_cell.md").write_text("# T Cell\n\nCD3D marker", encoding="utf-8")
    tools = {tool.name: tool for tool in build_read_tools(tmp_path)}

    result = tools["search_wiki"].invoke({"query": "CD3D", "limit": 5})
    status = json.loads(tools["get_project_status"].invoke({}))

    assert "t_cell" in result
    assert "CD3D" in result
    assert status["knowledge_version"].startswith("sha256:")
    assert status["approval_policy"] == "auto_all"


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


def test_subagents_never_receive_commit_tool(tmp_path: Path):
    read_tools = build_read_tools(tmp_path)
    specs = build_subagent_specs(
        "openai:test-model",
        read_tools,
        build_ingest_tools(tmp_path),
        lint_tools=build_lint_tools(tmp_path),
    )

    assert {spec["name"] for spec in specs} == {
        "general-purpose",
        "query-agent",
        "ingest-agent",
        "lint-agent",
    }
    for spec in specs:
        assert "commit_change_set" not in {tool.name for tool in spec["tools"]}


def test_lint_agent_cannot_bypass_snapshot_bound_project_status(tmp_path: Path):
    specs = build_subagent_specs(
        "openai:test-model",
        build_read_tools(tmp_path),
        build_ingest_tools(tmp_path),
        lint_tools=build_lint_tools(tmp_path),
    )

    lint_spec = next(spec for spec in specs if spec["name"] == "lint-agent")
    lint_tool_names = {tool.name for tool in lint_spec["tools"]}

    assert "run_broad_lint" in lint_tool_names
    assert "get_project_status" not in lint_tool_names
    assert "inspect_knowledge_quality" not in lint_tool_names
    assert "read_wiki_page" not in lint_tool_names


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


def test_coordinator_serializes_ingest_and_lint_delegation():
    assert "delegate exactly one specialist task" in SYSTEM_PROMPT
    assert "never launch parallel tasks" in SYSTEM_PROMPT
    assert "Reject wins; no publish" in SYSTEM_PROMPT


def test_default_harness_routes_external_research_through_broad_lint(
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
    assert names == {"general-purpose", "query-agent", "ingest-agent", "lint-agent"}
    lint_spec = next(spec for spec in specs if spec["name"] == "lint-agent")
    lint_tool_names = {tool.name for tool in lint_spec["tools"]}
    assert "run_broad_lint" in lint_tool_names
    assert "research_external_sources" not in lint_tool_names


def test_tool_boundary_rejects_generic_filesystem_calls():
    middleware = _CellWikiToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "call_blocked", "args": {"path": "secret"}}
    )

    result = middleware.wrap_tool_call(request, lambda _: pytest.fail("handler must not run"))

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "CellWiki tools" in result.content


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


def test_configured_agent_hides_generic_harness_tools_from_first_request(
    tmp_path: Path,
    monkeypatch,
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
        captured["tool_schema_chars"] = sum(
            len(json.dumps(schema, ensure_ascii=False, default=str))
            for schema in schemas
        )
        raise RequestCaptured

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

    assert captured["tool_names"] == {
        "commit_change_set",
        "rebase_change_set",
        "submit_agent_answer",
        "task",
    }
    assert captured["tool_choice"] in {None, "auto"}
    assert captured["message_chars"] < 6_500
    assert captured["tool_schema_chars"] < 2_500


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


def test_ingest_tool_uses_durable_agent_run_as_cancellation_authority(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, str] = {}
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
        ):
            captured.update(
                source_id=source_id,
                run_id=run_id,
                cancellation_id=cancellation_id,
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
        prepare.invoke({"source_id": "source-paper", "run_id": "model-task-id"})

    assert captured == {
        "source_id": "source-paper",
        "run_id": "model-task-id",
        "cancellation_id": "agent-run-durable",
    }


def test_ingest_tool_returns_the_full_pipeline_snapshot(tmp_path: Path, monkeypatch):
    snapshot = KnowledgePipelineHarness(tmp_path).capture_snapshot(
        task_type=PipelineTaskType.INGEST,
        run_id="snapshot-ingest-run",
    )

    class FakeIngestService:
        def __init__(self, project_root: Path):
            assert project_root == tmp_path.resolve()

        def prepare_change_set(self, source_id, run_id, *, cancellation_id):
            return SimpleNamespace(
                snapshot_id=snapshot.snapshot_id,
                model_dump_json=lambda: '{"change_set_id":"cs-snapshot"}',
            )

    monkeypatch.setattr("cellwiki.agent.tools.IngestService", FakeIngestService)
    prepare = build_ingest_tools(tmp_path)[0]

    payload = json.loads(prepare.invoke({"source_id": "source-paper", "run_id": "snapshot-ingest-run"}))

    assert payload["snapshot"]["snapshot_id"] == snapshot.snapshot_id
    assert payload["snapshot"]["task_type"] == "ingest"
    assert "formal" in payload["snapshot"]["inventory"]


def test_revision_tool_preserves_feedback_and_prepares_a_child_changeset(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}
    snapshot = KnowledgePipelineHarness(tmp_path).capture_snapshot(
        task_type=PipelineTaskType.INGEST,
        run_id="model-revision-run",
    )

    class FakeRevision:
        revision_id = "revision-test"

        def model_dump(self, mode="json"):
            return {"revision_id": self.revision_id, "status": "ready"}

    class FakeChangeSet:
        change_set_id = "cs-child"
        snapshot_id = snapshot.snapshot_id

        def model_dump(self, mode="json"):
            return {"change_set_id": self.change_set_id, "revision_id": "revision-test"}

    class FakeRevisionService:
        def __init__(self, project_root, *, ingest):
            assert project_root == tmp_path.resolve()
            captured["ingest"] = ingest

        def request_revision(self, change_set_id, *, reviewer, comments):
            captured.update(change_set_id=change_set_id, reviewer=reviewer, comments=comments)
            return FakeRevision()

        def prepare_revision(self, revision_id, *, run_id, cancellation_id):
            captured.update(revision_id=revision_id, run_id=run_id, cancellation_id=cancellation_id)
            return FakeChangeSet()

        def get(self, revision_id):
            return FakeRevision()

    monkeypatch.setattr("cellwiki.agent.tools.IngestRevisionService", FakeRevisionService)
    tools = {tool.name: tool for tool in build_ingest_tools(tmp_path)}

    with bind_agent_run("agent-run-revision"):
        payload = json.loads(
            tools["request_ingest_revision"].invoke(
                {
                    "change_set_id": "cs-parent",
                    "comments": ["Add the evidence locator."],
                    "reviewer": "default-reviewer",
                    "run_id": "model-revision-run",
                }
            )
        )

    assert payload["change_set"]["change_set_id"] == "cs-child"
    assert captured["comments"] == ["Add the evidence locator."]
    assert captured["cancellation_id"] == "agent-run-revision"
    assert payload["approval_policy"] == "auto_all"
    assert payload["requires_human_review"] is False
    assert payload["snapshot"]["snapshot_id"] == snapshot.snapshot_id
