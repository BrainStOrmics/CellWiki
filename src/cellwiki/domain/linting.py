# =============================================================================
# Lint 合约 —— 确定性检查、审查 UI 和修复提案的共享模型
# =============================================================================
# 定义 lint 检查的严重级别、分类和发现项（LintFinding）的稳定数据结构，
# 支持自动修复标记和跨版本的去重追踪（通过 stable_id 哈希）。
# =============================================================================

"""Stable lint contracts used by deterministic checks, review UI, and fix proposals."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import Field

from cellwiki.domain.contracts import ContractModel


# ---- Lint 级别 ----
# L0 = 阻塞级别（阻止发布）
# L1 = 警告级别（建议修复）
# L2 = 信息级别（仅供参考）
class LintLevel(str, Enum):
    L0 = "L0"   # 阻塞级别，必须修复
    L1 = "L1"   # 警告级别，建议修复
    L2 = "L2"   # 信息级别，仅供参考


# ---- Lint 严重程度 ----
class LintSeverity(str, Enum):
    ERROR = "error"       # 错误
    WARNING = "warning"   # 警告
    INFO = "info"         # 信息


# ---- Lint 发现项状态 ----
class LintFindingStatus(str, Enum):
    OPEN = "open"           # 未处理
    RESOLVED = "resolved"   # 已解决
    IGNORED = "ignored"     # 已忽略


# ---- Lint 发现项 ----
# 质量检查的单个发现项，包含级别、严重程度、分类、目标等。
# 支持自动修复标记（auto_fixable）和修复建议（suggested_operation）。
# 使用 stable_id 方法生成基于内容的唯一 ID，用于跨版本去重。
class LintFinding(ContractModel):
    finding_id: str                                   # 发现项唯一标识
    level: LintLevel                                  # 级别（L0/L1/L2）
    severity: LintSeverity                            # 严重程度
    category: str                                     # 分类（如 "structure", "reference"）
    target_id: str                                    # 目标 ID（如细胞类型名称）
    locator: str                                      # 定位器（如文件路径+行号）
    message: str                                      # 描述消息
    evidence: list[dict[str, Any]] = Field(default_factory=list)  # 证据列表
    blocking: bool = False                            # 是否阻塞发布
    auto_fixable: bool = False                         # 是否可自动修复
    suggested_operation: dict[str, Any] | None = None  # 修复建议
    status: LintFindingStatus = LintFindingStatus.OPEN  # 当前状态
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 首次发现时间
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))   # 最近发现时间

    # 生成基于内容的稳定 ID（用于跨版本去重）
    @classmethod
    def stable_id(
        cls,
        *,
        level: LintLevel,
        category: str,
        target_id: str,
        locator: str,
    ) -> str:
        material = f"{level.value}\0{category}\0{target_id}\0{locator}"
        return f"lint_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"

