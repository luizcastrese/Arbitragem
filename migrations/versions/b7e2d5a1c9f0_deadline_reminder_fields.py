"""campos de controle de notificação de prazos

Revision ID: b7e2d5a1c9f0
Revises: a1f3c9e2b7d4
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2d5a1c9f0'
down_revision: Union[str, None] = 'a1f3c9e2b7d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'deadlines',
        sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'deadlines',
        sa.Column('overdue_sent_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('deadlines', 'overdue_sent_at')
    op.drop_column('deadlines', 'reminder_sent_at')
