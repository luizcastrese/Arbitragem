"""decision record and party tax id

Revision ID: d2e6b8f41a93
Revises: c4d8e2a71b05
Create Date: 2026-09-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e6b8f41a93"
down_revision: Union[str, None] = "c4d8e2a71b05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("claimant_tax_id", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("respondent_tax_id", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("decision_records_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "decision_records_json")
    op.drop_column("cases", "respondent_tax_id")
    op.drop_column("cases", "claimant_tax_id")
