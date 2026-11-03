import { useState } from 'react'
import { AlertTriangle, Calculator, CheckCircle2, FileSearch, Plus, Trash2 } from 'lucide-react'
import { LiveMessage, Spinner } from './ui.jsx'

// Matérias em que o backend oferece o cálculo auditável.
export const CALCULATION_MATTERS = new Set(['consumer_banking_v1'])

const ORIGIN_LABEL = { ia: 'lido pela IA', parte: 'informado pela parte' }

function Citation({ citation }) {
  if (!citation || (!citation.document_name && !citation.document_id)) return null
  const where = `${citation.document_name || citation.document_id}${citation.page ? `, p. ${citation.page}` : ''}`
  return (
    <small className="calc-citation">
      <span className={citation.verified ? 'chip ok' : 'chip warn'}>
        {citation.verified ? 'trecho confirmado no documento' : 'trecho não encontrado no documento'}
      </span>
      {' '}{where}
      {citation.quote && <q>{citation.quote}</q>}
    </small>
  )
}

// A memória de cálculo, linha a linha: fórmula, entradas, valor e fonte.
export function MemoryTable({ lines = [], sha256, source }) {
  if (!lines.length) return null
  return (
    <div className="memory">
      <div className="memory-scroll">
        <table>
          <caption className="sr-only">Memória de cálculo</caption>
          <thead>
            <tr><th scope="col">Linha</th><th scope="col">Fórmula e entradas</th><th scope="col">Valor</th></tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.key || line.label} className={line.key === 'total_proposed' ? 'memory-total' : ''}>
                <th scope="row">{line.label}</th>
                <td>
                  <span>{line.formula}</span>
                  {line.inputs && Object.keys(line.inputs).length > 0 && (
                    <small>{Object.entries(line.inputs).map(([key, value]) => `${key} = ${value}`).join(' · ')}</small>
                  )}
                  {line.source && <small className="memory-source">Fonte: {line.source}</small>}
                </td>
                <td className="memory-value">{line.display || line.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <small className="memory-foot">
        Conta feita pelo módulo de cálculo determinístico, sem IA.
        {source?.name && <> Taxa média: {source.name}{source.series ? ` (série ${source.series})` : ''}, ref. {source.reference_date}.</>}
        {sha256 && <> Memória {sha256.slice(0, 12)}.</>}
      </small>
    </div>
  )
}

// Proposta da rodada: cláusulas e, por baixo, a memória que as sustenta.
export function ProposalPanel({ round }) {
  const calculation = round?.calculation
  const terms = round?.possible_terms || []
  if (!terms.length && !calculation) return null
  const removed = calculation?.number_guard?.removed || []
  return (
    <div className="proposal-panel">
      <span className="section-label">Proposta de acordo · rodada {round.round_number}</span>
      {terms.length ? (
        <ul className="proposal-terms">{terms.map((term) => <li key={term}>{term}</li>)}</ul>
      ) : (
        <p className="consent-note">
          {calculation?.status === 'abstained'
            ? `A IA se absteve de propor valores: ${calculation.abstention_reason || 'caso fora do escopo'}.`
            : calculation?.status === 'needs_inputs'
              ? 'Ainda não há valores a propor: falta completar os dados do cálculo (veja “Cálculo auditável”).'
              : 'Esta rodada não trouxe uma proposta que possa ser aceita.'}
        </p>
      )}
      {calculation?.status === 'ready' && (
        <details className="memory-details">
          <summary>
            Ver a memória de cálculo ({calculation.scenario.percent}% de {calculation.lines.at(-2)?.display || 'total apurado'})
          </summary>
          <MemoryTable lines={calculation.lines} sha256={calculation.sha256} source={calculation.average_rate_source} />
        </details>
      )}
      {removed.length > 0 && (
        <small className="consent-note">
          {removed.length} trecho(s) escrito(s) pela IA com valores fora da memória de cálculo foram removidos.
        </small>
      )}
    </div>
  )
}

function FieldWithCitation({ label, hint, value, onChange, origin, citation, placeholder, inputMode }) {
  return (
    <label className="mini-field calc-field">
      <span>
        {label}
        {origin && <em className={`origin origin-${origin}`}>{ORIGIN_LABEL[origin]}</em>}
      </span>
      <input
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        inputMode={inputMode}
        autoComplete="off"
      />
      {hint && <small>{hint}</small>}
      <Citation citation={citation} />
    </label>
  )
}

function initialDraft(state) {
  const inputs = state?.inputs || {}
  return {
    principal: inputs.principal ?? '',
    installments: inputs.installments ?? '',
    contract_rate_monthly: inputs.contract_rate_monthly ?? '',
    contract_rate_annual: inputs.contract_rate_annual ?? '',
    paid_installments: inputs.paid_installments ?? '',
    average_rate_monthly: inputs.average_rate_monthly ?? '',
    average_rate_source: { ...(inputs.average_rate_source || { name: '', series: '', reference_date: '', url: '' }) },
    interest_adjustment_applies: inputs.interest_adjustment_applies !== false,
    fees: (inputs.fees || []).map((fee) => ({
      name: fee.name || '',
      amount: fee.amount || '',
      questionable: fee.questionable !== false,
      reason: fee.reason || ''
    }))
  }
}

export default function CalculationCard({ caseData, roles, busy, run, request, actorHeaders }) {
  const state = caseData.calculation
  const party = roles.claimant ? 'claimant' : roles.respondent ? 'respondent' : null
  const hasDocuments = (caseData.documents || []).length > 0
  const closed = Boolean(caseData.organized || caseData.decision)
    || (caseData.conciliation_rounds || []).some((round) => round.agreement?.complete)
  // A mesma chave reinicia o formulário quando o servidor devolve um estado novo.
  return (
    <CalculationBody
      key={state?.updated_at || 'empty'}
      caseData={caseData}
      state={state}
      party={party}
      hasDocuments={hasDocuments}
      closed={closed}
      busy={busy}
      run={run}
      request={request}
      actorHeaders={actorHeaders}
    />
  )
}

function CalculationBody({ caseData, state, party, hasDocuments, closed, busy, run, request, actorHeaders }) {
  const [draft, setDraft] = useState(() => initialDraft(state))
  const inputs = state?.inputs || {}
  const origins = inputs.origins || {}
  const citations = inputs.citations || {}
  const calculation = state?.calculation
  const locked = closed || !party

  function set(field, value) {
    setDraft((current) => ({ ...current, [field]: value }))
  }

  function setFee(index, patch) {
    setDraft((current) => ({
      ...current,
      fees: current.fees.map((fee, position) => (position === index ? { ...fee, ...patch } : fee))
    }))
  }

  function extract() {
    return run('Lendo os documentos com IA...', () => request(`/cases/${caseData.id}/calculation/extract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...actorHeaders() },
      body: JSON.stringify({ party })
    }), { key: 'calculation-extract' })
  }

  function save(event) {
    event.preventDefault()
    const body = { party }
    const base = initialDraft(state)
    for (const field of ['principal', 'installments', 'contract_rate_monthly', 'contract_rate_annual', 'paid_installments', 'average_rate_monthly']) {
      if (String(draft[field]) !== String(base[field])) body[field] = String(draft[field])
    }
    if (JSON.stringify(draft.average_rate_source) !== JSON.stringify(base.average_rate_source)) {
      body.average_rate_source = draft.average_rate_source
    }
    if (draft.interest_adjustment_applies !== base.interest_adjustment_applies) {
      body.interest_adjustment_applies = draft.interest_adjustment_applies
    }
    if (JSON.stringify(draft.fees) !== JSON.stringify(base.fees)) {
      body.fees = draft.fees.filter((fee) => fee.name.trim())
    }
    if (Object.keys(body).length === 1) return Promise.resolve()
    return run('Recalculando com os dados corrigidos...', () => request(`/cases/${caseData.id}/calculation/inputs`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...actorHeaders() },
      body: JSON.stringify(body)
    }), { key: 'calculation-save' })
  }

  const extractionDone = Boolean(state?.extraction)
  const abstained = state?.status === 'abstained'

  return (
    <section className="calc-card-ui" id="calculo">
      <div className="calc-ui-heading">
        <span className="action-icon"><Calculator size={22} /></span>
        <div>
          <span className="section-label">Cálculo auditável</span>
          <h3>
            {calculation
              ? `Total apurado: ${calculation.lines.at(-2)?.display}`
              : 'Os números da proposta nascem de uma conta que você pode conferir'}
          </h3>
          <p>
            A IA lê o contrato e os extratos e cita a página de cada dado; um módulo de cálculo
            sem IA faz a conta. Corrija o que a IA leu: a memória é refeita na hora.
          </p>
        </div>
      </div>

      {!extractionDone && !state && (
        <div className="calc-start">
          <button
            type="button"
            className="button primary"
            onClick={extract}
            disabled={busy || locked || !hasDocuments}
          >
            <FileSearch size={17} /> Ler os documentos com IA
          </button>
          <small className="consent-note">
            {hasDocuments
              ? 'Ou informe os dados à mão abaixo.'
              : 'Anexe o contrato e os extratos antes. Você também pode informar os dados à mão.'}
          </small>
        </div>
      )}

      {abstained && (
        <div className="blocking-note" role="status">
          <AlertTriangle size={17} />
          <span>
            A IA se absteve: {state.assessment?.abstention_reason || 'o caso parece fora do escopo.'}
            {' '}Sem proposta de valores; o caso segue por outra via.
          </span>
        </div>
      )}
      {state?.extraction?.execution?.mode === 'safe_fallback' && (
        <div className="blocking-note" role="status">
          <AlertTriangle size={17} />
          <span>A leitura automática dos documentos está indisponível. Informe os dados abaixo.</span>
        </div>
      )}
      {(state?.assessment?.missing_information || []).length > 0 && (
        <small className="consent-note">Não encontrado nos documentos: {state.assessment.missing_information.join('; ')}</small>
      )}

      {!abstained && (
        <form className="calc-form" onSubmit={save}>
          <div className="calc-grid-ui">
            <FieldWithCitation
              label="Valor financiado"
              value={draft.principal}
              onChange={(value) => set('principal', value)}
              origin={origins.principal}
              citation={citations.principal}
              placeholder="R$ 10.000,00"
              inputMode="decimal"
            />
            <FieldWithCitation
              label="Prazo (parcelas)"
              value={draft.installments}
              onChange={(value) => set('installments', value)}
              origin={origins.installments}
              citation={citations.installments}
              placeholder="24"
              inputMode="numeric"
            />
            <FieldWithCitation
              label="Taxa do contrato (% ao mês)"
              hint={draft.contract_rate_annual && !draft.contract_rate_monthly ? 'Convertida da taxa anual abaixo.' : undefined}
              value={draft.contract_rate_monthly}
              onChange={(value) => set('contract_rate_monthly', value)}
              origin={origins.contract_rate}
              citation={citations.contract_rate}
              placeholder="9,80%"
              inputMode="decimal"
            />
            <FieldWithCitation
              label="Taxa do contrato (% ao ano), se só houver a anual"
              value={draft.contract_rate_annual}
              onChange={(value) => set('contract_rate_annual', value)}
              placeholder="210%"
              inputMode="decimal"
            />
            <FieldWithCitation
              label="Parcelas já pagas"
              value={draft.paid_installments}
              onChange={(value) => set('paid_installments', value)}
              origin={origins.paid_installments}
              citation={citations.paid_installments}
              placeholder="12"
              inputMode="numeric"
            />
          </div>

          <fieldset className="calc-bacen">
            <legend>Taxa média do Bacen <em className="origin origin-parte">sempre informada pela parte</em></legend>
            <p>
              A IA não preenche este dado. Use a taxa média divulgada pelo Bacen para a modalidade
              e o mês da contratação, e informe a fonte e a data de referência.
            </p>
            <div className="calc-grid-ui">
              <label className="mini-field">
                <span>Taxa média (% ao mês)</span>
                <input
                  value={draft.average_rate_monthly}
                  onChange={(event) => set('average_rate_monthly', event.target.value)}
                  placeholder="5,40%"
                  inputMode="decimal"
                />
              </label>
              <label className="mini-field">
                <span>Modalidade / fonte</span>
                <input
                  value={draft.average_rate_source.name}
                  onChange={(event) => set('average_rate_source', { ...draft.average_rate_source, name: event.target.value })}
                  placeholder="Bacen, crédito pessoal não consignado (PF)"
                />
              </label>
              <label className="mini-field">
                <span>Série SGS (opcional)</span>
                <input
                  value={draft.average_rate_source.series}
                  onChange={(event) => set('average_rate_source', { ...draft.average_rate_source, series: event.target.value })}
                  placeholder="Ex.: 25464"
                />
              </label>
              <label className="mini-field">
                <span>Mês de referência</span>
                <input
                  type="month"
                  value={draft.average_rate_source.reference_date.slice(0, 7)}
                  onChange={(event) => set('average_rate_source', { ...draft.average_rate_source, reference_date: event.target.value })}
                />
              </label>
            </div>
            <label className="check-line">
              <input
                type="checkbox"
                checked={draft.interest_adjustment_applies}
                onChange={(event) => set('interest_adjustment_applies', event.target.checked)}
              />
              <span>Pedir a revisão dos juros pela taxa média</span>
            </label>
          </fieldset>

          <fieldset className="calc-fees">
            <legend>
              Tarifas e seguros{' '}
              {origins.fees && <em className={`origin origin-${origins.fees}`}>{ORIGIN_LABEL[origins.fees]}</em>}
            </legend>
            {draft.fees.length === 0 && <p className="consent-note">Nenhuma cobrança listada.</p>}
            {draft.fees.map((fee, index) => {
              const source = (inputs.fees || []).find((item) => item.name === fee.name && item.amount === fee.amount)
              return (
                <div className="fee-row" key={index}>
                  <input
                    aria-label={`Nome da cobrança ${index + 1}`}
                    value={fee.name}
                    onChange={(event) => setFee(index, { name: event.target.value })}
                    placeholder="TAC"
                  />
                  <input
                    aria-label={`Valor da cobrança ${index + 1}`}
                    value={fee.amount}
                    onChange={(event) => setFee(index, { amount: event.target.value })}
                    placeholder="R$ 450,00"
                    inputMode="decimal"
                  />
                  <label className="check-line">
                    <input
                      type="checkbox"
                      checked={fee.questionable}
                      onChange={(event) => setFee(index, { questionable: event.target.checked })}
                    />
                    <span>Questionada</span>
                  </label>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`Remover a cobrança ${fee.name || index + 1}`}
                    onClick={() => set('fees', draft.fees.filter((_, position) => position !== index))}
                  >
                    <Trash2 size={15} />
                  </button>
                  <input
                    className="fee-reason"
                    aria-label={`Motivo da cobrança ${index + 1}`}
                    value={fee.reason}
                    onChange={(event) => setFee(index, { reason: event.target.value })}
                    placeholder="Por que é questionável (ou não)"
                  />
                  {source && <Citation citation={source.citation} />}
                </div>
              )
            })}
            <button
              type="button"
              className="button ghost compact"
              onClick={() => set('fees', [...draft.fees, { name: '', amount: '', questionable: true, reason: '' }])}
            >
              <Plus size={15} /> Adicionar cobrança
            </button>
          </fieldset>

          <LiveMessage type="error" text={state?.status === 'needs_inputs' ? state.error : ''} />
          <div className="calc-actions">
            {extractionDone && !(state.edits || []).length && (
              <button type="button" className="button ghost" onClick={extract} disabled={busy || locked}>
                <FileSearch size={16} /> Ler de novo
              </button>
            )}
            <button className="button primary" disabled={busy || locked}>
              {busy ? <Spinner size={16} /> : <CheckCircle2 size={16} />} Salvar e recalcular
            </button>
          </div>
          {closed && <small className="consent-note">O acordo ou a decisão já foi fechado: os dados não podem mais mudar.</small>}
        </form>
      )}

      {calculation && <MemoryTable lines={calculation.lines} sha256={calculation.sha256} source={calculation.inputs.average_rate_source} />}
      {(state?.edits || []).length > 0 && (
        <small className="consent-note">
          {state.edits.length} correção(ões) das partes registrada(s) na trilha de auditoria.
        </small>
      )}
    </section>
  )
}
