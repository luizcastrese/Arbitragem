"""Manutenção periódica do rito.

O procedimento se conduz sozinho, mas só *acorda* quando alguém age: cada ato
de parte chama `advance`, e nada mais chama. Isso deixa de fora justamente o
que depende da passagem do tempo:

- a **preclusão**, que é o mecanismo que impede uma parte de vetar o
  procedimento pelo silêncio. Se quem se beneficia do silêncio da outra nunca
  abre o aplicativo, o prazo vence e o caso fica parado — o oposto do que a
  preclusão existe para garantir;
- o **amadurecimento das provas OpenTimestamps**, que nascem pendentes e só
  viram carimbo em blockchain horas depois. Num caso já encerrado ninguém mais
  age, e a prova ficaria para sempre como recibo de calendário.

Os dois se resolvem com a mesma varredura, porque ambos são passos do rito e
`advance` executa todos os que já podem ser executados. Feito para cron:

    python -m app.core.worker

Rodar de hora em hora é suficiente: os prazos são contados em dias e a
confirmação em Bitcoin leva horas. Rodar com mais frequência não faz mal — a
varredura é idempotente e não faz nada quando não há o que fazer.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger("valinor.worker")


def sweep() -> Dict[str, Any]:
    """Deixa cada caso avançar até onde suas próprias pré-condições permitirem.

    Nenhuma pré-condição é relaxada aqui: a varredura não decide nada, apenas
    dá ao rito a oportunidade de executar o que já estava devido. Um caso que
    falha não interrompe os demais — o registro de um erro não pode impedir a
    preclusão de outro procedimento.
    """
    from app.core.procedure import advance
    from app.db.repository import get_case, list_cases
    from app.db.session import SessionLocal

    db = SessionLocal()
    examined = 0
    advanced = 0
    steps = 0
    failures = 0
    try:
        case_ids = [case.id for case in list_cases(db)]
        for case_id in case_ids:
            examined += 1
            try:
                case = get_case(db, case_id)
                if case is None:
                    continue
                result = advance(db, case)
            except Exception:  # noqa: BLE001 - um caso ruim não trava a fila
                failures += 1
                logger.exception("Falha ao avançar o caso %s", case_id)
                db.rollback()
                continue
            performed = result.get("performed") or []
            if performed:
                advanced += 1
                steps += len(performed)
                logger.info(
                    "caso=%s passos=%s",
                    case_id,
                    ",".join(item.get("step", "?") for item in performed),
                )
    finally:
        db.close()

    summary = {
        "examined": examined,
        "advanced": advanced,
        "steps": steps,
        "failures": failures,
    }
    logger.info("varredura concluída: %s", summary)
    return summary


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    print(sweep())
