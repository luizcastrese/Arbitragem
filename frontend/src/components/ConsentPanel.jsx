import { Check, ShieldCheck } from 'lucide-react'

export function ConsentPanel({ caseData, busy, run, request, actorHeaders }) {
  const entries = [
    {
      party: 'claimant',
      label: 'Cliente reclamante',
      name: caseData.claimant,
      consent: caseData.consent?.claimant
    },
    {
      party: 'respondent',
      label: 'Empresa reclamada',
      name: caseData.respondent,
      consent: caseData.consent?.respondent
    }
  ]

  return (
    <div className="consent-panel">
      <div className="consent-heading">
        <ShieldCheck size={20} />
        <div>
          <strong>Adesão ao procedimento</strong>
          <span>Cada parte deve aceitar as mesmas regras antes do procedimento Valinor.</span>
        </div>
      </div>
      <div className="consent-grid">
        {entries.map((entry) => (
          <div className={`consent-party ${entry.consent?.accepted ? 'accepted' : ''}`} key={entry.party}>
            <div>
              <span>{entry.label}</span>
              <strong>{entry.name}</strong>
            </div>
            {entry.consent?.accepted ? (
              <em><Check size={14} /> Aceitou</em>
            ) : (
              <button
                className="button secondary compact"
                disabled={busy}
                onClick={() => run(
                  `Registrando a adesão de ${entry.name}...`,
                  () => request(`/cases/${caseData.id}/consent`, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      ...actorHeaders(caseData.id, entry.party)
                    },
                    body: JSON.stringify({ party: entry.party, accepted: true })
                  })
                )}
              >
                Registrar aceite
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="terms-summary">
        <strong>Ao aceitar, cada parte confirma que compreendeu:</strong>
        <span>participação voluntária; acesso a todo material; oportunidade de resposta; composição somente por acordo; decisão fundamentada por IA; auditoria independente e possível revisão humana.</span>
      </div>
      <small>
        Versão dos termos: 2026-07-12. O aceite fica associado ao papel, ao momento e à cadeia de auditoria.
      </small>
    </div>
  )
}
