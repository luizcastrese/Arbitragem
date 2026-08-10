"""Ratificação da decisão pelas partes

Quando a auditoria independente faz ressalva — não aprova a decisão ou indica
revisão humana —, a execução automática fica bloqueada. Até aqui o caso
encalhava: não havia a quem recorrer, porque o procedimento não tem terceiro.

A revisão passa a ser das próprias partes. Elas são informadas da ressalva e
ratificam ou recusam o resultado. Só a ratificação das duas destrava a
execução, e nunca cria um resultado que não exista: decisão inconclusiva ou
produzida em modo seguro segue inexecutável, com ou sem acordo.

Revision ID: c4e2a8b71f39
Revises: b3f7d1c02e58
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e2a8b71f39'
down_revision: Union[str, None] = 'b3f7d1c02e58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'cases',
        sa.Column('ratification_json', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('cases', 'ratification_json')
