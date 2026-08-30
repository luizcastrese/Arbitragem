# Termos versionados

Cada arquivo `<versão>.md` deste diretório é um texto de termos completo e
imutável. A versão é o próprio nome do arquivo (`AAAA-MM-DD`), e a versão
vigente é a maior delas.

Regras:

- **nunca edite um arquivo já publicado.** O consentimento das partes é gravado
  com o hash SHA-256 do texto; alterar o arquivo quebra a prova do que foi
  aceito e a verificação do manifesto travado;
- para mudar os termos, crie um arquivo novo com a data da publicação. Os casos
  em andamento continuam apontando para a versão que as partes aceitaram;
- o hash é calculado sobre o texto normalizado (quebras de linha `\n`, sem
  espaços no fim do arquivo), então o mesmo texto sempre produz o mesmo hash
  em qualquer sistema operacional.

O endpoint `GET /terms` devolve a versão vigente com o texto e o hash;
`GET /terms/{versão}` devolve uma versão específica, inclusive as antigas
referenciadas por casos já travados.

> Pendência conhecida: os textos aqui ainda **não passaram por validação
> jurídica**. Antes da exposição pública, o conteúdo precisa de revisão por
> advogado, especialmente quanto ao enquadramento do rito (conciliação,
> mediação ou arbitragem), ao Código de Defesa do Consumidor e à política de
> privacidade referenciada na cláusula 10.
