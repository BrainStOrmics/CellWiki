# =============================================================================
# 检查点管理 —— LangGraph 持久化的检查点配置
# =============================================================================
# 处理基于 SQLite 的检查点存储，支持跨会话恢复。
# 提供线程管理、状态历史和清理功能。
# 如果 SQLite 不可用，回退到内存检查点（MemorySaver）。
# 定义于 MASTER_PLAN.md 第 4.7 节。
# =============================================================================

"""Checkpoint configuration for LangGraph persistence.

Handles SQLite-based checkpoint storage for cross-session recovery.
Supports thread management, state history, and cleanup.

Defined in MASTER_PLAN.md Section 4.7.
"""

import os
import json
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver

# 尝试导入 SQLiteSaver，如果不可用则回退到 MemorySaver
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False


# ---------------------------------------------------------------------------
# 创建检查点实例
# 优先使用 SQLite 持久化（如果可用），否则回退到内存检查点。
# 数据库默认存储在 ~/.cellwiki/checkpoints.db。
# ---------------------------------------------------------------------------
def get_checkpointer(use_sqlite: bool = True, db_path: str = None):
    """Create a checkpointer instance.

    Args:
        use_sqlite: If True and available, use SQLite for persistence.
                   Falls back to MemorySaver if SQLite not available.
        db_path: Custom path for SQLite database. Default: ~/.cellwiki/checkpoints.db

    Returns:
        A LangGraph checkpointer instance (MemorySaver or SqliteSaver)
    """
    if use_sqlite and HAS_SQLITE:
        if db_path is None:
            db_dir = Path.home() / ".cellwiki"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "checkpoints.db")

        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3

        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)

    return MemorySaver()


# ---------------------------------------------------------------------------
# 获取默认检查点数据库路径
# ---------------------------------------------------------------------------
def get_db_path() -> str:
    """Get the default checkpoint database path."""
    db_dir = Path.home() / ".cellwiki"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "checkpoints.db")


# ---------------------------------------------------------------------------
# 列出所有线程 ID
# 从检查点数据库查询所有唯一的线程 ID，附带检查点数量和时间信息。
# ---------------------------------------------------------------------------
def list_threads(db_path: str = None, limit: int = 50) -> list:
    """List all thread IDs from the checkpoint database.

    Args:
        db_path: Path to the SQLite database
        limit: Maximum number of threads to return

    Returns:
        List of dicts with thread_id, created_at, last_updated, operation counts
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        return []

    import sqlite3

    threads = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 查询 checkpoints 表，按线程 ID 分组
        cursor.execute("""
            SELECT thread_id,
                   COUNT(*) as checkpoint_count,
                   MIN(created_at) as first_seen,
                   MAX(created_at) as last_seen
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY last_seen DESC
            LIMIT ?
        """, (limit,))

        for row in cursor.fetchall():
            threads.append({
                "thread_id": row[0],
                "checkpoint_count": row[1],
                "first_seen": row[2],
                "last_seen": row[3],
            })

        conn.close()
    except Exception as e:
        return [{"error": str(e)}]

    return threads


# ---------------------------------------------------------------------------
# 获取指定线程的检查点历史
# ---------------------------------------------------------------------------
def get_thread_history(thread_id: str, db_path: str = None) -> list:
    """Get the checkpoint history for a specific thread.

    Args:
        thread_id: The thread ID to inspect
        db_path: Path to the SQLite database

    Returns:
        List of checkpoint snapshots with timestamps and node info
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        return []

    import sqlite3

    history = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 按创建时间升序查询
        cursor.execute("""
            SELECT checkpoint_id, thread_id, created_at, node, status
            FROM checkpoints
            WHERE thread_id = ?
            ORDER BY created_at ASC
        """, (thread_id,))

        for row in cursor.fetchall():
            history.append({
                "checkpoint_id": row[0],
                "thread_id": row[1],
                "created_at": row[2],
                "node": row[3],
                "status": row[4],
            })

        conn.close()
    except Exception as e:
        return [{"error": str(e)}]

    return history


# ---------------------------------------------------------------------------
# 删除指定线程的所有检查点
# ---------------------------------------------------------------------------
def delete_thread(thread_id: str, db_path: str = None) -> bool:
    """Delete all checkpoints for a thread.

    Args:
        thread_id: The thread ID to delete
        db_path: Path to the SQLite database

    Returns:
        True if deleted successfully
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        return False

    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 清理超过指定天数的旧检查点
# ---------------------------------------------------------------------------
def cleanup_old_threads(max_age_days: int = 30, db_path: str = None) -> int:
    """Delete checkpoints older than max_age_days.

    Args:
        max_age_days: Maximum age in days for checkpoints
        db_path: Path to the SQLite database

    Returns:
        Number of deleted checkpoint records
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        return 0

    import sqlite3
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE created_at < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# 获取检查点数据库统计信息
# 包括线程数、检查点总数、按节点类型分组、数据库大小等
# ---------------------------------------------------------------------------
def get_db_stats(db_path: str = None) -> dict:
    """Get statistics about the checkpoint database.

    Args:
        db_path: Path to the SQLite database

    Returns:
        Dict with thread count, checkpoint count, database size
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        return {"error": "Database not found"}

    import sqlite3

    stats = {"db_path": db_path, "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 2)}

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM checkpoints")
        stats["total_checkpoints"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT thread_id) FROM checkpoints")
        stats["total_threads"] = cursor.fetchone()[0]

        # 按节点类型分组统计
        cursor.execute("""
            SELECT node, COUNT(*) as count
            FROM checkpoints
            GROUP BY node
            ORDER BY count DESC
        """)
        stats["by_node"] = [{"node": r[0], "count": r[1]} for r in cursor.fetchall()]

        conn.close()
    except Exception as e:
        stats["error"] = str(e)

    return stats

