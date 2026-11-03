import { HeroArt } from './ValinorMark.jsx'
import {
  ArrowRight,
  Check,
  FileCheck2,
  Gavel,
  Handshake,
  Mail,
  Scale,
  X
} from 'lucide-react'
import './landing.css'

// ---------------------------------------------------------------------------
// Conteúdo editável da landing. Os números do exemplo são fictícios e foram
// conferidos entre si (parcela, diferença, total); mude todos juntos.
// ---------------------------------------------------------------------------

// Valor cobrado do banco ou escritório por caso resolvido. Deixe `null` para
// mostrar o placeholder "R$ [valor]"; use um texto como 'R$ 490' para publicar.
const PRICE_PER_RESOLVED_CASE = null

// Contato do piloto: VITE_PILOT_EMAIL no build, senão o e-mail de privacidade
// que o backend já publica (PRIVACY_CONTACT_EMAIL).
const PILOT_EMAIL = import.meta.env.VITE_PILOT_EMAIL || ''

const EXAMPLE = {
  principal: 'R$ 10.000,00',
  installments: 24,
  contractRate: 9.8,
  averageRate: 5.4,
  contractedPayment: 'R$ 1.096,27',
  recalculatedPayment: 'R$ 753,16',
  paidInstallments: 12,
  gapPerInstallment: 'R$ 343,11',
  excessInterest: 'R$ 4.117,32',
  fees: [
    { name: 'Tarifa de abertura de crédito (TAC)', reason: 'sem previsão regulatória', value: 'R$ 450,00' },
    { name: 'Seguro prestamista', reason: 'sem contratação expressa', value: 'R$ 610,00' }
  ],
  feesTotal: 'R$ 1.060,00',
  proposalTotal: 'R$ 5.177,32'
}

const HOW_STEPS = [
  {
    title: 'As duas partes aderem',
    text: 'Antes do processo ou com ele em curso. Mesmas regras para os dois lados.',
    time: '~10 min por parte'
  },
  {
    title: 'Provas com contraditório',
    text: 'Cada documento é visto e respondido pela outra parte antes de contar.',
    time: '1 a 3 dias'
  },
  {
    title: 'Acordo primeiro',
    text: 'A IA propõe o acordo, com o cálculo à vista. Cada parte aceita, recusa ou ajusta.',
    time: 'minutos para a proposta'
  },
  {
    title: 'Sem acordo, a IA arbitra',
    text: 'Decisão com provas citadas e cálculos visíveis, auditada por um segundo modelo. Só vincula se as duas partes escolheram a arbitragem.',
    time: 'até 2 dias, com o árbitro'
  },
  {
    title: 'Auto que encerra',
    text: 'Documento assinado que diz o que é e o que faz: acordo, sentença arbitral ou decisão não vinculante.',
    time: 'na hora'
  }
]

const LEGAL_POINTS = [
  {
    icon: Scale,
    title: 'Lei de Arbitragem (9.307/96)',
    text: 'Árbitro pessoa física, capaz e de confiança das partes, que assina a sentença (arts. 13 e 26). A IA elabora; quem adota e assina é ele.'
  },
  {
    icon: Handshake,
    title: 'Adesão voluntária, depois do conflito',
    text: 'Em relação de consumo, a arbitragem só vale se o consumidor a escolher depois que o conflito surgiu (art. 4º, §2º; CDC, art. 51, VII). Nunca por cláusula de contrato.'
  },
  {
    icon: Gavel,
    title: 'Sentença arbitral é título executivo',
    text: 'Assinada pelo árbitro, tem os efeitos de uma sentença judicial (art. 31) e é título executivo judicial (CPC, art. 515, VII).'
  },
  {
    icon: FileCheck2,
    title: 'Acordo com homologação',
    text: 'O acordo é transação (CC, art. 840) e pode ser homologado pelo juiz (CPC, arts. 515, III, e 725, VIII).'
  }
]

const SCOPE_CATEGORIES = [
  'Cobrança ou desconto não reconhecido',
  'Tarifas bancárias',
  'Juros e encargos',
  'Consignado não reconhecido',
  'Operação contestada por fraude de terceiro',
  'Restituição simples ou em dobro'
]

const SCOPE_EXCLUDED = [
  'Autenticidade que dependa de perícia',
  'Superendividamento (Lei 14.181/2021)',
  'Dano moral sem parâmetro fixado pelas partes',
  'Financiamento imobiliário',
  'Tutela de urgência',
  'Matéria suspensa por repetitivo ou IRDR',
  'Ação coletiva e direito indisponível',
  'Valor acima do limite fixado na matéria'
]

const PRINCIPLES = [
  { title: 'Acordo antes de decisão', text: 'A IA propõe o acordo primeiro.' },
  { title: 'Transparência total', text: 'Provas, regras e cálculos visíveis.' },
  { title: 'Adesão voluntária', text: 'Arbitragem só se as duas partes escolherem.' },
  { title: 'Abstenção na dúvida', text: 'Sem base segura, o sistema não decide.' }
]

const HERO_FACTS = [
  { value: '5', label: 'etapas, com o tempo de cada uma' },
  { value: '2', label: 'momentos: antes ou durante o processo' },
  { value: 'R$ 0', label: 'para o autor' },
  { value: '1', label: 'auto assinado ao final' }
]

export default function Landing({ onStart, contactEmail }) {
  const pilotEmail = PILOT_EMAIL || contactEmail || ''
  const pilotHref = pilotEmail
    ? `mailto:${pilotEmail}?subject=${encodeURIComponent('Piloto Valinor')}&body=${encodeURIComponent('Olá! Quero testar a Valinor com os meus processos.')}`
    : null

  return (
    <div className="landing">
      <Hero onStart={onStart} />
      <ExampleCalc />
      <HowItWorks />
      <Pathways />
      <LegalSecurity />
      <ScopeCompare />
      <Cost />
      <Principles />
      <PilotBand href={pilotHref} onFallback={onStart} />
    </div>
  )
}

function Hero({ onStart }) {
  return (
    <section className="intro" aria-labelledby="landing-title">
      <div className="intro-copy">
        <span className="eyebrow">Fora da Justiça, com as contas à vista</span>
        <h1 id="landing-title">Acordos e arbitragem em disputas bancárias, <em>em dias</em>, com o cálculo à vista</h1>
        <p>
          Primeiro a Valinor propõe o acordo. Sem acordo, a IA arbitra, com o raciocínio e
          os cálculos visíveis para os dois lados.
        </p>
        <div className="intro-actions">
          <a className="button gold" href="#piloto">
            Sou banco ou escritório <ArrowRight size={17} />
          </a>
          <button type="button" className="button ghost-light" onClick={onStart}>
            Sou parte ou advogado do autor
          </button>
        </div>
      </div>
      <aside className="intro-art" aria-hidden="true"><HeroArt /></aside>
      <dl className="intro-facts">
        {HERO_FACTS.map((fact) => (
          <div key={fact.label}>
            <dt>{fact.value}</dt>
            <dd>{fact.label}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function ExampleCalc() {
  const e = EXAMPLE
  const barWidth = Math.round((e.averageRate / e.contractRate) * 100)
  const above = Math.round((e.contractRate / e.averageRate - 1) * 100)
  const pct = (n) => `${String(n.toFixed(2)).replace('.', ',')}%`
  return (
    <section className="lp-section" id="exemplo" aria-labelledby="example-title">
      <div className="value-heading">
        <span className="section-label">O cálculo à vista</span>
        <h2 id="example-title">Um caso de exemplo, com cada número no lugar.</h2>
      </div>
      <article className="calc-card">
        <header className="calc-banner">
          <span className="calc-badge">Exemplo fictício</span>
          <span>
            Empréstimo pessoal inventado para mostrar o formato. Não é um caso real nem a taxa
            real do BACEN.
          </span>
        </header>
        <div className="calc-grid">
          <section className="calc-col" aria-labelledby="calc-rate">
            <h3 id="calc-rate">Taxa do contrato × taxa média do BACEN</h3>
            <div className="rate-bars">
              <div className="rate-row">
                <span>Contrato</span>
                <div className="rate-track"><i className="rate-fill contract" style={{ width: '100%' }} /></div>
                <strong>{pct(e.contractRate)} a.m.</strong>
              </div>
              <div className="rate-row">
                <span>Média BACEN</span>
                <div className="rate-track"><i className="rate-fill average" style={{ width: `${barWidth}%` }} /></div>
                <strong>{pct(e.averageRate)} a.m.</strong>
              </div>
            </div>
            <p className="calc-flag">{above}% acima da média</p>
            <p className="calc-note">
              {e.principal} em {e.installments} parcelas. Parcela contratada {e.contractedPayment};
              à taxa média, {e.recalculatedPayment}.
            </p>
          </section>

          <section className="calc-col" aria-labelledby="calc-fees">
            <h3 id="calc-fees">Tarifas questionadas</h3>
            <ul className="fee-list">
              {e.fees.map((fee) => (
                <li key={fee.name}>
                  <span><strong>{fee.name}</strong><small>{fee.reason}</small></span>
                  <b>{fee.value}</b>
                </li>
              ))}
            </ul>
            <p className="calc-sum"><span>Total das tarifas</span><b>{e.feesTotal}</b></p>
          </section>

          <section className="calc-col calc-proposal" aria-labelledby="calc-proposal">
            <h3 id="calc-proposal">Proposta de acordo</h3>
            <dl className="proposal-lines">
              <div><dt>Tarifas a restituir</dt><dd>{e.feesTotal}</dd></div>
              <div>
                <dt>Juros acima da média, nas {e.paidInstallments} parcelas pagas ({e.paidInstallments} × {e.gapPerInstallment})</dt>
                <dd>{e.excessInterest}</dd>
              </div>
            </dl>
            <p className="proposal-total"><span>Restituição proposta</span><b>{e.proposalTotal}</b></p>
            <p className="calc-note">Parcelas restantes recalculadas para {e.recalculatedPayment}.</p>
          </section>
        </div>
        <footer className="calc-foot">
          Em um caso real, cada número aponta para o documento de origem e para a fórmula usada.
          Quem não concordar pode ajustar a proposta, escolher a arbitragem (se as duas partes
          quiserem) ou seguir pela Justiça.
        </footer>
      </article>
    </section>
  )
}

function HowItWorks() {
  return (
    <section className="lp-section" id="como" aria-labelledby="how-title">
      <div className="value-heading">
        <span className="section-label">Como funciona</span>
        <h2 id="how-title">Cinco etapas, as mesmas regras para os dois lados.</h2>
      </div>
      <ol className="how-steps">
        {HOW_STEPS.map((step, index) => (
          <li key={step.title}>
            <span className="how-number">{index + 1}</span>
            <strong>{step.title}</strong>
            <p>{step.text}</p>
            <span className="how-time">{step.time}</span>
          </li>
        ))}
      </ol>
      <p className="how-caption">
        Tempos estimados, sem contar os prazos que as partes definem no caso.
      </p>
    </section>
  )
}

function Pathways() {
  return (
    <section className="lp-section" id="vias" aria-labelledby="paths-title">
      <div className="value-heading">
        <span className="section-label">Antes do processo ou no lugar dele</span>
        <h2 id="paths-title">O acordo é homologado em juízo. Sem acordo, o processo continua.</h2>
      </div>
      <div className="path-grid">
        <article className="path-card">
          <span className="path-icon"><Handshake size={22} /></span>
          <h3>Acordo homologado</h3>
          <p>
            Com processo em andamento, o acordo é juntado aos autos e o juiz o homologa: o processo
            se extingue com resolução de mérito (CPC, art. 487, III, b), e as custas remanescentes
            ficam dispensadas se o acordo vier antes da sentença (art. 90, §3º).
          </p>
          <p>
            Sem processo, o conflito nem vira ação. O acordo vale como transação e também pode ser
            homologado (CPC, art. 725, VIII).
          </p>
        </article>
        <article className="path-card">
          <span className="path-icon"><Scale size={22} /></span>
          <h3>Sem acordo, o processo que já existe</h3>
          <p>
            Ninguém perde o caminho da Justiça. Sem acordo, as partes seguem no processo já
            ajuizado, que retoma o curso, ou levam o conflito à Justiça se ainda não há ação.
          </p>
          <p>
            Quem optar pela via judicial recebe um auto de encerramento com o histórico completo,
            para juntar à petição.
          </p>
        </article>
      </div>
    </section>
  )
}

function LegalSecurity() {
  return (
    <section className="lp-section" id="seguranca" aria-labelledby="legal-title">
      <div className="value-heading">
        <span className="section-label">Segurança jurídica</span>
        <h2 id="legal-title">Cada resultado tem base legal e efeito conhecido.</h2>
      </div>
      <ul className="legal-grid">
        {LEGAL_POINTS.map(({ icon: Icon, title, text }) => (
          <li key={title}>
            <span className="path-icon"><Icon size={20} /></span>
            <strong>{title}</strong>
            <p>{text}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ScopeCompare() {
  return (
    <section className="lp-section" id="escopo" aria-labelledby="scope-title">
      <div className="value-heading">
        <span className="section-label">Escopo</span>
        <h2 id="scope-title">Quando não há base segura, o sistema não decide.</h2>
        <p>
          Abster-se é uma garantia para os dois lados: matéria fora do escopo encerra como
          inadmissível, sem decisão de mérito, e o conflito segue pela via que as partes escolherem.
        </p>
      </div>
      <div className="scope-compare">
        <div className="scope-col scope-in">
          <h3><span className="scope-count">{SCOPE_CATEGORIES.length}</span> o que a Valinor trata</h3>
          <p className="scope-lead">Primeiro setor: disputas bancárias de massa, que se resolvem com contrato, extrato e regra objetiva.</p>
          <ul>
            {SCOPE_CATEGORIES.map((item) => (
              <li key={item}><Check size={16} aria-hidden="true" />{item}</li>
            ))}
          </ul>
        </div>
        <div className="scope-col scope-out">
          <h3><span className="scope-count">{SCOPE_EXCLUDED.length}</span> o que fica de fora</h3>
          <p className="scope-lead">Aqui o sistema se abstém e diz por quê, em vez de arriscar um palpite.</p>
          <ul>
            {SCOPE_EXCLUDED.map((item) => (
              <li key={item}><X size={16} aria-hidden="true" />{item}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

function Cost() {
  return (
    <section className="lp-section" id="custo" aria-labelledby="cost-title">
      <div className="value-heading">
        <span className="section-label">Custo</span>
        <h2 id="cost-title">Quem paga, e quando.</h2>
      </div>
      <div className="cost-grid">
        <article className="cost-card">
          <span className="cost-who">Autor</span>
          <strong className="cost-value">R$ 0</strong>
          <p>O autor não paga.</p>
        </article>
        <article className="cost-card cost-main">
          <span className="cost-who">Banco ou escritório</span>
          <strong className="cost-value" data-placeholder={PRICE_PER_RESOLVED_CASE ? undefined : 'true'}>
            {PRICE_PER_RESOLVED_CASE || 'R$ [valor]'}
          </strong>
          <p>O banco ou escritório paga por caso resolvido.</p>
        </article>
      </div>
    </section>
  )
}

function Principles() {
  return (
    <section className="lp-section" id="principios" aria-labelledby="principles-title">
      <div className="value-heading">
        <span className="section-label">Princípios</span>
        <h2 id="principles-title">Quatro regras que não mudam.</h2>
      </div>
      <ul className="principles">
        {PRINCIPLES.map((item, index) => (
          <li key={item.title}>
            <span className="how-number">{index + 1}</span>
            <strong>{item.title}</strong>
            <span>{item.text}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function PilotBand({ href, onFallback }) {
  return (
    <section className="closing-band" id="piloto" aria-labelledby="pilot-title">
      <div>
        <h2 id="pilot-title">Quer testar com seus processos?</h2>
        <p>
          Fale com a gente sobre um piloto com a sua carteira. Cada caso sai com o cálculo à
          vista e um auto que diz o que é e o que faz.
        </p>
      </div>
      {href ? (
        <a className="button gold" href={href}>
          <Mail size={17} /> Falar sobre o piloto
        </a>
      ) : (
        <button type="button" className="button gold" onClick={onFallback}>
          <ArrowRight size={17} /> Falar sobre o piloto
        </button>
      )}
    </section>
  )
}
