# =============================================================================
# 迁移服务 —— 打包运行时数据库的程序化 Alembic 迁移运行器
# =============================================================================

"""Programmatic Alembic migration runner for the packaged runtime database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


# ---------------------------------------------------------------------------
# 升级运行时数据库
# 使用 Alembic 对 SQLite 运行时数据库执行迁移。
# 处理 Phase 3 安装的兼容性：这些版本直接创建了基线模式，
# 但没有 alembic_version 表，因此需要标记当前版本为 head。
#
# 注意：Alembic **不是**全部模式变更的落点。它只保留 0001 基线
# （agent_runs 与 agent_events）；其余表与后续列变更由
# `runtime_store._ensure_schema` 的内联守卫 `ALTER TABLE` 承载。
# 原因：不经 sidecar 的直连建库路径（测试、scripts/serve_e2e.py）不会跑
# Alembic，只补 revision 会让这些库静默缺列。新增模式变更时先看
# `_ensure_schema`，再决定是否需要 Alembic。
# ---------------------------------------------------------------------------
def upgrade_runtime_database(db_path: Path) -> None:
    db_path = Path(db_path).resolve()
    # 确保数据库目录存在
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # 迁移脚本位置：migrations/ 目录
    script_location = Path(__file__).resolve().parent.parent / "migrations"
    # 配置 Alembic
    config = Config()
    config.set_main_option("script_location", str(script_location))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    # 检查数据库是否已存在
    if db_path.exists():
        with sqlite3.connect(db_path) as connection:
            # 查询已存在的所有表
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        # Phase 3 兼容性：已存在 agent_runs 表但没有 alembic_version 表
        # 说明是从旧版本升级，直接标记为 head 而不是运行迁移
        if "agent_runs" in tables and "alembic_version" not in tables:
            command.stamp(config, "head")
            return
    # 正常升级：运行所有未执行的迁移
    command.upgrade(config, "head")
