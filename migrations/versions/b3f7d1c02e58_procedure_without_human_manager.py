"""Abole o gestor humano e dá ao rito o estado de que ele precisa

O papel `manager` deixa de existir como ator humano. Os atos que dependiam
dele passam a ser executados pelo próprio procedimento, com as mesmas
pré-condições. Esta migração:

- remove `cases.manager_token_hash`;
- apaga vínculos (`case_members`) e convites (`invitations`) com papel
  `manager`, para que nenhuma pessoa continue com poderes de terceiro;
- cria o encerramento de produção por parte, que substitui o julgamento do
  gestor sobre "o material está completo";
- cria o armazenamento das posições das partes entre rodadas de composição;
- cria `deadlines.reference_id`, para o rito fechar sozinho o prazo do
  material a que ele se refere.

Atenção: casos cujo único participante era o gestor ficam sem participante
depois desta migração. Eles continuam íntegros no banco, mas precisam de um
convite a `claimant` ou `respondent` para voltarem a ser acessíveis.

Revision ID: b3f7d1c02e58
Revises: 42bbe63ad5ce
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f7d1c02e58'
down_revision: Union[str, None] = '42bbe63ad5ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cases',
        sa.Column(
            'claimant_submission_closed',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'cases',
        sa.Column(
            'respondent_submission_closed',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'cases',
        sa.Column('claimant_submission_closed_at', sa.String(), nullable=True),
    )
    op.add_column(
        'cases',
        sa.Column('respondent_submission_closed_at', sa.String(), nullable=True),
    )
    op.add_column(
        'cases',
        sa.Column('composition_inputs_json', sa.Text(), nullable=True),
    )
    op.add_column(
        'deadlines',
        sa.Column('reference_id', sa.String(), nullable=True),
    )
    op.create_index(
        op.f('ix_deadlines_reference_id'),
        'deadlines',
        ['reference_id'],
        unique=False,
    )

    # Casos já travados produziram seu material antes desta mudança: o
    # encerramento das duas partes é retroativamente verdadeiro, senão o rito
    # os leria como produção ainda aberta.
    op.execute(
        "UPDATE cases SET claimant_submission_closed = true, "
        "respondent_submission_closed = true WHERE manifest_locked = true"
    )

    op.execute("DELETE FROM case_members WHERE role = 'manager'")
    op.execute("DELETE FROM invitations WHERE role = 'manager'")

    op.drop_column('cases', 'manager_token_hash')


def downgrade() -> None:
    op.add_column(
        'cases',
        sa.Column('manager_token_hash', sa.String(), nullable=True),
    )
    op.drop_index(op.f('ix_deadlines_reference_id'), table_name='deadlines')
    op.drop_column('deadlines', 'reference_id')
    op.drop_column('cases', 'composition_inputs_json')
    op.drop_column('cases', 'respondent_submission_closed_at')
    op.drop_column('cases', 'claimant_submission_closed_at')
    op.drop_column('cases', 'respondent_submission_closed')
    op.drop_column('cases', 'claimant_submission_closed')
