"""optional settlement payments via Stripe Connect

Revision ID: e3b5a7c9d1f2
Revises: d2e6b8f41a93
Create Date: 2026-10-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3b5a7c9d1f2"
down_revision: Union[str, None] = "d2e6b8f41a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("stripe_account_id", sa.String(), nullable=True))
    op.create_index(
        "uq_users_stripe_account_id", "users", ["stripe_account_id"], unique=True
    )
    op.create_table(
        "settlement_payments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("attestation_hash", sa.String(), nullable=False),
        sa.Column("payer_role", sa.String(), nullable=False),
        sa.Column("payee_role", sa.String(), nullable=False),
        sa.Column("payer_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("payee_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("amount_minor_units", sa.Integer(), nullable=False),
        sa.Column("fee_minor_units", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("checkout_session_id", sa.String(), nullable=True, unique=True),
        sa.Column("payment_intent_id", sa.String(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "case_id", "attestation_hash", name="uq_settlement_payments_attestation"
        ),
    )
    op.create_index("ix_settlement_payments_case_id", "settlement_payments", ["case_id"])
    op.create_index("ix_settlement_payments_status", "settlement_payments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_settlement_payments_status", table_name="settlement_payments")
    op.drop_index("ix_settlement_payments_case_id", table_name="settlement_payments")
    op.drop_table("settlement_payments")
    op.drop_index("uq_users_stripe_account_id", table_name="users")
    op.drop_column("users", "stripe_account_id")
