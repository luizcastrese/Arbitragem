# Runbook de operação

Procedimentos que precisam existir antes do primeiro caso real. Cada seção
descreve o que fazer, com que frequência e como conferir que funcionou.

---

## 1. Chave de assinatura Ed25519

A chave em `PLATFORM_ED25519_PRIVATE_KEY` assina toda attestation. Ela é o
único elo entre uma decisão e a possibilidade de um terceiro confirmar que a
plataforma realmente a emitiu.

### O que acontece se ela for perdida

Nada quebra no serviço, mas **todas as attestations já emitidas deixam de ser
verificáveis**: nem a plataforma consegue mais reproduzir a assinatura. Não há
recuperação possível a partir do banco, do backup dos documentos ou da âncora
Nostr. O backup da chave é o único remédio, e precisa existir antes do
incidente.

### Backup (obrigatório antes de subir em produção)

1. Guarde o valor de `PLATFORM_ED25519_PRIVATE_KEY` em um cofre de segredos
   (1Password, Bitwarden, AWS Secrets Manager, Vault — qualquer um com
   controle de acesso e histórico).
2. Guarde uma segunda cópia offline, fora do mesmo provedor de nuvem.
3. Registre o `key_id` correspondente: ele aparece em
   `GET /.well-known/valinor-signing-key` e dentro de cada attestation em
   `platform.key_id`.
4. Anote quem tem acesso ao cofre. A chave dá poder de emitir attestations em
   nome da plataforma; trate o acesso como acesso a produção.

### Rotação

Rotacione quando houver suspeita de exposição, saída de alguém com acesso, ou
por calendário (recomendado: anualmente).

```bash
python -m app.core.attestation --rotate
```

O comando imprime a chave nova e o valor de
`PLATFORM_ED25519_RETIRED_PUBLIC_KEYS` já montado com a chave atual à frente
das que já estavam aposentadas.

Passos:

1. Rode o comando e **guarde a chave privada nova no cofre antes de mexer no
   ambiente**.
2. Aplique as duas variáveis (`PLATFORM_ED25519_PRIVATE_KEY` nova e
   `PLATFORM_ED25519_RETIRED_PUBLIC_KEYS`) e reinicie o serviço.
3. Confira `GET /.well-known/valinor-signing-key`: `active` deve ser a nova e
   `retired` deve conter a anterior.
4. Confira uma attestation antiga em `POST /attestations/verify`: precisa
   voltar `valid: true` com `key_status: "retired"`.
5. Só depois remova a chave privada antiga do ambiente. A pública fica na
   lista de aposentadas **para sempre** — é ela que mantém verificável tudo o
   que foi emitido antes.

> Nunca remova uma chave de `PLATFORM_ED25519_RETIRED_PUBLIC_KEYS`. Remover é
> invalidar retroativamente as attestations que ela assinou.

---

## 2. Backup de dados

Três coisas precisam de backup, e um backup só de uma delas não restaura o
sistema:

| O quê | Onde | Frequência sugerida |
| --- | --- | --- |
| Banco de dados | Postgres (`DATABASE_URL`) | diário, com retenção de 30 dias |
| Documentos | object store (`DOCUMENT_STORAGE_*`) | diário ou versionamento do bucket |
| Segredos | cofre (`PLATFORM_SIGNING_SECRET`, `PLATFORM_ED25519_PRIVATE_KEY`, `DOCUMENT_ENCRYPTION_KEY`) | a cada mudança |

`DOCUMENT_ENCRYPTION_KEY` merece o mesmo cuidado da chave de assinatura: sem
ela os documentos no object store são bytes cifrados irrecuperáveis.

Postgres:

```bash
pg_dump "$DATABASE_URL" --format=custom --file=valinor-$(date +%F).dump
```

Restauração — **teste isto pelo menos uma vez antes de publicar**, num banco
descartável:

```bash
pg_restore --dbname="$DATABASE_URL_TESTE" --clean valinor-2026-09-12.dump
```

Depois de restaurar, confirme a integridade da cadeia de auditoria de alguns
casos em `GET /cases/{id}/audit` (`valid: true`) e a verificação do manifesto
em `GET /cases/{id}/manifest/verify`.

---

## 3. Retenção e expurgo de documentos

O expurgo apaga os **bytes** dos documentos de casos encerrados há mais tempo
que a janela de retenção, preservando metadados e hashes — o que mantém a
cadeia de auditoria e as attestations verificáveis.

```bash
# Simulação: lista o que seria apagado, sem apagar
python -m app.retention --dry-run

# Execução
python -m app.retention
```

Configure `DOCUMENT_RETENTION_DAYS` (padrão 365; `0` desliga o expurgo) e rode
o comando por cron, diariamente. A política de privacidade publicada precisa
declarar a mesma janela.

---

## 4. Proxy reverso e rate limit

`TRUSTED_PROXY_IPS` precisa listar o proxy/balanceador que fica na frente do
serviço, senão o rate limit trata todos os clientes como um só endereço.

- Proxy no mesmo host ou na mesma VPC: `TRUSTED_PROXY_IPS=private`
- PaaS onde o IP do proxy é dinâmico e o app não é alcançável direto: `TRUSTED_PROXY_IPS=*`
- Faixas específicas: `TRUSTED_PROXY_IPS=10.0.0.0/8,198.51.100.7`

Conferência: `GET /` não deve listar o aviso sobre `TRUSTED_PROXY_IPS`.

`*` só é correto quando o serviço **não** aceita conexões diretas da internet.
Se aceitar, qualquer cliente escolhe a própria chave de rate limit mandando um
`X-Forwarded-For`.

O limitador é por processo e vive em memória: com mais de uma réplica, cada
uma aplica o limite separadamente. Para várias réplicas, troque o
armazenamento de `SlidingWindowRateLimiter` por um backend compartilhado
mantendo a interface `allow`.

---

## 5. Etapas assíncronas

As etapas que chamam modelos (`conciliation`, `organize`, `decide`, `review`,
`contest`) respondem `202` e executam em segundo plano. O que monitorar:

- Casos parados em `processing_*` por mais de `PROCESSING_TTL` (10 minutos)
  indicam worker morto no meio da etapa. Passado o TTL a etapa pode ser
  reivindicada de novo — basta repetir a chamada.
- `GET /cases/{id}/stage/{etapa}` informa o estado corrente e, em caso de
  falha, o motivo registrado.

As etapas rodam no processo da aplicação. Ao reiniciar o serviço, dê
tempo de dreno (`--timeout-graceful-shutdown` no uvicorn) para não cortar uma
etapa no meio.
