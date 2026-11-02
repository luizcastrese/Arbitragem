# Escalar para mais de uma réplica

O piloto roda numa réplica (ver `docs/deploy-fly.md`). Este documento lista o
que vive na memória do processo, o que já foi resolvido para funcionar entre
réplicas e o que falta configurar antes de `fly scale count 2`.

## Estado por componente

| Componente | Onde vive | Entre réplicas |
| --- | --- | --- |
| Status do caso, resultado das etapas, reivindicação (`processing_*`) | Banco | Já funciona: a reivindicação é um UPDATE condicional |
| Encadeamento do gestor entre etapas de modelo | Banco (`cases.steward_chain_armed_at`) | Já funciona: tomar a marca é um UPDATE condicional |
| Retomada depois de reinício | Thread `valinor-steward-recovery` em cada réplica | Já funciona: duas réplicas varrendo ao mesmo tempo não conduzem o mesmo caso duas vezes |
| Execução das etapas de modelo (`StageRunner`) | Memória de cada réplica | Aceitável: o polling lê o banco. Só o texto do erro de uma etapa que falhou fica na réplica que a rodou |
| Rate limit | Memória (padrão) ou Redis | **Configurar Redis**: em memória, cada réplica aplica o limite separadamente |
| Documentos | Volume local (padrão) ou S3 | **Configurar S3**: um volume Fly só monta numa Machine |

## O encadeamento do gestor

O gestor (a IA que conduz o procedimento) abre uma etapa de modelo e pede
para seguir sozinho quando ela concluir. Antes, esse pedido ficava num `set`
em memória: se o processo reiniciasse no meio da etapa, o caso parava sem que
ninguém o retomasse, porque as partes não acionam as etapas de modelo.

Agora:

1. o gestor grava `steward_chain_armed_at` e faz commit antes de agendar a
   etapa;
2. a etapa, ao concluir, zera a marca com UPDATE condicional. Só quem zerou
   segue a condução;
3. a varredura (`app.api.steward.recover_abandoned_steward_chains`) roda no
   boot e a cada `STEWARD_RECOVERY_INTERVAL_SECONDS` (60 por padrão). Uma marca
   mais velha que o TTL de reivindicação (10 minutos) indica uma etapa que
   morreu com o processo: o status volta ao anterior à etapa, o evento
   `steward_chain_recovered` entra na trilha de auditoria e o gestor conduz
   de novo a partir do que está gravado.

Uma reivindicação mais recente que o TTL não é tocada, porque a etapa pode
estar rodando em outra réplica.

## Checklist antes da segunda réplica

- [ ] Redis gerenciado (Upstash pelo `fly redis create`, ou outro) e
      `RATE_LIMIT_BACKEND=redis` + `REDIS_URL` nos secrets. O boot recusa
      `redis` sem URL.
- [ ] `DOCUMENT_STORAGE_BACKEND=s3` com bucket, credenciais e criptografia
      (`DOCUMENT_ENCRYPTION_KEY` continua obrigatória). Migre os arquivos do
      volume para o bucket antes de trocar o backend.
- [ ] Remover o `[mounts]` do `fly.toml`: com S3, o volume deixa de ser usado
      e prenderia cada Machine a um volume próprio.
- [ ] `STAGE_WORKERS` por réplica × réplicas ≤ conexões do pool do Postgres.
- [ ] Polling das etapas (`GET /cases/{id}/stage/{etapa}`) pode cair em outra
      réplica: o estado vem do banco, então continua correto. Só o texto do
      erro de uma etapa que falhou aparece apenas na réplica que a rodou.
- [ ] O expurgo de documentos (`python -m app.retention`) continua sendo
      agendado fora da app, uma vez só.
