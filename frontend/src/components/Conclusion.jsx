import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'

import { decisionDisplayText, outcomeLabel } from '../helpers'
import { Fact } from './common'

export function Conclusion({ caseData }) {
  const decision = caseData.decision || {}
  const review = caseData.review || {}
  const inconclusive = decision.outcome === 'inconclusive'
  const unavailable = decision.execution?.mode === 'safe_fallback'
  const decisionText = decisionDisplayText(decision)

  return (
    <section className={`conclusion ${inconclusive ? 'attention' : 'approved'}`}>
      <div className="conclusion-icon">
        {inconclusive ? <AlertTriangle size={28} /> : <CheckCircle2 size={28} />}
      </div>
      <div className="conclusion-copy">
        <span className="section-label">Decisão do agente julgador</span>
        <h2>
          {unavailable
            ? 'A análise automática não foi concluída'
            : inconclusive
              ? 'A IA não pôde decidir o mérito'
              : 'A decisão foi proferida'}
        </h2>
        <p>{decisionText}</p>
      </div>
      <div className="conclusion-facts">
        <Fact
          label="Confiança"
          value={`${Math.round((decision.confidence || 0) * 100)}%`}
          note={unavailable ? 'O modelo não chegou a analisar o caso' : inconclusive ? 'Evidência insuficiente para concluir' : 'Nível informado pelo modelo'}
        />
        <Fact
          label="Auditoria"
          value={unavailable ? 'Não executada' : review.approved ? 'Aprovada' : 'Com ressalvas'}
          note={unavailable ? 'Não havia decisão para auditar' : review.requires_human_review ? 'Intervenção excepcional indicada' : 'Sem bloqueios materiais'}
        />
        <Fact
          label="Resultado"
          value={outcomeLabel(decision.outcome)}
          note="Decisão computacional do procedimento"
        />
      </div>
      {inconclusive && (
        <div className="human-review-note">
          <Info size={18} />
          <span>
            <strong>{unavailable ? 'Pendência técnica:' : 'Exceção do processo:'}</strong>
            {' '}{unavailable
              ? 'disponibilize cota para a API e processe um novo caso para obter uma decisão real da IA.'
              : 'resolva as lacunas apontadas ou encaminhe o caso para intervenção humana antes de uma nova decisão.'}
          </span>
        </div>
      )}
    </section>
  )
}
