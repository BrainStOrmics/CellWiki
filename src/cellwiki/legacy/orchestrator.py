# =============================================================================
# 编排器 —— 组合所有 CellWiki LangGraph 子图
# =============================================================================
# 将命令（ingest/query/lint/research）路由到相应的子图执行。
# 使用条件边（conditional_edges）根据命令类型动态分发到不同的处理节点。
# 定义于 MASTER_PLAN.md 第 4.6 节。
#
# 用法：
#     from cellwiki.orchestrator import build_orchestrator, run_command
#     result = run_command("ingest", {"source_path": "paper.pdf"})
#     result = run_command("query", {"question": "What are Treg markers?"})
#     result = run_command("lint", {"auto_fix": True})
# =============================================================================

"""Orchestrator: composes all CellWiki LangGraph subgraphs.

Routes commands (ingest/query/lint/research) to the appropriate subgraph.
Defined in MASTER_PLAN.md Section 4.6.

Usage:
    from cellwiki.orchestrator import build_orchestrator, run_command
    result = run_command("ingest", {"source_path": "paper.pdf"})
    result = run_command("query", {"question": "What are Treg markers?"})
    result = run_command("lint", {"auto_fix": True})
"""



# ---------------------------------------------------------------------------
# 构建并编译编排器 StateGraph
# 编排器是 CellWiki LangGraph 的顶层入口，根据命令类型将请求路由到
# 相应的子图：ingest（导入）、query（查询）、lint（Lint）、research（研究）。
# 每个路由节点实际上是一个子图调用，接收状态并返回结果。
# ---------------------------------------------------------------------------
def build_orchestrator():
    """Build and compile the orchestrator StateGraph."""
    from langgraph.graph import StateGraph, END
    from cellwiki.legacy.graphs.checkpointer import get_checkpointer
    from cellwiki.legacy.graphs.states import OrchestratorState

    # 创建状态图，OrchestratorState 定义了图中的状态结构
    workflow = StateGraph(OrchestratorState)

    # 路由函数：根据 state 中的 "command" 字段决定下一个节点
    def route_command(state: OrchestratorState) -> str:
        # 返回命令名称，用于条件边匹配
        return state.get("command", "unknown")

    # ---- 导入节点 ----
    # 调用 ingest_graph 子图处理论文导入
    def run_ingest_node(state: OrchestratorState) -> dict:
        from cellwiki.legacy.ingest_graph import run_ingest
        # 从 state 中提取命令参数
        args = state.get("command_args", {})
        result = run_ingest(
            source_path=args.get("source_path", ""),
            source_type=args.get("source_type", "paper"),
            no_review=args.get("no_review", False),
        )
        return {"result": result}

    # ---- 查询节点 ----
    # 调用 query_graph 子图处理用户查询
    def run_query_node(state: OrchestratorState) -> dict:
        from cellwiki.legacy.query_graph import run_query
        args = state.get("command_args", {})
        result = run_query(
            question=args.get("question", ""),
            max_tokens=args.get("max_tokens", 8000),
        )
        return {"result": result}

    # ---- Lint 节点 ----
    # 调用 lint_graph 子图进行知识库质量检查
    def run_lint_node(state: OrchestratorState) -> dict:
        from cellwiki.legacy.lint_graph import run_lint
        args = state.get("command_args", {})
        result = run_lint(
            auto_fix=args.get("auto_fix", True),
            max_iterations=args.get("max_iterations", 3),
        )
        return {"result": result}

    # ---- 研究节点 ----
    # 调用 research_graph 子图进行外部文献发现
    def run_research_node(state: OrchestratorState) -> dict:
        from cellwiki.legacy.research_graph import run_research
        args = state.get("command_args", {})
        result = run_research(
            gap=args.get("gap", {}),
            max_iterations=args.get("max_iterations", 3),
        )
        return {"result": result}

    # 添加节点（每个节点都是一个子图调用）
    workflow.add_node("ingest", run_ingest_node)
    workflow.add_node("query", run_query_node)
    workflow.add_node("lint", run_lint_node)
    workflow.add_node("research", run_research_node)
    # 路由节点本身不执行任何逻辑，仅作为条件边起点
    workflow.add_node("route_command", lambda state: {"command": state.get("command", "unknown")})

    # 设置入口点为路由函数
    workflow.set_entry_point("route_command")
    # 根据命令类型条件路由到不同的子图节点
    workflow.add_conditional_edges("route_command", route_command, {
        "ingest": "ingest",
        "query": "query",
        "lint": "lint",
        "research": "research",
    })

    # 所有子图执行完成后都到达 END
    workflow.add_edge("ingest", END)
    workflow.add_edge("query", END)
    workflow.add_edge("lint", END)
    workflow.add_edge("research", END)

    # 编译图，使用检查点器实现状态持久化
    return workflow.compile(checkpointer=get_checkpointer())


# ---------------------------------------------------------------------------
# 通过编排器运行 CellWiki 命令
# 便捷函数，构造初始状态并调用编排器图。
# ---------------------------------------------------------------------------
def run_command(command: str, args: dict = None):
    """Run a CellWiki command through the orchestrator."""
    graph = build_orchestrator()

    # 构造初始状态，包含命令名称和参数
    initial_state = {
        "command": command,
        "command_args": args or {},
        "result": {},
    }

    # 调用图执行
    return graph.invoke(initial_state)

