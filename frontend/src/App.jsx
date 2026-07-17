import { useEffect, useMemo, useState } from 'react'
import {
  FolderOpen,
  Info,
  LogIn,
  LogOut,
  Mail,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRound
} from 'lucide-react'

import { API_BASE, statusLabels, steps } from './constants'
import { AudienceValue, HowItWorks } from './components/Landing'
import { AuthPanel } from './components/AuthPanel'
import { CaseWorkspace } from './components/CaseWorkspace'
import { CreateCase } from './components/CreateCase'
import { LoadingState, Message } from './components/common'

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
  const [busy, setBusy] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showTechnical, setShowTechnical] = useState(false)
  const [claimantResponse, setClaimantResponse] = useState('')
  const [respondentResponse, setRespondentResponse] = useState('')
  const [conciliationUpdate, setConciliationUpdate] = useState('')
  const [sessionToken, setSessionToken] = useState(() => localStorage.getItem('arbitragem_session') || '')
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('arbitragem_user') || 'null') } catch { return null }
  })
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState('register')
  const [inviteToken] = useState(() => new URLSearchParams(window.location.search).get('invite') || '')
  const [caseCredentials, setCaseCredentials] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('arbitragem_case_credentials') || '{}')
    } catch {
      return {}
    }
  })

  const currentStage = useMemo(
    () => Math.max(0, steps.findIndex((step) => step.key === caseData?.status)),
    [caseData]
  )

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(sessionToken ? { 'X-Session-Token': sessionToken } : {}),
        ...(options.headers || {})
      }
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `Erro HTTP ${response.status}`)
    return data
  }

  function actorHeaders(caseId, party) {
    const token = caseCredentials[caseId]?.[party]
    return token || sessionToken ? { 'X-Actor-Token': token || sessionToken } : {}
  }

  async function authenticate(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
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
      setSessionToken(data.session_token)
      setUser(data.user)
      localStorage.setItem('arbitragem_session', data.session_token)
      localStorage.setItem('arbitragem_user', JSON.stringify(data.user))
      setShowAuth(false)
      setStatus('Acesso confirmado. Seus casos e convites estão protegidos pela sua conta.')
      setTimeout(() => window.location.reload(), 100)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    try { await request('/auth/logout', { method: 'POST' }) } catch { /* sessão local também será removida */ }
    localStorage.removeItem('arbitragem_session')
    localStorage.removeItem('arbitragem_user')
    setSessionToken('')
    setUser(null)
    window.location.reload()
  }

  async function acceptPendingInvite() {
    await run('Vinculando o convite à sua conta...', () => request('/invitations/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: inviteToken })
    }))
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
    async function bootstrap() {
      try {
        const [root, items] = await Promise.all([request('/'), request('/cases')])
        setSystem(root)
        setCases(items)
        if (items[0]) {
          await loadCase(items[0].id)
        } else {
          setShowCreate(true)
        }
      } catch (err) {
        setError(err.message)
      }
    }
    bootstrap()
  }, [])

  async function run(label, action) {
    setBusy(true)
    setError('')
    setStatus(label)
    try {
      const result = await action()
      if (caseData?.id) await loadCases(caseData.id)
      setStatus('Pronto. Você pode seguir para a próxima etapa.')
      return result
    } catch (err) {
      setError(err.message)
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  async function createCase(event) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    setBusy(true)
    setError('')

    try {
      const data = await request('/cases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.get('title'),
          claimant: form.get('claimant'),
          respondent: form.get('respondent')
        })
      })
      const credentials = data.access_credentials
      delete data.access_credentials
      const updatedCredentials = { ...caseCredentials, [data.id]: credentials }
      setCaseCredentials(updatedCredentials)
      localStorage.setItem(
        'arbitragem_case_credentials',
        JSON.stringify(updatedCredentials)
      )
      formElement.reset()
      await loadCases(data.id)
      setStatus('Caso criado. Agora adicione os documentos da disputa.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
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

  function startNewCase() {
    setShowCreate(true)
    setError('')
    setStatus('')
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark">
              <img src={`${import.meta.env.BASE_URL}valinor-logo.svg`} alt="Valinor" width="40" height="40" />
            </span>
            <div>
              <strong>Valinor</strong>
              <small>Auditoria decisória por IA</small>
            </div>
          </div>
          <div className="topbar-actions">
            <span className={`system-status ${system?.openai_enabled ? 'online' : 'demo'}`}>
              <span />
              {system?.openai_enabled ? 'Chave de IA configurada' : 'Modo demonstração'}
            </span>
            {user ? (
              <span className="account-chip">
                <UserRound size={15} /> {user.display_name}
                <button onClick={logout} title="Sair"><LogOut size={14} /></button>
              </span>
            ) : (
              <button className="button ghost compact" onClick={() => setShowAuth(true)}>
                <LogIn size={16} /> Entrar
              </button>
            )}
            <button className="button primary compact" onClick={startNewCase}>
              <Plus size={17} /> Novo caso
            </button>
          </div>
        </div>
      </header>

      <main className="page">
        <section className="intro">
          <div>
            <span className="eyebrow">Resolução de disputas conduzida por IA</span>
            <h1>Resolva a disputa em dias — não em anos de processo.</h1>
            <p>
              O Valinor é uma alternativa ao litígio para conflitos documentais entre empresa e cliente.
              As duas partes apresentam suas provas, a IA busca um acordo e, se não houver,
              profere uma decisão fundamentada — auditada por uma segunda IA e verificável
              pelas duas partes, do primeiro documento ao resultado.
            </p>
          </div>
          <div className="trust-note">
            <ShieldCheck size={22} />
            <div>
              <strong>Fração do custo, com garantias de processo</strong>
              <span>Nenhuma prova entra na decisão sem a outra parte ver e responder. Todo o histórico é lacrado e auditável.</span>
            </div>
          </div>
        </section>

        <HowItWorks />

        <AudienceValue />

        {showAuth && (
          <AuthPanel
            mode={authMode}
            setMode={setAuthMode}
            busy={busy}
            onSubmit={authenticate}
            onClose={() => setShowAuth(false)}
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
              <button className="button primary" onClick={acceptPendingInvite} disabled={busy}>Aceitar convite</button>
            ) : (
              <button className="button primary" onClick={() => setShowAuth(true)}>Entrar para aceitar</button>
            )}
          </div>
        )}

        {!system?.openai_enabled && (
          <div className="demo-notice">
            <Info size={19} />
            <div>
              <strong>Você está no modo demonstração</strong>
              <span>
                Sem uma chave de IA, o agente julgador não profere decisão de mérito
                e o caso permanece inconclusivo.
              </span>
            </div>
          </div>
        )}

        {error && !caseData && (
          <Message type="error" text={error} />
        )}

        <div className="workspace">
          <aside className="case-sidebar">
            <div className="sidebar-heading">
              <div>
                <span className="section-label">Seus casos</span>
                <strong>{cases.length} {cases.length === 1 ? 'disputa' : 'disputas'}</strong>
              </div>
              <button className="icon-button" onClick={() => loadCases()} title="Atualizar casos">
                <RefreshCw size={16} />
              </button>
            </div>

            <div className="case-list">
              {cases.map((item) => (
                <button
                  key={item.id}
                  className={`case-item ${caseData?.id === item.id && !showCreate ? 'active' : ''}`}
                  onClick={() => loadCase(item.id)}
                >
                  <span className="case-icon"><FolderOpen size={17} /></span>
                  <span className="case-item-content">
                    <strong>{item.title}</strong>
                    <small>{item.claimant} × {item.respondent}</small>
                    <em>
                      {item.ai_result_status === 'unavailable'
                        ? 'Análise automática indisponível'
                        : statusLabels[item.status]}
                      {' · '}{item.documents_count} doc.
                    </em>
                  </span>
                </button>
              ))}
              {!cases.length && (
                <div className="empty-cases">
                  <FolderOpen size={24} />
                  <span>Seus casos aparecerão aqui.</span>
                </div>
              )}
            </div>

            <div className="sidebar-help">
              <Sparkles size={17} />
              <p>
                <strong>Como funciona?</strong>
                Você avança uma etapa por vez. O sistema sempre destaca a próxima ação.
              </p>
            </div>
          </aside>

          <div className="main-content">
            {showCreate ? (
              <CreateCase busy={busy} onSubmit={createCase} onCancel={
                cases.length ? () => setShowCreate(false) : null
              } />
            ) : caseData ? (
              <CaseWorkspace
                caseData={caseData}
                currentStage={currentStage}
                busy={busy}
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
                showTechnical={showTechnical}
                setShowTechnical={setShowTechnical}
                user={user}
                sessionToken={sessionToken}
              />
            ) : (
              <LoadingState />
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
