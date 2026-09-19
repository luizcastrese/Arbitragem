# Checklist de publicação do MVP

Este checklist é a barreira mínima para receber casos reais. Ele não exige uma
operação perfeita, mas evita publicar uma instalação que sobe e não consegue
confirmar usuários, perde documentos ao recriar o contêiner ou confia em IPs
forjados.

## 1. Infraestrutura e segredos

- [ ] Definir `APP_ENV=production`.
- [ ] Apontar `DATABASE_URL` para PostgreSQL com uma senha exclusiva; SQLite e
      `change-this-password` são recusados em produção.
- [ ] Gerar `PLATFORM_SIGNING_SECRET` e `DOCUMENT_ENCRYPTION_KEY` e guardá-los
      em um cofre de segredos.
- [ ] Se houver emissão de attestations, gerar
      `PLATFORM_ED25519_PRIVATE_KEY`, guardar uma cópia offline e registrar o
      `key_id` publicado.
- [ ] Usar S3 privado ou confirmar que o volume `document_data` está montado e
      incluído no backup.
- [ ] Preencher `DATA_CONTROLLER_NAME` e `PRIVACY_CONTACT_EMAIL`.

## 2. Domínio, HTTPS e proxy

- [ ] Configurar `PUBLIC_BASE_URL=https://<domínio>`.
- [ ] Configurar `CORS_ORIGINS` somente com as origens HTTPS utilizadas.
- [ ] Terminar TLS no proxy/load balancer e redirecionar HTTP para HTTPS.
- [ ] Não publicar a porta do PostgreSQL.
- [ ] Manter a aplicação inacessível diretamente quando
      `TRUSTED_PROXY_IPS=*`; preferir a rede/CIDR exata do proxy.
- [ ] Iniciar o Uvicorn com `--no-proxy-headers` (o `Dockerfile` já faz isso).
- [ ] Deixar `EXPOSE_API_DOCS=false`, salvo necessidade operacional consciente.

## 3. E-mail transacional

- [ ] Configurar `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` e
      `SMTP_FROM` com remetente verificado.
- [ ] Publicar SPF, DKIM e DMARC para o domínio remetente.
- [ ] Confirmar entrega real de cadastro, convite e redefinição de senha.
- [ ] Confirmar que todos os links recebidos usam o domínio HTTPS público.

Em produção a verificação de e-mail é obrigatória e os tokens não aparecem na
resposta da API. Por isso a aplicação recusa o boot sem SMTP básico configurado.

## 4. Backup e retenção

- [ ] Automatizar backup diário do PostgreSQL e do object store/volume.
- [ ] Guardar as chaves de assinatura e criptografia fora do mesmo servidor.
- [ ] Restaurar uma cópia em ambiente descartável antes do primeiro caso.
- [ ] Após restaurar, verificar `GET /cases/{id}/audit` e
      `GET /cases/{id}/manifest/verify`.
- [ ] Agendar diariamente `python -m app.retention` e manter
      `DOCUMENT_RETENTION_DAYS` igual ao prazo informado na política.

## 5. Smoke test com duas contas

- [ ] Cadastrar e verificar duas contas em navegadores separados.
- [ ] Criar o caso, entregar e aceitar o convite da contraparte.
- [ ] Aceitar os termos individualmente.
- [ ] Enviar um PDF de cada parte, registrar ciência/resposta e admitir o
      material.
- [ ] Travar o manifesto e verificar sua assinatura.
- [ ] Executar conciliação, organização, decisão e revisão.
- [ ] Baixar e conferir o relatório DOCX.
- [ ] Se habilitada, emitir e verificar a attestation.
- [ ] Apresentar um recurso e conferir a preservação da decisão original.
- [ ] Testar que uma terceira conta recebe `403` ao tentar abrir o caso.

## 6. Operação do piloto

- [ ] Criar monitor externo para `/health` e alerta de erro 5xx.
- [ ] Alertar para falha de backup, falta de espaço e e-mail não entregue.
- [ ] Verificar casos presos em `processing_*` por mais de 10 minutos.
- [ ] Começar com uma réplica: o rate limit e as etapas assíncronas vivem no
      processo e não são compartilhados entre réplicas.
- [ ] Definir um canal humano para suporte, privacidade e incidente.
- [ ] Obter revisão jurídica mínima dos termos e da política antes da exposição
      pública.

## Comandos finais

```bash
python -m pytest -q
cd frontend && npm ci && npm run build && cd ..
docker compose config
docker compose up --build -d
curl -fsS https://<domínio>/health
```

O primeiro piloto deve ser fechado e de baixo volume. Amplie somente depois de
observar entrega de e-mail, custo dos modelos, etapas inconclusivas, recursos e
um ciclo completo de backup e restauração.
