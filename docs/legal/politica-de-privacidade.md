# Política de Privacidade — Valinor

**Versão 2026-08-19.**

> **Minuta pendente de revisão jurídica.** O que está descrito aqui corresponde
> ao comportamento real do sistema, verificado no código. Ainda assim, os
> campos `[A DEFINIR]` precisam de decisão do operador — sobretudo os prazos de
> retenção, que hoje não existem — e o texto precisa de revisão por advogado à
> luz da Lei 13.709/2018 (LGPD) antes de ser publicado.

## 1. Controlador

`[A DEFINIR: razão social, CNPJ, endereço]`. Encarregado pelo tratamento de
dados pessoais (DPO): `[A DEFINIR: nome e e-mail]`.

## 2. Que dados são tratados

**Da conta:** nome de exibição, endereço de e-mail, senha (armazenada apenas
como hash, nunca em texto), data de criação e data de confirmação do e-mail.

**Do procedimento:** o título e a descrição do caso, a identificação das
partes, e **todo o material que as partes apresentam** — documentos em texto e
arquivos PDF, incluindo o que quer que eles contenham. Também as manifestações,
os prazos, os aceites e cada ato praticado.

**De operação:** registros técnicos de requisição (data, rota, tempo de
resposta, identificador de requisição) e, para o controle de abuso, o endereço
IP de origem.

Não há cookies de rastreamento nem publicidade. O único cookie é o de sessão,
necessário para manter você autenticado.

## 3. Por que são tratados

- **Executar o procedimento** que você contratou ao aderir: é a finalidade
  central, e sem os dados do caso não há procedimento (execução de contrato).
- **Identificar as partes** com segurança, o que inclui confirmar a posse do
  endereço de e-mail — sem isso não há como garantir à outra parte quem está do
  outro lado.
- **Provar a integridade do registro**, obrigação que a própria natureza do
  serviço impõe: um procedimento de decisão que não pode comprovar o que
  aconteceu não serve para nada.
- **Segurança e prevenção a abuso** (limite de requisições, registros técnicos).

## 4. Análise por inteligência artificial

O material admitido no caso é submetido a modelos de inteligência artificial
para organização, decisão e auditoria. Quando a plataforma está configurada com
um provedor externo de IA `[A DEFINIR: identificar o provedor contratado]`, o
conteúdo do material admitido é **transmitido a esse provedor** para
processamento, sob os termos contratados com ele.

Isso é parte inseparável do serviço: sem análise não há decisão. Se você não
concorda com essa transmissão, não deve aderir ao procedimento.

Nenhum material é usado para treinar modelos, e a plataforma não vende nem
compartilha dados com terceiros para fins comerciais.

## 5. O que se torna público

Periodicamente, a plataforma publica fora dos seus próprios servidores — em
relays Nostr e como carimbo do tempo na blockchain do Bitcoin — **apenas
valores de hash** que representam o estado do registro, acompanhados do
identificador interno do caso e de uma contagem de eventos.

Essas publicações são **irreversíveis e permanentes por natureza**, e não podem
ser apagadas a pedido. Por isso elas jamais contêm o conteúdo do caso, o
resultado da decisão, os nomes das partes ou qualquer dado pessoal: de um hash
não se extrai o que ele representa.

## 6. Como são protegidos

- Os documentos são cifrados em repouso com AES-256-GCM, tanto os arquivos
  quanto o texto extraído deles.
- As senhas são guardadas apenas como hash; os tokens de convite, de sessão e
  de redefinição, idem.
- O acesso ao material de um caso é restrito às duas partes daquele caso.
- O acesso a arquivos originais se dá por links temporários assinados, que
  expiram.
- O tráfego é protegido por TLS.

## 7. Com quem são compartilhados

- **A outra parte do caso**, necessariamente: o contraditório exige que cada
  parte veja o material da outra. Esta é a característica central do serviço.
- **O provedor de infraestrutura** `[A DEFINIR]` e o **provedor de e-mail
  transacional** `[A DEFINIR]`, como operadores.
- **O provedor de inteligência artificial**, nos termos do item 4.
- **Autoridades**, mediante ordem legal.

## 8. Por quanto tempo

`[A DEFINIR: esta é a decisão mais importante em aberto.]` Hoje o sistema **não
apaga nada automaticamente**: casos, documentos e a cadeia de auditoria
permanecem por prazo indeterminado. Antes de publicar esta política é preciso
definir, no mínimo:

- por quanto tempo o material de um caso encerrado é mantido;
- o que acontece com casos abandonados antes da trava do conjunto documental;
- o prazo de guarda dos registros técnicos.

Note que a cadeia de auditoria e os hashes já publicados não podem ser
apagados sem destruir a garantia de integridade que o serviço oferece — e que
interessa igualmente à outra parte. A retenção do **registro** e a retenção do
**conteúdo** são decisões separadas e devem ser tratadas como tais.

## 9. Seus direitos

Você pode solicitar acesso, correção, portabilidade, informação sobre
compartilhamentos e, nos limites legais, eliminação dos seus dados pessoais,
pelo contato do item 1.

Há limites reais, e é melhor dizê-los do que descobri-los depois:

- **o material de um caso não pode ser retirado unilateralmente** depois de
  disponibilizado à outra parte — ele já integra o contraditório, e removê-lo
  prejudicaria direito de terceiro;
- **os hashes já publicados** em Nostr e Bitcoin são irreversíveis;
- **a cadeia de auditoria** não pode ser alterada sem destruir a prova de
  integridade do procedimento.

Nesses casos a plataforma informará a limitação e sua justificativa.

## 10. Incidentes

Em caso de incidente de segurança com risco relevante, a plataforma comunicará
os titulares afetados e a autoridade competente, nos prazos e na forma da
legislação.

## 11. Alterações

Alterações são publicadas com nova versão e data. `[A DEFINIR: forma de
comunicação prévia aos titulares]`
