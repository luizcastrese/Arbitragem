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
  espaços no fim) **já preenchido** (ver abaixo), então o mesmo texto com os
  mesmos valores sempre produz o mesmo hash.

## Marcadores

O texto do arquivo pode ter marcadores `{{nome}}`, preenchidos com a
configuração no momento de servir (`app/core/privacy.py`):

| Marcador | Origem | Se não configurado |
| --- | --- | --- |
| `{{controlador}}` | `DATA_CONTROLLER_NAME` | "a organização que opera esta plataforma" |
| `{{contato}}` | `PRIVACY_CONTACT_EMAIL` | contato padrão do site (`alugai.adm@gmail.com`) |
| `{{prazo_documentos}}` | `DOCUMENT_RETENTION_DAYS` | frase neutra (apagamento automático desligado) |

Nunca escreva no texto o nome de uma variável de ambiente nem uma rota de API:
a política é lida por titulares, não por desenvolvedores. Um teste
(`tests/test_privacy_text.py`) reprova a versão vigente se isso acontecer.

Como o hash vale para o texto preenchido, trocar controlador, contato ou prazo
muda o texto servido e o hash. Se a mudança for material, publique também uma
versão nova.

`GET /privacy` devolve a versão vigente com texto, hash e os dados do
controlador; `GET /privacy/{versão}` devolve uma versão específica.

## Pendência jurídica (interna, não vai para o texto público)

Os textos ainda **não passaram por validação jurídica**. Antes da exposição
pública, precisam de revisão por advogado, em conjunto com os termos do
procedimento, em especial quanto às bases legais escolhidas, à transferência
internacional para provedores de modelo de IA e à publicação de impressões
digitais em rede pública (Nostr).

## Versões

- `2026-09-12`: primeira versão. Imutável. Cita nomes de variáveis e rotas de
  API no texto, por isso a versão vigente é a mais nova.
- `2026-11-03`: texto em português claro, com os marcadores acima, sem rotas
  de API, descrevendo como o titular pede acesso, cópia e exclusão (pela conta
  ou por e-mail) e os avisos por e-mail do procedimento.

Ao publicar uma versão nova, confira se ela continua descrevendo o sistema
como ele é: janela de retenção, provedores de modelo configurados, ancoragem
Nostr ligada ou não.
