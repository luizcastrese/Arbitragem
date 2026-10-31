"""case pathway: entry point, lawsuit and arbitration elections

Revision ID: a7d3e5f9c2b1
Revises: e3b5a7c9d1f2
Create Date: 2026-10-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d3e5f9c2b1"
down_revision: Union[str, None] = "e3b5a7c9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Casos anteriores ficam com NULL: são tratados como antes do processo,
    # sem escolha de arbitragem, e mantêm a decisão não vinculante.
    op.add_column("cases", sa.Column("pathway_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "pathway_json")
