"""move document bytes to object storage

Guarda apenas metadados e referências no banco: o texto canônico e o arquivo
original passam a viver no object store.

ATENÇÃO: um ambiente com dados reais deve migrar o conteúdo de `content` para o
object store (preenchendo `content_key`) ANTES de aplicar esta migração, que
remove a coluna `content`.

Revision ID: c8a1d2f4b9e6
Revises: a1f3c9e2b7d4
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8a1d2f4b9e6'
down_revision: Union[str, None] = 'a1f3c9e2b7d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('content_key', sa.String(), nullable=False, server_default=''),
    )
    op.add_column('documents', sa.Column('original_key', sa.String(), nullable=True))
    op.add_column(
        'documents', sa.Column('original_media_type', sa.String(), nullable=True)
    )
    op.add_column(
        'documents',
        sa.Column('byte_size', sa.Integer(), nullable=False, server_default='0'),
    )
    op.drop_column('documents', 'content')


def downgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
    )
    op.drop_column('documents', 'byte_size')
    op.drop_column('documents', 'original_media_type')
    op.drop_column('documents', 'original_key')
    op.drop_column('documents', 'content_key')
