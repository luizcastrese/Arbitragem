# Valinor

Plataforma de resolução e auditoria decisória por IA, criada para reduzir
drasticamente o custo de disputas entre empresas e clientes sem sacrificar
contraditório, transparência ou integridade.

MVP operacional de uma infraestrutura de auditoria decisória de disputas
documentais por IA.

O sistema cria um procedimento persistente, fixa documentos com SHA-256,
recupera evidências, conduz quantas rodadas consensuais forem úteis, organiza o
registro, profere uma decisão computacional e executa uma auditoria separada
por uma segunda IA. Cada etapa é persistida no SQLite e registrada em uma
cadeia de auditoria encadeada por hashes.

> Este projeto é experimental. Ele profere uma decisão dentro do procedimento
> computacional configurado, mas essa saída não constitui, por si só, sentença
> arbitral ou decisão estatal. Eventual eficácia jurídica depende da estrutura
> contratual adotada e da legislação aplicável.

## O que funciona

- API FastAPI com validação e documentação OpenAPI;
- painel React responsivo;
- casos persistidos em SQLite;
- contas com senha derivada por PBKDF2 e sessões expiráveis;
- sessão web em cookie `HttpOnly`, `SameSite=Strict` e `Secure` em produção;
- verificação de e-mail e recuperação de senha por links expiráveis;
- convites de uso único vinculados ao e-mail e ao papel no caso;
- agenda processual com responsável, vencimento e notificações internas;
- aceite individual das duas partes antes da formação do procedimento;
- upload de texto e PDF;
- contraditório documentado: disponibilização, ciência, resposta ou renúncia e
  admissão antes do uso pela IA;
- hashing SHA-256 e chunking com sobreposição;
- embeddings OpenAI opcionais;
- recuperação vetorial com fallback lexical;
- agentes conciliador, organizador, julgador e revisor;
- rodadas de composição com respostas separadas da empresa e do cliente;
- Structured Outputs pela Responses API;
- validação programática dos IDs citados pela decisão;
- modelo de auditoria separado e defesa contra instruções em documentos;
- manifesto imutável assinado com HMAC-SHA256;
- verificação do manifesto e da cadeia de auditoria;
- etapas idempotentes e documentos imutáveis após o lock;
- modo seguro sem OpenAI, sempre inconclusivo e sujeito a revisão humana;
- relatório final Word com o histórico completo, decisão, auditoria e hashes;
- finalização controlada antes da liberação do relatório;
- criptografia opcional do conteúdo sensível armazenado no banco;
- limitação de solicitações e cabeçalhos de segurança;
- PostgreSQL e migrações Alembic no ambiente Docker;
- testes automatizados, CI, Dependabot e imagem Docker sem usuário privilegiado.

## Fluxo

```text
caso
  -> aceite bilateral
  -> documentos e argumentos identificados por autor e finalidade
  -> ciência da contraparte
  -> resposta, contestação ou renúncia
  -> admissão do material
  -> manifesto travado
  -> rodadas de conciliação ou mediação
  -> organização
  -> decisão da IA
  -> auditoria separada por IA
  -> aprovação ou revisão humana fundamentada
  -> finalização
  -> relatório
```

Nenhum material entra silenciosamente na decisão. Tudo precisa ser atribuído a
uma parte, disponibilizado à contraparte, reconhecido como recebido e respondido
ou expressamente dispensado. O gestor só pode admitir o material depois desse
percurso, e o lock é bloqueado enquanto houver pendência.

O aceite registra a versão dos termos exibidos às partes: participação
voluntária, acesso a todo material, oportunidade de resposta, composição
consensual, decisão fundamentada por IA, auditoria separada e revisão
humana quando indicada.

Depois do lock, novos documentos não são aceitos. Cada rodada de composição
considera as posições atualizadas das partes. A IA informa se vale continuar,
quantas rodadas adicionais parecem adequadas e qual deve ser o próximo foco.

## Usuários do produto

- **cliente reclamante:** apresenta sua versão, documentos, pedidos e respostas
  às propostas; deve compreender e aceitar o procedimento;
- **empresa reclamada:** apresenta defesa e documentos, formula contrapropostas
  e acompanha exposição, acordos e decisões de forma consistente;
- **gestor do procedimento:** administra convites, acesso, prazos e integridade
  do rito, sem decidir o mérito;
- **representantes e advogados:** podem apoiar qualquer parte na preparação e
  manifestação dentro do caso.

O nicho inicial é a resolução privada de reclamações entre empresas e clientes,
especialmente situações que já geraram ou poderiam gerar processos. A empresa
ganha previsibilidade e escala; o cliente ganha um canal inteligível, bilateral
e baseado em evidências. A composição é voluntária e não pode ser apresentada
como imposição automática da empresa à contraparte.

## Rodar localmente

Requisitos: Python 3.9+ e Node.js 20.19+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env

cd frontend
npm install
npm run build
cd ..

uvicorn app.main:app --reload
```

Acesse:

- painel: <http://127.0.0.1:8000/ui/>
- documentação: <http://127.0.0.1:8000/docs>
- saúde: <http://127.0.0.1:8000/health>

Para desenvolver o frontend com hot reload:

```bash
cd frontend
npm run dev
```

## Rodar com Docker

```bash
cp .env.example .env
docker compose up --build
```

O Compose publica a aplicação apenas em `127.0.0.1:8000`, inicia PostgreSQL,
aguarda o banco ficar saudável e executa as migrações antes da API. Troque
`POSTGRES_PASSWORD` no `.env` antes de usar fora da máquina local.

Para aplicar migrações sem Docker:

```bash
alembic upgrade head
```

## Configuração

Variáveis do arquivo `.env`:

| Variável | Uso |
|---|---|
| `OPENAI_API_KEY` | Ativa embeddings e os quatro agentes |
| `OPENAI_MODEL` | Modelo dos agentes; padrão `gpt-5-mini` |
| `OPENAI_REVIEW_MODEL` | Modelo distinto usado pelo auditor em produção |
| `OPENAI_EMBEDDING_MODEL` | Modelo de embedding |
| `DATABASE_URL` | Banco SQLAlchemy |
| `POSTGRES_DB` | Banco criado pelo Docker Compose |
| `POSTGRES_USER` | Usuário PostgreSQL do Compose |
| `POSTGRES_PASSWORD` | Senha PostgreSQL do Compose |
| `PLATFORM_SIGNING_SECRET` | Assina manifestos com HMAC-SHA256 |
| `DATA_ENCRYPTION_KEY` | Chave Fernet para criptografar conteúdo sensível |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |
| `MAX_UPLOAD_BYTES` | Limite de upload de PDF |
| `AUTH_REQUIRED` | Exige conta e participação no caso nas consultas |
| `ALLOW_LEGACY_CASE_TOKENS` | Compatibilidade de testes; deve ser `false` fora deles |
| `SECURE_COOKIES` | Restringe cookies a conexões HTTPS |
| `EMAIL_VERIFICATION_REQUIRED` | Bloqueia acesso até confirmação do e-mail |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Entrega de convites e links de conta |
| `PUBLIC_BASE_URL` | Endereço HTTPS usado nos links enviados por e-mail |

Gere um segredo local:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Sem `OPENAI_API_KEY`, o sistema continua executável. Ele organiza o material
com recuperação lexical, mas não profere decisão de mérito: o resultado fica
explicitamente inconclusivo. Nenhum percentual ou pagamento é inventado.

## Endpoints principais

| Endpoint | Função |
|---|---|
| `POST /cases` | Criar caso |
| `POST /auth/register` | Criar conta e sessão |
| `POST /auth/login` | Entrar e criar sessão expiráveis |
| `POST /auth/logout` | Encerrar a sessão atual |
| `POST /auth/verify-email` | Confirmar o endereço de e-mail |
| `POST /auth/password-reset/request` | Solicitar redefinição sem revelar se a conta existe |
| `POST /auth/password-reset/confirm` | Definir nova senha com token de uso único |
| `POST /cases/{id}/invitations` | Convidar participante por e-mail e papel |
| `POST /invitations/accept` | Aceitar convite na conta correspondente |
| `POST /cases/{id}/deadlines` | Criar prazo e notificações |
| `GET /cases` | Listar casos |
| `GET /cases/{id}` | Reabrir caso completo |
| `POST /cases/{id}/consent` | Registrar aceite individual da parte |
| `POST /cases/{id}/documents/text` | Adicionar texto |
| `POST /cases/{id}/documents/pdf` | Adicionar PDF |
| `POST /cases/{id}/documents/{document_id}/acknowledge` | Confirmar ciência da contraparte |
| `POST /cases/{id}/documents/{document_id}/respond` | Responder, contestar ou renunciar |
| `POST /cases/{id}/documents/{document_id}/admit` | Admitir material após contraditório |
| `POST /cases/{id}/lock` | Travar manifesto |
| `POST /cases/{id}/conciliation` | Criar ou avançar uma rodada de composição |
| `GET /cases/{id}/manifest/verify` | Verificar hash e assinatura |
| `GET /cases/{id}/retrieve` | Consultar evidências |
| `POST /cases/{id}/organize` | Organizar registro |
| `POST /cases/{id}/decide` | Proferir decisão da IA |
| `POST /cases/{id}/review` | Auditar decisão |
| `POST /cases/{id}/finalize` | Aprovar auditoria ou registrar revisão humana |
| `GET /cases/{id}/audit` | Verificar cadeia de auditoria |
| `GET /cases/{id}/report` | Obter relatório consolidado |
| `GET /cases/{id}/report.docx` | Baixar relatório final em Word |

## Testes

```bash
source .venv/bin/activate
python -m pytest

cd frontend
npm run build
npm audit --audit-level=moderate
```

Os testes cobrem o fluxo integral, contas, convites, isolamento entre os papéis, contraditório,
persistência, imutabilidade após o lock, idempotência, PDF, transições inválidas,
agenda, relatório Word, assinatura, auditoria, modo seguro, verificação de e-mail,
finalização controlada e criptografia.

## Limites antes de produção pública

- autenticação multifator ainda não foi implementada;
- tokens locais por papel só podem ser habilitados explicitamente em testes de
  compatibilidade; o modo padrão exige conta em todas as rotas;
- o texto extraído dos documentos pode ser criptografado no banco, mas produção
  ainda precisa de banco gerenciado com criptografia de volume, backups e restauração testada;
- PDFs precisam de varredura antimalware externa antes de um lançamento aberto;
- prompts e avaliações ainda precisam de versionamento formal;
- a assinatura HMAC prova integridade dentro da plataforma, não autoria externa;
- o limitador local precisa ser complementado por WAF ou gateway distribuído;
- ainda não há observabilidade centralizada nem cofre de segredos integrado;
- não há validação jurídica dos frameworks;
- decisões inconclusivas ou reprovadas pela auditoria exigem intervenção humana.

Antes de exposição pública, configure SMTP transacional, cofre de segredos,
monitoramento, backup, WAF e os dois modelos de IA; habilite as proteções do
GitHub descritas em `docs/PRODUCTION_CHECKLIST.md`; e conclua avaliações,
revisão de segurança e revisão jurídica.

## Referências OpenAI

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
