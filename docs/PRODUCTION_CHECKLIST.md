# Checklist de publicação

## Bloqueios técnicos

- [ ] Usar domínio próprio e HTTPS atrás de proxy reverso ou balanceador.
- [ ] Definir todos os segredos exigidos pelo modo `APP_ENV=production`.
- [ ] Guardar cópia segura da `DATA_ENCRYPTION_KEY`; sua perda torna os dados ilegíveis.
- [ ] Em banco existente, executar `python -m app.maintenance.encrypt_existing_data` após configurar a chave.
- [ ] Configurar PostgreSQL gerenciado, backups automáticos e restauração testada.
- [ ] Configurar SMTP transacional e validar entrega, rejeição e expiração de links.
- [ ] Definir `OPENAI_MODEL` e um `OPENAI_REVIEW_MODEL` diferente.
- [ ] Habilitar proteção da branch `main`, revisão obrigatória e CI obrigatório.
- [ ] Habilitar Dependabot e secret scanning no GitHub.
- [ ] Configurar logs centralizados, métricas, alertas e resposta a incidentes.
- [ ] Executar teste de carga, teste de autorização e revisão de segurança externa.

## Bloqueios jurídicos e operacionais

- [ ] Validar o enquadramento jurídico do procedimento e da decisão computacional.
- [ ] Aprovar termos de uso, política de privacidade e política de retenção.
- [ ] Definir hipóteses de revisão humana, impedimento e conflito de interesses.
- [ ] Definir responsável pelo tratamento de dados e canal para titulares.
- [ ] Definir suporte, tratamento de incidentes e continuidade do serviço.
- [ ] Aprovar os tipos de conflito admitidos e os casos que devem ser recusados.

O software não deve ser anunciado como produtor de sentença arbitral juridicamente vinculante até a conclusão da validação jurídica específica.
