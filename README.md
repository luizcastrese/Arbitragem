# Arbitragem

MVP de uma infraestrutura de arbitragem computacional assistida por IA.

A proposta é testar um fluxo mínimo:

1. criar um caso;
2. enviar documentos e alegações;
3. extrair e hashear evidências;
4. organizar fatos com um agente de IA;
5. aplicar um framework normativo inicial;
6. revisar criticamente a decisão;
7. gerar um relatório final auditável.

## Escopo inicial

O MVP é restrito a disputas documentais simples entre contratante e freelancer digital, especialmente casos de:

- atraso;
- entrega parcial;
- divergência de escopo;
- pagamento proporcional.

## Stack

- Python
- FastAPI
- Pydantic
- OpenAI API opcional
- PyMuPDF para PDFs
- Chroma/pgvector em fase posterior

## Rodando localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Acesse:

```text
http://localhost:8000/docs
```

## Endpoints principais

- `POST /cases`
- `POST /cases/{case_id}/documents/text`
- `POST /cases/{case_id}/organize`
- `POST /cases/{case_id}/decide`
- `POST /cases/{case_id}/review`
- `GET /cases/{case_id}/report`

## Observação

Esta é uma base técnica inicial. Ela ainda não é uma câmara arbitral real, não executa pagamentos e não substitui revisão jurídica humana.