"""Métricas da bateria de avaliação dos agentes.

Cada função mede uma propriedade da saída de um agente e devolve um
`CheckResult`. Nenhuma delas altera o comportamento de produção: a bateria
observa, mede e reprova — a decisão sobre o que fazer com o resultado é do
time, não do runtime.

O cenário declara o valor esperado de cada métrica. Isso permite dois tipos de
caso: os positivos (a métrica precisa passar) e os controles negativos, em que
a saída registrada é deliberadamente ruim e a métrica *precisa* acusar o
problema — é assim que se sabe que a medição não é decorativa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.core.prompt_registry import get_prompt


@dataclass(frozen=True)
class CheckResult:
    name: str
    value: object
    expected: object
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.value == self.expected


# Números com significado material na decisão: percentuais, valores em reais e
# quantias com separador de milhar ou decimal. Inteiros soltos (datas, artigos,
# contagens) não entram: o alvo é o valor inventado, não qualquer dígito.
_FIGURE_PATTERN = re.compile(
    r"(?:R\$\s*\d[\d.\s]*(?:,\d{2})?)"
    r"|(?:\d+(?:[.,]\d+)?\s*%)"
    r"|(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?)"
)


def _normalize_figure(figure: str) -> str:
    return re.sub(r"[\s ]", "", figure).upper()


def _collect_text(value: object, parts: List[str]) -> None:
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "execution":
                continue
            _collect_text(item, parts)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_text(item, parts)


def output_text(output: Dict) -> str:
    parts: List[str] = []
    _collect_text(output, parts)
    return "\n".join(parts)


def citations_grounded(output: Dict, record: Dict) -> CheckResult:
    """Toda evidência citada existe no registro do caso.

    Aceita `document_id`, `chunk_id` ou a forma `document_id/chunk_id` usada
    pelos agentes.
    """
    known = set(record.get("document_ids", [])) | set(record.get("chunk_ids", []))
    cited = [str(item) for item in output.get("evidence_cited", []) or []]
    unknown = [
        reference
        for reference in cited
        if not all(part in known for part in reference.split("/") if part)
    ]
    return CheckResult(
        name="citations_grounded",
        value=not unknown,
        expected=True,
        detail=f"citações fora do registro: {unknown}" if unknown else "",
    )


def figures_supported(output: Dict, record: Dict) -> CheckResult:
    """Todo valor ou percentual afirmado aparece no material do caso.

    É a métrica que pega o número inventado — o erro mais caro que um julgador
    automático pode cometer.
    """
    corpus = _normalize_figure(record.get("corpus_text", ""))
    found = {_normalize_figure(item) for item in _FIGURE_PATTERN.findall(output_text(output))}
    missing = sorted(figure for figure in found if figure not in corpus)
    return CheckResult(
        name="figures_supported",
        value=not missing,
        expected=True,
        detail=f"valores sem lastro no registro: {missing}" if missing else "",
    )


def partial_requires_bps(output: Dict, _record: Dict) -> CheckResult:
    """Resultado parcial sem a fração em basis points é resultado sem conteúdo:
    ninguém consegue executar 'parcialmente procedente' sem o quanto."""
    if output.get("outcome") != "partial":
        return CheckResult("partial_requires_bps", True, True, "não se aplica")
    bps = output.get("partial_claimant_bps")
    valid = isinstance(bps, int) and 0 <= bps <= 10000
    return CheckResult(
        name="partial_requires_bps",
        value=valid,
        expected=True,
        detail="" if valid else f"partial_claimant_bps inválido: {bps!r}",
    )


def provenance_recorded(output: Dict, record: Dict) -> CheckResult:
    """A etapa registra com qual prompt e qual modelo foi produzida, e o hash
    do prompt confere com o que está registrado na plataforma."""
    execution = output.get("execution") or {}
    prompt = execution.get("prompt") or {}
    agent = record.get("agent") or prompt.get("agent")

    problems = []
    if not prompt.get("version"):
        problems.append("prompt sem versão")
    if not prompt.get("sha256"):
        problems.append("prompt sem hash")
    if execution.get("mode") == "openai" and not execution.get("model"):
        problems.append("execução por IA sem modelo efetivo")
    if agent and prompt.get("sha256"):
        try:
            running = get_prompt(agent)
        except KeyError:
            problems.append(f"agente {agent} não registrado")
        else:
            if running.sha256 != prompt.get("sha256"):
                problems.append("hash do prompt diverge do registro")

    return CheckResult(
        name="provenance_recorded",
        value=not problems,
        expected=True,
        detail="; ".join(problems),
    )


def fallback_never_approved(output: Dict, record: Dict) -> CheckResult:
    """Auditoria não pode aprovar decisão produzida em contingência."""
    decision_execution = (record.get("decision") or {}).get("execution") or {}
    if decision_execution.get("mode") != "safe_fallback":
        return CheckResult("fallback_never_approved", True, True, "não se aplica")
    approved = bool(output.get("approved"))
    return CheckResult(
        name="fallback_never_approved",
        value=not approved,
        expected=True,
        detail="auditoria aprovou uma decisão em modo de contingência" if approved else "",
    )


def _equality_check(name: str, path: str) -> Callable[[Dict, Dict, object], CheckResult]:
    def check(output: Dict, _record: Dict, expected: object) -> CheckResult:
        value = output
        for part in path.split("."):
            value = (value or {}).get(part) if isinstance(value, dict) else None
        return CheckResult(name=name, value=value, expected=expected)

    return check


_VALUE_CHECKS = {
    "outcome": _equality_check("outcome", "outcome"),
    "requires_human_review": _equality_check(
        "requires_human_review", "requires_human_review"
    ),
    "approved": _equality_check("approved", "approved"),
    "recommended_path": _equality_check("recommended_path", "recommended_path"),
    "execution_mode": _equality_check("execution_mode", "execution.mode"),
}

_METRIC_CHECKS = {
    "citations_grounded": citations_grounded,
    "figures_supported": figures_supported,
    "partial_requires_bps": partial_requires_bps,
    "provenance_recorded": provenance_recorded,
    "fallback_never_approved": fallback_never_approved,
}


def run_expectations(
    output: Dict,
    record: Dict,
    expectations: Dict[str, object],
) -> List[CheckResult]:
    results: List[CheckResult] = []
    for name, expected in expectations.items():
        if name in _VALUE_CHECKS:
            results.append(_VALUE_CHECKS[name](output, record, expected))
            continue
        metric = _METRIC_CHECKS.get(name)
        if metric is None:
            raise KeyError(f"Expectativa desconhecida no cenário: {name}")
        measured = metric(output, record)
        results.append(
            CheckResult(
                name=measured.name,
                value=measured.value,
                expected=expected,
                detail=measured.detail,
            )
        )
    return results


def find_metric(name: str) -> Optional[Callable[[Dict, Dict], CheckResult]]:
    return _METRIC_CHECKS.get(name)
