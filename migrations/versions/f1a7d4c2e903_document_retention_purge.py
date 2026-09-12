"""marca de expurgo de conteúdo por retenção

Revision ID: f1a7d4c2e903
Revises: e9f2a1c8d3b7
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a7d4c2e903"
down_revision: Union[str, None] = "e9f2a1c8d3b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_purged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "content_purged_at")
