"""Encadeamento do gestor entre etapas de modelo, gravado no banco.

Quando o gestor abre uma etapa de modelo (conciliação, organização, decisão,
revisão), a etapa roda em segundo plano e, ao concluir, o gestor precisa
seguir para a próxima. Essa intenção ficava num `set` em memória: um reinício
no meio da etapa a apagava e o caso parava sem que ninguém o retomasse — as
partes não acionam as etapas de modelo, só o atuador do gestor.

Agora a intenção é a coluna `cases.steward_chain_armed_at`:

- **armar** grava o instante e faz commit antes de a etapa ser agendada;
- **tomar** é um UPDATE condicional que zera a marca. Só quem vê
  `rowcount == 1` segue a condução, então duas threads ou duas réplicas não
  conduzem o mesmo caso duas vezes;
- **recuperar** (`app.api.steward.recover_abandoned_steward_chains`) procura
  marcas mais velhas que o TTL de reivindicação: a etapa morreu com o processo
  e o gestor retoma a condução a partir do que está gravado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.db.models import Case


def arm_steward_chain(db: Session, case_id: str, now: Optional[datetime] = None) -> None:
    """Registra que o gestor deve seguir quando a etapa aberta concluir."""
    db.query(Case).filter(Case.id == case_id).update(
        {Case.steward_chain_armed_at: now or datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    db.commit()


def take_steward_chain(
    db: Session,
    case_id: str,
    armed_at: Optional[datetime] = None,
) -> bool:
    """Zera a marca e devolve True só para quem de fato a zerou.

    `armed_at` restringe a tomada à marca observada antes: a recuperação usa
    isso para não tomar uma marca que o gestor acabou de rearmar.
    """
    query = db.query(Case).filter(
        Case.id == case_id,
        Case.steward_chain_armed_at.isnot(None),
    )
    if armed_at is not None:
        query = query.filter(Case.steward_chain_armed_at == armed_at)
    taken = query.update(
        {Case.steward_chain_armed_at: None},
        synchronize_session=False,
    )
    db.commit()
    return taken == 1


def armed_before(db: Session, cutoff: datetime, limit: int = 50) -> List[Case]:
    """Casos cuja marca é mais antiga que `cutoff`, dos mais antigos aos novos."""
    return (
        db.query(Case)
        .filter(
            Case.steward_chain_armed_at.isnot(None),
            Case.steward_chain_armed_at < cutoff,
        )
        .order_by(Case.steward_chain_armed_at)
        .limit(limit)
        .all()
    )
