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
- credenciais locais separadas para cliente, empresa e gestor em cada caso;
- contas com senha derivada por PBKDF2 e sessões expiráveis;
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
- manifesto imutável assinado com HMAC-SHA256;
- verificação do manifesto e da cadeia de auditoria;
- etapas idempotentes e documentos imutáveis após o lock;
- modo seguro sem OpenAI, sempre inconclusivo e sujeito a revisão humana;
- relatório final Word com o histórico completo, decisão, auditoria e hashes;
- convites por e-mail transacional (SMTP), com reenvio por convite; quando o
  envio não acontece, o link de aceite volta ao gestor para repasse manual, de
  modo que o caso nunca fica travado por falta de SMTP;
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
```

Nenhum material entra silenciosamente na decisão. Tudo precisa ser atribuído a
uma parte, disponibilizado à contraparte, reconhecido como recebido e respondido
ou expressamente dispensado. O gestor só pode admitir o material depois desse
percurso, e o lock é bloqueado enquanto houver pendência.

O aceite registra a versão dos termos exibidos às partes: participação
voluntária, acesso a todo material, oportunidade de resposta, composição
consensual, decisão fundamentada por IA, auditoria independente e revisão
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

# O Compose sobe em APP_ENV=production, onde o segredo de assinatura é
# obrigatório: sem ele o serviço se recusa a iniciar.
python -c "import secrets; print('PLATFORM_SIGNING_SECRET=' + secrets.token_urlsafe(48))" >> .env
python -m app.core.encryption | sed 's/^/DOCUMENT_ENCRYPTION_KEY=/' >> .env

docker compose up --build
```

O Compose publica a aplicação apenas em `127.0.0.1:8000`, inicia PostgreSQL,
aguarda o banco ficar saudável e executa as migrações antes da API. Troque
`POSTGRES_PASSWORD` no `.env` antes de usar fora da máquina local.

Os documentos ficam no volume `app_data`, montado em `/app/data`, e sobrevivem
ao restart do container. O banco fica no volume `postgres_data`.

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
| `DATABASE_URL` | Banco SQLAlchemy |
| `POSTGRES_DB` | Banco criado pelo Docker Compose |
| `POSTGRES_USER` | Usuário PostgreSQL do Compose |
| `POSTGRES_PASSWORD` | Senha PostgreSQL do Compose |
| `PLATFORM_SIGNING_SECRET` | Assina manifestos com HMAC-SHA256 |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |
| `MAX_UPLOAD_BYTES` | Limite de upload de PDF |
| `AUTH_REQUIRED` | Exige conta e participação no caso nas consultas (forçado em produção) |
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

Gere um segredo local:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
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
| `POST /cases/{id}/invitations` | Convidar participante por e-mail e papel |
| `POST /cases/{id}/invitations/{invitation_id}/resend` | Reemitir o token e reenviar o convite |
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
| `GET /cases/{id}/documents/{document_id}/original` | Baixar o arquivo original armazenado |
| `POST /cases/{id}/documents/{document_id}/original-url` | Emitir link temporário e assinado do original |
| `GET /documents/download` | Baixar via link assinado (valida token e expiração) |
| `POST /cases/{id}/lock` | Travar manifesto |
| `POST /cases/{id}/conciliation` | Criar ou avançar uma rodada de composição |
| `GET /cases/{id}/manifest/verify` | Verificar hash e assinatura |
| `GET /cases/{id}/retrieve` | Consultar evidências |
| `POST /cases/{id}/organize` | Organizar registro |
| `POST /cases/{id}/decide` | Proferir decisão da IA |
| `POST /cases/{id}/review` | Auditar decisão |
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
agenda, relatório Word, assinatura e auditoria.

## Limites antes de produção pública

- contas por e-mail reduzem o risco de compartilhamento indevido, mas ainda não
  há verificação de e-mail, recuperação de acesso ou autenticação multifator;
- em `APP_ENV=production` a autenticação por conta é exigida em todas as rotas e
  os tokens por papel são desabilitados; o modo local com tokens permanece
  apenas em desenvolvimento;
- o envio de convites por SMTP já existe, mas depende de um provedor
  transacional configurado e de um domínio com SPF/DKIM para entrega confiável;
  sem SMTP o link de aceite é devolvido ao gestor, que precisa repassá-lo por
  um canal próprio;
- os documentos ficam fora do banco (object store), cifrados em repouso com
  AES-256-GCM e acessíveis por link temporário assinado; ainda falta rotação de
  chaves e um cofre dedicado, e o texto derivado em chunks permanece no banco
  em claro para a recuperação — um passo seguinte é cifrá-lo ou tokenizá-lo;
- prompts e avaliações ainda precisam de versionamento formal;
- a assinatura HMAC prova integridade dentro da plataforma, não autoria externa;
- o rate limiting é em memória, adequado a uma instância; várias réplicas
  exigem um backend compartilhado (por exemplo Redis);
- a gestão de segredos ainda depende do ambiente, sem cofre dedicado;
- não há validação jurídica dos frameworks;
- decisões inconclusivas ou reprovadas pela auditoria exigem intervenção humana.

Antes de exposição pública, a próxima etapa é verificar e-mails, configurar o
provedor SMTP com um domínio autenticado, adicionar rotação de chaves e cofre de
segredos, cifrar ou tokenizar o texto dos chunks, migrar o rate limiting para um
backend compartilhado e concluir uma bateria de avaliações e revisão jurídica.

## Referências OpenAI

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
