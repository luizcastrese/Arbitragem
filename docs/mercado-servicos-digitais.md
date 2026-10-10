# Mercado de entrada: disputas de serviços digitais B2B

Levantamento de outubro de 2026 para decidir o primeiro mercado da Valinor.
É pesquisa de mesa, feita em fontes públicas, e não uma pesquisa com clientes:
os números servem para dimensionar o terreno, não para projetar receita.

## Tese

Disputas entre contratantes e prestadores de serviços digitais (sites,
software simples sob encomenda, design, marketing, conteúdo, audiovisual,
consultoria operacional e automação não crítica) sobre entrega, atraso,
pagamento, escopo, aceite e rescisão.

Esse é o escopo do framework padrão (`digital_services_b2b_v1`).

- **Prova digital.** Contrato, proposta, e-mails, entregas e logs já são texto
  e arquivo, que é o que o procedimento sabe tratar.
- **Menor risco jurídico.** Entre profissionais não há, em regra, relação de
  consumo, e a cláusula de submissão prévia é mais defensável.
- **Ticket que o Judiciário atende mal.** Disputas de alguns milhares a
  algumas dezenas de milhares de reais, em que litigar custa caro em relação
  ao valor em jogo.

## Tamanho

Não há dado público sobre quantas disputas desse tipo existem. Os números
abaixo são *proxies* do universo de empresas, não da demanda.

| Recorte | Dado | Fonte |
|---|---|---|
| Software e serviços de TI | 41.613 empresas e mercado de US$ 35,4 bilhões em 2025 | ABES/IDC, Panorama 2026 |
| TI como um todo | US$ 67,8 bilhões em 2025 (+18,5%); projeção de +5,3% em 2026 | ABES |
| Agências (compra de mídia) | R$ 28,9 bilhões em 2025 (+10%); inclui o que não é digital | Cenp-Meios |
| Pequenos negócios de serviços | Mais de 2,2 milhões de MEI, ME e EPP abertos de janeiro a agosto de 2025; inclui todos os serviços | Sebrae/Receita |
| Agências digitais | Último censo da Abradi é de 2010 (2.518 agências) | Abradi |

Na prática: o universo de prestadores é grande e fragmentado, com muitos MEIs
e pequenas empresas, mas **não há número confiável de agências digitais nem de
frequência de conflito**. O piloto precisa medir a demanda, não a presumir.

## Alternativas que o cliente já tem

### Judiciário

- Segundo o CNJ, 2025 teve 40,9 milhões de casos novos, recorde da série, e o
  acervo fechou em 75,5 milhões.
- O relatório do ano anterior indicava duração média de cerca de 4 anos, com
  fase de conhecimento em torno de 2 anos e 9 meses. Esse número precisa ser
  conferido no PDF oficial, porque a tabela veio truncada.
- **Juizado Especial Cível** é o concorrente gratuito mais direto em ticket
  baixo:
  - microempresas podem ser autoras, ao lado de pessoas físicas;
  - o teto é de 40 salários mínimos, e até 20 salários mínimos dispensa
    advogado;
  - há divergência sobre EPP e MEI, a confirmar com o advogado.

  Para o prestador pequeno que cobra um calote, o juizado é a alternativa
  natural.

### Câmaras de arbitragem e mediação

- Vinculam as partes e custam mais.
- A CEMAAC, da Associação Comercial de São Paulo, fala em cerca de 1 ano por
  arbitragem. Registrou 42 arbitragens e 328 mediações entre 2022 e 2025, o
  que sugere baixa adoção pelo pequeno empresário.
- Há câmaras digitais com taxa fixa, como a CAMES e a Arbitralis.
- O canal recomendado por elas é a cláusula no contrato, o mesmo canal que a
  Valinor pode usar.

### Plataformas de ODR

- A AB2L conta pelo menos 17 empresas no Brasil. Entre as citadas estão MOL
  (Mediação Online), Sem Processo, Acordo Fechado, Justto, Concilie Online e
  eConciliar.
- O foco delas é **acordo** em contencioso de massa, sobretudo de consumo, com
  grandes empresas como clientes (MOL cita Itaú, Magazine Luiza, Mercado Livre
  e Caixa).
- Elas não proferem decisão quando o acordo falha.
- As fontes têm de 3 a 9 anos, então convém confirmar quem segue ativo.

### Plataformas de freelance

- A Workana retém o pagamento em garantia e decide disputas por um time de
  mediação próprio, com base nas provas do projeto.
- Há relatos de usuários que consideram o processo unilateral, por exemplo uma
  divisão de 70/30 contestada.
- Isso prova a demanda e mostra o que a Valinor não tem: **retenção do
  dinheiro**, que dá força à decisão.

### IA aplicada a conflitos

- AcordoAgyl (fevereiro de 2026): spin-off de escritório que usa IA para
  negociar acordos judiciais em consumo, trabalho e bancário.
- Jurídico AI: prevê resultados trabalhistas.
- Não foi encontrado nenhum serviço que profira **decisão não vinculante, por
  IA, em disputas B2B de serviços**, com auto assinado e verificável. A busca
  não foi exaustiva.

## Leitura

O espaço parece desocupado, e há duas explicações possíveis:

1. **Oportunidade.** Quem faz ODR mira acordo em massa no consumo; quem faz
   arbitragem mira ticket alto. Ninguém entrega decisão rápida e fundamentada
   para o pequeno contrato de serviço.
2. **Pouca disposição a pagar.** Uma decisão que ninguém é obrigado a cumprir
   compete com o juizado gratuito, com a arbitragem que vincula e com o escrow
   das plataformas.

A Valinor só vence a segunda explicação se atacar a fraqueza da decisão não
vinculante:

- **Adesão antes do conflito.** Uma cláusula escalonada no contrato (Valinor
  primeiro, depois juizado, foro ou arbitragem) resolve o aceite bilateral e
  dá peso reputacional e contratual ao resultado.
- **Integração com quem segura o dinheiro.** Plataformas, intermediadores de
  pagamento e contratos com sinal ou retenção usam o auto como critério de
  liberação.
- **Auto útil depois.** O auto organiza a prova e a fundamentação para o
  juizado ou para o advogado, o que reduz o custo da etapa seguinte mesmo
  quando não há cumprimento voluntário.

## Canais de entrada

1. Agências, software houses e estúdios que adotem a cláusula no modelo de
   contrato. O prestador é quem mais sofre com calote e com mudança de escopo
   sem aditivo.
2. Plataformas e marketplaces de serviços sem mediação própria, ou que queiram
   terceirizá-la com mais transparência.
3. Geradores de contrato, assinatura eletrônica e contadores de MEI e ME, como
   ponto de inserção da cláusula.
4. Associações setoriais, como a Abradi.

## O que medir no piloto

- taxa de adesão da contraparte, separando casos com e sem cláusula prévia;
- fração de casos conclusivos e motivo dos inconclusivos (escopo combinado só
  por mensagem, falta de aceite documentado);
- cumprimento voluntário do resultado e uso do auto em etapa posterior;
- disposição a pagar, quem paga (prestador, contratante ou plataforma) e em
  que modelo (por caso ou assinatura);
- custo de modelo por caso.

## Riscos a levar ao advogado

- **Teoria finalista mitigada.** A jurisprudência do STJ aplica o CDC a
  pequenas empresas e profissionais quando há vulnerabilidade técnica, jurídica
  ou econômica. Um MEI que contrata um site pode ser tratado como consumidor,
  o que reabre o risco que o recorte B2B queria evitar.
- **Enquadramento do rito.** Conciliação, mediação privada (Lei 13.140/2015)
  ou procedimento atípico, e o que isso exige de quem conduz.
- **Cláusula escalonada.** Redação que não pareça renúncia ao Judiciário nem
  arbitragem disfarçada.
- **Regulação de IA.** Situação do PL 2338 e exigências para decisões
  automatizadas de impacto.

## Fontes

- [ABES — Brasil mantém liderança em TI na América Latina (Panorama 2026)](https://abes.org.br/brasil-mantem-lideranca-em-ti-na-america-latina-cresce-acima-da-expectativa-em-2025-mas-desacelera-ritmo-de-crescimento-neste-ano-e-consolida-nova-fase-do-mercado-aponta-estudo-da-abes-2/)
- [Meio & Mensagem — Cenp-Meios aponta crescimento de 10% em 2025](https://www.meioemensagem.com.br/midia/cenp-meios-aponta-crescimento-de-10-em-2025)
- [Jornal Contábil — Setor de serviços lidera abertura de pequenos negócios em 2025](https://jornalcontabil.com.br/noticia/setor-de-servicos-lidera-abertura-de-pequenos-negocios-no-brasil-em-2025/amp/)
- [Baguete — Abradi lança censo de agências digitais](https://baguete.com.br/public/noticias/abradi-lanca-censo-de-agencias-digitais)
- [Correio da Manhã — Judiciário encerrou 2025 com 75,5 milhões de processos](https://www.correiodamanha.com.br/economia/justica/2026/06/297188-judiciario-encerrou-2025-com-755-milhoes-de-processos-e-recorde-de-acoes.html)
- [CNJ — Sumário executivo Justiça em Números 2025](https://www.cnj.jus.br/wp-content/uploads/2025/10/sumario-executivo-2025.pdf)
- [TJAP — Cartilha do Juizado Especial Cível](https://old.tjap.jus.br/portal/images/stories/documentos/corregedoria/cartilha-juizado_especial_civel.pdf)
- [Conjur — Juizado só pode processar ação de empresa pequena](https://www.conjur.com.br/?p=540948)
- [Brasil 61 — Empreendedores de SP contam com câmara para agilizar e baratear conflitos](https://brasil61.com/n/empreendedores-de-sp-contam-com-camara-para-agilizar-e-baratear-resolucao-de-conflitos-cacb260250)
- [Projuris — ODR: o que é e como funciona](https://www.projuris.com.br/blog/odr/)
- [Conjur — Plataformas de ODR agilizam conciliação online](https://www.conjur.com.br/2022-set-25/plataformas-odr-agilizam-conciliacao-online-facilitam-acordos/)
- [Bernardo de Azevedo — Plataformas brasileiras de resolução de conflitos online](https://bernardodeazevedo.com/conteudos/2-plataformas-brasileiras-de-resolucao-de-conflitos-online/)
- [Reclame Aqui — Sistema de garantia de pagamento da Workana](https://www.reclameaqui.com.br/empresa/workana/conteudos/como-funciona-o-sistema-de-garantia-de-pagamento-da-workana_V1HHmp3xDyEEI0xt)
- [Trustpilot — Avaliações da Workana](https://uk.trustpilot.com/review/workana.com)
- [Conjur — Startup alia IA a expertise jurídica para cortar custos com acordos](https://www.conjur.com.br/2026-fev-26/startup-nacional-alia-ia-a-expertise-juridica-para-cortar-ate-60-dos-custos-com-acordos/)
- [Brasil Inovador — Jurídico AI prevê decisões trabalhistas](https://brasilinovador.com.br/startup-juridico-ai-desenvolve-ia-capaz-de-prever-cenarios-de-decisoes-trabalhistas-antes-da-sentenca/)
