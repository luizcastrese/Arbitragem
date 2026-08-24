"""account lifecycle tokens, login lockout and versioned terms on consent

Revision ID: b7c4e91a5d20
Revises: 42bbe63ad5ce
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c4e91a5d20'
down_revision: Union[str, None] = '42bbe63ad5ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'failed_login_attempts',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'users',
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'auth_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('purpose', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auth_tokens_user_id', 'auth_tokens', ['user_id'])
    op.create_index('ix_auth_tokens_purpose', 'auth_tokens', ['purpose'])
    op.create_index(
        'ix_auth_tokens_token_hash',
        'auth_tokens',
        ['token_hash'],
        unique=True,
    )

    for party in ('claimant', 'respondent'):
        op.add_column(
            'cases',
            sa.Column(f'{party}_terms_version', sa.String(), nullable=True),
        )
        op.add_column(
            'cases',
            sa.Column(f'{party}_terms_sha256', sa.String(), nullable=True),
        )


def downgrade() -> None:
    for party in ('claimant', 'respondent'):
        op.drop_column('cases', f'{party}_terms_sha256')
        op.drop_column('cases', f'{party}_terms_version')

    op.drop_index('ix_auth_tokens_token_hash', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_purpose', table_name='auth_tokens')
    op.drop_index('ix_auth_tokens_user_id', table_name='auth_tokens')
    op.drop_table('auth_tokens')

    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'email_verified_at')
