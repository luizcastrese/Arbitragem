import { AlertTriangle } from 'lucide-react'

import { hasUnavailableAI, truncateText } from '../helpers'

export function CaseBrief({ caseData }) {
  const claimantPurposes = caseData.documents
    .filter((document) => document.submitted_by === 'claimant')
    .map((document) => document.purpose)
    .filter(Boolean)
  const respondentPurposes = caseData.documents
    .filter((document) => document.submitted_by === 'respondent')
    .map((document) => document.purpose)
    .filter(Boolean)
  const companyResponses = caseData.documents
    .filter((document) => document.submitted_by === 'claimant' && document.response_text)
    .map((document) => document.response_text)
  const customerResponses = caseData.documents
    .filter((document) => document.submitted_by === 'respondent' && document.response_text)
    .map((document) => document.response_text)
  const unavailable = hasUnavailableAI(caseData)

  return (
    <section className="case-brief">
      <div className="case-brief-heading">
        <span className="section-label">Entenda o caso em 30 segundos</span>
        <h3>O conflito antes do procedimento</h3>
      </div>
      <div className="case-brief-grid">
        <BriefPoint
          label="O que aconteceu"
          text={truncateText(
            caseData.organized?.factual_overview
            || `${caseData.title}. Há ${caseData.documents.length} materiais apresentados e compartilhados entre as partes.`,
            280
          )}
        />
        <BriefPoint
          label={`Posição de ${caseData.claimant}`}
          text={[...customerResponses, ...claimantPurposes][0]
            || 'A posição do cliente ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label={`Posição de ${caseData.respondent}`}
          text={[...companyResponses, ...respondentPurposes][0]
            || 'A posição da empresa ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label="Questão central"
          text={
            caseData.organized?.disputed_facts?.[0]
            || 'Comparar o pedido do cliente e a defesa da empresa usando apenas os materiais admitidos.'
          }
        />
      </div>
      {unavailable && (
        <div className="ai-unavailable-note">
          <AlertTriangle size={18} />
          <span>
            <strong>Este caso não contém uma decisão da IA.</strong>
            O procedimento documental foi concluído, mas a análise automática não
            rodou porque o serviço de IA estava sem cota disponível.
          </span>
        </div>
      )}
    </section>
  )
}

function BriefPoint({ label, text }) {
  return (
    <div className="brief-point">
      <span>{label}</span>
      <p>{text}</p>
    </div>
  )
}
