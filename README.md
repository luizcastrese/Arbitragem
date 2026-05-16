# Arbitragem

AI-assisted computational arbitration infrastructure MVP.

## Vision

The project explores whether structured documentary disputes can be partially adjudicated through multi-agent AI systems operating under explicit normative frameworks.

The system is designed as:

- procedural;
- auditable;
- framework-based;
- retrieval-augmented;
- evidence-oriented.

It is NOT intended to replace courts.

The initial goal is to test whether structured disputes can be organized, analyzed and reasoned about consistently through computational adjudication pipelines.

---

# Current Architecture

## Pipeline

```text
create case
↓
upload documents
↓
SHA-256 hashing
↓
chunking
↓
OpenAI embeddings
↓
retrieval / RAG
↓
organizer agent
↓
judge agent
↓
reviewer agent
↓
final report
```

---

# Components

| Component | Status |
|---|---|
| FastAPI backend | ✓ |
| Hashing | ✓ |
| Chunking | ✓ |
| Embeddings | ✓ |
| Retrieval | ✓ |
| RAG pipeline | ✓ |
| Organizer agent | ✓ |
| Judge agent | ✓ |
| Reviewer agent | ✓ |
| OpenAI integration | ✓ |
| Framework system | ✓ |
| Audit-oriented structure | ✓ |

---

# Initial Framework

## Commercial Balanced

Principles:

1. contractual priority;
2. proportionality;
3. good faith;
4. avoid unjust enrichment;
5. contextual analysis of delays;
6. partial fulfillment may justify proportional payment.

---

# Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000/docs
```

---

# Environment Variables

```text
OPENAI_API_KEY=your_api_key
```

---

# Main Endpoints

| Endpoint | Purpose |
|---|---|
| POST /cases | create dispute |
| POST /cases/{id}/documents/text | upload document |
| GET /cases/{id}/chunks | inspect chunks |
| GET /cases/{id}/retrieve | test retrieval |
| POST /cases/{id}/organize | factual organization |
| POST /cases/{id}/decide | generate decision |
| POST /cases/{id}/review | review decision |
| GET /cases/{id}/report | final report |

---

# Current Limitations

- no PostgreSQL yet;
- no persistent storage;
- no PDF upload endpoint yet;
- no vector database yet;
- no authentication;
- no blockchain/escrow layer;
- no frontend;
- no production audit system.

---

# Long-Term Vision

A marketplace of:

- normative frameworks;
- arbitration engines;
- institutional reputations;
- computational adjudication systems.
