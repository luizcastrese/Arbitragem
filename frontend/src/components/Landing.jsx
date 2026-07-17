import {
  BriefcaseBusiness,
  Building2,
  CircleDollarSign,
  Clock3,
  MessagesSquare,
  ShieldCheck,
  UserRound
} from 'lucide-react'

export function HowItWorks() {
  const steps = [
    {
      title: 'As duas partes aderem',
      text: 'Empresa e cliente aceitam as mesmas regras, com convite e consentimento registrados.'
    },
    {
      title: 'Provas com contraditório',
      text: 'Cada documento enviado é visto e respondido pela outra parte antes de contar para qualquer coisa.'
    },
    {
      title: 'A IA busca acordo primeiro',
      text: 'Propostas de conciliação fundamentadas, que cada parte pode aceitar, recusar ou ajustar.'
    },
    {
      title: 'Sem acordo, decisão fundamentada',
      text: 'A IA decide citando as provas; uma segunda IA audita a decisão. Tudo verificável por hash.'
    }
  ]
  return (
    <section className="how-it-works">
      <div className="value-heading">
        <span className="section-label">Como funciona</span>
        <h2>Quatro etapas, as mesmas regras para os dois lados.</h2>
      </div>
      <ol className="how-steps">
        {steps.map((step, index) => (
          <li key={step.title}>
            <span className="how-number">{index + 1}</span>
            <strong>{step.title}</strong>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

export function AudienceValue() {
  return (
    <section className="audience-value">
      <div className="value-heading">
        <span className="section-label">Por que usar</span>
        <h2>O custo de resolver deixa de ser maior que o valor da disputa.</h2>
        <p>
          A IA faz o trabalho que consome tempo e honorários: organiza documentos,
          identifica convergências, conduz rodadas de acordo e fundamenta a análise.
          As garantias ficam: autoria, ciência, resposta, admissão e auditoria
          registradas do início ao fim.
        </p>
      </div>

      <div className="economy-strip">
        <div>
          <CircleDollarSign size={22} />
          <span>
            <strong>Fração do custo</strong>
            Sem custas, audiências ou anos de honorários. A IA absorve o trabalho repetitivo.
          </span>
        </div>
        <div>
          <Clock3 size={22} />
          <span>
            <strong>Dias, não anos</strong>
            O procedimento inteiro — adesão, provas, acordo, decisão — corre na plataforma, sem pauta.
          </span>
        </div>
        <div>
          <ShieldCheck size={22} />
          <span>
            <strong>Verificável, não é caixa-preta</strong>
            Decisão com provas citadas, auditoria independente e histórico lacrado por hash.
          </span>
        </div>
      </div>

      <div className="audience-cards">
        <article className="audience-card company">
          <span className="audience-icon"><Building2 size={22} /></span>
          <span className="audience-kicker">Para a empresa reclamada</span>
          <h3>Reduza o custo por reclamação sem transformar eficiência em parcialidade.</h3>
          <ul>
            <li>Diminui horas operacionais e jurídicas consumidas em cada disputa.</li>
            <li>Centraliza documentos, defesa e histórico em um único procedimento.</li>
            <li>Cria novas propostas quando ainda houver espaço real para acordo.</li>
            <li>Produz uma trilha auditável para jurídico, atendimento e compliance.</li>
          </ul>
        </article>

        <article className="audience-card claimant">
          <span className="audience-icon"><UserRound size={22} /></span>
          <span className="audience-kicker">Para o cliente reclamante</span>
          <h3>Busque uma solução de menor custo sem perder voz, acesso ou proteção.</h3>
          <ul>
            <li>Evita que o custo de discutir o direito torne a reclamação inviável.</li>
            <li>Apresenta sua versão, documentos, pedidos e respostas às propostas.</li>
            <li>Entende por que cada acordo foi sugerido e pode aceitar ou recusar.</li>
            <li>Vê quais provas sustentam a decisão, em vez de receber apenas um resultado.</li>
          </ul>
        </article>
      </div>

      <div className="role-strip">
        <div>
          <BriefcaseBusiness size={20} />
          <span><strong>Gestor do procedimento</strong> organiza acesso, prazos e documentos; não decide o mérito.</span>
        </div>
        <div>
          <MessagesSquare size={20} />
          <span><strong>Representantes e advogados</strong> podem apoiar qualquer parte na apresentação do caso.</span>
        </div>
        <div>
          <ShieldCheck size={20} />
          <span><strong>Adesão transparente</strong> a contraparte deve compreender e aceitar o procedimento.</span>
        </div>
      </div>

      <div className="user-journeys">
        <div className="journey-heading">
          <span className="section-label">Quem faz o quê?</span>
          <h3>O fluxo de cada usuário dentro do caso</h3>
        </div>
        <div className="journey-columns">
          <Journey
            title="Empresa reclamada"
            steps={[
              'Convida o cliente com explicação clara do procedimento.',
              'Apresenta defesa, documentos e limites possíveis para acordo.',
              'Responde a cada rodada com aceite, recusa ou contraproposta.',
              'Recebe a decisão e a auditoria para cumprimento e controle interno.'
            ]}
          />
          <Journey
            title="Cliente reclamante"
            steps={[
              'Conhece as regras e decide se aceita participar.',
              'Apresenta fatos, documentos, pedido e resultado esperado.',
              'Avalia cada proposta e informa o que aceita ou deseja alterar.',
              'Recebe decisão explicada, provas citadas e resultado da auditoria.'
            ]}
          />
          <Journey
            title="Gestor do procedimento"
            steps={[
              'Confere cadastro, consentimento, acesso e prazos.',
              'Garante que os dois lados possam incluir seu material.',
              'Opera as etapas e registra eventos sem escolher o vencedor.',
              'Disponibiliza acordo, decisão e trilha final às partes.'
            ]}
          />
        </div>
      </div>
    </section>
  )
}

export function Journey({ title, steps }) {
  return (
    <article className="journey">
      <h4>{title}</h4>
      <ol>
        {steps.map((step, index) => (
          <li key={step}>
            <span>{index + 1}</span>
            <p>{step}</p>
          </li>
        ))}
      </ol>
    </article>
  )
}
