"""Via do caso e efeito jurídico do resultado.

A Valinor existe para tirar conflitos da Justiça. Ela atua em dois momentos:

- **antes do processo** (``pre_litigation``): o conflito chega direto à
  Valinor e não vira ação;
- **com processo ajuizado** (``pending_lawsuit``): as partes trocam a via
  judicial pela Valinor, e o resultado precisa poder encerrar o processo, por
  acordo homologado ou por sentença arbitral.

Sem acordo, o caso segue uma de duas trilhas:

- ``arbitration``: as **duas** partes escolheram, dentro do caso, submeter a
  disputa à arbitragem se não houver acordo. Em relação de consumo, essa
  escolha só vale se feita pelo próprio consumidor depois de surgido o
  conflito (Lei 9.307/96, art. 4º, §2º; CDC, art. 51, VII). Cláusula
  anterior ao conflito nunca é aceita como escolha: a eleição é um ato da
  parte no caso, que só existe depois do conflito;
- ``non_binding``: falta a escolha de alguma parte. A IA decide do mesmo
  jeito, com o raciocínio e os cálculos visíveis, mas a decisão não obriga.

O núcleo é genérico: nada aqui conhece a matéria além da marca
``consumer_relation`` do framework. Este módulo não decide o mérito; só
descreve a via, valida a escolha e diz o que o documento final pode fazer.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PRE_LITIGATION = "pre_litigation"
PENDING_LAWSUIT = "pending_lawsuit"
ENTRY_POINTS = (PRE_LITIGATION, PENDING_LAWSUIT)

ARBITRATION = "arbitration"
NON_BINDING = "non_binding"

# Primeira versão dos termos que descreve a via arbitral. Escolha feita sob
# termos anteriores não é escolha informada e não é aceita.
ARBITRATION_TERMS_SINCE = "2026-10-31"

PARTIES = ("claimant", "respondent")

ENTRY_LABELS = {
    PRE_LITIGATION: "Antes do processo",
    PENDING_LAWSUIT: "Processo já ajuizado",
}
TRACK_LABELS = {
    ARBITRATION: "Arbitragem escolhida pelas duas partes",
    NON_BINDING: "Decisão não vinculante",
}

_CNJ_PATTERN = re.compile(r"^(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})$")


class PathwayError(ValueError):
    """Via ou escolha inválida. A mensagem vai para o usuário."""


def normalize_lawsuit_number(raw: Optional[str]) -> str:
    """Número único do processo (Res. CNJ 65/2008), com dígito verificador.

    Aceita com ou sem pontuação e devolve ``NNNNNNN-DD.AAAA.J.TR.OOOO``.
    """
    value = re.sub(r"\s+", "", raw or "")
    match = _CNJ_PATTERN.match(value)
    if not match:
        raise PathwayError(
            "Número do processo inválido. Use o padrão CNJ "
            "NNNNNNN-DD.AAAA.J.TR.OOOO."
        )
    number, check, year, segment, court, origin = match.groups()
    expected = 98 - (int(f"{number}{year}{segment}{court}{origin}00") % 97)
    if int(check) != expected:
        raise PathwayError(
            "Número do processo inválido: o dígito verificador não confere."
        )
    return f"{number}-{check}.{year}.{segment}.{court}.{origin}"


def build_pathway(
    *,
    entry_point: str,
    matter_framework_id: str,
    consumer_relation: bool,
    lawsuit_number: Optional[str] = None,
    court: Optional[str] = None,
    consumer_party: Optional[str] = None,
) -> Dict[str, Any]:
    if entry_point not in ENTRY_POINTS:
        raise PathwayError("Via desconhecida: use pre_litigation ou pending_lawsuit.")
    lawsuit = None
    if entry_point == PENDING_LAWSUIT:
        court_name = (court or "").strip()
        if not court_name:
            raise PathwayError("Informe o juízo onde o processo tramita.")
        lawsuit = {
            "number": normalize_lawsuit_number(lawsuit_number),
            "court": court_name[:200],
        }
    elif lawsuit_number or court:
        raise PathwayError(
            "Número do processo e juízo só se aplicam a processo já ajuizado."
        )
    if consumer_relation:
        # Ausente, presume-se que o consumidor é quem abre o caso, que é o
        # caminho comum. A presunção não habilita arbitragem sozinha: ela
        # continua exigindo a escolha das duas partes dentro do caso.
        consumer_party = consumer_party or "claimant"
        if consumer_party not in PARTIES:
            raise PathwayError(
                "Em relação de consumo, indique qual parte é o consumidor."
            )
    elif consumer_party:
        raise PathwayError("Esta matéria não é de consumo: não há parte consumidora.")
    return {
        "entry_point": entry_point,
        "lawsuit": lawsuit,
        "matter_framework_id": matter_framework_id,
        "consumer_relation": bool(consumer_relation),
        "consumer_party": consumer_party if consumer_relation else None,
        "arbitration_elections": {},
    }


def record_election(
    pathway: Dict[str, Any],
    *,
    party: str,
    elected: bool,
    terms_version: str,
    terms_sha256: str,
) -> Dict[str, Any]:
    """Registra a escolha da parte pela arbitragem, se não houver acordo.

    A escolha é individual, voluntária e feita dentro do caso, ou seja, depois
    de surgido o conflito. Só vale sob termos que descrevem a via arbitral.
    """
    if party not in PARTIES:
        raise PathwayError("Parte desconhecida.")
    if elected and (terms_version or "") < ARBITRATION_TERMS_SINCE:
        raise PathwayError(
            "A escolha pela arbitragem exige aceite dos termos vigentes, que "
            "descrevem a via arbitral. Recarregue os termos e aceite de novo."
        )
    updated = dict(pathway)
    elections = dict(updated.get("arbitration_elections") or {})
    elections[party] = {
        "elected": bool(elected),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "terms_version": terms_version,
        "terms_sha256": terms_sha256,
        # A eleição é um ato da parte num caso já aberto: o conflito existe.
        "after_dispute_arose": True,
        "by_consumer": bool(
            updated.get("consumer_relation") and updated.get("consumer_party") == party
        ),
    }
    updated["arbitration_elections"] = elections
    return updated


def clear_election(pathway: Dict[str, Any], party: str) -> Dict[str, Any]:
    updated = dict(pathway)
    elections = dict(updated.get("arbitration_elections") or {})
    elections.pop(party, None)
    updated["arbitration_elections"] = elections
    return updated


def resolution_track(pathway: Optional[Dict[str, Any]]) -> str:
    """Arbitragem só quando as duas partes escolheram, e de forma válida."""
    pathway = pathway or {}
    elections = pathway.get("arbitration_elections") or {}
    if not all((elections.get(party) or {}).get("elected") for party in PARTIES):
        return NON_BINDING
    if pathway.get("consumer_relation"):
        consumer = pathway.get("consumer_party")
        entry = elections.get(consumer) or {}
        if not (entry.get("by_consumer") and entry.get("after_dispute_arose")):
            return NON_BINDING
    return ARBITRATION


def public_pathway(pathway: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not pathway:
        return None
    data = dict(pathway)
    data["entry_label"] = ENTRY_LABELS.get(data.get("entry_point"), data.get("entry_point"))
    track = resolution_track(pathway)
    data["resolution_track"] = track
    data["resolution_track_label"] = TRACK_LABELS[track]
    return data


def _lawsuit_ref(pathway: Dict[str, Any]) -> str:
    lawsuit = pathway.get("lawsuit") or {}
    number = lawsuit.get("number") or "(número não informado)"
    court = lawsuit.get("court")
    return f"processo nº {number}" + (f", em trâmite em {court}" if court else "")


def legal_effect(pathway: Optional[Dict[str, Any]], kind: str) -> Dict[str, Any]:
    """O que o documento final é e o que ele pode fazer com o conflito.

    ``kind`` é o desfecho do auto: ``agreement``, ``decision`` ou
    ``no_merit_decision``. Casos anteriores à via são tratados como antes do
    processo e sem escolha de arbitragem.
    """
    pathway = pathway or {}
    entry = pathway.get("entry_point") or PRE_LITIGATION
    track = resolution_track(pathway)
    pending_lawsuit = entry == PENDING_LAWSUIT
    basis: List[str] = []
    steps: List[str] = []
    pending: List[str] = []
    ends_lawsuit_by: Optional[str] = None

    if kind == "agreement":
        binding = True
        basis.append("Código Civil, art. 840 (transação)")
        if pending_lawsuit:
            instrument = "termo_de_acordo_para_homologacao"
            label = "Termo de acordo para homologação judicial"
            ends_lawsuit_by = "homologacao_de_acordo"
            basis += [
                "CPC, art. 487, III, b (homologação da transação resolve o mérito)",
                "CPC, art. 515, II (a homologação forma título executivo judicial)",
                "CPC, art. 90, §3º (transação antes da sentença dispensa custas remanescentes)",
            ]
            steps.append(
                f"Peticionar no {_lawsuit_ref(pathway)}, juntando este auto, "
                "para homologar o acordo e extinguir o processo com "
                "resolução de mérito."
            )
        else:
            instrument = "termo_de_acordo_extrajudicial"
            label = "Termo de acordo extrajudicial"
            basis += [
                "CPC, art. 784, III (título executivo extrajudicial com assinatura do devedor e de duas testemunhas)",
                "CPC, arts. 515, III, e 725, VIII (homologação judicial de autocomposição extrajudicial)",
            ]
            steps.append(
                "O acordo obriga as partes como transação. Para executá-lo "
                "diretamente, as partes podem assinar o termo com duas "
                "testemunhas ou pedir sua homologação judicial."
            )
    elif kind == "decision" and track == ARBITRATION:
        instrument = "sentenca_arbitral"
        label = "Projeto de sentença arbitral (aguarda assinatura do árbitro)"
        # A lei exige árbitro pessoa capaz (art. 13) e sentença assinada por
        # ele (art. 26). Sem essa assinatura, o documento não tem os efeitos
        # do art. 31 e não é apresentado como vinculante.
        binding = False
        ends_lawsuit_by = "sentenca_arbitral" if pending_lawsuit else None
        basis += [
            "Lei 9.307/96, art. 31 (a sentença arbitral produz os efeitos da sentença judicial)",
            "CPC, art. 515, VII (sentença arbitral é título executivo judicial)",
            "Lei 9.307/96, arts. 13 e 26 (árbitro pessoa capaz; sentença assinada pelo árbitro)",
            "Lei 9.307/96, arts. 32 e 33 (nulidade só pelas hipóteses legais, em 90 dias)",
        ]
        if pathway.get("consumer_relation"):
            basis.append(
                "Lei 9.307/96, art. 4º, §2º, e CDC, art. 51, VII (arbitragem "
                "de consumo só por escolha do consumidor depois do conflito)"
            )
        pending.append(
            "Assinatura do árbitro pessoa física indicado no compromisso "
            "arbitral, que adota ou não a decisão elaborada pela IA. A Valinor "
            "ainda não conduz essa etapa; até ela, o documento é projeto de "
            "sentença e não obriga as partes."
        )
        if pending_lawsuit:
            basis += [
                "Lei 9.307/96, art. 9º, §1º (compromisso arbitral por termo nos autos)",
                "CPC, art. 485, VII (convenção de arbitragem extingue o processo sem resolução de mérito)",
            ]
            steps.append(
                f"Firmar o compromisso arbitral no {_lawsuit_ref(pathway)} e "
                "pedir a extinção do processo; a sentença arbitral assinada "
                "passa a ser o título do conflito."
            )
        else:
            steps.append(
                "Assinada pelo árbitro, a sentença arbitral encerra o conflito "
                "sem ação judicial e pode ser executada como sentença."
            )
    elif kind == "decision":
        instrument = "decisao_nao_vinculante"
        label = "Decisão fundamentada não vinculante"
        binding = False
        steps.append(
            "A decisão não obriga: as partes podem cumpri-la voluntariamente "
            "(inclusive pagando pela plataforma) ou usá-la como base de acordo."
        )
        if pending_lawsuit:
            steps.append(
                f"O auto pode ser juntado ao {_lawsuit_ref(pathway)} como prova "
                "do procedimento, cabendo ao juízo avaliá-lo."
            )
    else:
        instrument = "auto_sem_merito"
        label = "Encerramento sem decisão de mérito"
        binding = False
        steps.append(
            "Na dúvida, o sistema se abstém: o conflito não foi resolvido aqui "
            "e segue pela via que as partes escolherem."
        )
        if pending_lawsuit:
            steps.append(
                f"Comunicar o encerramento no {_lawsuit_ref(pathway)} para que "
                "o processo retome o curso, se estava suspenso (CPC, art. 313, II)."
            )

    return {
        "entry_point": entry,
        "entry_label": ENTRY_LABELS.get(entry, entry),
        "lawsuit": pathway.get("lawsuit"),
        "resolution_track": track,
        "resolution_track_label": TRACK_LABELS[track],
        "consumer_relation": bool(pathway.get("consumer_relation")),
        "consumer_party": pathway.get("consumer_party"),
        "arbitration_elections": pathway.get("arbitration_elections") or {},
        "instrument": instrument,
        "instrument_label": label,
        "binding": binding,
        "ends_lawsuit_by": ends_lawsuit_by,
        "legal_basis": basis,
        "next_steps": steps,
        "pending": pending,
    }
