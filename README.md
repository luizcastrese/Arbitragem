# Arbitragem

MVP de uma infraestrutura de arbitragem computacional assistida por IA.

## Visão

O projeto investiga se disputas documentais estruturadas podem ser parcialmente organizadas, analisadas e decididas por sistemas multiagentes de IA operando sob frameworks normativos explícitos.

O sistema foi pensado para ser:

- procedural;
- auditável;
- baseado em frameworks;
- orientado por evidências;
- aumentado por retrieval/RAG.

Ele **não** pretende substituir tribunais ou câmaras arbitrais reais nesta fase.

O objetivo inicial é testar se disputas estruturadas podem ser organizadas e analisadas de forma consistente por um pipeline computacional de adjudicação.

---

## Arquitetura atual

### Pipeline

```text
criação do caso
↓
upload de documentos
↓
hash SHA-256
↓
chunking
↓
embeddings OpenAI
↓
retrieval / RAG
↓
agente organizador
↓
agente julgador
↓
agente revisor
↓
relatório final
```

---

## Componentes

| Componente | Status |
|---|---|
| Backend FastAPI | ✓ |
| Hashing SHA-256 | ✓ |
| Chunking de documentos | ✓ |
| Upload de texto | ✓ |
| Upload de PDF | ✓ |
| Parser de PDF | ✓ |
| Embeddings OpenAI | ✓ |
| Retrieval lexical | ✓ |
| Retrieval vetorial | ✓ |
| Pipeline RAG | ✓ |
| Agente organizador | ✓ |
| Agente julgador | ✓ |
| Agente revisor | ✓ |
| Integração OpenAI | ✓ |
| Framework normativo inicial | ✓ |
| Estrutura orientada à auditabilidade | ✓ |
| Persistência SQLite/SQLAlchemy inicial | ✓ |

---

## Framework inicial

### Comercial Equilibrado

Princípios:

1. prioridade contratual;
2. proporcionalidade;
3. boa-fé;
4. vedação ao enriquecimento injusto;
5. análise contextual de atrasos;
6. cumprimento parcial pode justificar pagamento proporcional.

---

## Como rodar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

No Windows, a ativação do ambiente virtual pode ser feita com:

```bash
.venv\Scripts\activate
```

Depois, acesse:

```text
http://localhost:8000/docs
```

---

## Variáveis de ambiente

Crie um arquivo `.env` com:

```text
OPENAI_API_KEY=sua_chave_aqui
```

---

## Endpoints principais

| Endpoint | Função |
|---|---|
| `POST /cases` | criar disputa |
| `POST /cases/{id}/documents/text` | adicionar documento em texto |
| `POST /cases/{id}/documents/pdf` | adicionar documento em PDF |
| `GET /cases/{id}/chunks` | inspecionar chunks |
| `GET /cases/{id}/retrieve` | testar retrieval |
| `POST /cases/{id}/organize` | organizar fatos |
| `POST /cases/{id}/decide` | gerar decisão |
| `POST /cases/{id}/review` | revisar decisão |
| `GET /cases/{id}/report` | obter relatório final |

---

## Fluxo de uso

1. Criar um caso.
2. Enviar documentos em texto ou PDF.
3. O sistema gera hashes, chunks e embeddings.
4. O retrieval recupera trechos relevantes.
5. O agente organizador estrutura a disputa.
6. O agente julgador aplica o framework Comercial Equilibrado.
7. O agente revisor audita a decisão.
8. O sistema gera relatório final.

---

## Limitações atuais

- a API ainda usa memória em parte do fluxo principal;
- a persistência SQLAlchemy foi iniciada, mas ainda precisa ser integrada a todos os endpoints;
- ainda não há autenticação;
- ainda não há frontend;
- ainda não há banco vetorial externo como pgvector, Chroma ou Pinecone;
- ainda não há camada blockchain/escrow;
- ainda não há auditoria de produção;
- ainda não há versionamento completo de prompts, modelos e frameworks.

---

## Próximos passos técnicos

1. Integrar totalmente os endpoints ao banco SQLite/SQLAlchemy.
2. Persistir decisões, revisões e execuções dos agentes.
3. Criar camada de logs auditáveis.
4. Adicionar banco vetorial real.
5. Criar frontend simples.
6. Adicionar autenticação e permissões por parte.
7. Evoluir para PostgreSQL + pgvector.
8. Futuramente, integrar escrow/smart contracts.

---

## Visão de longo prazo

O projeto pode evoluir para um ecossistema de:

- frameworks normativos;
- motores de arbitragem;
- reputações institucionais;
- sistemas computacionais de adjudicação;
- resolução financeira privada com execução programável.

A tese central é que disputas documentais e financeiras podem ser tratadas por uma infraestrutura institucional computacional, desde que haja consentimento, rastreabilidade, auditabilidade e frameworks explícitos.