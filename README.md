# Valinor

Plataforma de resolução e auditoria decisória por IA, criada para reduzir
drasticamente o custo de disputas entre empresas e clientes sem sacrificar
contraditório, transparência ou integridade.

MVP operacional de uma infraestrutura de auditoria decisória de disputas
documentais por IA.

O sistema cria um procedimento persistente, fixa documentos com SHA-256,
recupera evidências, conduz quantas rodadas consensuais forem úteis, organiza o
registro, profere uma decisão computacional e executa uma auditoria independente
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
- autorização separada para cliente, empresa e gestor em cada caso;
- contas com senha derivada por PBKDF2 e sessões expiráveis em cookie HttpOnly;
- verificação de e-mail, redefinição de senha por link de uso único e bloqueio
  da conta após tentativas de senha malsucedidas;
- convites de uso único vinculados ao e-mail e ao papel no caso;
- agenda processual com responsável, vencimento e notificações internas;
- aceite individual das duas partes antes da formação do procedimento, com o
  texto dos termos versionado no servidor e o hash SHA-256 do que foi exibido
  gravado no caso, na auditoria e no manifesto assinado;
- upload de texto e PDF;
- contraditório documentado: disponibilização, ciência, resposta ou renúncia e
  admissão antes do uso pela IA;
- hashing SHA-256 e chunking com sobreposição;
- embeddings OpenAI opcionais;
- recuperação vetorial com fallback lexical;
- agentes conciliador, organizador, julgador e revisor;
- rodadas de composição com respostas separadas da empresa e do cliente;
- Structured Outputs pela Responses API;
- prompts versionados e endereçados por hash, fixados no manifesto travado, com
  o modelo efetivamente usado e eventual divergência de prompt registrados em
  cada etapa;
- bateria de avaliação dos agentes (`evals/`), determinística no modo offline e
  opcionalmente contra o modelo real;
- manifesto imutável assinado com HMAC-SHA256;
- verificação do manifesto e da cadeia de auditoria;
- Decision Attestation assinada em Ed25519: artefato que um executor externo
  (instituição de pagamento ou contrato inteligente) verifica offline com a
  chave pública publicada em `/.well-known/valinor-signing-key`, emitido apenas
  com a cadeia de auditoria íntegra e sujeito a uma janela de contestação em que
  qualquer das partes pode barrar a execução;
- âncora pública opcional da attestation em relays Nostr (só hash, assinatura e
  identificadores — nunca o teor da decisão ou das partes), dando timestamp
  independente do servidor da Valinor; a âncora só é registrada quando algum
  relay aceita o evento, para a auditoria nunca apontar uma prova pública
  inexistente;
- etapas idempotentes e documentos imutáveis após o lock;
- modo seguro sem OpenAI, sempre inconclusivo e sujeito a revisão humana;
- relatório final Word com o histórico completo, decisão, auditoria e hashes;
- convites por e-mail transacional (SMTP) com fallback para log quando não configurado;
- autenticação obrigatória em todas as rotas quando `APP_ENV=production`, sem o atalho de tokens por papel;
- rate limiting por IP (janela deslizante) e logging estruturado com identificador de requisição;
- documentos armazenados fora do banco (object store local, S3-compatível ou memória nos testes), com o arquivo original preservado e baixável;
- criptografia dos documentos em repouso (AES-256-GCM) e download por link temporário assinado que dispensa nova autenticação e expira sozinho;
- PostgreSQL e migrações Alembic no ambiente Docker;
- testes automatizados e imagem Docker.

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
  -> auditoria independente
  -> relatório
  -> attestation assinada (opcional)
  -> janela de contestação
  -> execução externa do escrow
```

Nenhum material entra silenciosamente na decisão. Tudo precisa ser atribuído a
uma parte, disponibilizado à contraparte, reconhecido como recebido e respondido
ou expressamente dispensado. O gestor só pode admitir o material depois desse
percurso, e o lock é bloqueado enquanto houver pendência.

O aceite registra a versão **e o hash SHA-256** do texto exibido às partes:
participação voluntária, acesso a todo material, oportunidade de resposta,
composição consensual, decisão fundamentada por IA, auditoria independente e
revisão humana quando indicada. O texto vive em `app/terms/<versão>.md` e é
servido por `GET /terms`; versões publicadas nunca são editadas, e o caso não
pode ser travado se o aceite de alguma parte não puder mais ser reproduzido.

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
| `OPENAI_EMBEDDING_MODEL` | Modelo de embedding |
| `APP_ENV` | `development` ou `production`; em produção força autenticação, exige os segredos e desliga os tokens por papel |
| `DATABASE_URL` | Banco SQLAlchemy |
| `POSTGRES_DB` | Banco criado pelo Docker Compose |
| `POSTGRES_USER` | Usuário PostgreSQL do Compose |
| `POSTGRES_PASSWORD` | Senha PostgreSQL do Compose |
| `PLATFORM_SIGNING_SECRET` | Assina manifestos com HMAC-SHA256 e os links de download |
| `PLATFORM_ED25519_PRIVATE_KEY` | Seed de 32 bytes (base64) que assina as Decision Attestations; vazia desabilita a emissão |
| `CONTEST_WINDOW_DAYS` | Dias de contestação após a emissão da attestation, antes da execução externa |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |
| `MAX_UPLOAD_BYTES` | Limite de upload de PDF |
| `AUTH_REQUIRED` | Exige conta e participação; padrão `true` e obrigatório em produção |
| `EMAIL_VERIFICATION_REQUIRED` | Exige e-mail confirmado para atos no caso; forçado em produção |
| `EMAIL_VERIFICATION_TTL_HOURS` | Validade do link de confirmação de e-mail |
| `PASSWORD_RESET_TTL_MINUTES` | Validade do link de redefinição de senha |
| `LOGIN_MAX_ATTEMPTS` | Tentativas de senha antes do bloqueio da conta |
| `LOGIN_LOCKOUT_SECONDS` | Duração do bloqueio da conta |
| `AUTH_RATE_LIMIT_MAX_REQUESTS` | Limite das rotas de credencial por IP e janela |
| `AUTH_RATE_LIMIT_WINDOW_SECONDS` | Janela do limite das rotas de credencial |
| `RATE_LIMIT_ENABLED` | Liga o rate limiting por IP; padrão ligado em produção |
| `RATE_LIMIT_MAX_REQUESTS` | Requisições permitidas por janela e por IP |
| `RATE_LIMIT_WINDOW_SECONDS` | Tamanho da janela de rate limiting em segundos |
| `PUBLIC_BASE_URL` | URL pública usada no link de aceite do convite |
| `SMTP_HOST` / `SMTP_PORT` | Servidor de e-mail transacional para convites |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Credenciais SMTP |
| `SMTP_FROM` | Remetente dos convites |
| `SMTP_USE_TLS` | Usa STARTTLS na conexão SMTP |
| `DOCUMENT_STORAGE_BACKEND` | `local`, `s3` ou `memory` (testes) |
| `DOCUMENT_STORAGE_DIR` | Diretório do backend local |
| `DOCUMENT_S3_BUCKET` / `DOCUMENT_S3_PREFIX` | Bucket e prefixo no backend S3 |
| `DOCUMENT_S3_ENDPOINT_URL` / `DOCUMENT_S3_REGION` | Endpoint e região S3-compatíveis |
| `DOCUMENT_ENCRYPTION_KEY` | Chave AES-256-GCM (base64 de 32 bytes) para cifrar documentos |
| `DOWNLOAD_URL_TTL_SECONDS` | Validade dos links de download assinados |
| `NOSTR_PRIVATE_KEY_HEX` | Chave secp256k1 (hex) para ancorar attestations em relays Nostr; opcional |
| `NOSTR_RELAYS` | Relays Nostr (`wss://...`, separados por vírgula) para a âncora pública |

Gere os segredos:

```bash
# PLATFORM_SIGNING_SECRET (obrigatório em produção)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# DOCUMENT_ENCRYPTION_KEY, AES-256-GCM (obrigatória em produção)
python -m app.core.encryption

# PLATFORM_ED25519_PRIVATE_KEY, assina as Decision Attestations (opcional)
python -m app.core.attestation

# NOSTR_PRIVATE_KEY_HEX, âncora pública da attestation (opcional)
python -m app.core.nostr_anchor
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
| `POST /auth/verify-email` | Confirmar o e-mail pelo link de uso único |
| `POST /auth/verify-email/resend` | Reenviar o link de confirmação |
| `POST /auth/password-reset` | Pedir link de redefinição de senha |
| `POST /auth/password-reset/confirm` | Definir a nova senha e encerrar as sessões |
| `GET /auth/me` | Conta da sessão atual, com o estado de verificação do e-mail |
| `GET /terms` | Texto vigente dos termos, com versão e hash |
| `GET /terms/{version}` | Texto de uma versão específica dos termos |
| `GET /cases/{id}/invitations` | Listar convites do caso (gestor) |
| `POST /cases/{id}/invitations` | Convidar participante por e-mail e papel |
| `POST /invitations/accept` | Aceitar convite na conta correspondente |
| `GET /cases/{id}/deadlines` | Listar a agenda processual |
| `POST /cases/{id}/deadlines` | Criar prazo e notificações |
| `POST /cases/{id}/deadlines/{deadline_id}/complete` | Marcar o prazo como cumprido |
| `GET /cases` | Listar casos |
| `GET /cases/{id}` | Reabrir caso completo |
| `POST /cases/{id}/consent` | Registrar aceite individual da parte |
| `POST /cases/{id}/documents/text` | Adicionar texto |
| `POST /cases/{id}/documents/pdf` | Adicionar PDF |
| `POST /cases/{id}/documents/{document_id}/acknowledge` | Confirmar ciência da contraparte |
| `POST /cases/{id}/documents/{document_id}/respond` | Responder, contestar ou renunciar |
| `POST /cases/{id}/documents/{document_id}/admit` | Admitir material após contraditório |
| `GET /cases/{id}/documents/{document_id}/original` | Baixar o arquivo original armazenado |
| `POST /cases/{id}/documents/{document_id}/original-url` | Emitir link temporário e assinado do original |
| `GET /documents/download` | Baixar via link assinado (valida token e expiração) |
| `POST /cases/{id}/lock` | Travar manifesto |
| `POST /cases/{id}/conciliation` | Criar ou avançar uma rodada de composição |
| `GET /cases/{id}/manifest` | Ler o manifesto travado |
| `GET /cases/{id}/manifest/verify` | Verificar hash e assinatura |
| `GET /cases/{id}/chunks` | Listar os trechos indexados do caso |
| `GET /cases/{id}/retrieve` | Consultar evidências |
| `POST /cases/{id}/organize` | Organizar registro |
| `POST /cases/{id}/decide` | Proferir decisão da IA |
| `POST /cases/{id}/review` | Auditar decisão |
| `GET /cases/{id}/audit` | Verificar cadeia de auditoria |
| `GET /cases/{id}/report` | Obter relatório consolidado |
| `GET /cases/{id}/report.docx` | Baixar relatório final em Word |
| `POST /cases/{id}/attestation` | Emitir a Decision Attestation assinada |
| `GET /cases/{id}/attestation` | Ler a attestation emitida |
| `GET /cases/{id}/attestation/nostr-anchor` | Ler a âncora pública da attestation |
| `POST /cases/{id}/contest` | Contestar a decisão dentro da janela |
| `POST /attestations/verify` | Verificar uma attestation avulsa, sem contexto de caso |
| `GET /.well-known/valinor-signing-key` | Publicar a chave pública Ed25519 da plataforma |
| `GET /health` | Saúde da API, do banco e do modo de IA |

## Testes

```bash
source .venv/bin/activate
python -m pytest

# bateria de avaliação dos agentes (offline, determinística)
python -m evals.runner
# contra o modelo real, antes de trocar prompt ou modelo
python -m evals.runner --live

cd frontend
npm run build
npm audit --audit-level=moderate
```

Os testes cobrem o fluxo integral, contas, convites, isolamento entre os papéis, contraditório,
persistência, imutabilidade após o lock, idempotência, PDF, transições inválidas,
agenda, relatório Word, assinatura e auditoria. Somam-se a eles o ciclo de vida da
conta (verificação, redefinição e bloqueio), os termos versionados com hash no
consentimento e a procedência de prompt e modelo em cada etapa por IA.

A bateria de `evals/` mede propriedades da saída dos agentes — evidência citada
que existe, valores com lastro no registro, resultado parcial com fração
executável, procedência registrada e contingência nunca aprovada pela auditoria.
Cada métrica tem um controle negativo: um cenário com saída deliberadamente ruim
que ela precisa reprovar. Detalhes em `evals/README.md`.

## Limites antes de produção pública

- a conta já exige e-mail verificado para atuar no caso, oferece redefinição de
  senha e bloqueia tentativa repetida de senha, mas ainda não há autenticação
  multifator;
- ainda faltam política de privacidade, base legal declarada, canal do titular e
  exclusão ou portabilidade de dados (LGPD), incluindo o aviso de transferência
  internacional pelo processamento dos documentos no provedor de modelo;
- em `APP_ENV=production` a autenticação por conta é exigida em todas as rotas e
  os tokens por papel são desabilitados; o modo local com tokens permanece
  apenas em desenvolvimento;
- o envio de convites por SMTP já existe, mas depende de um provedor
  transacional configurado e de um domínio com SPF/DKIM para entrega confiável;
- os documentos ficam fora do banco (object store) e o texto dos chunks no
  banco, ambos cifrados em repouso com AES-256-GCM (`DOCUMENT_ENCRYPTION_KEY`,
  obrigatória em produção) e acessíveis por link temporário assinado; ainda
  falta rotação de chaves e um cofre dedicado;
- prompts têm versão e hash fixados no manifesto, e a bateria de `evals/` roda
  offline no CI; falta ampliar os cenários para disputas reais anonimizadas e
  rodar o modo live a cada troca de modelo;
- o texto dos termos é versionado e endereçado por hash, mas ainda não passou
  por validação jurídica;
- a assinatura HMAC prova integridade dentro da plataforma, não autoria externa;
- o rate limiting é em memória, adequado a uma instância; várias réplicas
  exigem um backend compartilhado (por exemplo Redis);
- a gestão de segredos ainda depende do ambiente, sem cofre dedicado;
- não há validação jurídica dos frameworks;
- decisões inconclusivas ou reprovadas pela auditoria exigem intervenção humana.

Antes de exposição pública, a próxima etapa é configurar o provedor SMTP com um
domínio autenticado (a verificação de e-mail depende de entrega confiável),
publicar a política de privacidade com os direitos do titular, obter a revisão
jurídica do rito e dos termos, montar CI e o ambiente de produção com TLS,
backup testado e monitoramento, e migrar o rate limiting para um backend
compartilhado com rotação de chaves e cofre de segredos.

## Referências OpenAI

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
