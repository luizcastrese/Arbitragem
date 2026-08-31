"""Remove o papel de gestor e vincula subsidiários a cada lado.

Revision ID: f4b8d2a7c1e9
Revises: e9f2a1c8d3b7
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4b8d2a7c1e9"
down_revision: Union[str, None] = "e9f2a1c8d3b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("case_members") as batch:
        batch.add_column(sa.Column("party", sa.String(), nullable=True))
    with op.batch_alter_table("invitations") as batch:
        batch.add_column(sa.Column("party", sa.String(), nullable=True))

    connection = op.get_bind()
    members = connection.execute(
        sa.text("SELECT id, case_id, user_id, role FROM case_members")
    ).fetchall()
    principals = {
        (row.case_id, row.role)
        for row in members
        if row.role in {"claimant", "respondent"}
    }
    user_roles = {
        (row.case_id, row.user_id, row.role)
        for row in members
    }
    for row in members:
        if row.role in {"claimant", "respondent"}:
            connection.execute(
                sa.text("UPDATE case_members SET party = :party WHERE id = :id"),
                {"party": row.role, "id": row.id},
            )
            continue
        if row.role != "manager":
            continue
        already_claimant = (row.case_id, row.user_id, "claimant") in user_roles
        side_has_claimant = (row.case_id, "claimant") in principals
        if already_claimant or side_has_claimant:
            connection.execute(
                sa.text(
                    "UPDATE case_members SET role = 'subsidiary', party = 'claimant' "
                    "WHERE id = :id"
                ),
                {"id": row.id},
            )
        else:
            connection.execute(
                sa.text(
                    "UPDATE case_members SET role = 'claimant', party = 'claimant' "
                    "WHERE id = :id"
                ),
                {"id": row.id},
            )
            principals.add((row.case_id, "claimant"))
            user_roles.add((row.case_id, row.user_id, "claimant"))

    connection.execute(
        sa.text(
            "UPDATE invitations SET party = role "
            "WHERE role IN ('claimant', 'respondent')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE invitations SET status = 'cancelled', party = 'claimant' "
            "WHERE role = 'manager' AND status = 'pending'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE invitations SET party = 'claimant' "
            "WHERE role = 'manager' AND party IS NULL"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("invitations") as batch:
        batch.drop_column("party")
    with op.batch_alter_table("case_members") as batch:
        batch.drop_column("party")
