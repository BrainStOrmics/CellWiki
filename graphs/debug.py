"""State debugging and visualization tools for CellWiki LangGraph.

Provides:
- State snapshot printing with pretty formatting
- Graph visualization (text-based and mermaid)
- State history replay
- Node execution tracing
- Memory usage tracking

Usage:
    from graphs.debug import StateDebugger, visualize_graph, trace_execution
    
    debugger = StateDebugger()
    debugger.print_state(state_dict)
    visualize_graph(ingest_graph.get_graph())
    trace_execution(graph, initial_state)
"""

import json
import time
import os
import sys
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# === Pretty State Printer ===

class StateDebugger:
    """Debug utilities for LangGraph state inspection."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.execution_log: list[dict] = []
        self.start_time = None

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
                # Truncate long text fields
                if isinstance(value, str) and len(value) > 100:
                    print(f"{prefix}  {key}: \"{value[:80]}...\" ({len(value)} chars)")
                else:
                    print(f"{prefix}  {key}: {repr(value)[:100]}")
            elif key in ("analysis", "existing_pages", "selected_pages"):
                # Summarize complex dicts/lists
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
                    # Pretty print JSON
                    formatted = json.dumps(value, indent=2, ensure_ascii=False, default=str)
                    for line in formatted.split("\n"):
                        print(f"{prefix}    {line}")
            else:
                print(f"{prefix}  {key}: {value}")

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

    def start_timing(self):
        """Start execution timing."""
        self.start_time = time.time()

    def end_timing(self) -> float:
        """End timing and return elapsed seconds."""
        if self.start_time is None:
            return 0
        elapsed = time.time() - self.start_time
        self.start_time = None
        return elapsed


# === Graph Visualization ===

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


def _to_mermaid(graph_obj) -> str:
    """Convert graph to mermaid flowchart syntax."""
    lines = ["```mermaid", "flowchart TD"]

    try:
        nodes = graph_obj.nodes
        edges = graph_obj.edges

        for node_id, node in nodes.items():
            label = node_id.replace("_", " ").title()
            lines.append(f"    {node_id}[\"{label}\"]")

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


def _to_ascii(graph_obj) -> str:
    """Convert graph to ASCII art visualization."""
    lines = []
    lines.append("=" * 60)

    try:
        nodes = graph_obj.nodes
        edges = graph_obj.edges

        # Build adjacency
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

        # Find root nodes (no parents or __start__)
        roots = [n for n in nodes if not parents.get(n) or n == "__start__"]
        if not roots:
            roots = [next(iter(nodes))]

        # Print tree-like structure
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


# === Execution Tracer ===

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

    # Print initial state
    print(f"\n[INITIAL STATE]")
    debugger.print_state(initial_state)

    try:
        config = {"configurable": {"thread_id": thread_id}}

        # Use LangGraph's astream_events or stream for tracing
        stream = graph.stream(initial_state, config=config)

        step = 0
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

        # Try to get final state
        try:
            final_state = graph.get_state(config=config)
            print(f"\n[FINAL STATE]")
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


def _safe_repr(value: Any, max_len: int = 200) -> str:
    """Safely represent a value for logging."""
    try:
        s = repr(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except Exception:
        return f"<unrepresentable: {type(value).__name__}>"


# === Memory Usage ===

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
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "percent": process.memory_percent(),
        }
    except ImportError:
        # Fallback: read /proc/meminfo
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        return {"rss_mb": round(rss_kb / 1024, 1), "vms_mb": 0, "percent": 0}
        except Exception:
            pass
    return {"error": "Could not get memory usage"}


# === State History Visualizer ===

def visualize_state_history(thread_id: str, db_path: str = None) -> str:
    """Create a timeline visualization of state history for a thread.
    
    Args:
        thread_id: The thread ID to visualize
        db_path: Path to checkpoint database
    
    Returns:
        Timeline string
    """
    from graphs.checkpointer import get_thread_history

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
            lines.append(f"   │")
            lines.append(f"   ▼")

    lines.append("=" * 60)
    return "\n".join(lines)

