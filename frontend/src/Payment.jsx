import { useEffect, useState } from 'react'
import { CreditCard, Landmark } from 'lucide-react'
import { LiveMessage } from './ui.jsx'

const REASONS = {
  contest_window_open: 'O prazo para contestar a decisão ainda está aberto.',
  appeal_pending: 'Há um recurso em andamento.',
  attestation_not_issued: 'A decisão ainda não foi atestada.',
  no_agreement: 'Ainda não há acordo fechado.',
  no_verified_amount: 'Não há valor verificado a pagar.',
  no_amount_owed: 'A decisão não reconhece valor a pagar.',
  no_merit_decision: 'O procedimento terminou sem decisão de mérito.'
}

function money(minor, currency = 'BRL') {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format((minor || 0) / 100)
}

// Tela mínima do pagamento opcional (Stripe Connect e Checkout). Só é montada
// quando a instância tem pagamentos habilitados.
export default function PaymentCard({ caseData, roles, run, request, actorHeaders }) {
  const [settlement, setSettlement] = useState(null)
  const [connect, setConnect] = useState(null)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const caseId = caseData.id

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await request(`/cases/${caseId}/settlement`)
        if (cancelled) return
        setSettlement(data)
        const payeeRole = data.offer?.payee_role || 'claimant'
        if (data.offer?.available && roles[payeeRole]) {
          const status = await request('/payments/connect/status')
          if (!cancelled) setConnect(status)
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }
    load()
    return () => { cancelled = true }
  }, [caseId, caseData.status, caseData.updated_at, reload])

  const offer = settlement?.offer
  const payment = settlement?.payment
  if (!settlement || (!offer?.available && !payment)) {
    // Sem oferta não há o que pagar; só explica quando a razão ajuda a parte.
    const reason = offer && REASONS[offer.reason]
    if (!reason || !['contest_window_open', 'appeal_pending'].includes(offer.reason)) return null
    return (
      <section className="payment-card">
        <span className="section-label">Pagamento opcional</span>
        <p className="consent-note">{reason}</p>
      </section>
    )
  }

  const payerRole = offer.payer_role
  const payeeRole = offer.payee_role
  const isPayer = Boolean(roles[payerRole])
  const isPayee = Boolean(roles[payeeRole])
  const paid = payment?.status === 'paid'
  const label = offer.kind === 'agreement' ? 'do acordo' : 'da decisão'

  function onboard() {
    return run('Abrindo o cadastro para receber pagamentos...', async () => {
      const data = await request('/payments/connect/onboarding', { method: 'POST' })
      window.location.assign(data.onboarding_url)
      return {}
    }, { key: 'payment-onboarding', exclusive: false })
  }

  function pay() {
    return run('Abrindo o pagamento seguro...', async () => {
      const data = await request(`/cases/${caseId}/settlement/checkout`, {
        method: 'POST',
        headers: { ...actorHeaders(caseId, payerRole) }
      })
      window.location.assign(data.checkout_url)
      return {}
    }, { key: 'payment-checkout', exclusive: false })
  }

  return (
    <section className="payment-card">
      <div className="calc-ui-heading">
        <span className="action-icon"><CreditCard size={22} /></span>
        <div>
          <span className="section-label">Pagamento opcional</span>
          <h3>{paid ? `Pagamento ${label} confirmado` : `Pagar o valor ${label}`}</h3>
          <p>
            {money(offer.amount_minor_units, offer.currency)} da parte {payerRole === 'respondent' ? 'reclamada' : 'reclamante'}
            {' '}para a parte {payeeRole === 'claimant' ? 'reclamante' : 'reclamada'}. A plataforma retém{' '}
            {money(offer.platform_fee_minor_units, offer.currency)}. O pagamento é uma escolha de quem paga e a
            confirmação vem do provedor de pagamento, não do navegador.
          </p>
        </div>
      </div>

      {paid ? (
        <p className="consent-note" role="status">Pago. O comprovante fica na trilha de auditoria do caso.</p>
      ) : (
        <>
          {isPayee && !settlement.payee_onboarded && (
            <div className="payment-step">
              <p>Para receber, cadastre a sua conta de recebimento (Stripe Connect). Leva poucos minutos.</p>
              <button type="button" className="button primary" onClick={onboard}>
                <Landmark size={16} /> Cadastrar conta para receber
              </button>
            </div>
          )}
          {isPayee && settlement.payee_onboarded && connect && !connect.ready && (
            <div className="payment-step">
              <p>Seu cadastro de recebimento ainda não foi concluído.</p>
              <button type="button" className="button secondary" onClick={onboard}>Concluir cadastro</button>
              <button type="button" className="button ghost" onClick={() => setReload((value) => value + 1)}>Já concluí, verificar</button>
            </div>
          )}
          {isPayer && (
            <div className="payment-step">
              {settlement.payee_onboarded ? (
                <button type="button" className="button primary" onClick={pay}>
                  <CreditCard size={16} /> Pagar {money(offer.amount_minor_units, offer.currency)}
                </button>
              ) : (
                <p className="consent-note">Aguardando a outra parte cadastrar a conta de recebimento.</p>
              )}
              {payment?.status === 'pending' && (
                <small className="consent-note">Há um pagamento em aberto; ele continua de onde parou.</small>
              )}
            </div>
          )}
          {!isPayer && !isPayee && <p className="consent-note">Só as partes podem pagar ou receber.</p>}
        </>
      )}
      <LiveMessage type="error" text={error} />
    </section>
  )
}
