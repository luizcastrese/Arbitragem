"""add controlled case finalization

Revision ID: 6a2fb35af120
Revises: d54be0411ca0
Create Date: 2026-07-15 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a2fb35af120"
down_revision: Union[str, None] = "d54be0411ca0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("finalized_by_user_id", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("finalization_basis", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("finalization_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "finalization_note")
    op.drop_column("cases", "finalization_basis")
    op.drop_column("cases", "finalized_by_user_id")
    op.drop_column("cases", "finalized_at")
