"""gestor IA: apresentação encerrada por cada parte

Revision ID: c4d8e2a71b05
Revises: f1a7d4c2e903
Create Date: 2026-09-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d8e2a71b05"
down_revision: Union[str, None] = "f1a7d4c2e903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column(
            "claimant_submission_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "cases",
        sa.Column(
            "respondent_submission_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "cases",
        sa.Column("claimant_submission_ready_at", sa.String(), nullable=True),
    )
    op.add_column(
        "cases",
        sa.Column("respondent_submission_ready_at", sa.String(), nullable=True),
    )
    op.add_column("cases", sa.Column("steward_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cases", "steward_json")
    op.drop_column("cases", "respondent_submission_ready_at")
    op.drop_column("cases", "claimant_submission_ready_at")
    op.drop_column("cases", "respondent_submission_ready")
    op.drop_column("cases", "claimant_submission_ready")
