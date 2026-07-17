import { Gavel, Handshake, Search, ShieldCheck } from 'lucide-react'

import {
  auditDisplayIssues,
  auditDisplayRisks,
  conciliationPathLabel,
  decisionDisplayLimitations,
  decisionDisplayReasoning,
  decisionDisplayText,
  organizedDisplaySummary
} from '../helpers'

export function AnalysisDetails({ caseData }) {
  const conciliationRounds = caseData.conciliation_rounds
    || (caseData.conciliation ? [caseData.conciliation] : [])
  const organized = caseData.organized
  const decision = caseData.decision
  const review = caseData.review

  return (
    <section className="analysis-section">
      <div className="analysis-heading">
        <span className="section-label">O que o sistema encontrou</span>
        <h2>Resumo da análise</h2>
        <p>Veja os fatos organizados, a decisão do agente julgador e sua auditoria independente.</p>
      </div>

      <div className="analysis-grid">
        {conciliationRounds.length > 0 && (
          <ConciliationHistory rounds={conciliationRounds} />
        )}

        {organized && (
          <SummaryCard icon={<Search size={19} />} title="Visão geral">
            <p>{organizedDisplaySummary(organized)}</p>
            <ListBlock title="Pontos ainda em aberto" items={organized.missing_information} />
          </SummaryCard>
        )}

        {decision && (
          <SummaryCard icon={<Gavel size={19} />} title="Decisão da IA">
            <p>{decisionDisplayText(decision)}</p>
            <ListBlock title="Fundamentos" items={decisionDisplayReasoning(decision)} />
            <ListBlock title="Limitações" items={decisionDisplayLimitations(decision)} tone="warning" />
          </SummaryCard>
        )}

        {review && (
          <SummaryCard icon={<ShieldCheck size={19} />} title="Auditoria independente">
            <p>{review.framework_alignment}</p>
            <ListBlock title="Riscos identificados" items={auditDisplayRisks(review)} tone="warning" />
            <ListBlock title="Questões encontradas" items={auditDisplayIssues(review)} />
          </SummaryCard>
        )}
      </div>
    </section>
  )
}

function ConciliationHistory({ rounds }) {
  return (
    <article className="summary-card conciliation-history">
      <div className="summary-card-title">
        <span><Handshake size={19} /></span>
        <div>
          <h3>Rodadas de conciliação e mediação</h3>
          <small>{rounds.length} {rounds.length === 1 ? 'tentativa registrada' : 'tentativas registradas'}</small>
        </div>
      </div>
      <div className="round-list">
        {rounds.map((round, index) => (
          <section className="round-item" key={`round-${round.round_number || index + 1}`}>
            <div className="round-number">{round.round_number || index + 1}</div>
            <div>
              <span className="round-path">{conciliationPathLabel(round.recommended_path)}</span>
              <h4>Rodada {round.round_number || index + 1}</h4>
              <p>{round.neutral_summary}</p>
              <ListBlock title="Interesses em comum" items={round.common_interests} />
              <ListBlock title="Pontos negociáveis" items={round.negotiable_issues} />
              <ListBlock title="Propostas para esta rodada" items={round.possible_terms} />
              {round.continue_recommended && (
                <div className="next-round-callout">
                  <strong>Outra rodada pode ser útil</strong>
                  <span>{round.next_round_focus}</span>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
      <div className="list-block warning">
        <strong>Participação voluntária</strong>
        <p>As propostas só formam acordo quando empresa e cliente manifestam concordância.</p>
      </div>
    </article>
  )
}

function SummaryCard({ icon, title, children }) {
  return (
    <article className="summary-card">
      <div className="summary-card-title"><span>{icon}</span><h3>{title}</h3></div>
      {children}
    </article>
  )
}

function ListBlock({ title, items = [], tone = 'default' }) {
  if (!items?.length) return null
  return (
    <div className={`list-block ${tone}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
      </ul>
    </div>
  )
}
