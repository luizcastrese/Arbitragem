"""cálculo auditável: extração por IA e memória de cálculo

Revision ID: e4b8c2d6f1a9
Revises: d3a7b9c1e5f2
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b8c2d6f1a9"
down_revision: Union[str, None] = "d3a7b9c1e5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("calculation_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "calculation_json")
