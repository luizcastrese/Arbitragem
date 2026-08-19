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
- autorização separada para cliente e empresa em cada caso, sem terceiro humano;
- contas com senha derivada por PBKDF2 e sessões expiráveis em cookie HttpOnly;
- convites de uso único vinculados ao e-mail e ao papel no caso;
- agenda processual aberta e encerrada pelo próprio rito, com notificações internas;
- aceite individual das duas partes antes da formação do procedimento;
- upload de texto e PDF;
- contraditório documentado: disponibilização, ciência, resposta ou renúncia e
  admissão automática antes do uso pela IA;
- hashing SHA-256 e chunking com sobreposição;
- embeddings OpenAI opcionais;
- recuperação vetorial com fallback lexical;
- agentes conciliador, organizador, julgador e revisor;
- rodadas de composição com respostas separadas da empresa e do cliente;
- Structured Outputs pela Responses API;
- manifesto imutável assinado com HMAC-SHA256;
- verificação do manifesto e da cadeia de auditoria;
- ancoragem pública do topo da cadeia de auditoria na trava do manifesto e no
  encerramento do caso, por dois publicadores independentes: relays Nostr e
  carimbo do tempo OpenTimestamps (Bitcoin);
- etapas idempotentes e documentos imutáveis após o lock;
- atos das partes idempotentes: reafirmar consentimento ou ciência não gera
  registro novo, e a manifestação sobre um material é ato único — para mudar de
  posição, apresenta-se material novo, que abre prazo para a contraparte;
- modo seguro sem OpenAI, sempre inconclusivo e sujeito a revisão humana;
- relatório final Word com o histórico completo, decisão, auditoria e hashes;
- convites por e-mail transacional (SMTP), com o link de aceite sempre
  devolvido a quem convidou e reemissão quando o link se perde;
- teor integral do material acessível a quem participa do caso, antes da
  ciência e da resposta;
- autenticação obrigatória em todas as rotas quando `APP_ENV=production`, sem o atalho de tokens por papel;
- rate limiting por IP (janela deslizante) e logging estruturado com identificador de requisição;
- documentos armazenados fora do banco (object store local, S3-compatível ou memória nos testes), com o arquivo original preservado e baixável;
- criptografia dos documentos em repouso (AES-256-GCM) e download por link temporário assinado que dispensa nova autenticação e expira sozinho;
- PostgreSQL e migrações Alembic no ambiente Docker;
- testes automatizados e imagem Docker.

## Fluxo

```text
caso aberto por uma das partes
  -> aceite bilateral                          (parte)
  -> convite à contraparte                     (parte)
  -> documentos identificados por autor e finalidade   (parte)
  -> prazo de ciência e resposta aberto        (rito)
  -> ciência da contraparte                    (parte)
  -> resposta, contestação ou renúncia         (parte)
     ou preclusão, se o prazo vencer em silêncio       (rito)
  -> admissão do material                      (rito)
  -> encerramento da produção pelas duas partes        (parte)
     ou preclusão, se o prazo vencer em silêncio       (rito)
  -> manifesto travado                         (rito)
  -> rodadas de composição                     (rito, com a posição de cada parte)
  -> organização                               (rito)
  -> decisão da IA                             (rito)
  -> auditoria independente                    (rito)
  -> se a auditoria ressalvou:
       ratificação pelas duas partes           (parte)
       ou encerramento sem decisão executável  (rito)
  -> attestation e janela de contestação       (rito)
  -> contestação, se houver                    (parte)
  -> relatório
```

Nenhum material entra silenciosamente na decisão. Tudo precisa ser atribuído a
uma parte, disponibilizado à contraparte, reconhecido como recebido e respondido
ou expressamente dispensado. Só então o material é admitido, e a trava é
bloqueada enquanto houver pendência.

## Não há terceiro humano

O procedimento tem exatamente dois participantes humanos: o cliente reclamante e
a empresa reclamada. O papel de gestor foi abolido. Todo ato que antes dependia
de um terceiro — admitir material, travar o manifesto, abrir e fechar prazos,
conduzir as rodadas de composição, organizar, julgar, auditar e emitir a
attestation — é executado pelo próprio rito, em `app/core/procedure.py`.

Nenhuma pré-condição foi relaxada nessa mudança. As mesmas verificações que antes
rodavam antes de alguém apertar o botão continuam valendo; o que muda é quem
executa. Cada ato do rito entra na cadeia de auditoria com `actor: "procedure"`,
e cada ato das partes com o papel de quem agiu — de modo que a própria trilha
prova que nenhuma pessoa conduziu o procedimento de dentro.

Isso também elimina uma assimetria: quem abre o caso declara de que lado está e
entra como parte. Ninguém administra o próprio litígio.

O que continua sendo das partes, e só delas:

- aceitar o procedimento;
- convidar a contraparte (e apenas ela);
- apresentar material e explicar sua finalidade;
- dar ciência e responder, contestar ou renunciar ao material da outra;
- declarar encerrada a própria produção (`POST /cases/{id}/submission-complete`);
- registrar a própria posição em cada rodada de composição, ou encerrá-la;
- ratificar ou recusar uma decisão que a auditoria ressalvou;
- contestar a decisão dentro da janela.

`POST /cases/{id}/advance` apenas pede ao rito que execute o que já pode ser
executado. Ele não concede poder algum a quem chama: cada passo continua
condicionado às suas próprias pré-condições, e chamá-lo com o caso pendente não
faz nada.

### Preclusão: silêncio não veta o procedimento

Sem um terceiro humano, uma parte que simplesmente não age travaria o caso para
sempre — não haveria ninguém para destravá-lo por fora. Por isso o rito abre
prazo para cada ato da contraparte, comunica esse prazo por e-mail, e, vencido o
prazo sem manifestação, registra a **preclusão**:

- material sem ciência ou sem resposta passa a `response_status: "precluded"`,
  com `acknowledged_by: "preclusion"`, e segue para admissão;
- parte que não declara encerrada a própria produção tem o encerramento
  registrado por decurso de prazo.

A preclusão **não presume concordância** com o material da outra parte: ela
apenas encerra uma oportunidade que foi aberta, comunicada e não exercida. O
resultado da entrega do aviso entra na cadeia de auditoria (`notice_delivered`,
`notice_transport`), justamente porque a legitimidade da preclusão depende de a
oportunidade ter sido comunicada.

### A revisão humana é das partes

Quando a auditoria independente faz ressalva — não aprova a decisão, ou indica
revisão humana —, a execução automática fica bloqueada. Antes o caso encalhava
aí: não havia a quem recorrer, e inventar um revisor humano contrariaria a
premissa do procedimento.

A revisão passa a ser de quem é titular do conflito. O rito abre a fase de
**ratificação**: informa as duas partes da ressalva concreta e pergunta se o
resultado vale assim mesmo.

- **as duas aceitam** → a execução é destravada e a attestation é emitida com
  `basis: "party_ratification"`, registrando de forma assinada que ela se apoia
  na vontade das partes, e não na aprovação automática. A ressalva continua
  visível no artefato: a ratificação não a apaga;
- **qualquer uma recusa** (com motivo, que entra no registro) → o caso encerra
  como `unresolved`, sem decisão executável;
- **o prazo vence em silêncio** → encerra como `unresolved`. Ratificar é
  endossar um resultado que o próprio sistema ressalvou; ninguém é levado a
  esse endosso por inércia. É o segundo ponto do fluxo, ao lado do
  consentimento, em que a preclusão não opera a favor do andamento.

Quem ratificou não pode contestar em seguida: a ratificação é o fundamento da
attestation, e voltar atrás dela seria contradizer o próprio aceite.

**A ratificação supera ressalvas de mérito, nunca a ausência de resultado.**
Uma decisão inconclusiva ou produzida em modo seguro não tem split a executar, e
nem o acordo das partes cria um: esses casos encerram direto como `unresolved`,
com o relatório e a cadeia de auditoria íntegros. Encerrar sem decisão é um
desfecho legítimo do procedimento, não uma falha — as partes ficam livres para
buscar outro caminho levando consigo o registro do que foi produzido aqui.

**O consentimento nunca preclui.** Adesão é voluntária: nenhum prazo transforma
silêncio em aceite. Um caso sem o aceite das duas partes simplesmente não avança,
e é o único ponto do fluxo em que isso é o comportamento correto.

As duas partes são sempre pessoas distintas: convidar o próprio e-mail é
recusado, e uma conta que já é parte não pode ocupar o outro polo. Sem terceiro
humano observando, é o código que impede alguém de litigar consigo mesmo e
colher uma decisão assinada de uma disputa que nunca existiu.

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
- **representantes e advogados:** podem apoiar qualquer parte na preparação e
  manifestação dentro do caso.

Não há um terceiro humano no caso. A condução do rito é do próprio sistema, e a
integridade do procedimento é verificável pela cadeia de auditoria em vez de
depender da imparcialidade de um administrador.

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
| `DATABASE_URL` | Banco SQLAlchemy |
| `POSTGRES_DB` | Banco criado pelo Docker Compose |
| `POSTGRES_USER` | Usuário PostgreSQL do Compose |
| `POSTGRES_PASSWORD` | Senha PostgreSQL do Compose |
| `PLATFORM_SIGNING_SECRET` | Assina manifestos com HMAC-SHA256 |
| `CONTRADICTORY_RESPONSE_DAYS` | Dias do prazo de ciência e resposta aberto pelo rito; padrão 7 |
| `SUBMISSION_CLOSURE_DAYS` | Dias para cada parte encerrar a própria produção; padrão 7 |
| `RATIFICATION_DAYS` | Dias para as partes ratificarem uma decisão ressalvada; padrão 7 |
| `COMPOSITION_MAX_ROUNDS` | Teto de rodadas de composição por caso; padrão 5 |
| `CONTEST_WINDOW_DAYS` | Dias da janela de contestação após a attestation; padrão 7 |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |
| `MAX_UPLOAD_BYTES` | Limite de upload de PDF |
| `AUTH_REQUIRED` | Exige conta e participação; padrão `true` e obrigatório em produção |
| `RATE_LIMIT_ENABLED` | Liga o rate limiting por IP; padrão ligado em produção |
| `RATE_LIMIT_MAX_REQUESTS` | Requisições permitidas por janela e por IP |
| `RATE_LIMIT_WINDOW_SECONDS` | Tamanho da janela de rate limiting em segundos |
| `PUBLIC_BASE_URL` | URL pública usada no link de aceite do convite; obrigatória e não-local em produção |
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
| `NOSTR_PRIVATE_KEY_HEX` | Chave secp256k1 (hex) para ancorar attestations e o topo da auditoria em relays Nostr; opcional |
| `NOSTR_RELAYS` | Relays Nostr (`wss://...`, separados por vírgula) para a âncora pública |
| `OTS_CALENDARS` | Calendários OpenTimestamps que carimbam o topo da auditoria; ligado por padrão, vazio desliga |

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
| `POST /cases/{id}/invitations` | Convidar a contraparte por e-mail |
| `POST /cases/{id}/invitations/{invitation_id}/resend` | Reemitir o convite pendente com link novo |
| `POST /invitations/accept` | Aceitar convite na conta correspondente |
| `GET /cases/{id}/deadlines` | Consultar a agenda mantida pelo rito |
| `GET /cases/{id}/procedure` | Estado do rito: etapa atual e o que falta, de quem |
| `POST /cases/{id}/advance` | Pedir ao rito que execute o que já é possível |
| `GET /cases` | Listar casos |
| `GET /cases/{id}` | Reabrir caso completo |
| `POST /cases/{id}/consent` | Registrar aceite individual da parte |
| `POST /cases/{id}/documents/text` | Adicionar texto |
| `POST /cases/{id}/documents/pdf` | Adicionar PDF |
| `POST /cases/{id}/documents/{document_id}/acknowledge` | Confirmar ciência da contraparte |
| `POST /cases/{id}/documents/{document_id}/respond` | Responder, contestar ou renunciar |
| `POST /cases/{id}/submission-complete` | Encerrar ou reabrir a própria produção de material |
| `GET /cases/{id}/documents/{document_id}/content` | Ler o teor integral do material |
| `GET /cases/{id}/documents/{document_id}/original` | Baixar o arquivo original armazenado |
| `POST /cases/{id}/documents/{document_id}/original-url` | Emitir link temporário e assinado do original |
| `GET /documents/download` | Baixar via link assinado (valida token e expiração) |
| `POST /cases/{id}/composition/position` | Registrar a própria posição na rodada |
| `POST /cases/{id}/composition/close` | Encerrar a composição |
| `POST /cases/{id}/ratification` | Ratificar ou recusar decisão ressalvada |
| `GET /cases/{id}/manifest/verify` | Verificar hash e assinatura |
| `GET /cases/{id}/retrieve` | Consultar evidências |
| `POST /cases/{id}/contest` | Contestar a decisão dentro da janela |
| `GET /cases/{id}/audit` | Verificar cadeia de auditoria, com o topo e as âncoras públicas |
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

Os testes cobrem o fluxo integral conduzido pelo rito, contas, convites restritos
à contraparte, o link de aceite alcançável em produção sem SMTP e sua reemissão,
a leitura do material pela contraparte, isolamento entre os papéis,
ancoragem e carimbo do topo da auditoria (contra relay Nostr e calendário
OpenTimestamps locais, sem rede externa), idempotência dos atos das partes,
contraditório, admissão automática,
trava automática e suas pré-condições, composição com a posição de cada parte,
persistência, imutabilidade após o lock, idempotência do `advance`, PDF, agenda
automática, relatório Word, assinatura e auditoria. Um teste específico verifica
que nenhum ato do procedimento é atribuído a um terceiro humano.

## Limites antes de produção pública

- contas por e-mail reduzem o risco de compartilhamento indevido, mas ainda não
  há verificação de e-mail, recuperação de acesso ou autenticação multifator;
- em `APP_ENV=production` a autenticação por conta é exigida em todas as rotas e
  os tokens por papel são desabilitados; o modo local com tokens permanece
  apenas em desenvolvimento;
- o envio de convites por SMTP depende de um provedor transacional
  configurado e de um domínio com SPF/DKIM para entrega confiável; sem ele o
  caso não trava, porque o link de aceite é devolvido a quem convidou e pode
  ser reemitido, mas a entrega passa a ser responsabilidade da parte;
- os documentos ficam fora do banco (object store) e o texto dos chunks no
  banco, ambos cifrados em repouso com AES-256-GCM (`DOCUMENT_ENCRYPTION_KEY`,
  obrigatória em produção) e acessíveis por link temporário assinado; ainda
  falta rotação de chaves e um cofre dedicado;
- prompts e avaliações ainda precisam de versionamento formal;
- a assinatura HMAC prova integridade dentro da plataforma, não autoria externa;
- a cadeia de auditoria é encadeada por SHA-256 sem segredo: ela detecta
  adulteração parcial, mas quem tiver escrita no banco pode reescrevê-la
  inteira e recalcular os hashes. Contra isso vale a âncora pública — o topo
  da cadeia é publicado em relays na trava e no encerramento, e `GET
  /cases/{id}/audit` devolve `head_hash`, `anchors` e `anchors_consistent`
  para que a conferência possa ser refeita contra as cópias públicas, sem
  depender deste servidor;
- a âncora Nostr prova publicação, não instante: o `created_at` de um evento
  Nostr é escrito pelo próprio autor, ou seja, por esta plataforma. Quem dá
  data por consenso é o carimbo OpenTimestamps, que agrega o hash em uma
  transação Bitcoin e produz uma prova autocontida, verificável anos depois com
  a ferramenta oficial e sem nenhum servidor da Valinor no ar:

  ```
  printf '%s' <audit_head_hash> > head.txt   # e o .ots correspondente ao lado
  ots verify head.txt.ots
  ```

  A prova nasce pendente e só vira carimbo em blockchain horas depois; até lá
  vale como recibo de calendário. O amadurecimento acontece em qualquer
  chamada posterior de `advance`, mas num caso encerrado ninguém mais age —
  por isso `python -m app.core.timestamping upgrade` precisa rodar
  periodicamente;
- o rate limiting é em memória, adequado a uma instância; várias réplicas
  exigem um backend compartilhado (por exemplo Redis);
- a gestão de segredos ainda depende do ambiente, sem cofre dedicado;
- não há validação jurídica dos frameworks;
- decisões inconclusivas encerram o caso sem resultado executável: a
  plataforma não oferece caminho de mérito além do que produziu;
- o rito roda de forma síncrona dentro da requisição da parte: um caso que
  destrava várias etapas de uma vez encadeia várias chamadas ao modelo na mesma
  requisição. Antes de exposição pública isso deve virar um worker em segundo
  plano;
- a janela de contestação ainda é apenas uma cláusula assinada na attestation:
  não há liquidação automática no vencimento nem revogação assinada quando o
  caso é contestado, de modo que um executor externo que verificou o artefato
  offline não sabe da contestação.

Antes de exposição pública, a próxima etapa é verificar e-mails, configurar o
provedor SMTP com um domínio autenticado, adicionar rotação de chaves e cofre de
segredos, migrar o rate limiting para um backend compartilhado e concluir uma
bateria de avaliações e revisão jurídica.

## Referências OpenAI

- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Embeddings](https://developers.openai.com/api/docs/guides/embeddings)
- [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini)
