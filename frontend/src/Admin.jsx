import { useCallback, useEffect, useState } from 'react'
import {
  CheckCircle2,
  ChevronLeft,
  Mail,
  RefreshCw,
  ShieldCheck,
  XCircle
} from 'lucide-react'
import './admin.css'
import { statusLabels } from './shared.js'
import { LiveMessage, LoadingState, Modal } from './ui.jsx'

// Painel de operação. Mostra metadados (situação, papéis, falhas, e-mails,
// modelos), nunca o teor dos casos; o servidor registra cada consulta a um caso
// e cada intervenção.

const TABS = [
  { id: 'overview', label: 'Visão geral' },
  { id: 'cases', label: 'Casos' },
  { id: 'leads', label: 'Leads do piloto' },
  { id: 'emails', label: 'E-mails' },
  { id: 'users', label: 'Usuários' },
  { id: 'actions', label: 'Registro' }
]

const FLAG_LABELS = {
  stuck: 'Etapa presa',
  stage_failed: 'Etapa falhou',
  no_merit: 'Sem decisão de mérito',
  stalled: 'Parado há 14+ dias',
  contested: 'Com recurso',
  withdrawn: 'Saiu para a Justiça'
}

const ATTENTION_ITEMS = [
  { key: 'stuck', label: 'Casos com etapa presa', hint: 'Em processamento além de 10 minutos.', tab: 'cases', filter: { attention: 'stuck' } },
  { key: 'stage_failed', label: 'Etapas que falharam (24 h)', hint: 'O modelo ou a verificação falhou; o caso voltou à etapa anterior.', tab: 'cases', filter: { attention: 'stage_failed' } },
  { key: 'no_merit', label: 'Encerrados sem decisão de mérito', hint: 'Inconclusivos, inadmissíveis ou invalidados: revise o motivo.', tab: 'cases', filter: { attention: 'no_merit' } },
  { key: 'stalled', label: 'Casos parados há 14+ dias', hint: 'Sem movimento: vale um contato com as partes.', tab: 'cases', filter: { attention: 'stalled' } },
  { key: 'stale_invitations', label: 'Convites sem resposta há 3+ dias', hint: 'A contraparte ainda não entrou no caso.', tab: 'cases', filter: {} },
  { key: 'emails_failed', label: 'E-mails que falharam', hint: 'A parte pode não ter sido avisada.', tab: 'emails', filter: { status: 'failed' } },
  { key: 'emails_overdue', label: 'E-mails parados na fila', hint: 'Pendentes há mais de 10 minutos: o despachante pode estar parado.', tab: 'emails', filter: { status: 'pending' } },
  { key: 'leads_new', label: 'Leads novos', hint: 'Interessados no piloto sem contato.', tab: 'leads', filter: { status: 'new' } }
]

function when(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('pt-BR')
}

function Badge({ tone = 'neutral', children }) {
  return <span className={`adm-badge ${tone}`}>{children}</span>
}

function emailTone(status) {
  if (status === 'sent') return 'ok'
  if (status === 'failed') return 'bad'
  if (status === 'pending' || status === 'sending') return 'warn'
  return 'neutral'
}

const EMAIL_STATUS = {
  pending: 'Na fila',
  sending: 'Enviando',
  sent: 'Enviado',
  logged: 'Só em log',
  failed: 'Falhou'
}

function ReasonDialog({ title, description, confirmLabel, onConfirm, onClose, busy }) {
  const [reason, setReason] = useState('')
  return (
    <Modal onClose={onClose} labelledBy="adm-reason-title" size="narrow">
      <form
        className="dialog-card adm-reason"
        onSubmit={(event) => { event.preventDefault(); onConfirm(reason.trim()) }}
      >
        <h2 id="adm-reason-title">{title}</h2>
        <p>{description}</p>
        <label className="mini-field">
          <span>Motivo (fica no registro de operação)</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            minLength={5}
            maxLength={500}
            rows={3}
            required
            autoFocus
          />
        </label>
        <div className="adm-row end">
          <button type="button" className="button ghost compact" onClick={onClose}>Cancelar</button>
          <button className="button primary compact" disabled={busy || reason.trim().length < 5}>{confirmLabel}</button>
        </div>
      </form>
    </Modal>
  )
}

export default function Admin({ request, user, onBack }) {
  const params = new URLSearchParams(window.location.search)
  const [tab, setTab] = useState(params.get('case') ? 'cases' : 'overview')
  const [caseId, setCaseId] = useState(params.get('case') || '')
  const [filters, setFilters] = useState({})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const api = useCallback(async (path, options = {}) => {
    const { body, method = body ? 'POST' : 'GET' } = options
    return request(path, {
      method,
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
    })
  }, [request])

  function go(nextTab, nextFilters = {}) {
    setFilters(nextFilters)
    setCaseId('')
    setError('')
    setNotice('')
    setTab(nextTab)
  }

  return (
    <section className="adm" aria-label="Painel de operação">
      <header className="adm-head">
        <div>
          <span className="section-label">Operação</span>
          <h1><ShieldCheck size={26} aria-hidden="true" /> Painel de operação</h1>
          <p>
            Metadados e andamento, nunca o teor dos casos. Cada consulta a um caso e cada
            intervenção ficam registradas com o seu e-mail ({user.email}).
          </p>
        </div>
        <button type="button" className="button ghost compact" onClick={onBack}>
          <ChevronLeft size={16} /> Voltar aos casos
        </button>
      </header>

      <nav className="adm-tabs" aria-label="Seções do painel">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? 'active' : ''}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => go(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <LiveMessage type="error" text={error} />
      <LiveMessage type="success" text={notice} />

      {tab === 'overview' && <Overview api={api} setError={setError} go={go} />}
      {tab === 'cases' && (
        caseId
          ? <CaseDetail api={api} caseId={caseId} onBack={() => setCaseId('')} setError={setError} setNotice={setNotice} />
          : <Cases api={api} filters={filters} setFilters={setFilters} onOpen={setCaseId} setError={setError} />
      )}
      {tab === 'leads' && <Leads api={api} filters={filters} setError={setError} setNotice={setNotice} />}
      {tab === 'emails' && <Emails api={api} filters={filters} onOpenCase={(id) => { setTab('cases'); setCaseId(id) }} setError={setError} setNotice={setNotice} />}
      {tab === 'users' && <UsersTab api={api} setError={setError} setNotice={setNotice} />}
      {tab === 'actions' && <Actions api={api} setError={setError} />}
    </section>
  )
}

// Carrega um recurso e o recarrega sob demanda.
function useResource(load, deps, setError) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setData(await load())
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  return { data, loading, reload }
}

function Overview({ api, setError, go }) {
  const { data, loading, reload } = useResource(() => api('/admin/overview'), [], setError)
  if (loading && !data) return <LoadingState />
  if (!data) return null
  const attention = ATTENTION_ITEMS.filter((item) => data.attention[item.key] > 0)
  const llm = data.llm.last_24h
  return (
    <div className="adm-stack">
      <div className="adm-row between">
        <h2>O que pede atenção</h2>
        <button type="button" className="button ghost compact" onClick={reload} disabled={loading}>
          <RefreshCw size={15} /> Atualizar
        </button>
      </div>
      {attention.length === 0 ? (
        <p className="adm-ok"><CheckCircle2 size={18} /> Nada pendente: sem etapas presas, e-mails falhos ou leads novos.</p>
      ) : (
        <div className="adm-cards">
          {attention.map((item) => (
            <button
              key={item.key}
              type="button"
              className="adm-card attention"
              onClick={() => go(item.tab, item.filter)}
            >
              <strong>{data.attention[item.key]}</strong>
              <span>{item.label}</span>
              <small>{item.hint}</small>
            </button>
          ))}
        </div>
      )}

      <h2>Plataforma</h2>
      <div className="adm-cards">
        <div className="adm-card"><strong>{data.users.total}</strong><span>Contas</span><small>{data.users.verified} com e-mail confirmado · {data.users.new_7d} novas em 7 dias</small></div>
        <div className="adm-card"><strong>{data.cases.total}</strong><span>Casos</span><small>{data.cases.new_7d} novos em 7 dias</small></div>
        <div className="adm-card"><strong>{data.emails.sent}</strong><span>E-mails enviados</span><small>{data.emails.pending} na fila · {data.emails.failed} falhos · {data.emails.logged} só em log</small></div>
        <div className="adm-card"><strong>{llm.calls}</strong><span>Chamadas de modelo (24 h)</span><small>{llm.failed} falhas · {llm.tokens.toLocaleString('pt-BR')} tokens{llm.avg_latency_ms ? ` · ${(llm.avg_latency_ms / 1000).toFixed(1)} s em média` : ''}</small></div>
      </div>

      <h2>Casos por situação</h2>
      <div className="adm-chips">
        {Object.entries(data.cases.by_status).map(([status, count]) => (
          <button key={status} type="button" className="adm-chip" onClick={() => go('cases', { status })}>
            {statusLabels[status] || status} <b>{count}</b>
          </button>
        ))}
        {Object.keys(data.cases.by_status).length === 0 && <span className="adm-muted">Nenhum caso ainda.</span>}
      </div>

      <h2>Modelos (últimos 7 dias)</h2>
      {data.llm.last_7d.models.length === 0 ? (
        <p className="adm-muted">Nenhuma chamada de modelo no período.</p>
      ) : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead><tr><th>Modelo</th><th>Chamadas</th><th>Falhas</th><th>Tokens</th><th>Latência média</th></tr></thead>
            <tbody>
              {data.llm.last_7d.models.map((model) => (
                <tr key={model.model}>
                  <td>{model.model}</td><td>{model.calls}</td>
                  <td>{model.failed ? <Badge tone="bad">{model.failed}</Badge> : 0}</td>
                  <td>{model.tokens.toLocaleString('pt-BR')}</td>
                  <td>{model.avg_latency_ms ? `${(model.avg_latency_ms / 1000).toFixed(1)} s` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Configuração</h2>
      <ul className="adm-checks">
        {data.config.map((check) => (
          <li key={check.key} className={check.ok ? 'ok' : 'bad'}>
            {check.ok ? <CheckCircle2 size={18} aria-hidden="true" /> : <XCircle size={18} aria-hidden="true" />}
            <div><strong>{check.label}</strong>{!check.ok && <small>{check.hint}</small>}</div>
            <Badge tone={check.ok ? 'ok' : 'warn'}>{check.ok ? 'Ok' : 'Pendente'}</Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Pager({ total, offset, limit, onChange }) {
  if (total <= limit) return null
  return (
    <div className="adm-row between adm-pager">
      <span className="adm-muted">{offset + 1}–{Math.min(offset + limit, total)} de {total}</span>
      <div className="adm-row">
        <button type="button" className="button ghost compact" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Anterior</button>
        <button type="button" className="button ghost compact" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Próxima</button>
      </div>
    </div>
  )
}

function Cases({ api, filters, setFilters, onOpen, setError }) {
  const limit = 25
  const [offset, setOffset] = useState(0)
  const [q, setQ] = useState(filters.q || '')
  const query = new URLSearchParams({ limit, offset })
  if (filters.status) query.set('status', filters.status)
  if (filters.attention) query.set('attention', filters.attention)
  if (filters.q) query.set('q', filters.q)
  const { data, loading } = useResource(
    () => api(`/admin/cases?${query}`), [filters.status, filters.attention, filters.q, offset], setError
  )
  const update = (patch) => { setOffset(0); setFilters({ ...filters, ...patch }) }
  return (
    <div className="adm-stack">
      <form className="adm-filters" onSubmit={(event) => { event.preventDefault(); update({ q: q.trim() }) }}>
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Buscar por título, parte ou código" aria-label="Buscar casos" />
        <select value={filters.status || ''} onChange={(event) => update({ status: event.target.value })} aria-label="Situação">
          <option value="">Todas as situações</option>
          {Object.entries(statusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <select value={filters.attention || ''} onChange={(event) => update({ attention: event.target.value })} aria-label="Atenção">
          <option value="">Qualquer atenção</option>
          {Object.entries(FLAG_LABELS).filter(([key]) => key !== 'withdrawn').map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <button className="button secondary compact">Buscar</button>
      </form>
      {loading && !data ? <LoadingState /> : (
        <div className="adm-table-wrap">
          <table className="adm-table clickable">
            <thead><tr><th>Caso</th><th>Partes</th><th>Situação</th><th>Atenção</th><th>Atualizado</th></tr></thead>
            <tbody>
              {(data?.items || []).map((item) => (
                <tr key={item.id} tabIndex={0} onClick={() => onOpen(item.id)} onKeyDown={(event) => { if (event.key === 'Enter') onOpen(item.id) }}>
                  <td><strong>{item.title}</strong><small>{item.id.slice(0, 8)}</small></td>
                  <td>{item.claimant}<small>× {item.respondent}</small></td>
                  <td>{statusLabels[item.status] || item.status}</td>
                  <td>{item.flags.map((flag) => <Badge key={flag} tone={flag === 'stuck' || flag === 'stage_failed' ? 'bad' : 'warn'}>{FLAG_LABELS[flag]}</Badge>)}</td>
                  <td>{when(item.updated_at)}</td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td colSpan="5" className="adm-muted">Nenhum caso com esses filtros.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager total={data.total} offset={offset} limit={limit} onChange={setOffset} />}
    </div>
  )
}

function CaseDetail({ api, caseId, onBack, setError, setNotice }) {
  const { data, loading, reload } = useResource(() => api(`/admin/cases/${caseId}`), [caseId], setError)
  const [action, setAction] = useState(null)
  const [busy, setBusy] = useState(false)
  if (loading && !data) return <LoadingState />
  if (!data) return <button type="button" className="button ghost compact" onClick={onBack}><ChevronLeft size={16} /> Voltar</button>
  const { case: info } = data
  const stuck = info.flags.includes('stuck')

  async function confirm(reason) {
    setBusy(true)
    try {
      const result = await api(`/admin/cases/${caseId}/${action}`, { body: { reason } })
      setNotice(action === 'unstick'
        ? `Etapa liberada: o caso voltou para "${statusLabels[result.status] || result.status}".`
        : 'Pedido enviado ao gestor, que retoma a condução do caso.')
      setAction(null)
      await reload()
    } catch (err) {
      setError(err.message)
      setAction(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="adm-stack">
      <div className="adm-row between">
        <button type="button" className="button ghost compact" onClick={onBack}><ChevronLeft size={16} /> Voltar à lista</button>
        <div className="adm-row">
          <button type="button" className="button ghost compact" onClick={reload} disabled={loading}><RefreshCw size={15} /> Atualizar</button>
          {stuck && <button type="button" className="button secondary compact" onClick={() => setAction('unstick')}>Liberar etapa presa</button>}
          <button type="button" className="button primary compact" onClick={() => setAction('resume')}>Retomar condução</button>
        </div>
      </div>

      <div>
        <h2>{info.title}</h2>
        <p className="adm-muted">
          {info.claimant} × {info.respondent} · código {info.id}<br />
          {statusLabels[info.status] || info.status}{info.procedure_conclusion ? ` · conclusão: ${info.procedure_conclusion}` : ''}
          {' · '}criado em {when(info.created_at)}
        </p>
        <div className="adm-chips">{info.flags.map((flag) => <Badge key={flag} tone={flag === 'stuck' || flag === 'stage_failed' ? 'bad' : 'warn'}>{FLAG_LABELS[flag]}</Badge>)}</div>
      </div>

      <div className="adm-cards">
        <div className="adm-card"><span>Aceite dos termos</span><small>Reclamante: {info.consent.claimant ? 'sim' : 'não'} · Reclamada: {info.consent.respondent ? 'sim' : 'não'}</small></div>
        <div className="adm-card"><span>Apresentação encerrada</span><small>Reclamante: {info.submission_ready.claimant ? 'sim' : 'não'} · Reclamada: {info.submission_ready.respondent ? 'sim' : 'não'}</small></div>
        <div className="adm-card"><span>Documentos</span><small>{info.documents.total} no caso · {info.documents.admitted} admitidos · {info.documents.pending_response} sem resposta</small></div>
        <div className="adm-card"><span>Gestor</span><small>{info.steward.action || '—'} ({info.steward.state || '—'}){info.steward.reason ? ` · ${info.steward.reason}` : ''}</small></div>
      </div>

      <h3>Participantes</h3>
      <div className="adm-table-wrap">
        <table className="adm-table">
          <thead><tr><th>Papel</th><th>Nome</th><th>E-mail</th><th>Situação da conta</th></tr></thead>
          <tbody>
            {data.members.map((member) => (
              <tr key={`${member.role}-${member.user_id}`}>
                <td>{member.role}</td><td>{member.display_name}</td><td>{member.email}</td>
                <td>
                  <Badge tone={member.email_verified ? 'ok' : 'warn'}>{member.email_verified ? 'E-mail confirmado' : 'E-mail não confirmado'}</Badge>
                  {!member.active && <Badge tone="bad">Suspensa</Badge>}
                </td>
              </tr>
            ))}
            {data.members.length === 0 && <tr><td colSpan="4" className="adm-muted">Nenhum participante vinculado.</td></tr>}
          </tbody>
        </table>
      </div>
      {data.invitations.length > 0 && (
        <p className="adm-muted">
          Convites: {data.invitations.map((item) => `${item.role} (${item.status}, expira ${when(item.expires_at)})`).join(' · ')}
        </p>
      )}
      {data.deadlines.length > 0 && (
        <p className="adm-muted">
          Prazos: {data.deadlines.map((item) => `${item.label} → ${item.assigned_to}, ${when(item.due_at)}${item.completed_at ? ' (cumprido)' : ''}`).join(' · ')}
        </p>
      )}

      <h3>Linha do tempo <small className="adm-muted">(só tipos de evento)</small></h3>
      <ol className="adm-timeline">
        {data.timeline.map((event) => (
          <li key={event.id} className={event.event_type.includes('failed') ? 'bad' : ''}>
            <time>{when(event.timestamp_utc)}</time>
            <code>{event.event_type}</code>
            {event.detail && <span>{event.detail}</span>}
          </li>
        ))}
      </ol>

      <h3>Chamadas de modelo</h3>
      {data.llm_executions.length === 0 ? <p className="adm-muted">Nenhuma chamada registrada.</p> : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead><tr><th>Agente</th><th>Modelo</th><th>Situação</th><th>Tokens</th><th>Latência</th></tr></thead>
            <tbody>
              {data.llm_executions.map((item, index) => (
                <tr key={index}>
                  <td>{item.agent}</td><td>{item.provider}/{item.model || '—'}{item.fallback_used ? ' (fallback)' : ''}</td>
                  <td><Badge tone={item.status === 'completed' ? 'ok' : 'bad'}>{item.status}</Badge></td>
                  <td>{(item.prompt_tokens || 0) + (item.completion_tokens || 0)}</td>
                  <td>{item.latency_ms ? `${(item.latency_ms / 1000).toFixed(1)} s` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>E-mails do caso</h3>
      <EmailTable items={data.emails} />

      <h3>Intervenções da operação neste caso</h3>
      <ActionTable items={data.actions} />

      {action && (
        <ReasonDialog
          title={action === 'unstick' ? 'Liberar etapa presa' : 'Retomar condução do caso'}
          description={action === 'unstick'
            ? 'O caso volta ao status anterior à etapa. O ato entra na trilha de auditoria, visível às partes.'
            : 'O gestor conduz o caso de novo a partir do que está gravado. O ato entra na trilha de auditoria, visível às partes.'}
          confirmLabel={action === 'unstick' ? 'Liberar etapa' : 'Retomar'}
          busy={busy}
          onConfirm={confirm}
          onClose={() => setAction(null)}
        />
      )}
    </div>
  )
}

function EmailTable({ items, onRetry, onOpenCase }) {
  if (!items?.length) return <p className="adm-muted">Nenhum e-mail.</p>
  return (
    <div className="adm-table-wrap">
      <table className="adm-table">
        <thead><tr><th>Quando</th><th>Para</th><th>Assunto</th><th>Situação</th>{onRetry && <th />}</tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{when(item.created_at)}</td>
              <td>{item.to_email}<small>{item.audience === 'ops' ? 'alerta de operação' : 'parte'}</small></td>
              <td>
                {item.subject}<small>{item.kind}</small>
                {item.last_error && <small className="adm-error">{item.last_error}</small>}
                {onOpenCase && item.case_id && <button type="button" className="adm-link" onClick={() => onOpenCase(item.case_id)}>abrir caso</button>}
              </td>
              <td><Badge tone={emailTone(item.status)}>{EMAIL_STATUS[item.status] || item.status}</Badge><small>{item.attempts} tentativa(s)</small></td>
              {onRetry && (
                <td>{['failed', 'logged', 'pending'].includes(item.status) && (
                  <button type="button" className="button ghost compact" onClick={() => onRetry(item)}>Reenviar</button>
                )}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Emails({ api, filters, onOpenCase, setError, setNotice }) {
  const limit = 30
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState(filters.status || '')
  const [audience, setAudience] = useState('')
  const [busy, setBusy] = useState(false)
  const query = new URLSearchParams({ limit, offset })
  if (status) query.set('status', status)
  if (audience) query.set('audience', audience)
  const { data, loading, reload } = useResource(
    () => api(`/admin/emails?${query}`), [status, audience, offset], setError
  )
  async function retry(item) {
    try {
      await api(`/admin/emails/${item.id}/retry`, { method: 'POST' })
      setNotice('E-mail devolvido à fila.')
      await reload()
    } catch (err) { setError(err.message) }
  }
  async function dispatch() {
    setBusy(true)
    try {
      const counts = await api('/admin/emails/dispatch', { method: 'POST' })
      setNotice(`Fila processada: ${counts.sent} enviados, ${counts.logged} só em log, ${counts.retry} para repetir, ${counts.failed} falhos.`)
      await reload()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return (
    <div className="adm-stack">
      <div className="adm-row between">
        <div className="adm-filters">
          <select value={status} onChange={(event) => { setOffset(0); setStatus(event.target.value) }} aria-label="Situação do e-mail">
            <option value="">Todas as situações</option>
            {Object.entries(EMAIL_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          <select value={audience} onChange={(event) => { setOffset(0); setAudience(event.target.value) }} aria-label="Destinatário">
            <option value="">Partes e operação</option>
            <option value="party">Só partes</option>
            <option value="ops">Só alertas de operação</option>
          </select>
        </div>
        <button type="button" className="button secondary compact" onClick={dispatch} disabled={busy}><Mail size={15} /> Enviar fila agora</button>
      </div>
      {loading && !data ? <LoadingState /> : <EmailTable items={data?.items} onRetry={retry} onOpenCase={onOpenCase} />}
      {data && <Pager total={data.total} offset={offset} limit={limit} onChange={setOffset} />}
    </div>
  )
}

const LEAD_STATUS = { new: 'Novo', contacted: 'Contatado', qualified: 'Qualificado', discarded: 'Descartado' }

function Leads({ api, filters, setError, setNotice }) {
  const [status, setStatus] = useState(filters.status || '')
  const { data, loading, reload } = useResource(
    () => api(`/admin/leads${status ? `?status=${status}` : ''}`), [status], setError
  )
  const [notes, setNotes] = useState({})
  async function save(lead, patch) {
    try {
      await api(`/admin/leads/${lead.id}`, { method: 'PATCH', body: patch })
      setNotice('Lead atualizado.')
      await reload()
    } catch (err) { setError(err.message) }
  }
  if (loading && !data) return <LoadingState />
  return (
    <div className="adm-stack">
      <div className="adm-chips">
        <button type="button" className={`adm-chip ${status === '' ? 'on' : ''}`} onClick={() => setStatus('')}>Todos</button>
        {Object.entries(LEAD_STATUS).map(([key, label]) => (
          <button key={key} type="button" className={`adm-chip ${status === key ? 'on' : ''}`} onClick={() => setStatus(key)}>
            {label} <b>{data?.counts?.[key] ?? 0}</b>
          </button>
        ))}
      </div>
      {(data?.items || []).map((lead) => (
        <article key={lead.id} className="adm-lead">
          <div>
            <h3>{lead.company}</h3>
            <p>{lead.name} · <a href={`mailto:${lead.email}`}>{lead.email}</a></p>
            <p className="adm-muted">{lead.monthly_volume.toLocaleString('pt-BR')} processos/mês · recebido em {when(lead.created_at)}{lead.notification_status === 'failed' ? ' · aviso por e-mail falhou' : ''}</p>
          </div>
          <div className="adm-lead-work">
            <select value={lead.status} onChange={(event) => save(lead, { status: event.target.value })} aria-label={`Situação de ${lead.company}`}>
              {Object.entries(LEAD_STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
            <textarea
              rows={2}
              placeholder="Anotações do contato"
              value={notes[lead.id] ?? lead.notes}
              onChange={(event) => setNotes({ ...notes, [lead.id]: event.target.value })}
              aria-label={`Anotações de ${lead.company}`}
            />
            <button
              type="button"
              className="button ghost compact"
              disabled={(notes[lead.id] ?? lead.notes) === lead.notes}
              onClick={() => save(lead, { notes: notes[lead.id] })}
            >
              Salvar anotações
            </button>
          </div>
        </article>
      ))}
      {data && data.items.length === 0 && <p className="adm-muted">Nenhum lead nesta situação.</p>}
    </div>
  )
}

function UsersTab({ api, setError, setNotice }) {
  const limit = 30
  const [offset, setOffset] = useState(0)
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [dialog, setDialog] = useState(null)
  const [busy, setBusy] = useState(false)
  const { data, loading, reload } = useResource(
    () => api(`/admin/users?limit=${limit}&offset=${offset}${term ? `&q=${encodeURIComponent(term)}` : ''}`), [offset, term], setError
  )
  async function act(path, message, body) {
    try {
      await api(path, { method: 'POST', ...(body ? { body } : {}) })
      setNotice(message)
      await reload()
    } catch (err) { setError(err.message) }
  }
  async function confirmSuspend(reason) {
    setBusy(true)
    await act(`/admin/users/${dialog.user.id}/active`, dialog.user.active ? 'Conta suspensa e sessões encerradas.' : 'Conta reativada.', { active: !dialog.user.active, reason })
    setBusy(false)
    setDialog(null)
  }
  return (
    <div className="adm-stack">
      <form className="adm-filters" onSubmit={(event) => { event.preventDefault(); setOffset(0); setTerm(q.trim()) }}>
        <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Buscar por nome ou e-mail" aria-label="Buscar usuários" />
        <button className="button secondary compact">Buscar</button>
      </form>
      {loading && !data ? <LoadingState /> : (
        <div className="adm-table-wrap">
          <table className="adm-table">
            <thead><tr><th>Conta</th><th>Situação</th><th>Casos</th><th>Criada</th><th /></tr></thead>
            <tbody>
              {(data?.items || []).map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.display_name}</strong><small>{item.email}</small></td>
                  <td>
                    <Badge tone={item.email_verified ? 'ok' : 'warn'}>{item.email_verified ? 'E-mail confirmado' : 'E-mail pendente'}</Badge>
                    {!item.active && <Badge tone="bad">Suspensa</Badge>}
                    {item.locked_until && <Badge tone="warn">Bloqueada até {when(item.locked_until)}</Badge>}
                    {item.is_admin && <Badge tone="neutral">Operação</Badge>}
                  </td>
                  <td>{item.cases}</td>
                  <td>{when(item.created_at)}</td>
                  <td className="adm-actions">
                    {!item.email_verified && <button type="button" className="button ghost compact" onClick={() => act(`/admin/users/${item.id}/resend-verification`, 'Link de confirmação reenviado.')}>Reenviar confirmação</button>}
                    {item.locked_until && <button type="button" className="button ghost compact" onClick={() => act(`/admin/users/${item.id}/unlock`, 'Conta desbloqueada.')}>Desbloquear</button>}
                    <button type="button" className="button ghost compact" onClick={() => setDialog({ user: item })}>{item.active ? 'Suspender' : 'Reativar'}</button>
                  </td>
                </tr>
              ))}
              {data && data.items.length === 0 && <tr><td colSpan="5" className="adm-muted">Nenhuma conta encontrada.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager total={data.total} offset={offset} limit={limit} onChange={setOffset} />}
      {dialog && (
        <ReasonDialog
          title={dialog.user.active ? `Suspender ${dialog.user.display_name}` : `Reativar ${dialog.user.display_name}`}
          description={dialog.user.active
            ? 'A conta perde o acesso e as sessões abertas são encerradas. Os casos e a trilha de auditoria permanecem.'
            : 'A conta volta a poder entrar na plataforma.'}
          confirmLabel={dialog.user.active ? 'Suspender' : 'Reativar'}
          busy={busy}
          onConfirm={confirmSuspend}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}

function ActionTable({ items }) {
  if (!items?.length) return <p className="adm-muted">Nenhum registro.</p>
  return (
    <div className="adm-table-wrap">
      <table className="adm-table">
        <thead><tr><th>Quando</th><th>Quem</th><th>Ação</th><th>Alvo</th><th>Detalhe</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{when(item.created_at)}</td><td>{item.admin_email}</td>
              <td><code>{item.action}</code></td>
              <td>{item.target_type}{item.target_id ? ` ${String(item.target_id).slice(0, 8)}` : ''}</td>
              <td>{item.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Actions({ api, setError }) {
  const { data, loading } = useResource(() => api('/admin/actions?limit=200'), [], setError)
  if (loading && !data) return <LoadingState />
  return (
    <div className="adm-stack">
      <p className="adm-muted">Tudo o que a operação consultou ou alterou. Os registros não podem ser editados.</p>
      <ActionTable items={data?.items} />
    </div>
  )
}

