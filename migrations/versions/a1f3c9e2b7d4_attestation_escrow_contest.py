"""attestation, escrow and contest fields on cases

Revision ID: a1f3c9e2b7d4
Revises: d54be0411ca0
Create Date: 2026-07-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1f3c9e2b7d4'
down_revision: Union[str, None] = 'd54be0411ca0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('attestation_json', sa.Text(), nullable=True))
    op.add_column('cases', sa.Column('escrow_id', sa.String(), nullable=True))
    op.add_column('cases', sa.Column('contested_at', sa.String(), nullable=True))
    op.add_column('cases', sa.Column('contested_by', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'contested_by')
    op.drop_column('cases', 'contested_at')
    op.drop_column('cases', 'escrow_id')
    op.drop_column('cases', 'attestation_json')
