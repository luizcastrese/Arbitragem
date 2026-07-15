"""add account verification and reset tokens

Revision ID: 8c3112f409ab
Revises: 6a2fb35af120
Create Date: 2026-07-15 12:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c3112f409ab"
down_revision: Union[str, None] = "6a2fb35af120"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "email_verified" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    # Versões antigas criavam esta tabela diretamente pelos modelos.
    if "user_action_tokens" not in inspector.get_table_names():
        op.create_table(
            "user_action_tokens",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    indexes = {
        index["name"] for index in inspector.get_indexes("user_action_tokens")
    }
    if "ix_user_action_tokens_user_id" not in indexes:
        op.create_index("ix_user_action_tokens_user_id", "user_action_tokens", ["user_id"])
    if "ix_user_action_tokens_token_hash" not in indexes:
        op.create_index(
            "ix_user_action_tokens_token_hash",
            "user_action_tokens",
            ["token_hash"],
            unique=True,
        )
    if "ix_user_action_tokens_purpose" not in indexes:
        op.create_index("ix_user_action_tokens_purpose", "user_action_tokens", ["purpose"])


def downgrade() -> None:
    op.drop_index("ix_user_action_tokens_purpose", table_name="user_action_tokens")
    op.drop_index("ix_user_action_tokens_token_hash", table_name="user_action_tokens")
    op.drop_index("ix_user_action_tokens_user_id", table_name="user_action_tokens")
    op.drop_table("user_action_tokens")
    op.drop_column("users", "email_verified")
