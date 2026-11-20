"""Persist structured agent recommendations and policy citations.

Revision ID: b6c1e7a45d20
Revises: de30ab8c7142
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c1e7a45d20"
down_revision: Union[str, Sequence[str], None] = "de30ab8c7142"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_executions", sa.Column("recommendation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_executions", "recommendation")
