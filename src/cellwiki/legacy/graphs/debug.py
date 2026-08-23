# =============================================================================
# 状态调试和可视化工具 —— CellWiki LangGraph 调试工具集
# =============================================================================
# 提供：
# - 状态快照打印（格式化输出）
# - 图谱可视化（文本和 Mermaid 两种格式）
# - 状态历史回放
# - 节点执行追踪
# - 内存使用追踪
# 用于开发和调试 LangGraph 子图执行过程。
# =============================================================================

"""State debugging and visualization tools for CellWiki LangGraph.

Provides:
- State snapshot printing with pretty formatting
- Graph visualization (text-based and mermaid)
- State history replay
- Node execution tracing
- Memory usage tracking

Usage:
    from cellwiki.legacy.graphs.debug import StateDebugger, visualize_graph, trace_execution

    debugger = StateDebugger()
    debugger.print_state(state_dict)
    visualize_graph(ingest_graph.get_graph())
    trace_execution(graph, initial_state)
"""

import json
import time
from typing import Any


# ============================================================================
# StateDebugger —— 状态调试器
# 用于 LangGraph 状态检查的调试工具，提供格式化输出、差异比较和计时功能
# ============================================================================

class StateDebugger:
    """Debug utilities for LangGraph state inspection."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose                    # 是否显示详细信息
        self.execution_log: list[dict] = []       # 执行日志
        self.start_time = None                    # 计时起始时间

    # 格式化打印状态字典
    # 对长文本字段（paper_text）截断显示前 80 字符
    # 对复杂对象（dict/list）显示摘要信息
    # 超过 120 字符的 JSON 字符串截断显示
    def print_state(self, state: dict, prefix: str = "", show_full: bool = False):
        """Pretty-print a state dictionary.

        Args:
            state: The state dict to print
            prefix: Indentation prefix
            show_full: If False, truncate long string values
        """
        if not state:
            print(f"{prefix}  (empty state)")
            return

        for key, value in state.items():
            if key in ("paper_text",):
                # 截断长文本字段
                if isinstance(value, str) and len(value) > 100:
                    print(f"{prefix}  {key}: \"{value[:80]}...\" ({len(value)} chars)")
                else:
                    print(f"{prefix}  {key}: {repr(value)[:100]}")
            elif key in ("analysis", "existing_pages", "selected_pages"):
                # 对复杂 dict/list 显示摘要
                if isinstance(value, dict):
                    print(f"{prefix}  {key}: dict with {len(value)} keys: {list(value.keys())[:5]}")
                elif isinstance(value, list):
                    print(f"{prefix}  {key}: list with {len(value)} items")
                else:
                    print(f"{prefix}  {key}: {repr(value)[:80]}")
            elif isinstance(value, (list, dict)):
                json_str = json.dumps(value, ensure_ascii=False, default=str)
                if len(json_str) > 120 and not show_full:
                    print(f"{prefix}  {key}: {json_str[:100]}... ({len(json_str)} chars)")
                else:
                    # 格式化打印 JSON
                    formatted = json.dumps(value, indent=2, ensure_ascii=False, default=str)
                    for line in formatted.split("\n"):
                        print(f"{prefix}    {line}")
            else:
                print(f"{prefix}  {key}: {value}")

    # 打印两个状态快照之间的差异
    # 对文本字段显示长度变化，对列表显示条目数变化，对字典显示键数变化
    def print_state_diff(self, before: dict, after: dict, prefix: str = ""):
        """Print differences between two state snapshots.

        Args:
            before: Previous state
            after: New state
            prefix: Indentation prefix
        """
        all_keys = set(list(before.keys()) + list(after.keys()))
        changes = []

        for key in sorted(all_keys):
            old_val = before.get(key)
            new_val = after.get(key)

            if old_val != new_val:
                if key in ("paper_text", "content"):
                    old_len = len(str(old_val)) if old_val else 0
                    new_len = len(str(new_val)) if new_val else 0
                    changes.append((key, f"changed ({old_len} -> {new_len} chars)"))
                elif isinstance(old_val, list) and isinstance(new_val, list):
                    changes.append((key, f"changed ({len(old_val)} -> {len(new_val)} items)"))
                elif isinstance(old_val, dict) and isinstance(new_val, dict):
                    changes.append((key, f"changed ({len(old_val)} -> {len(new_val)} keys)"))
                else:
                    changes.append((key, f"{old_val!r} -> {new_val!r}"))

        if not changes:
            print(f"{prefix}  (no changes)")
            return

        for key, desc in changes:
            print(f"{prefix}  ~ {key}: {desc}")

    # 开始计时
    def start_timing(self):
        """Start execution timing."""
        self.start_time = time.time()

    # 结束计时，返回已用秒数
    def end_timing(self) -> float:
        """End timing and return elapsed seconds."""
        if self.start_time is None:
            return 0
        elapsed = time.time() - self.start_time
        self.start_time = None
        return elapsed


# ============================================================================
# 图谱可视化
# ============================================================================

# 将 LangGraph 可视化为文本或 Mermaid 图
def visualize_graph(graph, output_format: str = "text") -> str:
    """Visualize a LangGraph as text or mermaid diagram.

    Args:
        graph: A compiled LangGraph
        output_format: "text" for ASCII art, "mermaid" for mermaid syntax

    Returns:
        Visualization string
    """
    try:
        graph_obj = graph.get_graph()
    except Exception:
        return "Could not extract graph structure"

    if output_format == "mermaid":
        return _to_mermaid(graph_obj)
    else:
        return _to_ascii(graph_obj)


# 转换为 Mermaid 流程图语法
def _to_mermaid(graph_obj) -> str:
    """Convert graph to mermaid flowchart syntax."""
    lines = ["```mermaid", "flowchart TD"]

    try:
        nodes = graph_obj.nodes
        edges = graph_obj.edges

        # 添加节点
        for node_id, node in nodes.items():
            label = node_id.replace("_", " ").title()
            lines.append(f"    {node_id}[\"{label}\"]")

        # 添加边（如果存在条件边，显示条件标签）
        for edge in edges:
            source = edge.source
            target = edge.target
            condition = getattr(edge, "condition", None)
            if condition:
                lines.append(f"    {source} -- \"{condition}\" --> {target}")
            else:
                lines.append(f"    {source} --> {target}")
    except Exception:
        lines.append("    %% Could not parse graph structure")

    lines.append("```")
    return "\n".join(lines)


# 转换为 ASCII 艺术图（树形结构）
def _to_ascii(graph_obj) -> str:
    """Convert graph to ASCII art visualization."""
    lines = []
    lines.append("=" * 60)

    try:
        nodes = graph_obj.nodes
        edges = graph_obj.edges

        # 构建邻接表
        children = {}
        parents = {}
        for node_id in nodes:
            children[node_id] = []
            parents[node_id] = []

        for edge in edges:
            source = edge.source
            target = edge.target
            if source in children:
                children[source].append(target)
            if target in parents:
                parents[target].append(source)

        # 找到根节点（没有父节点或 __start__）
        roots = [n for n in nodes if not parents.get(n) or n == "__start__"]
        if not roots:
            roots = [next(iter(nodes))]

        # 递归打印树形结构
        visited = set()

        def print_node(node_id: str, indent: int = 0):
            if node_id in visited:
                lines.append("  " * indent + f"↻ {node_id} (already shown)")
                return
            visited.add(node_id)

            label = node_id.replace("_", " ").title()
            child_count = len(children.get(node_id, []))

            if indent == 0:
                lines.append(f"▶ {label} ({child_count} children)")
            else:
                lines.append("  " * indent + f"└── {label} ({child_count} children)")

            # 最多显示 5 个子节点，其余用省略号表示
            for child in children.get(node_id, [])[:5]:
                print_node(child, indent + 1)

            if child_count > 5:
                lines.append("  " * (indent + 1) + f"└── ... and {child_count - 5} more")

        for root in roots[:3]:
            print_node(root)

    except Exception as e:
        lines.append(f"  Error visualizing graph: {e}")

    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================================
# 执行追踪器
# 逐步执行图并打印每个步骤的状态变化
# ============================================================================

def trace_execution(graph, initial_state: dict, thread_id: str = "debug") -> dict:
    """Execute a graph with full state tracing at each step.

    Args:
        graph: Compiled LangGraph
        initial_state: Initial state dict
        thread_id: Thread ID for checkpointing

    Returns:
        Final result dict with execution log attached
    """
    debugger = StateDebugger()
    execution_log = []
    debugger.start_timing()

    print("\n" + "=" * 60)
    print("EXECUTION TRACE")
    print("=" * 60)

    # 打印初始状态
    print("\n[INITIAL STATE]")
    debugger.print_state(initial_state)

    step = 0
    try:
        config = {"configurable": {"thread_id": thread_id}}

        # 使用 LangGraph 的 stream 进行追踪
        stream = graph.stream(initial_state, config=config)

        for chunk in stream:
            step += 1
            elapsed = time.time() - debugger.start_time

            print(f"\n[STEP {step}] (t={elapsed:.2f}s)")
            for node_name, node_output in chunk.items():
                print(f"  Node: {node_name}")
                debugger.print_state(node_output, prefix="    ")

            execution_log.append({
                "step": step,
                "elapsed": round(elapsed, 2),
                "chunk": {k: _safe_repr(v) for k, v in chunk.items()},
            })

        # 尝试获取最终状态
        try:
            final_state = graph.get_state(config=config)
            print("\n[FINAL STATE]")
            debugger.print_state(final_state.values)
        except Exception:
            pass

    except Exception as e:
        print(f"\n⚠ Execution error: {e}")
        execution_log.append({"error": str(e)})

    elapsed = debugger.end_timing()
    print(f"\n{'=' * 60}")
    print(f"Total execution time: {elapsed:.2f}s")
    print(f"Steps executed: {step}")
    print(f"{'=' * 60}")

    return {
        "execution_log": execution_log,
        "total_time": elapsed,
        "steps": step,
    }


# 安全地表示一个值用于日志（防止不可序列化的对象）
def _safe_repr(value: Any, max_len: int = 200) -> str:
    """Safely represent a value for logging."""
    try:
        s = repr(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except Exception:
        return f"<unrepresentable: {type(value).__name__}>"


# ============================================================================
# 内存使用追踪
# 使用 psutil 获取当前进程内存使用情况
# 如果 psutil 不可用，尝试从 /proc/self/status 读取（Linux 回退方案）
# ============================================================================

def get_memory_usage() -> dict:
    """Get current process memory usage.

    Returns:
        Dict with RSS, VMS, percent
    """
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem = process.memory_info()
        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),      # 物理内存 (MB)
            "vms_mb": round(mem.vms / 1024 / 1024, 1),       # 虚拟内存 (MB)
            "percent": process.memory_percent(),               # 内存占比 (%)
        }
    except ImportError:
        # 回退方案：读取 /proc/self/status（仅 Linux）
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        return {"rss_mb": round(rss_kb / 1024, 1), "vms_mb": 0, "percent": 0}
        except Exception:
            pass
    return {"error": "Could not get memory usage"}


# ============================================================================
# 状态历史可视化
# 为指定线程创建时间线形式的可视化历史
# ============================================================================

def visualize_state_history(thread_id: str, db_path: str = None) -> str:
    """Create a timeline visualization of state history for a thread.

    Args:
        thread_id: The thread ID to visualize
        db_path: Path to checkpoint database

    Returns:
        Timeline string
    """
    from cellwiki.legacy.graphs.checkpointer import get_thread_history

    history = get_thread_history(thread_id, db_path)

    if not history:
        return f"No checkpoint history found for thread: {thread_id}"

    lines = []
    lines.append(f"\nState History: {thread_id}")
    lines.append("=" * 60)

    for i, entry in enumerate(history):
        ts = entry.get("created_at", "unknown")
        node = entry.get("node", "unknown")
        status = entry.get("status", "unknown")

        icon = "▶" if i == 0 else "  "
        if i == len(history) - 1:
            icon = "▶"

        lines.append(f"{icon} [{i+1}] {ts}")
        lines.append(f"   Node: {node}")
        lines.append(f"   Status: {status}")
        if i < len(history) - 1:
            lines.append("   │")
            lines.append("   ▼")

    lines.append("=" * 60)
    return "\n".join(lines)

