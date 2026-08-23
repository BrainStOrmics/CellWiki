# =============================================================================
# 子 Agent spec 注册表 + 独立白名单校验 + 顺序委托框架（阶段 7）
# =============================================================================
# v1 注册表为空：因此 build_delegation_tools 返回 []，任何 run 都不会暴露委托工具；
# 顺序委托框架函数保留并可直接测试（create_delegated_run），在注册表注入 spec 后启用。
# 每个 spec 必须显式声明 tool_whitelist（None 视为未声明 -> 校验失败；[] = 无工具），
# 且名称必须属于主白名单；权限域、结果契约、可选 model 一并记录。
# =============================================================================

"""Phase 7 hooks: subagent spec registry, standalone whitelist validation, delegation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence

from cellwiki.agent.executor import WHITELISTED_TOOL_NAMES

# 权限域枚举（v1 保守：只允许受限工作区工具）
PERMISSION_DOMAINS: frozenset[str] = frozenset(
    {
        "workspace_read",   # 只读浏览/搜索
        "workspace_edit",   # 文件编辑（写/改/删/重命名）
        "git_only",         # 仅 git status/diff/log
        "agent_confirm",    # 需要 ask_user_question 显式确认
    }
)

RESULT_CONTRACT_PLAIN_TEXT = "plain-text summary plus workspace-relative file path references"


@dataclass(frozen=True)
class SubagentSpec:
    """One delegation spec. tool_whitelist MUST be declared explicitly."""

    id: str
    version: str
    display_name: str
    description: str
    system_prompt_template: str = ""        # 可含 {workspace} 占位符
    tool_whitelist: list[str] | None = None  # None=未声明（非法）；[]=无工具
    permission_domain: str = "workspace_read"
    result_contract: str = RESULT_CONTRACT_PLAIN_TEXT
    max_run_seconds: int | None = None
    model: str | None = None


class SubagentRegistry:
    """Ordered spec registry keyed by spec id (v1 ships empty)."""

    def __init__(self, specs: Sequence[SubagentSpec] | None = None) -> None:
        self._specs: dict[str, SubagentSpec] = {}
        for spec in specs or ():
            validate_spec(spec)
            if spec.id in self._specs:
                raise ValueError(f"duplicate subagent spec id: {spec.id}")
            self._specs[spec.id] = spec

    def list(self) -> list[SubagentSpec]:
        return list(self._specs.values())

    def get(self, spec_id: str) -> SubagentSpec | None:
        return self._specs.get(spec_id)

    def has(self, spec_id: str) -> bool:
        return spec_id in self._specs


def validate_spec(spec: SubagentSpec) -> None:
    """独立白名单校验：显式工具白名单 + 名称在主白名单内 + 权限域合法。"""
    if not spec.id or not spec.id.isidentifier():
        raise ValueError("subagent spec id must be a non-empty identifier")
    if spec.tool_whitelist is None:
        raise ValueError(
            f"subagent spec {spec.id!r} must declare an explicit tool whitelist "
            "([] for no tools)"
        )
    unknown = [
        name for name in spec.tool_whitelist if name not in WHITELISTED_TOOL_NAMES
    ]
    if unknown:
        raise ValueError(
            f"subagent spec {spec.id!r} whitelists tools outside the main "
            f"whitelist: {sorted(unknown)}"
        )
    if spec.permission_domain not in PERMISSION_DOMAINS:
        raise ValueError(
            f"subagent spec {spec.id!r} has unknown permission domain: "
            f"{spec.permission_domain!r}"
        )


def build_delegation_tools(registry: SubagentRegistry | None = None) -> list[Any]:
    """Return delegation tools for the registry; empty registry exposes none."""
    registry = registry or SubagentRegistry()
    if not registry.list():
        return []
    # 顺序委托框架：注册表非空后，这里才注册 delegate_subtask 工具（v1 不可达）。
    return []


def create_delegated_run(
    registry: SubagentRegistry,
    spec_id: str,
    *,
    parent_run_id: str,
    thread_id: str,
    project_id: str,
    goal: str,
) -> dict[str, str | None]:
    """顺序委托框架：为存在的 spec 创建一个 parent_run_id 关联的子 run 记录。

    run 记录本身由 AgentRuntimeManager 持久化；这里完成 spec 解析与参数核验。
    """
    spec = registry.get(spec_id)
    if spec is None:
        raise KeyError(f"unknown subagent spec: {spec_id}")
    validate_spec(spec)
    now = datetime.now(UTC).isoformat()
    return {
        "spec_id": spec.id,
        "parent_run_id": parent_run_id,
        "thread_id": thread_id,
        "project_id": project_id,
        "goal": goal[:2_000],
        "tool_whitelist": ",".join(spec.tool_whitelist or []),
        "permission_domain": spec.permission_domain,
        "result_contract": spec.result_contract,
        "created_at": now,
    }


__all__ = [
    "PERMISSION_DOMAINS",
    "RESULT_CONTRACT_PLAIN_TEXT",
    "SubagentRegistry",
    "SubagentSpec",
    "build_delegation_tools",
    "create_delegated_run",
    "validate_spec",
]
