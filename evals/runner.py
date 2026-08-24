"""Executor da bateria de avaliação dos agentes.

Dois modos:

- **offline** (padrão): a chamada ao modelo é substituída pela saída gravada no
  cenário. Roda sem chave, sem rede e sem custo, e é determinístico — serve de
  teste de regressão do pipeline (procedência, contingência, formato) e dos
  próprios controles de qualidade;
- **live** (`--live`): chama a OpenAI de verdade com o prompt e o contexto do
  cenário. Mede o modelo, não o pipeline. Cenários marcados como
  `offline_only` (controles negativos com saída deliberadamente ruim) são
  pulados.

Uso:

    python -m evals.runner
    python -m evals.runner --live --min-pass-rate 0.8
    python -m evals.runner --scenario judge_partial_com_bps_lastreado
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from app.agents import conciliator, judge, organizer, reviewer
from app.core import llm
from app.core.config import get_settings
from app.core.llm import LLMResult
from evals.checks import CheckResult, run_expectations


SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class ScenarioResult:
    scenario_id: str
    agent: str
    checks: List[CheckResult]
    skipped: str = ""

    @property
    def passed(self) -> bool:
        return not self.skipped and all(check.passed for check in self.checks)


def load_scenarios(only: Optional[str] = None) -> List[Dict]:
    scenarios = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        scenario.setdefault("id", path.stem)
        if only and scenario["id"] != only:
            continue
        scenarios.append(scenario)
    if only and not scenarios:
        raise SystemExit(f"Cenário não encontrado: {only}")
    return scenarios


@contextlib.contextmanager
def _recorded_model(scenario: Dict) -> Iterator[None]:
    """Substitui a chamada ao modelo pela saída gravada no cenário — ou pela
    falha que o cenário quer simular."""
    original = llm.call_openai_structured
    failure = scenario.get("simulate_failure")
    recorded = scenario.get("recorded_output")

    def fake_call(system_prompt: str, user_payload, response_model, model=None):
        if failure:
            raise llm.LLMCallError(failure)
        if recorded is None:
            raise llm.LLMUnavailable("cenário sem saída gravada")
        return LLMResult(
            data=dict(recorded),
            model=scenario.get("recorded_model", "gpt-5-mini-2026-04-01"),
            response_id=f"eval-{scenario['id']}",
            usage={},
        )

    llm.call_openai_structured = fake_call
    # Os agentes importaram a função diretamente: a troca precisa alcançar
    # cada módulo, não só o módulo de origem.
    modules = (judge, reviewer, organizer, conciliator)
    saved = [module.call_openai_structured for module in modules]
    for module in modules:
        module.call_openai_structured = fake_call
    try:
        yield
    finally:
        llm.call_openai_structured = original
        for module, previous in zip(modules, saved):
            module.call_openai_structured = previous


def _invoke_agent(scenario: Dict) -> Dict:
    agent = scenario["agent"]
    payload = scenario["input"]
    if agent == "judge":
        return judge.decide_case(payload)
    if agent == "reviewer":
        return reviewer.review_decision(payload)
    if agent == "conciliator":
        return conciliator.assess_conciliation(payload, payload.get("round_number", 1))
    if agent == "organizer":
        return organizer.organize_case(
            documents=payload.get("documents", []),
            chunks=payload.get("chunks", []),
        )
    raise KeyError(f"Agente desconhecido no cenário: {agent}")


def run_scenario(scenario: Dict, live: bool = False) -> ScenarioResult:
    agent = scenario["agent"]

    if live and scenario.get("offline_only"):
        return ScenarioResult(
            scenario["id"],
            agent,
            [],
            skipped="controle negativo: só faz sentido com saída gravada",
        )
    if live and not get_settings().openai_enabled:
        return ScenarioResult(
            scenario["id"], agent, [], skipped="OPENAI_API_KEY não configurada"
        )

    if live:
        output = _invoke_agent(scenario)
    else:
        with _recorded_model(scenario):
            output = _invoke_agent(scenario)

    record = {**scenario.get("record", {}), "agent": agent}
    record.setdefault("decision", (scenario.get("input") or {}).get("decision"))
    checks = run_expectations(output, record, scenario.get("expectations", {}))
    return ScenarioResult(scenario["id"], agent, checks)


def _print_report(results: List[ScenarioResult], pass_rate: float) -> None:
    for result in results:
        if result.skipped:
            print(f"  ~ {result.scenario_id} [{result.agent}] pulado: {result.skipped}")
            continue
        mark = "ok" if result.passed else "FALHOU"
        print(f"  {mark:>6}  {result.scenario_id} [{result.agent}]")
        for check in result.checks:
            if check.passed:
                continue
            print(
                f"          - {check.name}: obtido {check.value!r}, "
                f"esperado {check.expected!r}"
                + (f" ({check.detail})" if check.detail else "")
            )
    executed = [result for result in results if not result.skipped]
    print(
        f"\n{sum(1 for r in executed if r.passed)}/{len(executed)} cenários "
        f"aprovados (taxa {pass_rate:.0%})"
    )


def run_all(live: bool = False, only: Optional[str] = None) -> List[ScenarioResult]:
    return [run_scenario(scenario, live=live) for scenario in load_scenarios(only)]


def pass_rate(results: List[ScenarioResult]) -> float:
    executed = [result for result in results if not result.skipped]
    if not executed:
        return 1.0
    return sum(1 for result in executed if result.passed) / len(executed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bateria de avaliação dos agentes")
    parser.add_argument(
        "--live",
        action="store_true",
        help="chama a OpenAI de verdade em vez de usar as saídas gravadas",
    )
    parser.add_argument("--scenario", help="roda apenas o cenário indicado")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=None,
        help="taxa mínima de aprovação (padrão: 1.0 offline, 0.8 live)",
    )
    args = parser.parse_args()

    minimum = args.min_pass_rate
    if minimum is None:
        minimum = 0.8 if args.live else 1.0

    modo = "live" if args.live else "offline"
    print(f"Bateria de avaliação Valinor — modo {modo}\n")
    results = run_all(live=args.live, only=args.scenario)
    rate = pass_rate(results)
    _print_report(results, rate)

    if rate < minimum:
        print(f"\nTaxa abaixo do mínimo exigido ({minimum:.0%}).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
