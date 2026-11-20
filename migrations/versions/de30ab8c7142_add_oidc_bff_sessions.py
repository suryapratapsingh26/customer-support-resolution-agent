"""Add one-time OIDC login attempts and opaque BFF sessions.

Revision ID: de30ab8c7142
Revises: c41e8bd29031
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "de30ab8c7142"
down_revision: Union[str, Sequence[str], None] = "c41e8bd29031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bff_login_attempts",
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("browser_binding_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index("ix_bff_login_attempts_expires_at", "bff_login_attempts", ["expires_at"])
    op.create_table(
        "bff_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("customer_ids", sa.JSON(), nullable=False),
        sa.Column("csrf_token", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_bff_sessions_subject", "bff_sessions", ["subject"])
    op.create_index("ix_bff_sessions_expires_at", "bff_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_bff_sessions_expires_at", table_name="bff_sessions")
    op.drop_index("ix_bff_sessions_subject", table_name="bff_sessions")
    op.drop_table("bff_sessions")
    op.drop_index("ix_bff_login_attempts_expires_at", table_name="bff_login_attempts")
    op.drop_table("bff_login_attempts")
