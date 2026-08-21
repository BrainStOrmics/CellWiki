"""Phase B contract tests: ingest-agent tool surface, subagent spec, and staging loop."""
import json

from cellwiki.agent.app import build_subagent_specs
from cellwiki.agent.tools import (
    build_ingest_agent_tools,
    build_ingest_tools,
    build_read_tools,
)
from cellwiki.services.sources import SourceRegistry


def _tool_map(tools):
    return {tool.name: tool for tool in tools}


def test_ingest_agent_tool_surface_is_exactly_four_governed_tools(tmp_path):
    tools = build_ingest_agent_tools(tmp_path)
    assert {tool.name for tool in tools} == {
        "read_source_full",
        "read_existing_knowledge",
        "submit_extraction_draft",
        "revise_evidence",
    }
    by_name = _tool_map(tools)
    assert "source_id" in by_name["read_source_full"].args
    assert {"source_id", "payload"} <= set(by_name["submit_extraction_draft"].args)
    assert {"source_id", "draft_run_id", "rewrites"} <= set(by_name["revise_evidence"].args)


def test_ingest_agent_subagent_spec_is_declared_with_governed_tools(tmp_path):
    ingest_tools = build_ingest_agent_tools(tmp_path)
    read_tools = build_read_tools(tmp_path)
    specs = build_subagent_specs("fake-model", read_tools, ingest_tools)
    by_name = {spec["name"]: spec for spec in specs}
    assert "ingest-agent" in by_name
    spec = by_name["ingest-agent"]
    assert {tool.name for tool in spec["tools"]} == {
        "read_source_full",
        "read_existing_knowledge",
        "submit_extraction_draft",
        "revise_evidence",
    }
    assert spec["middleware"]
    assert "Never use paper-internal cluster identifiers" in spec["system_prompt"]


def test_prepare_ingest_tool_accepts_agent_draft_run_id(tmp_path):
    ingest_tools = _tool_map(build_ingest_tools(tmp_path))
    tool = ingest_tools["prepare_ingest_change_set"]
    assert {"source_id", "run_id", "agent_draft_run_id"} <= set(tool.args)


def test_staged_draft_flows_through_revise_loop_into_changeset(tmp_path):
    source_file = tmp_path / "paper.md"
    source_file.write_text(
        "# Test\n\nTumor tissue contained LRRC15+ fibroblasts with high ENTPD1 expression.\n\n"
        "Regulatory T cells suppress proliferation.\n",
        encoding="utf-8",
    )
    source = SourceRegistry(tmp_path).register(source_file, source_type="paper")

    tools = _tool_map(build_ingest_agent_tools(tmp_path))
    payload = {
        "paper_info": {"title": "Test"},
        "cell_types": [
            {
                "name": "Regulatory T cells",
                "standard_name": "regulatory_t_cells",
                "functions": [
                    {"description": "suppresses proliferation", "evidence": "Regulatory cells suppress immune activation"}
                ],
            }
        ],
    }
    submitted = json.loads(tools["submit_extraction_draft"].invoke({"source_id": source.source_id, "payload": payload, "run_id": "draft_1"}))
    assert submitted["status"] == "draft_saved"
    assert any(item["item_id"] == "cell_0.function_0" for item in submitted["ungrounded_evidence"])

    revised = json.loads(
        tools["revise_evidence"].invoke(
            {
                "source_id": source.source_id,
                "draft_run_id": "draft_1",
                "rewrites": [{"item_id": "cell_0.function_0", "evidence": "Regulatory T cells suppress proliferation"}],
            }
        )
    )
    assert revised["status"] == "draft_revised"
    assert revised["applied_rewrites"] == ["cell_0.function_0"]
    assert revised["remaining_ungrounded_evidence"] == []

    prepare_tool = _tool_map(build_ingest_tools(tmp_path))["prepare_ingest_change_set"]
    prepared = json.loads(
        prepare_tool.invoke(
            {"source_id": source.source_id, "run_id": "final_1", "agent_draft_run_id": "draft_1"}
        )
    )
    change_set = prepared["change_set"]
    assert change_set["operations"][0]["payload"]["cell_types"][0]["standard_name"] == "regulatory_t_cells"
    assert change_set["evidence"]
    # Cluster identifiers cannot leak into durable names even from drafts.
    assert all(c["standard_name"] != "c01" for c in change_set["operations"][0]["payload"]["cell_types"])
