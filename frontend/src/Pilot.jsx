import { useState } from 'react'
import { Check, Circle, FileText, ListChecks, ThumbsUp, XCircle } from 'lucide-react'

// Roteiro do que anexar para a revisional bancária: o que a IA e o cálculo
// precisam para propor um acordo com números.
const CHECKLIST = [
  {
    key: 'contract',
    label: 'Contrato ou cédula de crédito',
    hint: 'Valor financiado, prazo e taxa de juros. PDF com texto selecionável, não foto.',
    match: /contrat|c[ée]dula|ccb|proposta/i
  },
  {
    key: 'statements',
    label: 'Extratos ou demonstrativo de pagamento',
    hint: 'Mostram quantas parcelas foram pagas e as cobranças lançadas.',
    match: /extrat|demonstrativ|fatura|hist[óo]rico|parcela/i
  },
  {
    key: 'fees',
    label: 'Comprovantes de tarifas e seguros',
    hint: 'TAC, tarifa de cadastro, seguro prestamista e outras cobranças além dos juros.',
    match: /tarifa|seguro|\btac\b|comprovante|boleto|cobran|encargo/i
  }
]

export function AttachChecklist({ documents = [] }) {
  const [manual, setManual] = useState({})
  return (
    <div className="attach-checklist">
      <div className="attach-title"><ListChecks size={18} /><strong>O que anexar para um acordo rápido</strong></div>
      <ul>
        {CHECKLIST.map((item) => {
          const found = documents.some((document) => item.match.test(`${document.name} ${document.purpose || ''}`))
          const done = found || manual[item.key]
          return (
            <li key={item.key} className={done ? 'done' : ''}>
              <span className="attach-mark" aria-hidden="true">{done ? <Check size={14} /> : <Circle size={10} />}</span>
              <div>
                <strong>{item.label}</strong>
                <small>{item.hint}</small>
              </div>
              {!found && (
                <label className="check-line attach-manual">
                  <input
                    type="checkbox"
                    checked={Boolean(manual[item.key])}
                    onChange={(event) => setManual({ ...manual, [item.key]: event.target.checked })}
                  />
                  <span>Já anexei</span>
                </label>
              )}
              <span className="sr-only">{done ? 'anexado' : 'pendente'}</span>
            </li>
          )
        })}
      </ul>
      <small className="consent-note">
        O sistema reconhece o documento pelo nome e pelo propósito informado. Quem não tiver um dos itens
        pode seguir: a IA aponta o que faltou.
      </small>
    </div>
  )
}

// Contraditório em lote: ciência e "nada a opor" para todos os documentos da
// outra parte de uma vez, em vez de documento por documento.
export function BatchContradictory({ caseData, roles, busy, run, request, actorHeaders }) {
  const documents = caseData.documents || []
  const sections = ['claimant', 'respondent']
    .filter((party) => roles[party])
    .map((party) => {
      const mine = documents.filter((document) => document.counterparty === party && !document.admitted)
      return {
        party,
        needsAck: mine.filter((document) => !document.acknowledged_at),
        needsAnswer: mine.filter((document) => document.response_status === 'pending')
      }
    })
    .filter((section) => section.needsAck.length || section.needsAnswer.length)
  if (caseData.manifest_locked || !sections.length) return null

  function post(path, party, body) {
    return request(`/cases/${caseData.id}/documents/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, party) },
      body: JSON.stringify({ party, ...body })
    })
  }

  function acknowledgeAll({ party, needsAck }) {
    return run('Registrando ciência de todos os documentos...', async () => {
      for (const document of needsAck) await post(`${document.id}/acknowledge`, party, {})
      return {}
    }, { key: `batch-ack-${party}` })
  }

  function noObjection({ party, needsAck, needsAnswer }) {
    return run('Registrando que não há nada a opor...', async () => {
      for (const document of needsAck) await post(`${document.id}/acknowledge`, party, {})
      for (const document of needsAnswer) {
        await post(`${document.id}/respond`, party, { response_status: 'waived', response_text: '' })
      }
      return {}
    }, { key: `batch-answer-${party}` })
  }

  return (
    <div className="batch-card">
      <div className="attach-title"><FileText size={18} /><strong>Contraditório de uma vez</strong></div>
      <p>
        Cada documento do outro lado precisa de ciência e de uma resposta antes da trava. Se você já leu
        tudo, resolva todos de uma vez; para contestar um documento, use o botão dele logo abaixo.
      </p>
      {sections.map((section) => (
        <div className="batch-row" key={section.party}>
          <span>
            {section.party === 'claimant' ? 'Reclamante' : 'Reclamada'}:{' '}
            {section.needsAck.length} sem ciência, {section.needsAnswer.length} sem resposta
          </span>
          <div>
            {section.needsAck.length > 0 && (
              <button type="button" className="button secondary compact" disabled={busy} onClick={() => acknowledgeAll(section)}>
                <Check size={15} /> Ciente de todos os documentos
              </button>
            )}
            <button type="button" className="button primary compact" disabled={busy} onClick={() => noObjection(section)}>
              <ThumbsUp size={15} /> Nada a opor
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

// Recusa da proposta: explica o que acontece depois antes de a parte decidir.
export function RefuseProposal({ party, refused, disabled, onRefuse }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  if (refused) {
    return (
      <p className="consent-note refused-note">
        <XCircle size={14} aria-hidden="true" /> Você recusou esta proposta. Aguarde o gestor: ele abre uma
        nova rodada de negociação ou segue para a decisão.
      </p>
    )
  }
  if (!open) {
    return (
      <button type="button" className="button ghost" disabled={disabled} onClick={() => setOpen(true)}>
        <XCircle size={16} /> Recusar proposta
      </button>
    )
  }
  return (
    <div className="refuse-box" role="group" aria-label="Recusar a proposta">
      <strong>O que acontece se você recusar</strong>
      <ol>
        <li>A proposta desta rodada deixa de valer para você; o caso não é encerrado.</li>
        <li>Sua recusa (e o motivo, se você escrever) vira a sua posição na rodada.</li>
        <li>
          Quando as duas partes se manifestarem, a IA gestora decide: <strong>nova rodada</strong> de
          negociação, se houver espaço, ou <strong>decisão</strong>, sem acordo.
        </li>
      </ol>
      <label className="mini-field">
        <span>Motivo (opcional)</span>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Ex.: o valor não cobre o seguro cobrado."
          maxLength={2000}
        />
      </label>
      <div className="refuse-actions">
        <button type="button" className="button ghost" onClick={() => setOpen(false)}>Voltar</button>
        <button type="button" className="button primary" disabled={disabled} onClick={() => onRefuse(party, reason)}>
          Confirmar recusa
        </button>
      </div>
    </div>
  )
}
