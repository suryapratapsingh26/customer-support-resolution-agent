"""Add persistent refund approval records.

Revision ID: 7d4efc2a91b0
Revises: 9520ac91d23f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d4efc2a91b0"
down_revision: Union[str, Sequence[str], None] = "9520ac91d23f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refund_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("requested_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("policy_basis", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("requested_by", sa.String(100), nullable=False),
        sa.Column("policy_review_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refund_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'executed')", name="ck_refund_approvals_status"),
        sa.CheckConstraint("requested_amount > 0", name="ck_refund_approvals_amount_positive"),
        sa.CheckConstraint(
            "policy_basis IN ('unused_original_packaging', 'faulty_item', 'incorrect_item', 'partial_return', 'missing_item', 'price_adjustment')",
            name="ck_refund_approvals_policy_basis",
        ),
        sa.CheckConstraint(
            "status != 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND policy_review_confirmed = true AND reviewed_by != requested_by)",
            name="ck_refund_approvals_approved_review",
        ),
        sa.CheckConstraint(
            "status != 'rejected' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND rejection_reason IS NOT NULL AND length(trim(rejection_reason)) > 0 AND reviewed_by != requested_by)",
            name="ck_refund_approvals_rejected_review",
        ),
        sa.CheckConstraint(
            "status != 'executed' OR (refund_id IS NOT NULL AND executed_at IS NOT NULL AND policy_review_confirmed = true AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_by != requested_by)",
            name="ck_refund_approvals_executed_refund",
        ),
        sa.CheckConstraint(
            "status != 'pending' OR (reviewed_by IS NULL AND reviewed_at IS NULL AND rejection_reason IS NULL AND executed_at IS NULL AND refund_id IS NULL AND policy_review_confirmed = false)",
            name="ck_refund_approvals_pending_unreviewed",
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.ForeignKeyConstraint(["refund_id"], ["refunds.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refund_id"),
    )
    op.create_index("ix_refund_approvals_id", "refund_approvals", ["id"], unique=False)
    op.create_index(
        "uq_refund_approvals_active_payment", "refund_approvals", ["payment_id"], unique=True,
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )


def downgrade() -> None:
    op.drop_index("uq_refund_approvals_active_payment", table_name="refund_approvals")
    op.drop_index("ix_refund_approvals_id", table_name="refund_approvals")
    op.drop_table("refund_approvals")
