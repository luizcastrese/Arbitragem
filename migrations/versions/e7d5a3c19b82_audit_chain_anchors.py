"""audit chain anchors on cases

Revision ID: e7d5a3c19b82
Revises: c4e2a8b71f39
Create Date: 2026-08-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7d5a3c19b82'
down_revision: Union[str, None] = 'c4e2a8b71f39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('audit_anchors_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'audit_anchors_json')
