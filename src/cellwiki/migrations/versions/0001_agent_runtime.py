# =============================================================================
# 迁移 0001 —— 创建持久化智能体运行和事件表
# =============================================================================
# 初始数据库迁移，建立智能体运行记录和事件存储所需的基础表结构。

"""Create durable Agent run and event tables.

Revision ID: 0001_agent_runtime
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_agent_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_agent_runs_thread", "agent_runs", ["thread_id", "updated_at"])
    op.create_table(
        "agent_events",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False, unique=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )


def downgrade() -> None:
    op.drop_table("agent_events")
    op.drop_index("ix_agent_runs_thread", table_name="agent_runs")
    op.drop_table("agent_runs")

