"""Add persistent customer agent sessions, messages, and executions.

Revision ID: c41e8bd29031
Revises: 7d4efc2a91b0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c41e8bd29031"
down_revision: Union[str, Sequence[str], None] = "7d4efc2a91b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("create_idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'closed')", name="ck_agent_sessions_status"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "create_idempotency_key", name="uq_agent_sessions_customer_idempotency"),
    )
    op.create_index("ix_agent_sessions_id", "agent_sessions", ["id"], unique=False)
    op.create_index("ix_agent_sessions_ticket_id", "agent_sessions", ["ticket_id"], unique=False)
    op.create_index("ix_agent_sessions_customer_id", "agent_sessions", ["customer_id"], unique=False)

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('customer', 'assistant')", name="ck_agent_messages_role"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_agent_messages_session_idempotency"),
    )
    op.create_index("ix_agent_messages_id", "agent_messages", ["id"], unique=False)
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"], unique=False)

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("agent_response", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.JSON(), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("error_info", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'waiting_for_approval', 'completed', 'failed', 'cancelled')",
            name="ck_agent_executions_status",
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["agent_messages.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["refund_approvals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_agent_executions_session_idempotency"),
        sa.UniqueConstraint("message_id", name="uq_agent_executions_message"),
    )
    op.create_index("ix_agent_executions_id", "agent_executions", ["id"], unique=False)
    op.create_index("ix_agent_executions_ticket_id", "agent_executions", ["ticket_id"], unique=False)
    op.create_index("ix_agent_executions_session_id", "agent_executions", ["session_id"], unique=False)
    op.create_index(
        "uq_agent_executions_active_session", "agent_executions", ["session_id"], unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running', 'waiting_for_approval')"),
        postgresql_where=sa.text("status IN ('pending', 'running', 'waiting_for_approval')"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_executions_active_session", table_name="agent_executions")
    op.drop_index("ix_agent_executions_session_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_ticket_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_id", table_name="agent_executions")
    op.drop_table("agent_executions")
    op.drop_index("ix_agent_messages_session_id", table_name="agent_messages")
    op.drop_index("ix_agent_messages_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_sessions_customer_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_ticket_id", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
