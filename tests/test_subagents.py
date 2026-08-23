# =============================================================================
# 阶段 7 验证：子 Agent spec 注册表、独立白名单校验、顺序委托框架
# =============================================================================

from __future__ import annotations

import pytest

from cellwiki.agent.executor import WHITELISTED_TOOL_NAMES
from cellwiki.services.subagents import (
    RESULT_CONTRACT_PLAIN_TEXT,
    SubagentRegistry,
    SubagentSpec,
    build_delegation_tools,
    create_delegated_run,
    validate_spec,
)


def _valid_spec() -> SubagentSpec:
    return SubagentSpec(
        id="reader",
        version="1.0.0",
        display_name="Reader",
        description="只读浏览与搜索",
        tool_whitelist=["ls", "glob", "grep", "read_file"],
        permission_domain="workspace_read",
        result_contract=RESULT_CONTRACT_PLAIN_TEXT,
    )


def test_empty_registry_exposes_no_delegation_tools():
    # v1 注册表为空：任何 run 都不暴露委托工具
    assert SubagentRegistry().list() == []
    assert build_delegation_tools() == []
    assert build_delegation_tools(SubagentRegistry()) == []


def test_spec_requires_explicit_tool_whitelist():
    with pytest.raises(ValueError, match="explicit tool whitelist"):
        validate_spec(
            SubagentSpec(
                id="x", version="1", display_name="X", description="none"
            )
        )


def test_spec_rejects_tools_outside_main_whitelist():
    with pytest.raises(ValueError, match="outside the main whitelist"):
        validate_spec(
            SubagentSpec(
                id="x",
                version="1",
                display_name="X",
                description="bad",
                tool_whitelist=["bash", "execute"],
            )
        )


def test_empty_tool_whitelist_is_allowed_as_no_tools():
    spec = SubagentSpec(
        id="dry", version="1", display_name="Dry", description="no tools",
        tool_whitelist=[],
    )
    validate_spec(spec)
    assert spec.tool_whitelist == []


def test_unknown_permission_domain_rejected():
    with pytest.raises(ValueError, match="permission domain"):
        validate_spec(
            SubagentSpec(
                id="x", version="1", display_name="X", description="bad",
                tool_whitelist=[], permission_domain="everything",
            )
        )


def test_registry_keys_by_id_and_rejects_duplicates():
    registry = SubagentRegistry([_valid_spec()])
    assert registry.has("reader") and registry.get("reader") is not None
    assert registry.get("missing") is None
    with pytest.raises(ValueError, match="duplicate subagent spec id"):
        SubagentRegistry([_valid_spec(), _valid_spec()])


def test_sequential_delegation_framework_creates_parent_linked_record():
    registry = SubagentRegistry([_valid_spec()])
    record = create_delegated_run(
        registry,
        "reader",
        parent_run_id="run_parent",
        thread_id="thread_1",
        project_id="cellwiki",
        goal="先只读浏览一遍 FOXP3 页面",
    )
    assert record["parent_run_id"] == "run_parent"
    assert record["spec_id"] == "reader"
    assert record["tool_whitelist"] == "ls,glob,grep,read_file"
    assert record["permission_domain"] == "workspace_read"
    with pytest.raises(KeyError):
        create_delegated_run(
            registry, "missing", parent_run_id="r", thread_id="t", project_id="p", goal="g"
        )


def test_whitelist_constant_covers_runtime_boundary():
    assert "ask_user_question" in WHITELISTED_TOOL_NAMES
    assert "read_attachment" in WHITELISTED_TOOL_NAMES
    assert "bash" not in WHITELISTED_TOOL_NAMES
    assert "execute" not in WHITELISTED_TOOL_NAMES
