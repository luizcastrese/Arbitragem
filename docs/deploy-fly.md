# Deploy no Fly.io (MVP, uma réplica)

Este é o caminho de publicação recomendado: um Machine, Fly Managed Postgres
e um volume persistente para os documentos. Use-o junto com o
[`checklist de publicação`](checklist-publicacao.md) — o checklist continua a
barreira mínima (e-mail, backup, smoke test, jurídico). Daqui sai só a
instalação no Fly.

Não use `fly postgres create` (Postgres não gerenciado). O produto espera
**Fly Managed Postgres** (`fly mpg`).

## O que o `fly.toml` já fixa

| Decisão | Valor | Por quê |
|---|---|---|
| Réplicas | 1 Machine | Rate limit e etapas assíncronas vivem na memória do processo |
| HTTP | 443 → `8000` | O `Dockerfile` sobe uvicorn em `0.0.0.0:8000` com `--no-proxy-headers` |
| Compute | `shared-cpu-1x` / 1 GB | Python + duas etapas de modelo; 256 MB é pouco |
| Auto-stop | `off` (always-on) | Parar o Machine no ócio mata trabalho de modelo e zera o rate limit; o boot ainda roda `alembic`. Always-on neste tamanho é o MVP barato. Para um staging ocioso, mude para `"stop"` e `min_machines_running = 0` |
| Volume | `documents` → `/app/data/documents` | `DOCUMENT_STORAGE_BACKEND=local`; recriar o Machine sem volume apaga os arquivos |
| Região | `gru` | MPG disponível e próxima do público LGPD. App, cluster e volume precisam estar na **mesma** região |

O `CMD` da imagem não muda: `alembic upgrade head && uvicorn ... --port 8000`.
Não há `release_command` no Fly — as migrações já rodam no boot.

## Pré-requisitos

- [flyctl](https://fly.io/docs/flyctl/install/) instalado
- `fly auth login`
- Segredos gerados **fora** do repositório (cofre). Nada do que segue vai
  para o git:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # PLATFORM_SIGNING_SECRET
python -m app.core.encryption                                  # DOCUMENT_ENCRYPTION_KEY
python -m app.core.attestation                                 # opcional, attestations
```

Substitua `valinor` e `gru` se o nome da app ou a região forem outros. Se
mudar, edite `app` e `primary_region` em `fly.toml` antes do primeiro deploy.

## 1. Criar a app

```bash
fly apps create valinor
```

Confira (ou ajuste) `app = "valinor"` e `primary_region = "gru"` em `fly.toml`.

## 2. Criar o Managed Postgres

Plano **Basic** basta no piloto (2 shared vCPU, 1 GB). Volume inicial 10 GB.

```bash
fly mpg create --name valinor-db --region gru --plan basic --volume-size 10
fly mpg list
```

Anote o **cluster ID**. Não publique a porta do Postgres: o MPG só existe na
rede privada da organização.

## 3. Anexar o banco à app

O attach grava `DATABASE_URL` (URL *pooled*, via PgBouncer) e pode reiniciar
a app. Se os outros segredos ainda não existirem, o boot de produção recusa
— isso é esperado; o deploy do passo 6 é que precisa subir limpo.

A aplicação reescreve `postgres://` → `postgresql+psycopg://` e desliga
prepared statements. Não copie a senha para o repositório nem rode
`fly secrets set DATABASE_URL=...` (isso sobrescreve o attach).

```bash
fly mpg attach <CLUSTER_ID> -a valinor
```

`DATABASE_URL` passa a existir como secret. Não rode `fly secrets set
DATABASE_URL=...` — isso sobrescreveria o attach. SQLite e a senha
`change-this-password` são recusados no boot de produção.

## 4. Criar o volume de documentos

O nome (`documents`) tem de bater com `[mounts].source` no `fly.toml`. Região
igual à da app. 3 GB cobrem o MVP; snapshots diários ficam 14 dias.

```bash
fly volumes create documents --region gru --size 3 --yes
fly volumes list
```

Se o volume ainda não existir, o primeiro `fly deploy` também pode criá-lo
por `initial_size`. Criar na mão deixa o tamanho e a região explícitos.

## 5. Segredos (checklist de publicação)

`APP_ENV`, storage local, `TRUSTED_PROXY_IPS=private` e `STAGE_WORKERS=2` já
estão no `[env]` do `fly.toml`. O resto entra como secret. Use o hostname
real (`https://valinor.fly.dev` ou o domínio próprio).

```bash
APP_HOST="https://valinor.fly.dev"

fly secrets set -a valinor \
  PUBLIC_BASE_URL="$APP_HOST" \
  CORS_ORIGINS="$APP_HOST" \
  PLATFORM_SIGNING_SECRET="..." \
  DOCUMENT_ENCRYPTION_KEY="..." \
  SMTP_HOST="..." \
  SMTP_PORT="587" \
  SMTP_USERNAME="..." \
  SMTP_PASSWORD="..." \
  SMTP_FROM="..." \
  SMTP_USE_TLS="true" \
  OPENROUTER_API_KEY="..." \
  DATA_CONTROLLER_NAME="..." \
  PRIVACY_CONTACT_EMAIL="..."
```

Opcional, se for emitir attestations:

```bash
fly secrets set -a valinor \
  PLATFORM_ED25519_PRIVATE_KEY="..." \
  PLATFORM_ED25519_RETIRED_PUBLIC_KEYS="..."
```

Deixe `JUDGE_MODEL` / `REVIEWER_MODEL` vazios para o seletor escolher
famílias distintas, ou fixe slugs `fornecedor/modelo` de laboratórios
diferentes. Sem `OPENROUTER_API_KEY` o boot sobe, mas o mérito fica
inconclusivo.

Confira os nomes (nunca os valores) com `fly secrets list -a valinor`.
`DATABASE_URL` precisa aparecer aí depois do attach.

### `TRUSTED_PROXY_IPS` no Fly

O HTTP público termina no Fly Proxy e chega na Machine pela 6PN. O valor
`private` no `fly.toml` cobre ULA (`fc00::/7`, inclusive `fdaa:`) e RFC1918,
que é o que o checklist pede no lugar de `*`.

Só mude para `TRUSTED_PROXY_IPS=*` se o rate limit tratar todos os clientes
como um só IP **e** você tiver certeza de que a porta 8000 não aceita
conexão direta da internet. `*` com a aplicação alcançável direto permite
forjar `X-Forwarded-For`.

## 6. Uma réplica e deploy

O volume prende o app a **um** Machine por volume. Mesmo assim, trave a
escala e desligue o HA padrão do primeiro deploy:

```bash
fly scale count 1 -a valinor
fly deploy --ha=false
```

`fly deploy` constrói o `Dockerfile` do repositório, publica o serviço HTTPS
em 443 e encaminha para `8000`. Acompanhe com `fly logs -a valinor`.

Se o boot recusar, é quase sempre secret faltando (`PLATFORM_SIGNING_SECRET`,
`DOCUMENT_ENCRYPTION_KEY`, SMTP, `PUBLIC_BASE_URL` HTTPS, CORS, controlador
de dados, Postgres). O mesmo critério do checklist.

## 7. Saúde

```bash
fly status -a valinor
curl -fsS https://valinor.fly.dev/health
```

Resposta esperada: JSON com `"status": "ok"` e `"database": "ok"`. O check
interno do Fly bate em `GET /health` a cada 15 s, com 90 s de graça no boot
(alembic + uvicorn).

Painel: `https://valinor.fly.dev/ui/`. `/docs` fica desligado em produção
(`EXPOSE_API_DOCS=false`).

## 8. Domínio próprio (opcional)

```bash
fly certs add app.exemplo.com -a valinor
```

Depois de o certificado ficar válido, atualize os dois secrets para o HTTPS
público — senão os e-mails de convite apontam para `*.fly.dev`:

```bash
fly secrets set -a valinor \
  PUBLIC_BASE_URL="https://app.exemplo.com" \
  CORS_ORIGINS="https://app.exemplo.com"
```

TLS termina no Fly (`force_https = true`). Não exponha Postgres.

## Depois do deploy

Volte ao [checklist](checklist-publicacao.md): SPF/DKIM, smoke test com duas
contas, monitor de `/health` e 5xx, canal humano.

Backup (ver também o [runbook](runbook-operacao.md)):

- **Postgres:** o MPG faz backup gerenciado. Ainda assim teste um restore
  (`fly mpg proxy` + `pg_dump` / restore num banco descartável) antes do
  primeiro caso.
- **Documentos:** snapshots diários do volume (`snapshot_retention = 14`).
  Restaurar volume ≠ restaurar o banco; os dois precisam bater.
- **Segredos:** só no cofre, inclusive `DOCUMENT_ENCRYPTION_KEY`. Sem ela os
  arquivos no volume são bytes inúteis.

Retenção diária dos bytes de documentos:

```bash
fly ssh console -a valinor -C "python -m app.retention --dry-run"
fly ssh console -a valinor -C "python -m app.retention"
```

Agende isso fora da app (cron na sua máquina, GitHub Actions com `fly ssh`,
etc.). Não rode duas réplicas para “fazer o cron”: o limitador e as etapas
não são compartilhados.

## Comandos úteis

```bash
fly logs -a valinor
fly ssh console -a valinor
fly mpg list
fly volumes list -a valinor
fly scale show -a valinor
fly secrets list -a valinor
```

Escala para 2+ só depois de migrar rate limit e fila de etapas para um
backend compartilhado (Redis ou similar). Com o código de hoje, a segunda
réplica é um bug de produto, não um ganho de disponibilidade.
