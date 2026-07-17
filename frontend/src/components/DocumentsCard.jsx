import { Check, Circle, FileCheck2, LockKeyhole } from 'lucide-react'

import { materialTypeLabel, partyLabel, responseStatusLabel } from '../helpers'

export function DocumentsCard({
  caseData,
  documents,
  locked,
  busy,
  run,
  request,
  actorHeaders,
  evidenceResponses,
  setEvidenceResponses
}) {
  return (
    <section className="surface documents-card">
      <div className="card-title-row">
        <div>
          <span className="section-label">Material analisado</span>
          <h3>{documents.length} {documents.length === 1 ? 'documento' : 'documentos'} no caso</h3>
        </div>
        {locked && <span className="locked-badge"><LockKeyhole size={14} /> Conjunto protegido</span>}
      </div>
      <div className="document-list">
        {documents.map((document) => (
          <article className="evidence-item" key={document.id}>
            <div className="evidence-main">
              <span className="document-icon"><FileCheck2 size={20} /></span>
              <div className="evidence-copy">
                <div className="evidence-title">
                  <strong>{document.name}</strong>
                  <span>{materialTypeLabel(document.material_type)}</span>
                </div>
                <small>
                  Apresentado por {partyLabel(document.submitted_by, caseData)}
                  {' · '}{document.chunks_count} trechos analisáveis
                </small>
                {document.purpose && <p>{document.purpose}</p>}
              </div>
            </div>

            <div className="evidence-timeline">
              <EvidenceState done={Boolean(document.disclosed_at)} label="Disponibilizado" />
              <EvidenceState done={Boolean(document.acknowledged_at)} label="Ciência confirmada" />
              <EvidenceState
                done={document.response_status !== 'pending'}
                label={responseStatusLabel(document.response_status)}
              />
              <EvidenceState done={document.admitted} label="Admitido para decisão" />
            </div>

            {!locked && !document.acknowledged_at && (
              <button
                className="button secondary compact"
                disabled={busy}
                onClick={() => run(
                  `Registrando ciência de ${partyLabel(document.counterparty, caseData)}...`,
                  () => request(
                    `/cases/${caseData.id}/documents/${document.id}/acknowledge`,
                    {
                      method: 'POST',
                      headers: {
                        'Content-Type': 'application/json',
                        ...actorHeaders(caseData.id, document.counterparty)
                      },
                      body: JSON.stringify({ party: document.counterparty })
                    }
                  )
                )}
              >
                Confirmar ciência da contraparte
              </button>
            )}

            {!locked && document.acknowledged_at && document.response_status === 'pending' && (
              <div className="evidence-response">
                <label className="mini-field">
                  <span>Manifestação de {partyLabel(document.counterparty, caseData)}</span>
                  <textarea
                    value={evidenceResponses[document.id] || ''}
                    onChange={(event) => setEvidenceResponses({
                      ...evidenceResponses,
                      [document.id]: event.target.value
                    })}
                    placeholder="Concorde, conteste a interpretação ou apresente sua resposta."
                  />
                </label>
                <div>
                  <button
                    className="button secondary compact"
                    disabled={busy || !(evidenceResponses[document.id] || '').trim()}
                    onClick={() => respondToEvidence(document, 'answered')}
                  >
                    Registrar resposta
                  </button>
                  <button
                    className="button ghost compact"
                    disabled={busy || !(evidenceResponses[document.id] || '').trim()}
                    onClick={() => respondToEvidence(document, 'challenged')}
                  >
                    Contestar
                  </button>
                  <button
                    className="button ghost compact"
                    disabled={busy}
                    onClick={() => respondToEvidence(document, 'waived')}
                  >
                    Renunciar à resposta
                  </button>
                </div>
              </div>
            )}

            {!locked
              && document.response_status !== 'pending'
              && !document.admitted
              && (
                <button
                  className="button primary compact"
                  disabled={busy}
                  onClick={() => run(
                    'Admitindo o material após o contraditório...',
                    () => request(
                      `/cases/${caseData.id}/documents/${document.id}/admit`,
                      {
                        method: 'POST',
                        headers: actorHeaders(caseData.id, 'manager')
                      }
                    )
                  )}
                >
                  Admitir para a decisão
                </button>
              )}

            {document.response_text && (
              <div className="recorded-response">
                <strong>Resposta da contraparte</strong>
                <p>{document.response_text}</p>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  )

  function respondToEvidence(document, responseStatus) {
    return run(
      'Registrando a manifestação da contraparte...',
      () => request(
        `/cases/${caseData.id}/documents/${document.id}/respond`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...actorHeaders(caseData.id, document.counterparty)
          },
          body: JSON.stringify({
            party: document.counterparty,
            response_status: responseStatus,
            response_text: (
              responseStatus === 'waived'
                ? ''
                : evidenceResponses[document.id] || ''
            )
          })
        }
      )
    )
  }
}

function EvidenceState({ done, label }) {
  return (
    <span className={done ? 'done' : ''}>
      {done ? <Check size={12} /> : <Circle size={10} />}
      {label}
    </span>
  )
}
