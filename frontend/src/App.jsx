import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import ValinorMark from './ValinorMark.jsx'
import { Info, LogIn, LogOut, Mail, Plus, UserRound } from 'lucide-react'
import {
  API_BASE,
  CONTACT_EMAIL,
  MATTERS,
  STAGE_PROCESSING_STATUS,
  canSeeSystemBadge,
  formatApiDetail,
  statusLabels
} from './shared.js'
import { InviteDialog, LeadDialog } from './Dialogs.jsx'
import Markdown from './Markdown.jsx'
import { LiveMessage, LoadingState, Modal, ProcessingCard } from './ui.jsx'

// A landing e o workspace são chunks separados: quem chega sem conta só baixa a
// apresentação, e quem já está logado não baixa a landing.
// Termos e política abrem em modal e têm endereço próprio (/ui/termos e
// /ui/privacidade); o servidor devolve o index para esses caminhos.
const LEGAL_SLUGS = { terms: 'termos', privacy: 'privacidade' }

function legalFromPath() {
  const match = window.location.pathname.match(/\/(termos|privacidade)\/?$/)
  if (!match) return null
  return match[1] === 'termos' ? 'terms' : 'privacy'
}

const Landing = lazy(() => import('./Landing.jsx'))
const Workspace = lazy(() => import('./Workspace.jsx'))

function llmReady(system) {
  if (!system) return false
  if (typeof system.llm_enabled === 'boolean') return system.llm_enabled
  return Boolean(system.openrouter_enabled || system.openai_enabled)
}

export default function App() {
  const [cases, setCases] = useState([])
  const [caseData, setCaseData] = useState(null)
  const [system, setSystem] = useState(null)
  const [documentText, setDocumentText] = useState('')
  const [documentName, setDocumentName] = useState('contrato.txt')
  const [documentParty, setDocumentParty] = useState('claimant')
  const [materialType, setMaterialType] = useState('evidence')
  const [documentPurpose, setDocumentPurpose] = useState('')
  const [evidenceResponses, setEvidenceResponses] = useState({})
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  // Cada ação tem a sua chave: { chave: exclusiva }. Só as exclusivas (escritas
  // no caso) travam outras escritas; auth, criação, conta e downloads são
  // independentes e não desabilitam o resto da tela.
  const [pending, setPending] = useState({})
  const pendingRef = useRef({})
  const [activity, setActivity] = useState(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showTechnical, setShowTechnical] = useState(false)
  const [claimantResponse, setClaimantResponse] = useState('')
  const [respondentResponse, setRespondentResponse] = useState('')
  const [conciliationUpdate, setConciliationUpdate] = useState('')
  const [user, setUser] = useState(null)
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState('register')
  // De onde o acesso foi aberto: muda o texto (abrir caso, convite recebido).
  const [authContext, setAuthContext] = useState('default')
  const [showInvite, setShowInvite] = useState(false)
  const [showLead, setShowLead] = useState(false)
  const [leadSent, setLeadSent] = useState(false)
  const [leadError, setLeadError] = useState('')
  const [inviteToken] = useState(() => new URLSearchParams(window.location.search).get('invite') || '')
  const [resetToken, setResetToken] = useState(() => new URLSearchParams(window.location.search).get('reset') || '')
  const [terms, setTerms] = useState(null)
  const [privacy, setPrivacy] = useState(null)
  const [authNotice, setAuthNotice] = useState('')
  const [showAccount, setShowAccount] = useState(false)
  const [legalView, setLegalViewState] = useState(legalFromPath)
  const [pendingStart, setPendingStart] = useState(false)
  const workspaceRef = useRef(null)

  function setLegalView(kind) {
    setLegalViewState(kind)
    const path = kind ? `${import.meta.env.BASE_URL}${LEGAL_SLUGS[kind]}` : import.meta.env.BASE_URL
    if (window.location.pathname !== path) window.history.pushState({}, '', path)
  }

  const isPending = (key) => key in pending
  const busy = Object.values(pending).some(Boolean)

  function markPending(key, exclusive) {
    pendingRef.current = { ...pendingRef.current, [key]: exclusive }
    setPending(pendingRef.current)
  }

  function clearPending(key) {
    const { [key]: _removed, ...rest } = pendingRef.current
    pendingRef.current = rest
    setPending(rest)
  }

  // Executa `fn` com um estado de carregamento próprio. Chamar de novo a mesma
  // ação enquanto ela roda não faz nada (protege contra duplo clique).
  async function track(key, fn, { exclusive = false } = {}) {
    if (key in pendingRef.current) return undefined
    if (exclusive && Object.values(pendingRef.current).some(Boolean)) return undefined
    markPending(key, exclusive)
    try {
      return await fn()
    } finally {
      clearPending(key)
    }
  }

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      headers: options.headers || {}
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(formatApiDetail(data.detail, `Erro HTTP ${response.status}`))
    return data
  }

  function actorHeaders() {
    // The HttpOnly cookie authenticates the account; the backend derives roles.
    return {}
  }

  function authenticate(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    return track('auth', async () => {
      setError('')
      try {
        const path = authMode === 'register' ? '/auth/register' : '/auth/login'
        const payload = authMode === 'register'
          ? { display_name: form.get('display_name'), email: form.get('email'), password: form.get('password') }
          : { email: form.get('email'), password: form.get('password') }
        const data = await request(path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
        setUser(data.user)
        setShowAuth(false)
        if (authMode === 'register' && data.user?.email_verified === false) {
          const delivery = data.email_verification?.delivery || {}
          if (data.email_verification?.verification_path) {
            setAuthNotice(`Confirme o e-mail. Link local: ${data.email_verification.verification_path}`)
          } else if (delivery.delivered) {
            setAuthNotice(`Enviamos um link de confirmação para ${data.user.email}.`)
          } else if (delivery.error) {
            setAuthNotice(`Não foi possível enviar o e-mail de confirmação (${delivery.error}). Use Reenviar link.`)
          } else {
            setAuthNotice(`Confirme o e-mail enviado para ${data.user.email} antes de atuar no procedimento.`)
          }
        } else {
          setStatus('Acesso confirmado. Seus casos e convites estão protegidos pela sua conta.')
        }
        await loadCases()
        // Quem entrou para abrir um caso cai direto no formulário, desde que o
        // e-mail já esteja confirmado; senão o aviso de confirmação vem antes.
        if (pendingStart) {
          setPendingStart(false)
          setShowCreate(true)
          scrollToWorkspace()
        }
      } catch (err) {
        setError(err.message)
      }
    })
  }

  function resendVerification() {
    return track('resend-verification', async () => {
      setError('')
      try {
        const data = await request('/auth/verify-email/resend', { method: 'POST' })
        setAuthNotice(data.message)
      } catch (err) {
        setError(err.message)
      }
    })
  }

  function requestPasswordReset(event) {
    event.preventDefault()
    const email = new FormData(event.currentTarget).get('email')
    return track('auth', async () => {
      setError('')
      try {
        const data = await request('/auth/password-reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        })
        // Em produção o link só chega por e-mail; no modo local ele volta aqui.
        setAuthNotice(data.reset_path
          ? `${data.message} Link local: ${data.reset_path}`
          : data.message)
        setAuthMode('login')
      } catch (err) {
        setError(err.message)
      }
    })
  }

  function confirmPasswordReset(event) {
    event.preventDefault()
    const password = new FormData(event.currentTarget).get('password')
    return track('reset', async () => {
      setError('')
      try {
        const data = await request('/auth/password-reset/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: resetToken, password })
        })
        setAuthNotice(data.message)
        setUser(null)
        setResetToken('')
        setAuthMode('login')
        window.history.replaceState({}, '', window.location.pathname)
      } catch (err) {
        setError(err.message)
      }
    })
  }

  async function logout() {
    try { await request('/auth/logout', { method: 'POST' }) } catch { /* clear local UI regardless */ }
    setUser(null)
    setCases([])
    setCaseData(null)
    setShowCreate(false)
    setShowAccount(false)
    window.scrollTo({ top: 0 })
  }

  function exportAccountData() {
    return track('account-export', async () => {
      setError('')
      try {
        const data = await request('/account/data-export')
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = 'valinor-meus-dados.json'
        anchor.click()
        URL.revokeObjectURL(url)
        setStatus('Exportação da conta baixada.')
        setShowAccount(false)
      } catch (err) {
        setError(err.message)
      }
    })
  }

  function eraseAccount() {
    return track('account-erase', async () => {
      setError('')
      try {
        const preview = await request('/account/erasure/preview')
        if (!preview.allowed) {
          throw new Error(preview.detail)
        }
        const confirmed = window.confirm(
          'Anonimizar esta conta? A identificação é removida e a sessão encerra. Casos, hashes e a cadeia de auditoria permanecem.'
        )
        if (!confirmed) return
        await request('/account/erasure', { method: 'POST' })
        setAuthNotice('Conta anonimizada. A identificação pessoal foi removida.')
        setUser(null)
        setCases([])
        setCaseData(null)
        setShowCreate(false)
        setShowAccount(false)
        window.scrollTo({ top: 0 })
      } catch (err) {
        setError(err.message)
      }
    })
  }

  async function acceptPendingInvite() {
    await run('Vinculando o convite à sua conta...', () => request('/invitations/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: inviteToken })
    }), { key: 'accept-invite' })
    window.history.replaceState({}, '', window.location.pathname)
  }

  async function loadCase(caseId) {
    const data = await request(`/cases/${caseId}`)
    setCaseData(data)
    setShowCreate(false)
    setShowTechnical(false)
    setClaimantResponse('')
    setRespondentResponse('')
    setConciliationUpdate('')
  }

  async function loadCases(selectId) {
    const items = await request('/cases')
    setCases(items)
    const target = selectId || caseData?.id || items[0]?.id
    if (target) await loadCase(target)
  }

  useEffect(() => {
    const onPop = () => setLegalViewState(legalFromPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    // Remove credentials left by versions that stored bearer tokens in the browser.
    localStorage.removeItem('arbitragem_session')
    localStorage.removeItem('arbitragem_user')
    localStorage.removeItem('arbitragem_case_credentials')

    async function bootstrap() {
      try {
        const root = await request('/')
        setSystem(root)
        try {
          setTerms(await request('/terms'))
        } catch { /* sem os termos, o painel de aceite avisa e não deixa aceitar às cegas */ }
        try {
          setPrivacy(await request('/privacy'))
        } catch { /* a política é informativa aqui; o aceite não depende dela */ }

        const verifyToken = new URLSearchParams(window.location.search).get('verify')
        if (verifyToken) {
          try {
            const verified = await request('/auth/verify-email', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ token: verifyToken })
            })
            setAuthNotice(`E-mail ${verified.user.email} confirmado.`)
          } catch (err) {
            setError(err.message)
          }
          window.history.replaceState({}, '', window.location.pathname)
        }
        try {
          setUser(await request('/auth/me'))
          const items = await request('/cases')
          setCases(items)
          if (items[0]) await loadCase(items[0].id)
          else setShowCreate(true)
        } catch (err) {
          // Sem sessão: o visitante vê a apresentação e entra quando quiser.
          if (!/401|sessão|entre/i.test(err.message)) throw err
        }
      } catch (err) {
        setError(err.message)
      }
    }
    bootstrap()
  }, [])

  // O card de processamento acompanha a etapa de IA em andamento: `status` é o
  // status `processing_*` quando já se sabe qual é, e `label` é o que o usuário pediu.
  function beginActivity(label, startedAt, stage) {
    setActivity({ label, startedAt, status: STAGE_PROCESSING_STATUS[stage] || null })
  }

  function updateActivityStatus(status) {
    if (!String(status || '').startsWith('processing')) return
    setActivity((current) => (current && current.status !== status ? { ...current, status } : current))
  }

  // As etapas que chamam modelos respondem 202 e seguem em segundo plano: uma
  // decisão pode levar minutos e nenhum gateway segura a conexão até lá. O
  // cliente acompanha pelo endpoint de polling que veio na resposta.
  async function settleCase(caseId, startedAt) {
    const deadline = Date.now() + 15 * 60 * 1000
    let delay = 800
    let previous = ''
    setActivity((current) => current || {
      label: 'O gestor está conduzindo o procedimento...',
      startedAt,
      status: null
    })
    while (Date.now() < deadline) {
      const current = await request(`/cases/${caseId}`)
      const working = String(current.status || '').startsWith('processing')
        || current.steward?.state === 'processing'
      updateActivityStatus(current.status)
      const signature = `${current.status}|${current.steward?.state}|${current.steward?.action}`
      if (!working && signature === previous) return current
      previous = working ? '' : signature
      await new Promise((resolve) => setTimeout(resolve, delay))
      delay = Math.min(Math.round(delay * 1.4), 5000)
    }
    throw new Error(
      'O gestor ainda está conduzindo o procedimento. Recarregue o caso em alguns minutos.'
    )
  }

  async function waitForStage(pollPath) {
    const deadline = Date.now() + 15 * 60 * 1000
    let delay = 800
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, delay))
      delay = Math.min(Math.round(delay * 1.4), 5000)
      const body = await request(pollPath)
      if (body.state === 'failed') {
        throw new Error(
          body.error
            ? `A etapa não pôde ser concluída (${body.error}). Você pode tentar de novo.`
            : 'A etapa não pôde ser concluída. Você pode tentar de novo.'
        )
      }
      if (body.state !== 'processing') return body.result
    }
    throw new Error(
      'A etapa está demorando mais do que o esperado. Ela continua rodando: '
      + 'recarregue o caso em alguns minutos para ver o resultado.'
    )
  }

  // `options.key` identifica a ação (padrão: o próprio rótulo); `exclusive:
  // false` é para ações que não escrevem no caso, como baixar um arquivo.
  function run(label, action, { key = label, exclusive = true } = {}) {
    return track(key, async () => {
      const startedAt = Date.now()
      setError('')
      setStatus(label)
      try {
        let result = await action()
        if (result?.state === 'processing' && result?.poll) {
          beginActivity(label, startedAt, result.stage)
          result = await waitForStage(result.poll)
        }
        if (caseData?.id) await loadCases(caseData.id)
        const stewardBusy = result?.steward?.state === 'processing'
          || String(result?.status || '').startsWith('processing')
        if (stewardBusy && caseData?.id) await settleCase(caseData.id, startedAt)
        setStatus('Pronto. O gestor segue com o que for da conta dele.')
        return result
      } catch (err) {
        setError(err.message)
        setStatus('')
        if (caseData?.id) await loadCases(caseData.id).catch(() => {})
      } finally {
        setActivity(null)
      }
      return undefined
    }, { exclusive })
  }

  function createCase(event) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    return track('create-case', async () => {
      setError('')
      try {
        const data = await request('/cases', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: form.get('title'),
            claimant: form.get('claimant'),
            respondent: form.get('respondent'),
            matter_framework_id: form.get('matter_framework_id'),
            entry_point: form.get('entry_point'),
            creator_role: form.get('creator_role') || 'claimant',
            ...(form.get('acting_as_counsel')
              ? { acting_as_counsel: true, counsel_bar_number: form.get('counsel_bar_number') }
              : {}),
            ...(form.get('entry_point') === 'pending_lawsuit'
              ? { lawsuit_number: form.get('lawsuit_number'), court: form.get('court') }
              : {}),
            ...(MATTERS.find((item) => item.id === form.get('matter_framework_id'))?.consumer
              ? { consumer_party: form.get('consumer_party') }
              : {})
          })
        })
        delete data.access_credentials
        formElement.reset()
        await loadCases(data.id)
        setStatus('Caso criado. Agora adicione os documentos da disputa.')
      } catch (err) {
        setError(err.message)
      }
    })
  }

  async function addTextDocument() {
    await run('Lendo e registrando o documento...', async () => {
      const data = await request(`/cases/${caseData.id}/documents/text`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...actorHeaders(caseData.id, documentParty)
        },
        body: JSON.stringify({
          name: documentName,
          content: documentText,
          submitted_by: documentParty,
          material_type: materialType,
          purpose: documentPurpose
        })
      })
      setDocumentText('')
      setDocumentPurpose('')
      return data
    })
  }

  async function uploadPdf(event) {
    const file = event.target.files[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('submitted_by', documentParty)
    form.append('material_type', materialType)
    form.append('purpose', documentPurpose)
    await run('Lendo e registrando o PDF...', () => request(
      `/cases/${caseData.id}/documents/pdf`,
      {
        method: 'POST',
        headers: actorHeaders(caseData.id, documentParty),
        body: form
      }
    ))
    event.target.value = ''
  }

  function scrollToWorkspace() {
    requestAnimationFrame(() => {
      workspaceRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  function openAuth(mode = 'login', context = 'default') {
    setAuthMode(mode)
    setAuthContext(context)
    setShowInvite(false)
    setShowAuth(true)
  }

  function openInvite() {
    setShowInvite(true)
  }

  function openLead() {
    setLeadSent(false)
    setLeadError('')
    setShowLead(true)
  }

  function submitLead(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    return track('lead', async () => {
      setLeadError('')
      try {
        await request('/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: form.get('name'),
            company: form.get('company'),
            email: form.get('email'),
            monthly_volume: Number(form.get('monthly_volume') || 0),
            website: form.get('website') || ''
          })
        })
        setLeadSent(true)
      } catch (err) {
        setLeadError(err.message)
      }
    })
  }

  function startNewCase() {
    setError('')
    setStatus('')
    if (!user) {
      // Criar um caso exige conta: abre o acesso e retoma o formulário depois.
      setPendingStart(true)
      openAuth('register', 'start')
      return
    }
    setShowCreate(true)
    scrollToWorkspace()
  }

  function closeAuth() {
    setShowAuth(false)
    setPendingStart(false)
  }

  const processingTitle = activity
    ? statusLabels[activity.status] || activity.label
    : ''
  const processingDetail = activity?.status
    ? 'Pode levar alguns minutos. A etapa continua mesmo se você sair desta tela.'
    : 'Aguardando o início da etapa. Pode levar alguns minutos.'

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark"><ValinorMark size={44} tone="light" title="Valinor" /></span>
            <div>
              <strong>Valinor</strong>
              <small>Conflitos resolvidos fora da Justiça</small>
            </div>
          </div>
          <div className="topbar-actions">
            {canSeeSystemBadge(user) && (
              <span className={`system-status ${llmReady(system) ? 'online' : 'demo'}`}>
                <span />
                {llmReady(system) ? 'Chave de IA configurada' : 'Modo demonstração'}
              </span>
            )}
            {user ? (
              <div className="account-menu-wrap">
                <span className="account-chip">
                  <button type="button" className="account-chip-open" onClick={() => setShowAccount((open) => !open)}>
                    <UserRound size={15} /> {user.display_name}
                  </button>
                  <button type="button" onClick={logout} title="Sair" aria-label="Sair"><LogOut size={14} /></button>
                </span>
                {showAccount && (
                  <AccountPanel
                    user={user}
                    exporting={isPending('account-export')}
                    erasing={isPending('account-erase')}
                    onClose={() => setShowAccount(false)}
                    onExport={exportAccountData}
                    onErase={eraseAccount}
                    onOpenLegal={setLegalView}
                  />
                )}
              </div>
            ) : (
              <>
                <button type="button" className="topbar-link" onClick={openInvite}>
                  Recebi um convite
                </button>
                <button type="button" className="button ghost compact" onClick={() => openAuth('login')} aria-label="Entrar">
                  <LogIn size={16} /> Entrar
                </button>
              </>
            )}
            <button type="button" className="button primary compact" onClick={startNewCase} aria-label="Novo caso">
              <Plus size={17} /> Novo caso
            </button>
          </div>
        </div>
      </header>

      <main className="page">
        {!user && (
          <Suspense fallback={<div className="landing-fallback" aria-busy="true" />}>
            <Landing onStart={startNewCase} onLead={openLead} />
          </Suspense>
        )}

        {authNotice && (
          <div className="invite-banner" role="status">
            <Mail size={20} />
            <div>
              <strong>{authNotice}</strong>
            </div>
            <button type="button" className="button ghost compact" onClick={() => setAuthNotice('')}>Fechar</button>
          </div>
        )}

        {resetToken && (
          <PasswordResetPanel
            busy={isPending('reset')}
            onSubmit={confirmPasswordReset}
            onCancel={() => {
              setResetToken('')
              window.history.replaceState({}, '', window.location.pathname)
            }}
          />
        )}

        {user && user.email_verified === false && (
          <div className="invite-banner">
            <Mail size={20} />
            <div>
              <strong>Confirme seu e-mail para atuar no procedimento</strong>
              <span>
                Enviamos um link para {user.email}. Enquanto ele não for confirmado,
                sua conta não pratica atos no caso.
              </span>
            </div>
            <button type="button" className="button primary" onClick={resendVerification} disabled={isPending('resend-verification')}>
              Reenviar link
            </button>
          </div>
        )}

        {showAuth && !resetToken && (
          <Modal onClose={closeAuth} labelledBy="auth-dialog-title">
            <AuthPanel
              mode={authMode}
              context={authContext}
              setMode={setAuthMode}
              busy={isPending('auth')}
              error={error}
              onSubmit={authMode === 'forgot' ? requestPasswordReset : authenticate}
              onClose={closeAuth}
              terms={terms}
              privacy={privacy}
              onOpenLegal={setLegalView}
            />
          </Modal>
        )}

        {showInvite && !user && (
          <InviteDialog
            hasToken={Boolean(inviteToken)}
            onClose={() => setShowInvite(false)}
            onLogin={() => openAuth('login', 'invite')}
            onRegister={() => openAuth('register', 'invite')}
          />
        )}

        {showLead && (
          <LeadDialog
            sent={leadSent}
            pending={isPending('lead')}
            error={leadError}
            onSubmit={submitLead}
            onClose={() => setShowLead(false)}
            onOpenPrivacy={() => { setShowLead(false); setLegalView('privacy') }}
          />
        )}

        {inviteToken && (
          <div className="invite-banner">
            <Mail size={20} />
            <div>
              <strong>Você recebeu um convite para participar de um caso</strong>
              <span>{user ? 'Vincule o caso à sua conta para acessar o papel que foi atribuído.' : 'Entre ou crie sua conta com o mesmo e-mail usado no convite.'}</span>
            </div>
            {user ? (
              <button type="button" className="button primary" onClick={acceptPendingInvite} disabled={isPending('accept-invite')}>Aceitar convite</button>
            ) : (
              <button type="button" className="button primary" onClick={() => openAuth('login')}>Entrar para aceitar</button>
            )}
          </div>
        )}

        {/* Visitante não vê aviso de infraestrutura. Quem está logado vê o efeito
            (sem decisão de mérito); o detalhe da chave só aparece para admin/dev. */}
        {user && !llmReady(system) && (
          <div className="demo-notice">
            <Info size={19} />
            <div>
              <strong>A análise por IA está indisponível neste ambiente</strong>
              <span>
                {canSeeSystemBadge(user)
                  ? 'Sem uma chave OpenRouter, o agente julgador não profere decisão de mérito e o caso permanece inconclusivo.'
                  : 'O caso é registrado, mas a IA não profere decisão de mérito: ele permanece inconclusivo.'}
              </span>
            </div>
          </div>
        )}

        <LiveMessage
          type="error"
          text={error && !caseData && !showCreate && !showAuth ? error : ''}
        />

        {user && (
          <Suspense fallback={<LoadingState />}>
            <Workspace
              workspaceRef={workspaceRef}
              cases={cases}
              caseData={caseData}
              showCreate={showCreate}
              setShowCreate={setShowCreate}
              loadCase={loadCase}
              loadCases={loadCases}
              createCase={createCase}
              creating={isPending('create-case')}
              createError={error}
              busy={busy}
              isPending={isPending}
              status={status}
              error={error}
              documentName={documentName}
              documentText={documentText}
              documentParty={documentParty}
              materialType={materialType}
              documentPurpose={documentPurpose}
              setDocumentName={setDocumentName}
              setDocumentText={setDocumentText}
              setDocumentParty={setDocumentParty}
              setMaterialType={setMaterialType}
              setDocumentPurpose={setDocumentPurpose}
              evidenceResponses={evidenceResponses}
              setEvidenceResponses={setEvidenceResponses}
              addTextDocument={addTextDocument}
              uploadPdf={uploadPdf}
              run={run}
              request={request}
              actorHeaders={actorHeaders}
              claimantResponse={claimantResponse}
              respondentResponse={respondentResponse}
              conciliationUpdate={conciliationUpdate}
              setClaimantResponse={setClaimantResponse}
              setRespondentResponse={setRespondentResponse}
              setConciliationUpdate={setConciliationUpdate}
              terms={terms}
              privacy={privacy}
              showTechnical={showTechnical}
              setShowTechnical={setShowTechnical}
              user={user}
            />
          </Suspense>
        )}

        {legalView && (
          <LegalReader
            kind={legalView}
            terms={terms}
            privacy={privacy}
            onClose={() => setLegalView(null)}
          />
        )}
      </main>
      <footer className="legal-footer">
        <div className="legal-footer-inner">
          <button type="button" onClick={() => setLegalView('terms')}>Termos do procedimento</button>
          <button type="button" onClick={() => setLegalView('privacy')}>Política de privacidade</button>
          <span>Contato e privacidade: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a></span>
        </div>
      </footer>

      {activity && (
        <ProcessingCard
          title={processingTitle}
          detail={processingDetail}
          startedAt={activity.startedAt}
        />
      )}
    </div>
  )
}

const AUTH_COPY = {
  register: {
    title: 'Crie sua conta',
    description: 'Uma conta permite receber convites, acessar apenas os casos vinculados e atuar com o papel correto. Confirmamos seu e-mail antes do primeiro ato no procedimento.',
    submit: 'Criar conta'
  },
  login: {
    title: 'Entre na plataforma',
    description: 'Uma conta permite receber convites, acessar apenas os casos vinculados e atuar com o papel correto.',
    submit: 'Entrar'
  },
  forgot: {
    title: 'Recuperar acesso',
    description: 'Informe o e-mail da conta. Se existir cadastro, enviamos um link de uso único para escolher uma nova senha. Redefinir a senha encerra todas as sessões abertas.',
    submit: 'Enviar link'
  }
}

// Variações do texto por origem: quem vem de "abrir um caso" ou de um convite
// precisa saber o que vem depois do cadastro.
const AUTH_CONTEXT_COPY = {
  start: {
    register: {
      title: 'Crie sua conta para abrir o caso',
      description: 'Para abrir o caso você precisa de uma conta. Depois do cadastro enviamos um link para confirmar seu e-mail; sem a confirmação não é possível abrir o caso nem anexar documentos.'
    },
    login: {
      title: 'Entre para abrir o caso',
      description: 'Entre com a conta que você já tem. Se o e-mail ainda não foi confirmado, confirme-o antes de abrir o caso.'
    }
  },
  invite: {
    register: {
      title: 'Crie a conta com o e-mail do convite',
      description: 'Use o mesmo e-mail que recebeu o convite: ele vale só para esse endereço. Depois do cadastro, abra o link do convite para vincular o caso à conta.'
    },
    login: {
      title: 'Entre com o e-mail do convite',
      description: 'Use a conta cadastrada com o mesmo e-mail que recebeu o convite: ele vale só para esse endereço.'
    }
  }
}

function AuthPanel({ mode, context = 'default', setMode, busy, error, onSubmit, onClose, terms, privacy, onOpenLegal }) {
  const copy = { ...(AUTH_COPY[mode] || AUTH_COPY.login), ...(AUTH_CONTEXT_COPY[context]?.[mode] || {}) }
  return (
    <section className="auth-panel">
      <div>
        <span className="section-label">Acesso protegido</span>
        <h2 id="auth-dialog-title">{copy.title}</h2>
        <p>{copy.description}</p>
        {mode === 'register' && (
          <p className="auth-callout" role="note">
            <Mail size={16} aria-hidden="true" /> Você vai precisar confirmar o e-mail: enviamos um link logo após o cadastro.
          </p>
        )}
        {mode === 'register' && (
          <p className="auth-legal">
            Ao criar a conta você declara ter lido os{' '}
            <button type="button" className="auth-switch" onClick={() => onOpenLegal?.('terms')}>
              termos do procedimento
            </button>
            {terms?.version ? ` (versão ${terms.version})` : ''} e a{' '}
            <button type="button" className="auth-switch" onClick={() => onOpenLegal?.('privacy')}>
              política de privacidade
            </button>
            {privacy?.version ? ` (versão ${privacy.version})` : ''}.
          </p>
        )}
      </div>
      <form onSubmit={onSubmit} className="auth-form">
        {mode === 'register' && (
          <label className="mini-field">
            <span>Seu nome</span>
            <input name="display_name" minLength="2" required placeholder="Nome completo" />
          </label>
        )}
        <label className="mini-field">
          <span>E-mail</span>
          <input name="email" type="email" required placeholder="voce@empresa.com" />
        </label>
        {mode !== 'forgot' && (
          <label className="mini-field">
            <span>Senha</span>
            <input name="password" type="password" minLength={mode === 'register' ? 10 : 1} required placeholder="Mínimo de 10 caracteres" />
          </label>
        )}
        <div className="auth-error"><LiveMessage type="error" text={error} /></div>
        <div className="auth-actions">
          <button type="button" className="button ghost" onClick={onClose}>Agora não</button>
          <button className="button primary" disabled={busy}>{copy.submit}</button>
        </div>
      </form>
      <div className="auth-links">
        <button type="button" className="auth-switch" onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>
          {mode === 'register' ? 'Já tenho uma conta' : 'Quero criar uma conta'}
        </button>
        <button type="button" className="auth-switch" onClick={() => setMode(mode === 'forgot' ? 'login' : 'forgot')}>
          {mode === 'forgot' ? 'Voltar para o acesso' : 'Esqueci minha senha'}
        </button>
      </div>
    </section>
  )
}

function AccountPanel({ user, exporting, erasing, onClose, onExport, onErase, onOpenLegal }) {
  return (
    <div className="account-panel">
      <strong>{user.display_name}</strong>
      <span>{user.email}</span>
      <button type="button" className="button ghost compact" onClick={onExport} disabled={exporting}>
        Baixar meus dados
      </button>
      <button type="button" className="button ghost compact" onClick={onErase} disabled={erasing}>
        Anonimizar conta
      </button>
      <button type="button" className="button ghost compact" onClick={() => onOpenLegal('privacy')}>
        Política de privacidade
      </button>
      <button type="button" className="button ghost compact" onClick={onClose}>
        Fechar
      </button>
    </div>
  )
}

function LegalReader({ kind, terms, privacy, onClose }) {
  const doc = kind === 'privacy' ? privacy : terms
  const title = kind === 'privacy' ? 'Política de privacidade' : 'Termos do procedimento'
  return (
    <Modal onClose={onClose} labelledBy="legal-title">
      <section className="dialog-card legal-card">
        <button type="button" className="dialog-close" onClick={onClose} aria-label="Fechar">×</button>
        <header className="legal-head">
          <span className="section-label">{title}</span>
          <h2 id="legal-title">{doc?.version ? `Versão ${doc.version}` : title}</h2>
          {doc?.sha256 && <small>SHA-256 {doc.sha256.slice(0, 16)}…</small>}
        </header>
        <div className="legal-scroll" tabIndex={0}>
          {doc?.text
            ? <Markdown source={doc.text} />
            : <p>Não foi possível carregar este texto agora.</p>}
        </div>
      </section>
    </Modal>
  )
}

function PasswordResetPanel({ busy, onSubmit, onCancel }) {
  return (
    <section className="auth-panel">
      <div>
        <span className="section-label">Redefinição de senha</span>
        <h2>Escolha uma nova senha</h2>
        <p>Ao concluir, todas as sessões abertas nesta conta são encerradas e você entra de novo com a senha nova.</p>
      </div>
      <form onSubmit={onSubmit} className="auth-form">
        <label className="mini-field">
          <span>Nova senha</span>
          <input name="password" type="password" minLength={10} required placeholder="Mínimo de 10 caracteres" />
        </label>
        <div className="auth-actions">
          <button type="button" className="button ghost" onClick={onCancel}>Cancelar</button>
          <button className="button primary" disabled={busy}>Redefinir senha</button>
        </div>
      </form>
    </section>
  )
}
