# Termos de Uso — Valinor

**Versão 2026-08-19.**

> **Minuta pendente de revisão jurídica.** Este texto descreve com precisão o
> que o sistema faz, mas não substitui a análise de um advogado. Antes de
> publicar, é preciso definir os campos marcados como `[A DEFINIR]`, confirmar
> a adequação à legislação aplicável e decidir sobre arbitragem, foro e
> limitação de responsabilidade. Enquanto esta advertência estiver aqui, o
> documento não deve ser apresentado como vinculante.

## 1. Quem opera a plataforma

A Valinor é operada por `[A DEFINIR: razão social, CNPJ, endereço]`, doravante
"a plataforma". Contato: `[A DEFINIR: e-mail]`.

## 2. O que a plataforma é — e o que não é

A Valinor conduz um procedimento estruturado de resolução de disputas
documentais. O procedimento é executado pelo próprio sistema: não há gestor,
mediador ou administrador humano, e a plataforma não representa nenhuma das
partes.

A decisão produzida ao final é **gerada por inteligência artificial** a partir
exclusivamente do material admitido no caso, e passa por uma auditoria
automatizada independente antes de ser assinada.

**A plataforma não presta serviço de advocacia** e não emite parecer jurídico.
O uso do procedimento não impede nenhuma das partes de buscar as vias
judiciais ou arbitrais cabíveis. A decisão produzida aqui **não é sentença
judicial nem laudo arbitral** para os fins da Lei 9.307/1996, salvo se as
partes assim convencionarem por instrumento próprio, fora desta plataforma.

## 3. Quem pode usar

Duas partes por caso: quem reclama e quem é reclamado. Cada parte precisa de
uma conta própria, com endereço de e-mail confirmado. **A mesma pessoa não
pode ocupar os dois polos** do mesmo caso, e o sistema recusa a tentativa.

O uso exige capacidade civil. Ao criar uma conta, você declara ter os poderes
necessários para representar a parte que indica.

## 4. Como o procedimento corre

1. **Adesão.** As duas partes aceitam estes termos. Sem os dois aceites, nada
   avança.
2. **Produção de material.** Cada parte apresenta documentos e alegações.
3. **Contraditório.** Todo material apresentado por uma parte é disponibilizado
   à outra, que recebe prazo para tomar ciência e se manifestar. A manifestação
   sobre um material é **ato único**: para mudar de posição, apresenta-se
   material novo, que reabre o prazo da outra parte.
4. **Preclusão.** Vencido o prazo sem manifestação, a oportunidade se encerra e
   o procedimento segue. **A preclusão não significa concordância** com o
   conteúdo: significa apenas que aquela chance de responder se esgotou.
5. **Encerramento da produção.** Quando as duas partes declaram concluída a
   própria produção, o conjunto documental é travado e não aceita mais
   alterações.
6. **Composição.** O sistema conduz rodadas de tentativa de acordo. Acordo só
   existe se as duas partes concordarem.
7. **Decisão e auditoria.** Não havendo acordo, o sistema profere decisão
   fundamentada e a submete a auditoria automatizada.
8. **Ratificação.** Se a auditoria fizer ressalva à decisão, ela não é
   executável por si: cada parte é informada da ressalva e diz se aceita o
   resultado assim mesmo. **Silêncio não vale como aceite** — vencido o prazo
   sem manifestação, o caso encerra sem decisão executável.
9. **Contestação.** Emitida a decisão assinada, cada parte tem
   `[A DEFINIR: prazo, hoje 7 dias]` para contestá-la, salvo se a tiver
   ratificado.

## 5. Prazos

Os prazos correm em dias corridos, contados do momento em que o ato é
registrado, e são comunicados por e-mail à parte responsável. A comunicação e o
resultado da tentativa de entrega ficam registrados na cadeia de auditoria.

É responsabilidade de cada parte manter seu endereço de e-mail acessível e
verificar a plataforma. Falha de entrega por caixa cheia, filtro de spam ou
endereço abandonado não suspende prazo.

## 6. Material apresentado

Ao apresentar material, você declara que:

- tem o direito de apresentá-lo e de submetê-lo à análise descrita aqui;
- o conteúdo não é falso nem adulterado;
- o material não contém dado pessoal de terceiros além do estritamente
  necessário à disputa.

A plataforma **não verifica a autenticidade** dos documentos apresentados. Ela
registra, com hash criptográfico, exatamente o que foi apresentado e quando —
não que aquilo seja verdadeiro.

Apresentar material que se sabe falso pode configurar ilícito e enseja o
encerramento da conta, sem prejuízo das medidas cabíveis.

## 7. Efeito da decisão

A decisão vincula as partes na medida em que elas tenham convencionado
vinculação — por contrato entre si, por cláusula em instrumento próprio, ou
pela ratificação prevista no item 4.8. A plataforma emite um artefato assinado
que descreve o resultado e permite a terceiros verificarem sua integridade,
mas **não executa** o resultado nem movimenta valores.

Casos encerrados sem decisão executável — por inconclusividade, recusa de
ratificação ou indisponibilidade da análise — não produzem resultado, e o
material e o histórico permanecem disponíveis às partes.

## 8. Integridade e verificabilidade

Todo ato do procedimento entra em uma cadeia de auditoria encadeada por hash. O
conjunto documental travado é assinado. O topo da cadeia é publicado
periodicamente fora dos servidores da plataforma — em relays Nostr e como
carimbo do tempo em Bitcoin — de forma que **apenas hashes** saem daqui: nunca
o conteúdo do caso, o resultado ou a identidade das partes.

Isso permite que qualquer pessoa, inclusive contra a plataforma, verifique que
o registro não foi alterado depois do fato.

## 9. Conta e segurança

Você é responsável pelo sigilo da sua senha e pelos atos praticados na sua
conta. Suspeitando de acesso indevido, redefina a senha — o que encerra todas
as sessões abertas — e comunique a plataforma.

## 10. Disponibilidade

A plataforma é oferecida no estado em que se encontra. `[A DEFINIR: há
compromisso de disponibilidade? há suporte? em que prazo?]` Interrupções não
suspendem prazos automaticamente; se uma indisponibilidade relevante impedir
uma parte de agir, ela deve comunicar a plataforma para avaliação.

## 11. Encerramento

Você pode encerrar sua conta a qualquer momento. O encerramento **não apaga o
histórico de casos em andamento ou concluídos**: o registro é o que dá
integridade ao procedimento e interessa também à outra parte. O tratamento dos
seus dados após o encerramento está descrito na Política de Privacidade.

## 12. Alterações destes termos

Alterações passam a valer para casos abertos após a publicação da nova versão.
**Um caso em andamento continua regido pela versão aceita pelas partes**, cuja
identificação fica registrada na cadeia de auditoria no momento do aceite.

## 13. Lei aplicável e foro

Estes termos são regidos pela lei brasileira. `[A DEFINIR: foro de eleição, ou
cláusula compromissória]`
