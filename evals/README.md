# Bateria de avaliação dos agentes

Esta é a primeira bateria de avaliação do procedimento. Ela mede propriedades
que uma decisão automática precisa ter para ser defensável:

| Métrica | O que reprova |
|---|---|
| `citations_grounded` | citar evidência que não existe no registro do caso |
| `figures_supported` | afirmar valor ou percentual que não aparece no material |
| `partial_requires_bps` | resultado parcial sem a fração em basis points |
| `provenance_recorded` | etapa sem versão/hash do prompt ou sem o modelo efetivo |
| `fallback_never_approved` | auditoria aprovar decisão produzida em contingência |

Além delas, um cenário pode exigir valores diretos da saída: `outcome`,
`approved`, `recommended_path` e `execution_mode`. `requires_human_review`
permanece apenas como métrica de leitura de registros antigos; saídas novas
não devem produzi-lo.

## Como rodar

```bash
# determinístico, sem chave, sem rede e sem custo
python -m evals.runner

# contra o modelo de verdade (exige OPENAI_API_KEY)
python -m evals.runner --live --min-pass-rate 0.8

# um cenário só
python -m evals.runner --scenario judge_parcial_com_bps_lastreado
```

O modo offline entra no `pytest` (`tests/test_evals.py`) e roda em qualquer
máquina; o modo live é para avaliar uma troca de modelo ou de prompt antes de
publicá-la.

## Modo offline e modo live

No **modo offline**, a chamada ao modelo é substituída pela saída gravada em
`recorded_output` (ou pela falha declarada em `simulate_failure`). O que se
mede aí é o *pipeline*: procedência registrada, comportamento em contingência,
formato da saída — e as próprias métricas, que precisam acusar problema nos
controles negativos.

No **modo live**, o agente chama a OpenAI com o prompt e o contexto do cenário.
O que se mede aí é o *modelo*. Cenários marcados com `offline_only` — os
controles negativos e as simulações de falha — são pulados.

## Anatomia de um cenário

```jsonc
{
  "agent": "judge",                  // judge | reviewer | organizer | conciliator
  "description": "...",              // o que este caso está medindo
  "offline_only": false,             // controles negativos ficam fora do live
  "simulate_failure": "LLMUnavailable", // opcional: força o caminho de contingência
  "input": { ... },                  // contexto entregue ao agente
  "recorded_output": { ... },        // saída de modelo usada no modo offline
  "record": {                        // registro do caso, base das métricas
    "document_ids": ["doc-contrato"],
    "chunk_ids": ["chunk-1"],
    "corpus_text": "texto integral do material admitido"
  },
  "expectations": { "outcome": "partial", "figures_supported": true }
}
```

Um cenário **positivo** espera `true` nas métricas. Um **controle negativo**
grava uma saída deliberadamente ruim e espera `false`: é o que prova que a
métrica não é decorativa. Ao adicionar uma métrica nova, adicione também o
controle negativo correspondente.

## Limites conhecidos

- `figures_supported` é heurística textual: compara valores em reais e
  percentuais com o material do caso. Não valida a aritmética da decisão;
- os cenários usam um caso comercial sintético. Ampliar a cobertura para
  disputas de consumo reais (anonimizadas) é o próximo passo;
- a bateria mede a saída dos agentes; ela não bloqueia o fluxo em produção.
