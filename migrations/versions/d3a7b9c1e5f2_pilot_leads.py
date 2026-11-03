"""leads do piloto vindos da landing

Revision ID: d3a7b9c1e5f2
Revises: b3e7f1a9c5d2
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3a7b9c1e5f2"
down_revision: Union[str, None] = "b3e7f1a9c5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pilot_leads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("monthly_volume", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(), nullable=False, server_default="landing"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notification_status", sa.String(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pilot_leads_email", "pilot_leads", ["email"])


def downgrade() -> None:
    op.drop_index("ix_pilot_leads_email", table_name="pilot_leads")
    op.drop_table("pilot_leads")
