# =============================================================================
# graphs 包 —— CellWiki LangGraph 状态、节点和调试工具
# =============================================================================
# 本包定义所有 LangGraph 子图所需的共享基础设施：
# - states.py: 所有 State 模型（WikiState, IngestState, QueryState 等）
# - nodes.py: 共享节点函数
# - checkpointer.py: 基于 SQLite 的检查点存储和线程管理
# - debug.py: 状态调试、图谱可视化和执行追踪
# 所有子图（ingest_graph, query_graph, lint_graph, research_graph, orchestrator）
# 都依赖本包提供的类型和工具。
# =============================================================================

"""LangGraph state, node, and debug definitions for CellWiki.

Modules:
- states.py: All State models (WikiState, IngestState, QueryState, etc.)
- nodes.py: Shared node functions
- checkpointer.py: SQLite-based checkpoint storage and memory management
- debug.py: State debugging, graph visualization, and execution tracing
"""

from cellwiki.legacy.graphs.states import (
    WikiState,
    IngestState,
    QueryState,
    LintState,
    ResearchState,
    OrchestratorState,
    merge_dict,
    append_list,
)

from cellwiki.legacy.graphs.checkpointer import (
    get_checkpointer,
    get_db_path,
    list_threads,
    get_thread_history,
    delete_thread,
    cleanup_old_threads,
    get_db_stats,
)

from cellwiki.legacy.graphs.debug import (
    StateDebugger,
    visualize_graph,
    trace_execution,
    get_memory_usage,
    visualize_state_history,
)

__all__ = [
    # States
    "WikiState",
    "IngestState",
    "QueryState",
    "LintState",
    "ResearchState",
    "OrchestratorState",
    "merge_dict",
    "append_list",
    # Checkpointer
    "get_checkpointer",
    "get_db_path",
    "list_threads",
    "get_thread_history",
    "delete_thread",
    "cleanup_old_threads",
    "get_db_stats",
    # Debug
    "StateDebugger",
    "visualize_graph",
    "trace_execution",
    "get_memory_usage",
    "visualize_state_history",
]

