"""gestor IA: encadeamento entre etapas gravado no banco

Revision ID: b3e7f1a9c5d2
Revises: a7d3e5f9c2b1
Create Date: 2026-11-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e7f1a9c5d2"
down_revision: Union[str, None] = "a7d3e5f9c2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("steward_chain_armed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cases", "steward_chain_armed_at")
