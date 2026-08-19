"""account tokens and email verification

Revision ID: f2a6c48d31b7
Revises: e7d5a3c19b82
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a6c48d31b7'
down_revision: Union[str, None] = 'e7d5a3c19b82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        'account_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_account_tokens_user_id', 'account_tokens', ['user_id'])
    op.create_index('ix_account_tokens_purpose', 'account_tokens', ['purpose'])
    op.create_index('ix_account_tokens_token_hash', 'account_tokens', ['token_hash'])

    # Contas que já existiam foram criadas antes de haver verificação. Marcá-las
    # como verificadas seria afirmar uma prova que nunca houve; deixá-las nulas
    # é o correto — elas passam pelo mesmo fluxo de confirmação das demais.


def downgrade() -> None:
    op.drop_index('ix_account_tokens_token_hash', table_name='account_tokens')
    op.drop_index('ix_account_tokens_purpose', table_name='account_tokens')
    op.drop_index('ix_account_tokens_user_id', table_name='account_tokens')
    op.drop_table('account_tokens')
    op.drop_column('users', 'email_verified_at')
