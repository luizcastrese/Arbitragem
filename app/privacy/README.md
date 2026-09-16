# Política de privacidade versionada

Cada arquivo `<versão>.md` deste diretório é uma política de privacidade
completa e imutável, no mesmo regime de `app/terms/`: a versão é o nome do
arquivo (`AAAA-MM-DD`) e a vigente é a maior delas.

Regras:

- **nunca edite um arquivo já publicado.** O titular precisa conseguir
  verificar depois qual texto estava vigente quando os dados foram coletados,
  e o hash SHA-256 é o que sustenta isso;
- para mudar a política, crie um arquivo novo com a data da publicação;
- o hash é calculado sobre o texto normalizado (quebras de linha `\n`, sem
  espaços no fim), então o mesmo texto sempre produz o mesmo hash.

`GET /privacy` devolve a versão vigente com texto, hash e os dados do
controlador; `GET /privacy/{versão}` devolve uma versão específica.

Ao publicar uma versão nova, confira se ela continua descrevendo o sistema
como ele é: janela de retenção (`DOCUMENT_RETENTION_DAYS`), provedores de
modelo configurados, ancoragem Nostr ligada ou não.
