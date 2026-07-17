import { ArrowRight, Handshake } from 'lucide-react'

export function ConciliationActions({
  caseData,
  busy,
  run,
  request,
  actorHeaders,
  claimantResponse,
  respondentResponse,
  conciliationUpdate,
  setClaimantResponse,
  setRespondentResponse,
  setConciliationUpdate
}) {
  const rounds = caseData.conciliation_rounds || []
  const latest = rounds[rounds.length - 1] || caseData.conciliation || {}
  const canAdvance = latest.continue_recommended
    || claimantResponse.trim()
    || respondentResponse.trim()
    || conciliationUpdate.trim()

  async function generateNextRound() {
    const result = await run(
      `Preparando a rodada ${rounds.length + 1} com base nas respostas das partes...`,
      () => request(`/cases/${caseData.id}/conciliation`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...actorHeaders(caseData.id, 'manager')
        },
        body: JSON.stringify({
          advance: true,
          claimant_response: claimantResponse,
          respondent_response: respondentResponse,
          new_information: conciliationUpdate
        })
      })
    )
    if (result) {
      setClaimantResponse('')
      setRespondentResponse('')
      setConciliationUpdate('')
    }
  }

  return (
    <div className="conciliation-actions">
      <div className="round-guidance">
        <span>Rodada {latest.round_number || rounds.length}</span>
        <strong>
          {latest.continue_recommended
            ? `A IA recomenda continuar a negociação`
            : 'A IA não recomenda repetir a mesma tentativa'}
        </strong>
        <p>
          {latest.continue_recommended
            ? `${latest.recommended_additional_rounds || 1} rodada(s) adicional(is) parecem úteis. Foco sugerido: ${latest.next_round_focus || 'aproximar as posições ainda negociáveis'}.`
            : `${latest.stop_reason || 'As posições parecem esgotadas.'} Fatos ou posições novas ainda podem justificar outra rodada.`}
        </p>
      </div>

      <div className="party-response-grid">
        <label className="mini-field">
          <span>Resposta do cliente reclamante</span>
          <textarea
            value={claimantResponse}
            onChange={(event) => setClaimantResponse(event.target.value)}
            placeholder="O que aceita, rejeita ou gostaria de alterar?"
          />
        </label>
        <label className="mini-field">
          <span>Resposta da empresa reclamada</span>
          <textarea
            value={respondentResponse}
            onChange={(event) => setRespondentResponse(event.target.value)}
            placeholder="Qual concessão, condição ou contraproposta a empresa apresenta?"
          />
        </label>
        <label className="mini-field full">
          <span>Fatos novos ou orientação para a próxima rodada</span>
          <textarea
            value={conciliationUpdate}
            onChange={(event) => setConciliationUpdate(event.target.value)}
            placeholder="Ex.: novo prazo possível, pagamento já realizado ou interesse em manter a relação."
          />
        </label>
      </div>

      <div className="conciliation-buttons">
        <button
          className="button secondary"
          disabled={busy || !canAdvance}
          onClick={generateNextRound}
        >
          <Handshake size={17} /> Gerar rodada {rounds.length + 1}
        </button>
        <button
          className="button primary"
          disabled={busy}
          onClick={() => run(
            'Encerrando a fase consensual e organizando o caso...',
            () => request(`/cases/${caseData.id}/organize`, {
              method: 'POST',
              headers: actorHeaders(caseData.id, 'manager')
            })
          )}
        >
          Seguir para julgamento <ArrowRight size={17} />
        </button>
      </div>
      <small className="consent-note">
        Nenhuma proposta é aceita automaticamente. Cada parte decide se concorda,
        contrapropõe ou encerra a negociação.
      </small>
    </div>
  )
}
