"""fila de e-mails do procedimento, registro de ações do admin e acompanhamento de leads

Revision ID: f5c2a8d4b1e7
Revises: e4b8c2d6f1a9
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5c2a8d4b1e7"
down_revision: Union[str, None] = "e4b8c2d6f1a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("to_email", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("audience", sa.String(), nullable=False, server_default="party"),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=True, unique=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_outbox_case_id", "email_outbox", ["case_id"])
    op.create_index("ix_email_outbox_user_id", "email_outbox", ["user_id"])
    op.create_index("ix_email_outbox_kind", "email_outbox", ["kind"])
    op.create_index("ix_email_outbox_status", "email_outbox", ["status"])
    op.create_index("ix_email_outbox_created_at", "email_outbox", ["created_at"])

    op.create_table(
        "admin_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("admin_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("admin_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_actions_admin_user_id", "admin_actions", ["admin_user_id"])
    op.create_index("ix_admin_actions_action", "admin_actions", ["action"])
    op.create_index("ix_admin_actions_target_id", "admin_actions", ["target_id"])
    op.create_index("ix_admin_actions_created_at", "admin_actions", ["created_at"])

    with op.batch_alter_table("pilot_leads") as batch:
        batch.add_column(
            sa.Column("status", sa.String(), nullable=False, server_default="new")
        )
        batch.add_column(
            sa.Column("notes", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("handled_by_user_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_pilot_leads_status", ["status"])


def downgrade() -> None:
    with op.batch_alter_table("pilot_leads") as batch:
        batch.drop_index("ix_pilot_leads_status")
        batch.drop_column("updated_at")
        batch.drop_column("handled_by_user_id")
        batch.drop_column("notes")
        batch.drop_column("status")
    for index in ("created_at", "target_id", "action", "admin_user_id"):
        op.drop_index(f"ix_admin_actions_{index}", table_name="admin_actions")
    op.drop_table("admin_actions")
    for index in ("created_at", "status", "kind", "user_id", "case_id"):
        op.drop_index(f"ix_email_outbox_{index}", table_name="email_outbox")
    op.drop_table("email_outbox")
