"""nostr anchor field on cases

Revision ID: 42bbe63ad5ce
Revises: c8a1d2f4b9e6
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '42bbe63ad5ce'
down_revision: Union[str, None] = 'c8a1d2f4b9e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('nostr_anchor_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'nostr_anchor_json')
