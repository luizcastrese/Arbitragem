# Valinor

**Missão: tirar conflitos da Justiça.** A Valinor é uma alternativa mais
barata e mais rápida ao processo judicial. Primeiro ela propõe o acordo. Se o
acordo não sair, a IA arbitra, sempre com o raciocínio e os cálculos visíveis.

Ela atua em dois momentos:

- **antes do processo:** o conflito chega direto à Valinor e nem vira ação;
- **com processo já ajuizado:** as partes trocam a via judicial pela Valinor,
  e o resultado pode encerrar o processo, seja por acordo homologado, seja por
  sentença arbitral.

**Primeiro setor: disputas bancárias de massa** (cobranças e descontos não
reconhecidos, tarifas, juros, consignados, fraude de terceiro). São casos de
alto volume, processo lento e mérito pouco subjetivo. O núcleo continua
genérico, e um setor novo entra como outro framework de matéria.

Princípios:

- **acordo antes de decisão;**
- **transparência total:** provas citadas, regras aplicadas e, para cada
  valor, fórmula, entradas e documento de origem;
- **adesão voluntária:** a arbitragem só existe se as duas partes a
  escolherem;
- **abstenção quando houver dúvida:** sem base segura, o caso termina sem
  decisão de mérito, com o motivo explicado.

Qualquer que seja o desfecho, a saída é o **auto da decisão**: documento final
assinado e verificável, com as partes qualificadas, o percurso, o acordo ou a
fundamentação, o dispositivo e uma seção de **efeito jurídico** que diz o que
o documento é, se obriga as partes e como encerra o conflito ou o processo.

O sistema cria um procedimento persistente e autônomo, fixa documentos com
SHA-256, recupera evidências, conduz rodadas consensuais, organiza o registro,
profere uma decisão computacional, verifica invariantes formais de forma
determinística e executa uma auditoria automática por um segundo modelo. Cada
etapa é persistida e registrada em uma cadeia de auditoria encadeada por
hashes.

## Vias e limites legais

| Desfecho | Antes do processo | Com processo ajuizado |
|---|---|---|
| Acordo | Transação (CC, art. 840); vira título executivo com duas testemunhas (CPC, art. 784, III) ou homologação (CPC, arts. 515, III, e 725, VIII) | Juntado aos autos para homologação: extingue o processo com resolução de mérito (CPC, art. 487, III, b), sem custas remanescentes (CPC, art. 90, §3º) |
| Decisão, com arbitragem escolhida pelas duas partes e árbitro designado | Sentença arbitral assinada pelo árbitro, com efeitos de sentença judicial (Lei 9.307/96, art. 31) | Compromisso nos autos (Lei 9.307/96, art. 9º, §1º) e extinção do processo (CPC, art. 485, VII) |
| Decisão, sem a escolha das duas partes | Decisão fundamentada **não vinculante** | Idem; pode ser juntada como prova |
| Abstenção | Conflito segue pela via que as partes escolherem | Processo retoma o curso (CPC, art. 313, II, se suspenso) |
| Uma parte opta pela via judicial | Auto de encerramento com o histórico completo, para as duas partes auditarem e juntarem à petição | Idem; o processo retoma o curso |

Limites respeitados pelo código (`app/domain/pathway.py`):

- **Arbitragem só por escolha.** Cada parte escolhe, individualmente e dentro
  do caso, se quer arbitragem caso não haja acordo (`elects_arbitration` no
  aceite). Sem a escolha das duas, a trilha é não vinculante.
- **Consumo.** Em relação de consumo, a arbitragem só vale se o consumidor a
  escolher depois que o conflito surgiu (Lei 9.307/96, art. 4º, §2º; CDC,
  art. 51, VII). A escolha é um ato da parte num caso já aberto, nunca uma
  cláusula anterior. Ela fica registrada com a versão e o hash dos termos e é
  congelada no manifesto. Escolha feita sob termos anteriores a `2026-10-31`
  é recusada.
- **Árbitro pessoa física.** A lei exige árbitro pessoa capaz, com a
  confiança das partes, nomeado no compromisso e que assine a sentença (Lei
  9.307/96, arts. 10, II, 13, 14 e 26). O percurso (`app/domain/arbitration.py`):
  1. uma parte convida o árbitro (convite com papel `arbitrator`);
  2. ele aceita a nomeação com nome, CPF e qualificação, declara
     independência e revela o que houver (`POST /cases/{id}/arbitrator/accept`);
     quem é parte no caso não pode ser árbitro;
  3. cada parte que escolheu a arbitragem confirma **aquele** árbitro, com
     **aquela** declaração (`POST /cases/{id}/arbitrator/confirm`, conferido por
     hash); uma revelação nova zera as confirmações;
  4. a designação fecha na trava e fica congelada no manifesto. Sem árbitro
     designado, a decisão é não vinculante;
  5. com a decisão final (auditada, sem recurso pendente e com o prazo de
     recurso encerrado), o árbitro **adota e assina** a decisão como sentença
     arbitral, informando o lugar, ou **recusa** (`POST /cases/{id}/arbitral-award`).
     O auto é reemitido, encadeado ao anterior, com o hash do documento
     adotado; assinado, ele passa a `binding: true`.
- **Saída para a Justiça.** A adesão é voluntária nos dois sentidos: qualquer
  parte sai antes do desfecho, sozinha. O caso fica só para leitura, e o auto
  traz documentos, contraditório, rodadas de acordo e a trilha de auditoria
  completa (cada evento com seu hash e o anterior). Propostas de acordo
  constam como registro, não como confissão, e a confidencialidade pode
  limitar o uso como prova (Lei 13.140/2015, art. 30; CPC, art. 166, §1º).
- **Processo ajuizado.** O caso registra o número CNJ (com dígito verificador
  conferido) e o juízo. Entrar na Valinor não suspende nem extingue o
  processo por si só: isso depende de pedido das partes ao juízo.

> Este projeto é experimental. Hashes, assinaturas e verificadores comprovam
> integridade e invariantes formais, não a verdade material das alegações.

## O que funciona

- API FastAPI com validação e documentação OpenAPI;
- painel React responsivo;
- casos persistidos em SQLite;
- autorização separada para reclamante e reclamada em cada caso, que conduzem
  o procedimento sem um terceiro gestor;
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
- embeddings OpenRouter opcionais;
- recuperação vetorial com fallback lexical;
- agentes conciliador, organizador, julgador e revisor, cada um em uma
  família de modelo distinta via OpenRouter;
- rodadas de composição com respostas separadas da empresa e do cliente;
- Structured Outputs via OpenRouter (Chat Completions + JSON schema);
- prompts versionados e endereçados por hash, fixados no manifesto travado, com
  o modelo efetivamente usado e eventual divergência de prompt registrados em
  cada etapa;
- bateria de avaliação dos agentes (`evals/`), determinística no modo offline e
  opcionalmente contra o modelo real;
- manifesto imutável assinado com HMAC-SHA256;
- verificação do manifesto e da cadeia de auditoria;
- **auto da decisão**: documento final emitido automaticamente no acordo ou
  depois da auditoria da decisão, com qualificação das partes (CPF/CNPJ,
  inclusive CNPJ alfanumérico), objeto, relatório do procedimento, termo de
  acordo ou fundamentação e dispositivo, auditoria, recurso e dados de
  autenticidade; baixável em Word e em JSON assinado (Ed25519 ou HMAC-SHA256),
  verificável em `POST /decision-records/verify`; um recurso que corrige a
  decisão emite novo auto encadeado ao anterior;
- Decision Attestation assinada em Ed25519: declaração da decisão que qualquer
  terceiro verifica offline com a chave pública publicada em
  `/.well-known/valinor-signing-key`, emitida apenas com a cadeia de auditoria
  íntegra; abre o prazo de recurso automático. Não há execução automática nem forçada de valores;
- pagamento **opcional** da decisão via Stripe Connect: a parte reclamada pode
  escolher pagar o valor verificado da decisão; 10% ficam com a plataforma e o
  restante vai à parte reclamante (ver "Pagamento opcional" abaixo);
- âncora pública opcional da attestation em relays Nostr (só hash, assinatura e
  identificadores — nunca o teor da decisão ou das partes), dando timestamp
  independente do servidor da Valinor; a âncora só é registrada quando algum
  relay aceita o evento, para a auditoria nunca apontar uma prova pública
  inexistente;
- etapas idempotentes e documentos imutáveis após o lock;
- modo seguro sem chave de modelo, sempre inconclusivo e encerrado de forma autônoma;
- relatório final Word com o histórico completo, decisão, auditoria e hashes;
- convites por e-mail transacional (SMTP) com fallback para log quando não configurado; convite pendente pode ser reenviado, o que revoga o token anterior;
- a contraparte lê o teor do material no painel (e o original, quando houver) antes de confirmar ciência e responder;
- a conta exporta seus dados e pede eliminação por anonimização a partir do painel;
- autenticação obrigatória em todas as rotas quando `APP_ENV=production`, sem o atalho de tokens por papel;
- rate limiting por IP (janela deslizante) e logging estruturado com identificador de requisição;
- documentos armazenados fora do banco (object store local, S3-compatível ou memória nos testes), com o arquivo original preservado e baixável;
- criptografia dos documentos em repouso (AES-256-GCM) e download por link temporário assinado que dispensa nova autenticação e expira sozinho;
- PostgreSQL e migrações Alembic no ambiente Docker;
- testes automatizados e imagem Docker.

## Fluxo

```text
caso (via: antes do processo | processo ajuizado nº CNJ; matéria)
  -> aceite bilateral, com a escolha individual pela arbitragem (opcional)
  -> documentos e argumentos identificados por autor e finalidade
  -> ciência da contraparte
  -> resposta, contestação ou renúncia
  -> admissão do material
  -> manifesto travado
  -> rodadas de conciliação ou mediação
  -> organização
  -> decisão da IA
  -> verificação determinística
  -> auditoria automática
  -> (opcional) teste de estabilidade
  -> attestation assinada (opcional)
  -> recurso automático
  -> auto da decisão (acordo, decisão ou encerramento sem mérito), com o
     efeito jurídico: acordo para homologar, projeto de sentença arbitral ou
     decisão não vinculante
  -> pagamento opcional pela plataforma (Stripe Connect)

a qualquer momento antes do desfecho:
  -> uma parte opta pela via judicial (POST /cases/{id}/withdraw-to-court)
  -> o caso encerra sem acordo nem decisão
  -> auto de encerramento com todo o histórico e a trilha de auditoria,
     igual para as duas partes
```

Nenhum material entra silenciosamente na decisão. Tudo precisa ser atribuído a
uma parte, disponibilizado à contraparte, reconhecido como recebido e respondido
ou expressamente dispensado. O gestor é uma IA: admite o material depois desse
percurso, e só trava o conjunto quando as duas partes declararam encerrada a
própria apresentação. Uma parte não conduz a etapa da outra.

O aceite registra a versão **e o hash SHA-256** do texto exibido às partes:
missão e dois momentos de atuação, matérias e exclusões, participação
voluntária, qualificação por CPF/CNPJ, acesso a todo material, oportunidade de
resposta, acordo primeiro, escolha opcional pela arbitragem (com a regra do
consumidor), decisão por IA com raciocínio e cálculos visíveis, abstenção na
dúvida, auditoria, recurso automático e auto da decisão. O texto vive em
`app/terms/<versão>.md` e é servido por `GET /terms`; versões publicadas nunca
são editadas, e o caso não pode ser travado se o aceite de alguma parte não
puder mais ser reproduzido.

Depois do lock, novos documentos não são aceitos. Cada rodada de composição
considera as posições atualizadas das partes. A IA informa se vale continuar,
quantas rodadas adicionais parecem adequadas e qual deve ser o próximo foco.

## Usuários do produto

- **reclamante:** quem abre o caso — em geral o consumidor que contesta
  uma cobrança, mas pode ser a instituição; apresenta sua versão, documentos,
  pedidos e respostas às propostas;
- **reclamada:** a outra parte; apresenta defesa e documentos e formula
  contrapropostas;
- **gestor:** uma IA do procedimento. Admite material, trava o conjunto e avança
  composição, organização, decisão e auditoria. Não fala por nenhuma parte e não
  julga o mérito;
- **as próprias partes:** aceitam o rito, escolhem ou não a arbitragem,
  apresentam material, respondem ao contraditório e às propostas; uma não
  registra manifestação, aceite ou escolha em nome da outra;
- **representantes e advogados:** podem apoiar qualquer parte, inclusive para
  juntar o auto ao processo.

O caso escolhe a matéria na abertura (`matter_framework_id`). A padrão é
`consumer_banking_v1`; em matéria de consumo, o caso registra qual parte é o
consumidor (`consumer_party`, padrão: a reclamante). `digital_services_b2b_v1`
continua disponível. O levantamento anterior sobre serviços digitais está em
[`docs/mercado-servicos-digitais.md`](docs/mercado-servicos-digitais.md).

### Frameworks: abordagem e matéria

Todo caso trava no manifesto duas camadas de framework, que se somam:

- **abordagem** (`commercial_balanced_v1`): como a IA trata qualquer caso —
  prioridade contratual, proporcionalidade, boa-fé, vedação ao enriquecimento
  injusto e análise contextual de atrasos;
- **matéria**: as regras do assunto, com escopo, exclusões e limite de valor
  próprios. `consumer_banking_v1` (bancário de consumo, limite de
  R$ 100.000,00) é a padrão; `digital_services_b2b_v1` segue disponível. A
  matéria de consumo marca `consumer_relation`, que liga as salvaguardas da
  via arbitral.

A decisão declara a matéria e pode aplicar regras das duas camadas; o
verificador determinístico confere contra a composição. Uma matéria nova (por
exemplo, telecom ou planos de saúde) entra como outro framework de matéria, sem duplicar a
abordagem. Os frameworks publicados são imutáveis: mudar o conteúdo exige um
id novo. Manifestos travados antes da separação continuam resolvidos só pelo
framework que fixaram.

## Rodar localmente

Requisitos: Python 3.10+ (a imagem usa 3.11) e Node.js 20.19+.

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
aguarda o banco ficar saudável, executa as migrações antes da API e mantém os
documentos do backend local no volume `document_data`. Troque
`POSTGRES_PASSWORD` no `.env` antes de usar fora da máquina local. Para publicar,
siga o [`deploy no Fly.io`](docs/deploy-fly.md) (Managed Postgres + volume) e o
[`checklist de publicação`](docs/checklist-publicacao.md).

Para aplicar migrações sem Docker:

```bash
alembic upgrade head
```

## Configuração

Variáveis do arquivo `.env`:

| Variável | Uso |
|---|---|
| `OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL` | Provedor único de modelos. Sem a chave, o sistema fica em modo seguro inconclusivo |
| `LLM_DEFAULT_PROVIDER` | Padrão `openrouter`. `openai` permanece só como override explícito |
| `CONCILIATOR_PROVIDER` / `CONCILIATOR_MODEL` | Política do conciliador (padrão `google/gemini-2.5-flash`) |
| `ORGANIZER_PROVIDER` / `ORGANIZER_MODEL` | Política do organizador (padrão `openai/gpt-4.1-mini`) |
| `JUDGE_PROVIDER` / `JUDGE_MODEL` | Política do julgador. Vazio: o seletor escolhe pelo benchmark de inteligência |
| `REVIEWER_PROVIDER` / `REVIEWER_MODEL` | Política do revisor; em produção deve ser de outra família |
| `APPEAL_PROVIDER` / `APPEAL_MODEL` | Política do recurso automático |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` | Embeddings via OpenRouter |
| `SELECTOR_PROVIDER` / `SELECTOR_MODEL` | Agente que escolhe os modelos na trava do manifesto |
| `MODEL_SELECTOR_ENABLED` | Liga o seletor (padrão `true`). Sem chave, cai no ranking determinístico |
| `OPENAI_API_KEY` | Override legado do adapter OpenAI direto; não é o caminho padrão |
| `OPENAI_MODEL` | **Deprecated.** Só ainda lido se um agente não tiver `*_MODEL` e o provedor não for OpenRouter |
| `OPENAI_EMBEDDING_MODEL` | **Deprecated.** Use `EMBEDDING_MODEL` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Timeout explícito |
| `LLM_MAX_RETRIES` | Retries só para erros transitórios |
| `LLM_ALLOWED_PROVIDERS` / `LLM_ALLOWED_MODELS` | Allowlists |
| `LLM_FALLBACK_PROVIDER` / `LLM_FALLBACK_MODEL` | Fallback explícito (nunca silencioso) |
| `FRAMEWORK_ID` | Framework de **matéria** padrão quando o caso não escolhe uma (padrão `consumer_banking_v1`) |
| `APPROACH_FRAMEWORK_ID` | Framework de **abordagem** somado à matéria em todo caso (padrão `commercial_balanced_v1`). Trocar as camadas derruba o boot |
| `DECISION_STABILITY_ENABLED` | Segunda execução controlada |
| `DECISION_STABILITY_RUNS` / `DECISION_STABILITY_THRESHOLD` | Política de estabilidade |
| `APP_ENV` | `development` ou `production`; em produção força autenticação, exige os segredos e desliga os tokens por papel |
| `EXPOSE_API_DOCS` | Expõe `/docs`, `/redoc` e `/openapi.json`; padrão ligado em desenvolvimento e desligado em produção |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Pagamento opcional da decisão. Sem os dois, o recurso fica desligado (`503`) e o restante funciona igual |
| `PLATFORM_FEE_BPS` | Taxa da plataforma sobre o valor pago, em basis points (padrão `1000` = 10%). Mudar o valor exige nova versão dos termos |
| `PUBLIC_APP_URL` | URL pública do front, usada nos retornos do Stripe |
| `DATABASE_URL` | Banco SQLAlchemy |
| `POSTGRES_DB` | Banco criado pelo Docker Compose |
| `POSTGRES_USER` | Usuário PostgreSQL do Compose |
| `POSTGRES_PASSWORD` | Senha PostgreSQL do Compose |
| `PLATFORM_SIGNING_SECRET` | Assina manifestos com HMAC-SHA256 e os links de download |
| `PLATFORM_ED25519_PRIVATE_KEY` | Seed de 32 bytes (base64) que assina as Decision Attestations e o auto da decisão; vazia desabilita as attestations e o auto passa a HMAC |
| `CONTEST_WINDOW_DAYS` | Dias do prazo de recurso automático após a emissão da attestation |
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
# PLATFORM_SIGNING_SECRET (obrigatório em produção; mínimo de 32 caracteres)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# DOCUMENT_ENCRYPTION_KEY, AES-256-GCM (obrigatória em produção)
python -m app.core.encryption

# PLATFORM_ED25519_PRIVATE_KEY, assina as Decision Attestations (opcional)
python -m app.core.attestation

# NOSTR_PRIVATE_KEY_HEX, âncora pública da attestation (opcional)
python -m app.core.nostr_anchor
```

Sem `OPENROUTER_API_KEY`, o sistema continua executável. Ele organiza o material
com recuperação lexical, mas não profere decisão de mérito: o resultado fica
explicitamente inconclusivo. Nenhum percentual ou pagamento é inventado.

Os agentes não concentram a decisão em um único laboratório. Na trava do
manifesto, um **agente seletor** consulta os benchmarks da OpenRouter
(Artificial Analysis) e escolhe o modelo de cada etapa conforme a necessidade:
conciliação prefere custo e velocidade, o julgador prioriza inteligência, o
revisor e o recurso precisam ser de famílias distintas da do julgador. Sem
chave, o mesmo critério roda de forma determinística sobre um catálogo local.
A escolha fica congelada no manifesto. Em produção, julgador e revisor da
mesma família derrubam o boot.

## Operação

`docs/runbook-operacao.md` reúne os procedimentos que precisam existir antes do
primeiro caso real:

- backup e rotação da chave Ed25519 (perdê-la torna inverificável toda
  attestation já emitida);
- backup do banco, do object store e dos segredos, com teste de restauração;
- expurgo de documentos por retenção, via cron:
  `python -m app.retention` (`--dry-run` para simular);
- configuração de `TRUSTED_PROXY_IPS` atrás de proxy reverso;
- o que monitorar nas etapas assíncronas.

`GET /` lista avisos de configuração pendente (segredo de desenvolvimento,
proxy não declarado, controlador de dados ausente). Em produção, os itens
críticos derrubam o boot em vez de virar aviso.

## Endpoints principais

| Endpoint | Função |
|---|---|
| `POST /cases` | Criar caso, com via (`entry_point`, `lawsuit_number`, `court`), matéria e parte consumidora |
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
| `GET /privacy` | Política de privacidade vigente, com hash e controlador |
| `GET /privacy/{version}` | Texto de uma versão específica da política |
| `GET /account/data-export` | Acesso e portabilidade dos dados do titular |
| `GET /account/erasure/preview` | Diz se a eliminação seria aceita e o que preserva |
| `POST /account/erasure` | Eliminação por anonimização da conta |
| `GET /cases/{id}/invitations` | Listar convites do caso (partes) |
| `POST /cases/{id}/invitations` | Convidar participante por e-mail e papel |
| `POST /cases/{id}/invitations/{invitation_id}/resend` | Reemitir convite pendente (revoga o token anterior) |
| `POST /invitations/accept` | Aceitar convite na conta correspondente |
| `GET /cases/{id}/deadlines` | Listar a agenda processual |
| `POST /cases/{id}/deadlines` | Criar prazo e notificações |
| `POST /cases/{id}/deadlines/{deadline_id}/complete` | Marcar o prazo como cumprido |
| `POST /payments/connect/onboarding` | Cria a conta Stripe Connect da pessoa e devolve o link de cadastro de recebedor |
| `GET /payments/connect/status` | Informa se a conta já pode receber repasses |
| `GET /cases/{id}/settlement` | Oferta de pagamento da decisão (valor, taxa, motivo de indisponibilidade) e estado do pagamento |
| `POST /cases/{id}/settlement/checkout` | A parte reclamada escolhe pagar: devolve a URL do Checkout |
| `POST /stripe/webhook` | Confirmação do Stripe (assinada). Só o webhook marca o pagamento como pago |
| `GET /cases` | Listar casos |
| `GET /cases/{id}` | Reabrir caso completo |
| `POST /cases/{id}/arbitrator/accept` | O árbitro convidado aceita a nomeação, se qualifica e declara independência |
| `POST /cases/{id}/arbitrator/confirm` | A parte que escolheu a arbitragem confirma o árbitro, antes da trava |
| `POST /cases/{id}/arbitral-award` | O árbitro designado adota e assina a decisão final como sentença arbitral, ou recusa |
| `POST /cases/{id}/withdraw-to-court` | A parte opta pela via judicial: encerra o caso e emite o auto com todo o histórico até ali |
| `POST /cases/{id}/consent` | Registrar aceite individual da parte, com o CPF/CNPJ dela e a escolha opcional pela arbitragem (`elects_arbitration`) |
| `POST /cases/{id}/conciliation/{round}/agreement` | Aceitar ou recusar individualmente a proposta da rodada; o acordo exige os dois aceites |
| `POST /cases/{id}/documents/text` | Adicionar texto |
| `POST /cases/{id}/documents/pdf` | Adicionar PDF |
| `POST /cases/{id}/documents/{document_id}/acknowledge` | Confirmar ciência da contraparte |
| `POST /cases/{id}/documents/{document_id}/respond` | Responder, contestar ou renunciar |
| `POST /cases/{id}/documents/{document_id}/admit` | Admitir material após contraditório |
| `GET /cases/{id}/documents/{document_id}/content` | Ler o teor do material (participantes do caso) |
| `GET /cases/{id}/documents/{document_id}/original` | Baixar o arquivo original armazenado |
| `POST /cases/{id}/documents/{document_id}/original-url` | Emitir link temporário e assinado do original |
| `GET /documents/download` | Baixar via link assinado (valida token e expiração) |
| `POST /cases/{id}/lock` | Travar manifesto |
| `POST /cases/{id}/conciliation` | Criar ou avançar uma rodada de composição (assíncrono) |
| `GET /cases/{id}/manifest` | Ler o manifesto travado |
| `GET /cases/{id}/manifest/verify` | Verificar hash e assinatura |
| `GET /cases/{id}/chunks` | Listar os trechos indexados do caso |
| `GET /cases/{id}/retrieve` | Consultar evidências |
| `POST /cases/{id}/organize` | Organizar registro (assíncrono) |
| `POST /cases/{id}/decide` | Proferir decisão da IA (assíncrono) |
| `POST /cases/{id}/review` | Auditar decisão (assíncrono) |
| `GET /cases/{id}/audit` | Verificar cadeia de auditoria |
| `GET /cases/{id}/report` | Obter relatório consolidado |
| `GET /cases/{id}/report.docx` | Baixar o relatório técnico em Word |
| `POST /cases/{id}/decision-record` | Emitir (ou devolver) o auto da decisão vigente |
| `GET /cases/{id}/decision-record` | Ler o auto da decisão assinado (JSON) |
| `GET /cases/{id}/decision-record.docx` | Baixar o auto da decisão em Word |
| `POST /decision-records/verify` | Verificar hash e assinatura de um auto |
| `POST /cases/{id}/attestation` | Emitir a Decision Attestation assinada |
| `GET /cases/{id}/attestation` | Ler a attestation emitida |
| `GET /cases/{id}/attestation/nostr-anchor` | Ler a âncora pública da attestation |
| `POST /cases/{id}/contest` | Recurso automático estruturado (assíncrono) |
| `GET /cases/{id}/stage/{stage}` | Andamento de uma etapa assíncrona |
| `GET /cases/{id}/verification` | Resultado do verificador determinístico |
| `GET /cases/{id}/appeals` | Recursos automáticos do caso |
| `GET /frameworks` | Frameworks versionados disponíveis |
| `POST /attestations/verify` | Verificar uma attestation avulsa, sem contexto de caso |
| `GET /.well-known/valinor-signing-key` | Publicar a chave pública Ed25519 da plataforma |
| `GET /health` | Saúde da API, do banco, do e-mail e do modo de IA |

### Etapas assíncronas

As cinco etapas marcadas como assíncronas chamam modelos de linguagem: com
timeout, novas tentativas e execuções de estabilidade, uma decisão pode levar
minutos. Mantê-las dentro do request significava uma conexão aberta esse tempo
todo — e um gateway que a derruba antes do fim, deixando o cliente sem saber se
a etapa concluiu.

Elas respondem **`202`** imediatamente:

```json
{
  "state": "processing",
  "stage": "decide",
  "poll": "/cases/{id}/stage/decide"
}
```

O cliente acompanha em `GET /cases/{id}/stage/{stage}`, que devolve
`processing`, `completed` (com `result`) ou `failed` (com `error`). Uma etapa
que falha devolve o caso ao estado anterior, então basta repetir a chamada.

Para um cliente que prefere uma chamada só, `?wait=<segundos>` (até 300) faz a
requisição aguardar: se a etapa terminar dentro do prazo, a resposta é `200`
com o resultado, como antes; se estourar, vira `202` e o trabalho continua.

```bash
# assíncrono (padrão)
curl -X POST .../cases/$ID/decide
curl .../cases/$ID/stage/decide

# síncrono, aguardando até 120s
curl -X POST ".../cases/$ID/decide?wait=120"
```

As etapas rodam no processo da aplicação (`STAGE_WORKERS` controla quantas em
paralelo). Um caso preso em `processing_*` é liberado pelo TTL de 10 minutos.

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
- a camada de proteção de dados existe: política de privacidade versionada e
  endereçada por hash (`GET /privacy`), bases legais declaradas, aviso de
  transferência internacional pelo processamento no provedor de modelo, aviso
  sobre a âncora pública em Nostr, exportação (`GET /account/data-export`),
  eliminação por anonimização (`POST /account/erasure`) e expurgo por retenção
  (`python -m app.retention`). O texto da política, porém, **ainda não passou
  por validação jurídica**, e `DATA_CONTROLLER_NAME`/`PRIVACY_CONTACT_EMAIL`
  precisam apontar para um responsável real;
- em `APP_ENV=production` a autenticação por conta é exigida em todas as rotas e
  os tokens por papel são desabilitados; o modo local com tokens permanece
  apenas em desenvolvimento;
- o envio de convites por SMTP já existe, mas depende de um provedor
  transacional configurado e de um domínio com SPF/DKIM para entrega confiável;
- os documentos ficam fora do banco (object store) e o texto dos chunks no
  banco, ambos cifrados em repouso com AES-256-GCM (`DOCUMENT_ENCRYPTION_KEY`,
  obrigatória em produção) e acessíveis por link temporário assinado; a chave de
  assinatura Ed25519 tem rotação com chaves aposentadas
  (`PLATFORM_ED25519_RETIRED_PUBLIC_KEYS`, runbook em
  `docs/runbook-operacao.md`), mas `DOCUMENT_ENCRYPTION_KEY` ainda não tem
  rotação e a guarda dos segredos depende de um cofre externo;
- prompts têm versão e hash fixados no manifesto, e a bateria de `evals/` roda
  offline no CI; falta ampliar os cenários para disputas reais anonimizadas e
  rodar o modo live a cada troca de modelo;
- o texto dos termos é versionado e endereçado por hash, mas ainda não passou
  por validação jurídica;
- **a via arbitral precisa de revisão jurídica antes do primeiro caso real:**
  - a assinatura do árbitro é um ato autenticado na conta dele, aceito pelas
    partes nos termos (MP 2.200-2/2001, art. 10, §2º). Avaliar se convém
    exigir assinatura qualificada ICP-Brasil;
  - o compromisso extrajudicial pede duas testemunhas ou instrumento público
    (Lei 9.307/96, art. 9º, §2º) e os elementos do art. 10 (inclusive o lugar
    da sentença, hoje informado na assinatura). O aceite eletrônico das
    partes ainda não substitui essa formalidade;
  - o árbitro só adota ou recusa a decisão da IA; uma sentença própria fica
    fora da plataforma. Também faltam honorários do árbitro, a instituição
    arbitral e o regulamento que o compromisso adota;
- a matéria bancária cita lei e jurisprudência como parâmetros (Súmulas 297,
  382 e 479 do STJ, Tema 1061, EAREsp 676.608, REsp 1.061.530); elas precisam
  de revisão jurídica e de acompanhamento de vigência;
- a assinatura HMAC prova integridade dentro da plataforma, não autoria externa;
- o rate limiting é em memória, adequado a uma instância; várias réplicas
  exigem um backend compartilhado (por exemplo Redis). Atrás de proxy,
  `TRUSTED_PROXY_IPS` precisa estar configurado, senão todos os clientes
  compartilham a mesma chave de limite;
- as etapas de modelo rodam em segundo plano no próprio processo, sem fila
  durável: um restart no meio de uma etapa a perde (o caso é liberado pelo TTL
  e a chamada pode ser repetida). Volume maior pede uma fila externa;
- a gestão de segredos ainda depende do ambiente, sem cofre dedicado;
- não há validação jurídica dos frameworks;
- a confidencialidade das tratativas de acordo (Lei 13.140/2015, art. 30)
  precisa de definição jurídica: hoje o auto as registra para as partes, com
  a ressalva de que não são confissão;
- as rodadas de acordo e a decisão ainda não recebem a via do caso no prompt:
  o efeito jurídico é calculado depois, no auto;
- decisões inconclusivas, inadmissíveis ou invalidadas encerram o procedimento
  de forma autônoma; não há julgador humano interno.

Antes de exposição pública, o que resta é operacional e jurídico, não de
produto: configurar o provedor SMTP com um domínio autenticado (a verificação
de e-mail depende de entrega confiável), obter a revisão jurídica do rito, dos
termos e da política de privacidade, subir o ambiente de produção com TLS,
executar pelo menos uma restauração de backup de verdade
(`docs/runbook-operacao.md`) e montar monitoramento. Com mais de uma réplica,
migrar o rate limiting e a fila de etapas para backends compartilhados.

## Referências OpenRouter

- [OpenRouter API](https://openrouter.ai/docs/api-reference/overview)
- [Structured Outputs](https://openrouter.ai/docs/features/structured-outputs)
- [Models](https://openrouter.ai/models)

## Pagamento opcional da decisão

A plataforma nunca debita ou retém valores por força da decisão. O pagamento
é uma saída que a parte reclamada pode escolher para cumprir o resultado.

- **Quando existe oferta:** decisão de mérito verificada e atestada, a favor do
  reclamante (`claimant` ou `partial`), com `remedy_calculation` em minor units,
  sem recurso pendente e depois do fim do prazo de contestação (ou do recurso).
  Sem valor verificado, não há oferta. A decisão a favor do reclamado não gera
  pagamento.
- **Fluxo:** o reclamante faz o cadastro de recebedor
  (`POST /payments/connect/onboarding`); o reclamado abre o Checkout
  (`POST /cases/{id}/settlement/checkout`) e paga. O Stripe repassa à conta do
  reclamante, retendo `PLATFORM_FEE_BPS` como `application_fee_amount`. É uma
  cobrança com destino: a plataforma não custodia o dinheiro e absorve as
  tarifas do Stripe.
- **Confirmação:** apenas o webhook `checkout.session.completed` (ou
  `async_payment_succeeded`) marca `paid`, após conferir valor e moeda. O
  retorno do navegador não confirma nada. Configure no Stripe o endpoint
  `/stripe/webhook` com os eventos `checkout.session.completed`,
  `checkout.session.async_payment_succeeded`,
  `checkout.session.async_payment_failed` e `checkout.session.expired`.
- **Vínculo:** o pagamento é único por attestation. Uma correção em recurso gera
  nova attestation e, portanto, nova oferta. Cada passo entra na cadeia de
  auditoria.
- **Termos:** a cláusula 10.1 (termos `2026-11-01`) descreve o pagamento e a taxa.
  Como os textos ainda aguardam revisão jurídica, trate o enquadramento
  (intermediação de pagamento, tributação, Banco Central) como pendência antes
  da exposição pública.
