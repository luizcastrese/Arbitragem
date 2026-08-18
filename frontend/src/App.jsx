import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  BriefcaseBusiness,
  Building2,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  CircleDollarSign,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  FolderOpen,
  Gavel,
  Handshake,
  Info,
  LockKeyhole,
  MessagesSquare,
  LogIn,
  LogOut,
  Mail,
  Plus,
  RefreshCw,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  UserRound
} from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE
  || (window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin)

const steps = [
  {
    key: 'draft',
    title: 'Documentos',
    short: 'Reúna o material',
    description: 'Adicione contratos, mensagens, comprovantes e alegações.'
  },
  {
    key: 'locked',
    title: 'Regras fixadas',
    short: 'Proteja o processo',
    description: 'O sistema registra os documentos e impede alterações posteriores.'
  },
  {
    key: 'conciliation',
    title: 'Composição',
    short: 'Negocie em rodadas',
    description: 'A IA conduz novas tentativas enquanto houver espaço útil para acordo.'
  },
  {
    key: 'organized',
    title: 'Fatos organizados',
    short: 'Separe fatos e alegações',
    description: 'O conteúdo é estruturado para facilitar a análise.'
  },
  {
    key: 'decided',
    title: 'Decisão da IA',
    short: 'Julgue o conflito',
    description: 'A IA aplica as regras fixadas e profere uma decisão fundamentada.'
  },
  {
    key: 'reviewed',
    title: 'Auditoria',
    short: 'Valide a decisão',
    description: 'Uma segunda IA procura falhas, contradições e desvios das regras.'
  }
]

function userHasRole(caseData, user, role) {
  if (!user) return false
  return (caseData.participants || []).some(
    (participant) => participant.email === user.email && participant.role === role
  )
}

const statusLabels = {
  draft: 'Recebendo documentos',
  locked: 'Documentos protegidos',
  conciliation: 'Composição em curso',
  organized: 'Fatos organizados',
  decided: 'Decisão proferida',
  reviewed: 'Decisão auditada',
  ratification: 'Aguardando as partes',
  ratified: 'Ratificada pelas partes',
  attested: 'Decisão assinada',
  contested: 'Decisão contestada',
  unresolved: 'Encerrado sem decisão executável'
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
  const [busy, setBusy] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showTechnical, setShowTechnical] = useState(false)
  const [claimantResponse, setClaimantResponse] = useState('')
  const [respondentResponse, setRespondentResponse] = useState('')
  const [user, setUser] = useState(null)
  const [showAuth, setShowAuth] = useState(false)
  const [authMode, setAuthMode] = useState('register')
  const [inviteToken] = useState(() => new URLSearchParams(window.location.search).get('invite') || '')

  const currentStage = useMemo(
    () => Math.max(0, steps.findIndex((step) => step.key === caseData?.status)),
    [caseData]
  )

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      credentials: 'include',
      headers: options.headers || {}
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || `Erro HTTP ${response.status}`)
    return data
  }

  function actorHeaders() {
    // The HttpOnly cookie authenticates the account; the backend derives roles.
    return {}
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
      setUser(data.user)
      setShowAuth(false)
      setStatus('Acesso confirmado. Seus casos e convites estão protegidos pela sua conta.')
      await loadCases()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    try { await request('/auth/logout', { method: 'POST' }) } catch { /* clear local UI regardless */ }
    setUser(null)
    setCases([])
    setCaseData(null)
    setShowAuth(true)
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
  }

  async function loadCases(selectId) {
    const items = await request('/cases')
    setCases(items)
    const target = selectId || caseData?.id || items[0]?.id
    if (target) await loadCase(target)
  }

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
          setUser(await request('/auth/me'))
          const items = await request('/cases')
          setCases(items)
          if (items[0]) await loadCase(items[0].id)
          else setShowCreate(true)
        } catch (err) {
          if (/401|sessão|entre/i.test(err.message)) setShowAuth(true)
          else throw err
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
          respondent: form.get('respondent'),
          creator_role: form.get('creator_role')
        })
      })
      delete data.access_credentials
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
            <span className="brand-mark"><Scale size={20} /></span>
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
                setClaimantResponse={setClaimantResponse}
                setRespondentResponse={setRespondentResponse}
                showTechnical={showTechnical}
                setShowTechnical={setShowTechnical}
                user={user}
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

function HowItWorks() {
  const steps = [
    {
      title: 'As duas partes aderem',
      text: 'Empresa e cliente aceitam as mesmas regras, com convite e consentimento registrados.'
    },
    {
      title: 'Provas com contraditório',
      text: 'Cada documento enviado é visto e respondido pela outra parte antes de contar para qualquer coisa.'
    },
    {
      title: 'A IA busca acordo primeiro',
      text: 'Propostas de conciliação fundamentadas, que cada parte pode aceitar, recusar ou ajustar.'
    },
    {
      title: 'Sem acordo, decisão fundamentada',
      text: 'A IA decide citando as provas; uma segunda IA audita a decisão. Tudo verificável por hash.'
    }
  ]
  return (
    <section className="how-it-works">
      <div className="value-heading">
        <span className="section-label">Como funciona</span>
        <h2>Quatro etapas, as mesmas regras para os dois lados.</h2>
      </div>
      <ol className="how-steps">
        {steps.map((step, index) => (
          <li key={step.title}>
            <span className="how-number">{index + 1}</span>
            <strong>{step.title}</strong>
            <p>{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

function AudienceValue() {
  return (
    <section className="audience-value">
      <div className="value-heading">
        <span className="section-label">Por que usar</span>
        <h2>O custo de resolver deixa de ser maior que o valor da disputa.</h2>
        <p>
          A IA faz o trabalho que consome tempo e honorários: organiza documentos,
          identifica convergências, conduz rodadas de acordo e fundamenta a análise.
          As garantias ficam: autoria, ciência, resposta, admissão e auditoria
          registradas do início ao fim.
        </p>
      </div>

      <div className="economy-strip">
        <div>
          <CircleDollarSign size={22} />
          <span>
            <strong>Fração do custo</strong>
            Sem custas, audiências ou anos de honorários. A IA absorve o trabalho repetitivo.
          </span>
        </div>
        <div>
          <Clock3 size={22} />
          <span>
            <strong>Dias, não anos</strong>
            O procedimento inteiro — adesão, provas, acordo, decisão — corre na plataforma, sem pauta.
          </span>
        </div>
        <div>
          <ShieldCheck size={22} />
          <span>
            <strong>Verificável, não é caixa-preta</strong>
            Decisão com provas citadas, auditoria independente e histórico lacrado por hash.
          </span>
        </div>
      </div>

      <div className="audience-cards">
        <article className="audience-card company">
          <span className="audience-icon"><Building2 size={22} /></span>
          <span className="audience-kicker">Para a empresa reclamada</span>
          <h3>Reduza o custo por reclamação sem transformar eficiência em parcialidade.</h3>
          <ul>
            <li>Diminui horas operacionais e jurídicas consumidas em cada disputa.</li>
            <li>Centraliza documentos, defesa e histórico em um único procedimento.</li>
            <li>Cria novas propostas quando ainda houver espaço real para acordo.</li>
            <li>Produz uma trilha auditável para jurídico, atendimento e compliance.</li>
          </ul>
        </article>

        <article className="audience-card claimant">
          <span className="audience-icon"><UserRound size={22} /></span>
          <span className="audience-kicker">Para o cliente reclamante</span>
          <h3>Busque uma solução de menor custo sem perder voz, acesso ou proteção.</h3>
          <ul>
            <li>Evita que o custo de discutir o direito torne a reclamação inviável.</li>
            <li>Apresenta sua versão, documentos, pedidos e respostas às propostas.</li>
            <li>Entende por que cada acordo foi sugerido e pode aceitar ou recusar.</li>
            <li>Vê quais provas sustentam a decisão, em vez de receber apenas um resultado.</li>
          </ul>
        </article>
      </div>

      <div className="role-strip">
        <div>
          <BriefcaseBusiness size={20} />
          <span><strong>Sem terceiro humano</strong> o rito conduz acesso, prazos e etapas; as partes cuidam do que é delas.</span>
        </div>
        <div>
          <MessagesSquare size={20} />
          <span><strong>Representantes e advogados</strong> podem apoiar qualquer parte na apresentação do caso.</span>
        </div>
        <div>
          <ShieldCheck size={20} />
          <span><strong>Adesão transparente</strong> a contraparte deve compreender e aceitar o procedimento.</span>
        </div>
      </div>

      <div className="user-journeys">
        <div className="journey-heading">
          <span className="section-label">Quem faz o quê?</span>
          <h3>O fluxo de cada usuário dentro do caso</h3>
        </div>
        <div className="journey-columns">
          <Journey
            title="Empresa reclamada"
            steps={[
              'Convida o cliente com explicação clara do procedimento.',
              'Apresenta defesa, documentos e limites possíveis para acordo.',
              'Responde a cada rodada com aceite, recusa ou contraproposta.',
              'Recebe a decisão e a auditoria para cumprimento e controle interno.'
            ]}
          />
          <Journey
            title="Cliente reclamante"
            steps={[
              'Conhece as regras e decide se aceita participar.',
              'Apresenta fatos, documentos, pedido e resultado esperado.',
              'Avalia cada proposta e informa o que aceita ou deseja alterar.',
              'Recebe decisão explicada, provas citadas e resultado da auditoria.'
            ]}
          />
          <Journey
            title="O rito (sem pessoa no meio)"
            steps={[
              'Abre o prazo de ciência e resposta assim que um material entra.',
              'Admite o material quando o contraditório se cumpre.',
              'Trava o conjunto quando os dois lados encerram a produção.',
              'Conduz composição, julgamento e auditoria sem escolher o vencedor.'
            ]}
          />
        </div>
      </div>
    </section>
  )
}

function Journey({ title, steps }) {
  return (
    <article className="journey">
      <h4>{title}</h4>
      <ol>
        {steps.map((step, index) => (
          <li key={step}>
            <span>{index + 1}</span>
            <p>{step}</p>
          </li>
        ))}
      </ol>
    </article>
  )
}

function AuthPanel({ mode, setMode, busy, onSubmit, onClose }) {
  return (
    <section className="auth-panel">
      <div>
        <span className="section-label">Acesso protegido</span>
        <h2>{mode === 'register' ? 'Crie sua conta' : 'Entre na plataforma'}</h2>
        <p>Uma conta permite receber convites, acessar apenas os casos vinculados e atuar com o papel correto.</p>
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
        <label className="mini-field">
          <span>Senha</span>
          <input name="password" type="password" minLength={mode === 'register' ? 10 : 1} required placeholder="Mínimo de 10 caracteres" />
        </label>
        <div className="auth-actions">
          <button type="button" className="button ghost" onClick={onClose}>Agora não</button>
          <button className="button primary" disabled={busy}>{mode === 'register' ? 'Criar conta' : 'Entrar'}</button>
        </div>
      </form>
      <button className="auth-switch" onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>
        {mode === 'register' ? 'Já tenho uma conta' : 'Quero criar uma conta'}
      </button>
    </section>
  )
}

function CreateCase({ busy, onSubmit, onCancel }) {
  return (
    <section className="surface create-surface">
      <div className="surface-header">
        <span className="number-badge">1</span>
        <div>
          <span className="section-label">Comece por aqui</span>
          <h2>Qual reclamação será encaminhada?</h2>
          <p>Identifique o cliente reclamante e a empresa que responderá ao caso.</p>
        </div>
      </div>

      <form onSubmit={onSubmit} className="guided-form">
        <label className="field full">
          <span>Nome do caso</span>
          <small>Use um título curto que ajude você a encontrá-lo depois.</small>
          <input
            name="title"
            placeholder="Ex.: Atraso na entrega do site"
            required
            minLength="3"
          />
        </label>
        <label className="field">
          <span>Cliente ou reclamante</span>
          <small>Quem apresentou a reclamação ou iniciou o processo.</small>
          <input name="claimant" placeholder="Ex.: Maria Oliveira" required minLength="2" />
        </label>
        <label className="field">
          <span>Empresa reclamada</span>
          <small>Empresa responsável por responder à reclamação.</small>
          <input name="respondent" placeholder="Ex.: Empresa Alfa" required minLength="2" />
        </label>
        <label className="field full">
          <span>Você está de que lado?</span>
          <small>
            Quem abre o caso entra como parte. Ninguém administra o próprio
            litígio: quem conduz o procedimento é o rito, não uma pessoa.
          </small>
          <select name="creator_role" defaultValue="claimant" required>
            <option value="claimant">Sou o cliente reclamante</option>
            <option value="respondent">Sou a empresa reclamada</option>
          </select>
        </label>

        <div className="form-actions">
          {onCancel && (
            <button type="button" className="button ghost" onClick={onCancel}>Cancelar</button>
          )}
          <button className="button primary" disabled={busy}>
            Criar caso e adicionar documentos <ArrowRight size={17} />
          </button>
        </div>
      </form>
    </section>
  )
}

function CaseWorkspace({
  caseData,
  currentStage,
  busy,
  status,
  error,
  documentName,
  documentText,
  documentParty,
  materialType,
  documentPurpose,
  setDocumentName,
  setDocumentText,
  setDocumentParty,
  setMaterialType,
  setDocumentPurpose,
  evidenceResponses,
  setEvidenceResponses,
  addTextDocument,
  uploadPdf,
  run,
  request,
  actorHeaders,
  claimantResponse,
  respondentResponse,
  setClaimantResponse,
  setRespondentResponse,
  showTechnical,
  setShowTechnical,
  user
}) {
  const unavailable = hasUnavailableAI(caseData)
  const displayedStage = unavailable ? 2 : currentStage
  // Só existem dois papéis humanos. Tudo o que antes exigia um gestor é
  // executado pelo próprio rito, no servidor.
  const roles = {
    claimant: userHasRole(caseData, user, 'claimant'),
    respondent: userHasRole(caseData, user, 'respondent')
  }
  const myParty = roles.claimant ? 'claimant' : roles.respondent ? 'respondent' : null

  return (
    <>
      <section className="case-heading">
        <div>
          <div className="case-meta">
            <span>Caso {caseData.id.slice(0, 8).toUpperCase()}</span>
            <span className={`case-status ${unavailable ? 'unavailable' : caseData.status}`}>
              {unavailable ? 'Análise automática indisponível' : statusLabels[caseData.status]}
            </span>
          </div>
          <h2>{caseData.title}</h2>
          <p>{caseData.claimant} <span>contra</span> {caseData.respondent}</p>
        </div>
        <div className="progress-summary">
          <strong>{Math.min(displayedStage + 1, steps.length)} de {steps.length}</strong>
          <span>{unavailable ? 'etapas antes do bloqueio técnico' : 'etapas alcançadas'}</span>
        </div>
      </section>

      {caseData.documents.length > 0 && <CaseBrief caseData={caseData} />}

      <ProcessSteps currentStage={displayedStage} blockedByAI={unavailable} />

      {!['reviewed', 'unresolved'].includes(caseData.status) && (
        <NextAction
          caseData={caseData}
          busy={busy}
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
          addTextDocument={addTextDocument}
          uploadPdf={uploadPdf}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          claimantResponse={claimantResponse}
          respondentResponse={respondentResponse}
          setClaimantResponse={setClaimantResponse}
          setRespondentResponse={setRespondentResponse}
          roles={roles}
          myParty={myParty}
        />
      )}

      {status && <Message type="success" text={status} />}
      {error && <Message type="error" text={error} />}

      {caseData.documents.length > 0 && (
        <DocumentsCard
          caseData={caseData}
          documents={caseData.documents}
          locked={caseData.manifest_locked}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          evidenceResponses={evidenceResponses}
          setEvidenceResponses={setEvidenceResponses}
          roles={roles}
        />
      )}

      <OperationsCard
        caseData={caseData}
        busy={busy}
        run={run}
        request={request}
        actorHeaders={actorHeaders}
        myParty={myParty}
      />

      {['reviewed', 'unresolved', 'ratified', 'attested'].includes(caseData.status) && (
        <Conclusion caseData={caseData} />
      )}

      {(caseData.conciliation || caseData.organized || caseData.decision || caseData.review) && (
        <AnalysisDetails caseData={caseData} />
      )}

      <TechnicalDetails
        caseData={caseData}
        open={showTechnical}
        setOpen={setShowTechnical}
      />
    </>
  )
}

function OperationsCard({ caseData, busy, run, request, actorHeaders, myParty }) {
  const [issuedInvite, setIssuedInvite] = useState(null)
  const [copied, setCopied] = useState(false)
  const deadlines = caseData.deadlines || []
  const participants = caseData.participants || []
  const counterparty = myParty === 'claimant' ? 'respondent' : 'claimant'
  const counterpartyPresent = participants.some(
    (participant) => participant.role === counterparty
  )
  const pendingInvitation = (caseData.invitations || []).find(
    (item) => item.status === 'pending' && item.role === counterparty
  )
  const canInvite = Boolean(myParty) && !counterpartyPresent && !pendingInvitation

  function keepInvite(data) {
    setIssuedInvite({
      email: data.email,
      url: data.acceptance_url || `${window.location.origin}${data.acceptance_path}`,
      delivery: data.email_delivery || {}
    })
    setCopied(false)
    return data
  }

  async function invite(event) {
    event.preventDefault()
    const formElement = event.currentTarget
    const form = new FormData(formElement)
    await run('Criando convite protegido...', async () => {
      const data = await request(`/cases/${caseData.id}/invitations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, myParty) },
        body: JSON.stringify({ email: form.get('email'), role: counterparty })
      })
      formElement.reset?.()
      return keepInvite(data)
    })
  }

  async function resendInvite() {
    await run('Gerando um link novo para a contraparte...', async () => keepInvite(
      await request(
        `/cases/${caseData.id}/invitations/${pendingInvitation.id}/resend`,
        { method: 'POST', headers: actorHeaders(caseData.id, myParty) }
      )
    ))
  }

  async function copyInviteLink() {
    try {
      await navigator.clipboard.writeText(issuedInvite.url)
      setCopied(true)
    } catch {
      // Sem permissão de área de transferência o link continua visível e
      // selecionável no campo abaixo.
      setCopied(false)
    }
  }

  async function downloadReport() {
    await run('Gerando o relatório Word...', async () => {
      const response = await fetch(`${API_BASE}/cases/${caseData.id}/report.docx`, {
        credentials: 'include'
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || 'Não foi possível gerar o relatório')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `relatorio-valinor-${caseData.id.slice(0, 8)}.docx`
      anchor.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <section className="operations-card">
      <div className="card-title-row">
        <div>
          <span className="section-label">Participantes, agenda e entrega</span>
          <h3>O caso por dentro</h3>
        </div>
        <button className="button secondary" onClick={downloadReport} disabled={busy}>
          <Download size={16} /> Baixar relatório Word
        </button>
      </div>

      <div className="operations-grid">
        <div className="operation-block">
          <div className="operation-title"><Mail size={18} /><strong>Partes do caso</strong></div>
          <p>
            O procedimento tem exatamente dois participantes. Não há gestor,
            mediador ou administrador: quem conduz o rito é o próprio sistema.
          </p>
          {participants.map((participant) => (
            <span className="participant-row" key={`${participant.email}-${participant.role}`}>
              <strong>{participant.display_name}</strong> {partyRoleLabel(participant.role)} · {participant.email}
            </span>
          ))}
          {canInvite && <form className="compact-form" onSubmit={invite}>
            <input name="email" type="email" required placeholder={`E-mail de ${partyRoleLabel(counterparty).toLowerCase()}`} />
            <button className="button primary" disabled={busy}>
              Convidar a contraparte
            </button>
          </form>}
          {issuedInvite && (
            <div className="invite-issued">
              <div className="invite-delivery">
                {issuedInvite.delivery.delivered ? (
                  <>
                    <Check size={15} />
                    <span>
                      Convite enviado por e-mail para <strong>{issuedInvite.email}</strong>.
                      Se não chegar, o link abaixo serve para qualquer canal.
                    </span>
                  </>
                ) : (
                  <>
                    <AlertTriangle size={15} />
                    <span>
                      O envio automático de e-mail não está disponível
                      {issuedInvite.delivery.error ? ' no momento' : ''}.
                      Entregue o link abaixo a <strong>{issuedInvite.email}</strong> por
                      um canal que você já use.
                    </span>
                  </>
                )}
              </div>
              <label className="invite-link">
                <span>Link de acesso da contraparte</span>
                <input
                  value={issuedInvite.url}
                  readOnly
                  onFocus={(event) => event.target.select()}
                />
              </label>
              <div className="invite-actions">
                <button className="button secondary compact" onClick={copyInviteLink}>
                  {copied ? <><Check size={15} /> Link copiado</> : 'Copiar link'}
                </button>
                <small>
                  Só quem tiver uma conta com esse e-mail consegue usá-lo, e ele
                  expira em 7 dias.
                </small>
              </div>
            </div>
          )}
          {pendingInvitation && !issuedInvite && (
            <div className="invite-pending">
              <Clock3 size={16} />
              <div>
                <strong>Convite pendente para {pendingInvitation.email}</strong>
                <span>
                  Enquanto a contraparte não entrar, o caso não avança. Se o link
                  se perdeu, gere outro — o anterior deixa de valer.
                </span>
              </div>
              <button
                className="button secondary compact"
                onClick={resendInvite}
                disabled={busy || !myParty}
              >
                Gerar link novo
              </button>
            </div>
          )}
          {!myParty && <small>Só as partes do caso podem convidar.</small>}
          {myParty && counterpartyPresent && (
            <small>Os dois lados já estão no caso.</small>
          )}
        </div>

        <div className="operation-block">
          <div className="operation-title"><Clock3 size={18} /><strong>Agenda processual</strong></div>
          <p>
            O rito abre o prazo de ciência e resposta quando um material é
            disponibilizado, e dá baixa nele assim que a contraparte se
            manifesta. Nenhuma pessoa define prazos aqui.
          </p>
          <div className="deadline-list">
            {deadlines.map((deadline) => (
              <span className={`deadline-row ${deadline.status}`} key={deadline.id}>
                <strong>{deadline.label}</strong>
                <small>{partyRoleLabel(deadline.assigned_to)} · {new Date(deadline.due_at).toLocaleString('pt-BR')} · {deadline.status}</small>
              </span>
            ))}
            {!deadlines.length && <span className="empty-inline">Nenhum prazo aberto no momento.</span>}
          </div>
        </div>
      </div>
    </section>
  )
}

function CaseBrief({ caseData }) {
  const claimantPurposes = caseData.documents
    .filter((document) => document.submitted_by === 'claimant')
    .map((document) => document.purpose)
    .filter(Boolean)
  const respondentPurposes = caseData.documents
    .filter((document) => document.submitted_by === 'respondent')
    .map((document) => document.purpose)
    .filter(Boolean)
  const companyResponses = caseData.documents
    .filter((document) => document.submitted_by === 'claimant' && document.response_text)
    .map((document) => document.response_text)
  const customerResponses = caseData.documents
    .filter((document) => document.submitted_by === 'respondent' && document.response_text)
    .map((document) => document.response_text)
  const unavailable = hasUnavailableAI(caseData)

  return (
    <section className="case-brief">
      <div className="case-brief-heading">
        <span className="section-label">Entenda o caso em 30 segundos</span>
        <h3>O conflito antes do procedimento</h3>
      </div>
      <div className="case-brief-grid">
        <BriefPoint
          label="O que aconteceu"
          text={truncateText(
            caseData.organized?.factual_overview
            || `${caseData.title}. Há ${caseData.documents.length} materiais apresentados e compartilhados entre as partes.`,
            280
          )}
        />
        <BriefPoint
          label={`Posição de ${caseData.claimant}`}
          text={[...customerResponses, ...claimantPurposes][0]
            || 'A posição do cliente ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label={`Posição de ${caseData.respondent}`}
          text={[...companyResponses, ...respondentPurposes][0]
            || 'A posição da empresa ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label="Questão central"
          text={
            caseData.organized?.disputed_facts?.[0]
            || 'Comparar o pedido do cliente e a defesa da empresa usando apenas os materiais admitidos.'
          }
        />
      </div>
      {unavailable && (
        <div className="ai-unavailable-note">
          <AlertTriangle size={18} />
          <span>
            <strong>Este caso não contém uma decisão da IA.</strong>
            O procedimento documental foi concluído, mas a análise automática não
            rodou porque o serviço de IA estava sem cota disponível.
          </span>
        </div>
      )}
    </section>
  )
}

function BriefPoint({ label, text }) {
  return (
    <div className="brief-point">
      <span>{label}</span>
      <p>{text}</p>
    </div>
  )
}

function ProcessSteps({ currentStage, blockedByAI = false }) {
  return (
    <section className="process-card">
      <div className="process-heading">
        <div>
          <span className="section-label">Andamento do caso</span>
          <h3>O processo, passo a passo</h3>
        </div>
        <span>
          {blockedByAI
            ? 'Análise interrompida com segurança'
            : `${Math.round(((currentStage + 1) / steps.length) * 100)}% concluído`}
        </span>
      </div>
      <div className="progress-bar">
        <span style={{ width: `${((currentStage + 1) / steps.length) * 100}%` }} />
      </div>
      <div className="steps">
        {steps.map((step, index) => {
          const processComplete = currentStage === steps.length - 1
          const done = index < currentStage || processComplete
          const active = index === currentStage && !processComplete
          return (
            <div className={`step ${done ? 'done' : ''} ${active ? 'active' : ''}`} key={step.key}>
              <span className="step-marker">
                {done ? <Check size={15} /> : active ? index + 1 : <Circle size={11} />}
              </span>
              <div>
                <strong>{step.title}</strong>
                <small>{active ? step.description : step.short}</small>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function NextAction({
  caseData,
  busy,
  documentName,
  documentText,
  documentParty,
  materialType,
  documentPurpose,
  setDocumentName,
  setDocumentText,
  setDocumentParty,
  setMaterialType,
  setDocumentPurpose,
  addTextDocument,
  uploadPdf,
  run,
  request,
  actorHeaders,
  claimantResponse,
  respondentResponse,
  setClaimantResponse,
  setRespondentResponse,
  roles,
  myParty
}) {
  const actionContent = {
    draft: {
      icon: <Upload size={22} />,
      label: 'Etapa atual',
      title: 'Adicione os documentos da disputa',
      description: 'Inclua tudo que ajuda a entender o acordo, o que aconteceu e o que cada parte pede.'
    },
    locked: {
      icon: <Handshake size={22} />,
      label: 'Em curso',
      title: 'O rito está buscando espaço para acordo',
      description: 'A IA identifica interesses convergentes e indica conciliação, mediação ou seguimento para julgamento.'
    },
    conciliation: {
      icon: <Handshake size={22} />,
      label: 'Sua vez',
      title: 'Registre sua posição na composição',
      description: 'A rodada seguinte só é aberta quando os dois lados se manifestam. Qualquer parte pode encerrar a composição.'
    },
    organized: {
      icon: <Gavel size={22} />,
      label: 'Em curso',
      title: 'O caso está sendo julgado',
      description: 'O agente julgador aplica o framework Comercial Equilibrado às evidências admitidas.'
    },
    decided: {
      icon: <ShieldCheck size={22} />,
      label: 'Em curso',
      title: 'A decisão está sendo auditada',
      description: 'Uma segunda IA verifica fundamentos, evidências, contradições e aderência às regras.'
    },
    ratification: {
      icon: <Gavel size={22} />,
      label: 'Sua vez',
      title: 'A auditoria fez ressalva à decisão',
      description: 'A revisão é de vocês: cada parte diz se aceita o resultado assim mesmo. Sem o aceite dos dois lados, o caso encerra sem decisão executável.'
    },
    ratified: {
      icon: <ShieldCheck size={22} />,
      label: 'Ratificada',
      title: 'As duas partes aceitaram o resultado',
      description: 'A execução passa a se apoiar na ratificação das partes, e não na aprovação automática.'
    },
    unresolved: {
      icon: <AlertTriangle size={22} />,
      label: 'Encerrado',
      title: 'O procedimento terminou sem decisão executável',
      description: 'O registro, o relatório e a cadeia de auditoria continuam íntegros e verificáveis.'
    },
    attested: {
      icon: <ShieldCheck size={22} />,
      label: 'Janela de contestação',
      title: 'A decisão foi assinada',
      description: 'Enquanto a janela estiver aberta, qualquer uma das partes pode contestar o resultado.'
    },
    contested: {
      icon: <AlertTriangle size={22} />,
      label: 'Contestado',
      title: 'Uma das partes contestou a decisão',
      description: 'O caso fica registrado como contestado e nenhuma nova attestation é emitida.'
    }
  }[caseData.status] || {
    icon: <Search size={22} />,
    label: 'Em curso',
    title: 'O procedimento está em andamento',
    description: 'O rito segue conduzindo as etapas cujas pré-condições já estão cumpridas.'
  }

  return (
    <section className="next-action">
      <div className="next-action-heading">
        <span className="action-icon">{actionContent.icon}</span>
        <div>
          <span className="section-label">{actionContent.label}</span>
          <h3>{actionContent.title}</h3>
          <p>{actionContent.description}</p>
        </div>
      </div>

      {caseData.status === 'conciliation' ? (
        <ConciliationActions
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          claimantResponse={claimantResponse}
          respondentResponse={respondentResponse}
          setClaimantResponse={setClaimantResponse}
          setRespondentResponse={setRespondentResponse}
          roles={roles}
          myParty={myParty}
        />
      ) : caseData.status === 'ratification' ? (
        <RatificationPanel
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          myParty={myParty}
        />
      ) : caseData.status === 'draft' ? (
        <>
          <ConsentPanel
            caseData={caseData}
            busy={busy}
            run={run}
            request={request}
            actorHeaders={actorHeaders}
            roles={roles}
          />

          <div className="submission-context">
            <label className="mini-field">
              <span>Quem está apresentando?</span>
              <select
                value={documentParty}
                onChange={(event) => setDocumentParty(event.target.value)}
              >
                {roles.claimant && <option value="claimant">Cliente reclamante</option>}
                {roles.respondent && <option value="respondent">Empresa reclamada</option>}
                {!roles.claimant && !roles.respondent && <option value="">Sem papel de parte</option>}
              </select>
            </label>
            <label className="mini-field">
              <span>Tipo de material</span>
              <select
                value={materialType}
                onChange={(event) => setMaterialType(event.target.value)}
              >
                <option value="evidence">Prova ou documento</option>
                <option value="argument">Alegação ou argumento</option>
              </select>
            </label>
            <label className="mini-field full">
              <span>O que este material pretende demonstrar?</span>
              <input
                value={documentPurpose}
                onChange={(event) => setDocumentPurpose(event.target.value)}
                placeholder="Ex.: comprovar pagamento, contestar prazo ou explicar o pedido."
              />
            </label>
          </div>

          <div className="upload-options">
            <label className="upload-option">
              <span className="upload-option-icon"><Upload size={21} /></span>
              <strong>Enviar um PDF</strong>
              <small>Contrato, proposta, nota fiscal ou outro documento.</small>
              <span className="button secondary">Escolher arquivo</span>
              <input type="file" accept="application/pdf" onChange={uploadPdf} disabled={busy || !roles[documentParty]} />
            </label>

            <div className="upload-divider"><span>ou</span></div>

            <div className="text-option">
              <div>
                <strong>Colar um texto</strong>
                <small>Útil para mensagens, e-mails ou um relato dos fatos.</small>
              </div>
              <label className="mini-field">
                <span>Nome do documento</span>
                <input
                  value={documentName}
                  onChange={(event) => setDocumentName(event.target.value)}
                  placeholder="Ex.: conversa por e-mail"
                />
              </label>
              <label className="mini-field">
                <span>Conteúdo</span>
                <textarea
                  value={documentText}
                  onChange={(event) => setDocumentText(event.target.value)}
                  placeholder="Cole aqui o texto que faz parte da disputa..."
                />
              </label>
              <button
                className="button secondary"
                disabled={busy || !roles[documentParty] || !documentText.trim()}
                onClick={addTextDocument}
              >
                <FileText size={17} /> Adicionar texto ao caso
              </button>
            </div>
          </div>

          <SubmissionClosure
            caseData={caseData}
            busy={busy}
            run={run}
            request={request}
            actorHeaders={actorHeaders}
            myParty={myParty}
          />
        </>
      ) : (
        <ProcedureRunning
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          myParty={myParty}
        />
      )}
    </section>
  )
}

function RatificationPanel({ caseData, busy, run, request, actorHeaders, myParty }) {
  const [reason, setReason] = useState('')
  const ratification = caseData.ratification || {}
  const mine = myParty ? ratification[myParty] : null
  const review = caseData.review || {}
  const decision = caseData.decision || {}

  const reservations = [
    !review.approved && 'A auditoria independente não aprovou a decisão.',
    decision.requires_human_review && 'O agente julgador indicou revisão humana.',
    review.requires_human_review && 'A auditoria independente indicou revisão humana.'
  ].filter(Boolean)

  function answer(accepted) {
    return run(
      accepted
        ? 'Registrando o seu aceite da decisão...'
        : 'Registrando a sua recusa...',
      () => request(`/cases/${caseData.id}/ratification`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...actorHeaders(caseData.id, myParty)
        },
        body: JSON.stringify({ accepted, reason })
      })
    )
  }

  return (
    <div className="ratification-panel">
      <div className="blocking-note">
        <AlertTriangle size={17} />
        <span>
          {reservations.join(' ')} Por isso a execução automática está
          bloqueada. Não há terceiro para revisar: quem decide se o resultado
          vale assim mesmo são vocês.
        </span>
      </div>

      <div className="consent-grid">
        {['claimant', 'respondent'].map((party) => (
          <div className={`consent-party ${ratification[party]?.accepted ? 'accepted' : ''}`} key={party}>
            <div>
              <span>{partyRoleLabel(party)}</span>
              <strong>{party === 'claimant' ? caseData.claimant : caseData.respondent}</strong>
            </div>
            {ratification[party]?.answered ? (
              ratification[party]?.accepted
                ? <em><Check size={14} /> Aceitou</em>
                : <em><AlertTriangle size={14} /> Recusou</em>
            ) : (
              <em><Clock3 size={14} /> Aguardando a parte</em>
            )}
          </div>
        ))}
      </div>

      {myParty && !mine?.answered && (
        <>
          <label className="mini-field full">
            <span>Motivo (obrigatório para recusar)</span>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Se for recusar, explique o que na decisão não se sustenta."
            />
          </label>
          <div className="conciliation-buttons">
            <button
              className="button primary"
              disabled={busy}
              onClick={() => answer(true)}
            >
              <Check size={17} /> Aceito o resultado
            </button>
            <button
              className="button ghost"
              disabled={busy || reason.trim().length < 10}
              onClick={() => answer(false)}
            >
              Recuso a decisão
            </button>
          </div>
        </>
      )}

      <small className="consent-note">
        O silêncio não vale como aceite: se o prazo vencer sem manifestação das
        duas partes, o caso encerra sem decisão executável. Recusar não é
        derrota — apenas devolve o conflito a vocês, com o registro íntegro do
        que foi produzido aqui.
      </small>
    </div>
  )
}

function SubmissionClosure({ caseData, busy, run, request, actorHeaders, myParty }) {
  const submission = caseData.submission || {}
  const mine = myParty ? submission[myParty] : null
  const consentPending = !caseData.consent?.complete
  const contradictoryPending = !caseData.contradictory?.complete

  return (
    <>
      <div className="lock-explanation">
        <LockKeyhole size={20} />
        <div>
          <strong>Quando terminar de apresentar seu material</strong>
          <span>
            Declare que encerrou a sua produção. Quando os dois lados encerrarem
            — e todo material tiver passado pelo contraditório — o próprio rito
            trava o conjunto documental. Ninguém decide isso por vocês. Se o
            prazo vencer sem declaração, o rito encerra a produção por decurso
            de prazo.
          </span>
        </div>
        {myParty && (
          <button
            className={`button ${mine?.closed ? 'ghost' : 'primary'}`}
            disabled={busy || (!mine?.closed && !caseData.documents.length)}
            onClick={() => run(
              mine?.closed
                ? 'Reabrindo a sua produção de material...'
                : 'Registrando o encerramento da sua produção...',
              () => request(`/cases/${caseData.id}/submission-complete`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  ...actorHeaders(caseData.id, myParty)
                },
                body: JSON.stringify({ closed: !mine?.closed })
              })
            )}
          >
            {mine?.closed ? 'Reabrir minha produção' : 'Encerrei minha produção'}
            {!mine?.closed && <ArrowRight size={17} />}
          </button>
        )}
      </div>

      <div className="submission-state">
        {['claimant', 'respondent'].map((party) => (
          <span className={`deadline-row ${submission[party]?.closed ? 'completed' : 'open'}`} key={party}>
            <strong>{partyRoleLabel(party)}</strong>
            <small>
              {submission[party]?.closed
                ? 'encerrou a produção de material'
                : 'ainda pode apresentar material'}
            </small>
          </span>
        ))}
      </div>

      {(consentPending || contradictoryPending) && (
        <div className="blocking-note">
          <AlertTriangle size={17} />
          <span>
            {consentPending ? 'A adesão das duas partes ainda está pendente. ' : ''}
            {contradictoryPending
              ? 'Todo material precisa de ciência e de resposta ou renúncia da contraparte antes da trava. A admissão é automática.'
              : ''}
          </span>
        </div>
      )}
    </>
  )
}

function ProcedureRunning({ caseData, busy, run, request, actorHeaders, myParty }) {
  const stageMessage = {
    locked: 'O conjunto documental está travado. O rito abriu a fase de composição.',
    conciliation: 'A composição está em curso.',
    organized: 'Os fatos foram organizados. O julgamento vem em seguida.',
    decided: 'A decisão foi proferida e segue para a auditoria independente.',
    attested: 'A decisão foi assinada e a janela de contestação está aberta.',
    contested: 'O caso foi contestado por uma das partes.'
  }[caseData.status] || 'O rito está conduzindo o procedimento.'

  return (
    <div className="procedure-running">
      <p>{stageMessage}</p>
      <small>
        Nenhuma destas etapas depende de uma pessoa. Cada uma executa quando as
        pré-condições da anterior estão cumpridas.
      </small>
      {myParty && (
        <button
          className="button secondary action-cta"
          disabled={busy}
          onClick={() => run(
            'Verificando o que o rito já pode executar...',
            () => request(`/cases/${caseData.id}/advance`, {
              method: 'POST',
              headers: actorHeaders(caseData.id, myParty)
            })
          )}
        >
          Atualizar o andamento <ArrowRight size={18} />
        </button>
      )}
    </div>
  )
}

function ConsentPanel({ caseData, busy, run, request, actorHeaders, roles }) {
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
            ) : roles[entry.party] ? (
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
            ) : (
              <em><Clock3 size={14} /> Aguardando a parte</em>
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

function ConciliationActions({
  caseData,
  busy,
  run,
  request,
  actorHeaders,
  claimantResponse,
  respondentResponse,
  setClaimantResponse,
  setRespondentResponse,
  myParty
}) {
  const rounds = caseData.conciliation_rounds || []
  const latest = rounds[rounds.length - 1] || caseData.conciliation || {}
  const composition = caseData.composition || {}
  const myPosition = myParty === 'respondent' ? respondentResponse : claimantResponse
  const setMyPosition = myParty === 'respondent' ? setRespondentResponse : setClaimantResponse
  const alreadySubmitted = Boolean(myParty && composition[myParty]?.submitted)

  async function submitPosition() {
    const result = await run(
      'Registrando a sua posição para a próxima rodada...',
      () => request(`/cases/${caseData.id}/composition/position`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...actorHeaders(caseData.id, myParty)
        },
        body: JSON.stringify({ position: myPosition })
      })
    )
    if (result) setMyPosition('')
  }

  return (
    <div className="conciliation-actions">
      <div className="round-guidance">
        <span>Rodada {latest.round_number || rounds.length}</span>
        <strong>
          {latest.continue_recommended
            ? 'A IA recomenda continuar a negociação'
            : 'A IA não recomenda repetir a mesma tentativa'}
        </strong>
        <p>
          {latest.continue_recommended
            ? `${latest.recommended_additional_rounds || 1} rodada(s) adicional(is) parecem úteis. Foco sugerido: ${latest.next_round_focus || 'aproximar as posições ainda negociáveis'}. A próxima rodada é aberta assim que os dois lados se manifestarem.`
            : `${latest.stop_reason || 'As posições parecem esgotadas.'} O rito segue para o julgamento.`}
        </p>
      </div>

      <div className="party-response-grid">
        {['claimant', 'respondent'].map((party) => (
          <label className="mini-field" key={party}>
            <span>
              Posição de {partyRoleLabel(party).toLowerCase()}
              {composition[party]?.submitted ? ' · registrada' : ''}
            </span>
            {party === myParty && !alreadySubmitted ? (
              <textarea
                value={myPosition}
                onChange={(event) => setMyPosition(event.target.value)}
                placeholder="O que você aceita, rejeita ou gostaria de alterar nesta rodada?"
              />
            ) : (
              <div className="waiting-slot">
                {composition[party]?.submitted
                  ? <em><Check size={14} /> Posição registrada para esta rodada</em>
                  : <em><Clock3 size={14} /> Aguardando a manifestação da parte</em>}
              </div>
            )}
          </label>
        ))}
      </div>

      {myParty && (
        <div className="conciliation-buttons">
          <button
            className="button secondary"
            disabled={busy || alreadySubmitted || !myPosition.trim()}
            onClick={submitPosition}
          >
            <Handshake size={17} /> Registrar minha posição
          </button>
          <button
            className="button ghost"
            disabled={busy}
            onClick={() => run(
              'Encerrando a composição e seguindo para o julgamento...',
              () => request(`/cases/${caseData.id}/composition/close`, {
                method: 'POST',
                headers: actorHeaders(caseData.id, myParty)
              })
            )}
          >
            Encerrar a composição <ArrowRight size={17} />
          </button>
        </div>
      )}
      <small className="consent-note">
        Cada parte fala por si: ninguém redige a manifestação da outra. A
        composição é voluntária — basta um dos lados encerrá-la para o rito
        seguir para o julgamento.
      </small>
    </div>
  )
}

function DocumentsCard({
  caseData,
  documents,
  locked,
  busy,
  run,
  request,
  actorHeaders,
  evidenceResponses,
  setEvidenceResponses,
  roles
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

            {document.response_status === 'precluded' && (
              <small className="admission-note">
                O prazo para se manifestar sobre este material venceu sem
                resposta. A oportunidade foi encerrada por preclusão — o que não
                significa concordância com o conteúdo.
              </small>
            )}

            <MaterialReader
              caseId={caseData.id}
              document={document}
              busy={busy}
              request={request}
            />

            {!locked && roles[document.counterparty] && !document.acknowledged_at && (
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

            {!locked && roles[document.counterparty] && document.acknowledged_at && document.response_status === 'pending' && (
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
                <small className="admission-note">
                  Contraditório cumprido: o rito admite este material
                  automaticamente, sem intervenção de terceiros.
                </small>
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

function MaterialReader({ caseId, document, busy, request }) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState('')

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (content) return
    setLoading(true)
    setFailure('')
    try {
      const data = await request(`/cases/${caseId}/documents/${document.id}/content`)
      setContent(data.content || '')
    } catch (err) {
      setFailure(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function openOriginal() {
    setFailure('')
    try {
      const data = await request(
        `/cases/${caseId}/documents/${document.id}/original-url`,
        { method: 'POST' }
      )
      window.open(data.url, '_blank', 'noopener')
    } catch (err) {
      setFailure(err.message)
    }
  }

  return (
    <div className="material-reader">
      <div className="material-reader-actions">
        <button className="button ghost compact" onClick={toggle} disabled={busy}>
          <FileText size={15} /> {open ? 'Fechar o material' : 'Ler o material'}
        </button>
        {document.has_original && (
          <button className="button ghost compact" onClick={openOriginal} disabled={busy}>
            <Download size={15} /> Baixar o arquivo original
          </button>
        )}
      </div>
      {failure && <small className="material-reader-error">{failure}</small>}
      {open && (
        loading
          ? <small>Carregando o teor do material...</small>
          : <pre className="material-content">{content}</pre>
      )}
    </div>
  )
}

function EvidenceState({ done, label }) {
  return (
    <span className={done ? 'done' : ''}>
      {done ? <Check size={12} /> : <Circle size={10} />}
      {label}
    </span>
  )
}

function Conclusion({ caseData }) {
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

function AnalysisDetails({ caseData }) {
  const conciliationRounds = caseData.conciliation_rounds
    || (caseData.conciliation ? [caseData.conciliation] : [])
  const organized = caseData.organized
  const decision = caseData.decision
  const review = caseData.review

  return (
    <section className="analysis-section">
      <div className="analysis-heading">
        <span className="section-label">O que o sistema encontrou</span>
        <h2>Resumo da análise</h2>
        <p>Veja os fatos organizados, a decisão do agente julgador e sua auditoria independente.</p>
      </div>

      <div className="analysis-grid">
        {conciliationRounds.length > 0 && (
          <ConciliationHistory rounds={conciliationRounds} />
        )}

        {organized && (
          <SummaryCard icon={<Search size={19} />} title="Visão geral">
            <p>{organizedDisplaySummary(organized)}</p>
            <ListBlock title="Pontos ainda em aberto" items={organized.missing_information} />
          </SummaryCard>
        )}

        {decision && (
          <SummaryCard icon={<Gavel size={19} />} title="Decisão da IA">
            <p>{decisionDisplayText(decision)}</p>
            <ListBlock title="Fundamentos" items={decisionDisplayReasoning(decision)} />
            <ListBlock title="Limitações" items={decisionDisplayLimitations(decision)} tone="warning" />
          </SummaryCard>
        )}

        {review && (
          <SummaryCard icon={<ShieldCheck size={19} />} title="Auditoria independente">
            <p>{review.framework_alignment}</p>
            <ListBlock title="Riscos identificados" items={auditDisplayRisks(review)} tone="warning" />
            <ListBlock title="Questões encontradas" items={auditDisplayIssues(review)} />
          </SummaryCard>
        )}
      </div>
    </section>
  )
}

function ConciliationHistory({ rounds }) {
  return (
    <article className="summary-card conciliation-history">
      <div className="summary-card-title">
        <span><Handshake size={19} /></span>
        <div>
          <h3>Rodadas de conciliação e mediação</h3>
          <small>{rounds.length} {rounds.length === 1 ? 'tentativa registrada' : 'tentativas registradas'}</small>
        </div>
      </div>
      <div className="round-list">
        {rounds.map((round, index) => (
          <section className="round-item" key={`round-${round.round_number || index + 1}`}>
            <div className="round-number">{round.round_number || index + 1}</div>
            <div>
              <span className="round-path">{conciliationPathLabel(round.recommended_path)}</span>
              <h4>Rodada {round.round_number || index + 1}</h4>
              <p>{round.neutral_summary}</p>
              <ListBlock title="Interesses em comum" items={round.common_interests} />
              <ListBlock title="Pontos negociáveis" items={round.negotiable_issues} />
              <ListBlock title="Propostas para esta rodada" items={round.possible_terms} />
              {round.continue_recommended && (
                <div className="next-round-callout">
                  <strong>Outra rodada pode ser útil</strong>
                  <span>{round.next_round_focus}</span>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
      <div className="list-block warning">
        <strong>Participação voluntária</strong>
        <p>As propostas só formam acordo quando empresa e cliente manifestam concordância.</p>
      </div>
    </article>
  )
}

function SummaryCard({ icon, title, children }) {
  return (
    <article className="summary-card">
      <div className="summary-card-title"><span>{icon}</span><h3>{title}</h3></div>
      {children}
    </article>
  )
}

function ListBlock({ title, items = [], tone = 'default' }) {
  if (!items?.length) return null
  return (
    <div className={`list-block ${tone}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
      </ul>
    </div>
  )
}

function TechnicalDetails({ caseData, open, setOpen }) {
  return (
    <section className="technical">
      <button className="technical-toggle" onClick={() => setOpen(!open)}>
        <span>
          <strong>Detalhes técnicos e auditoria</strong>
          <small>Hashes, manifesto, dados estruturados e histórico do processo.</small>
        </span>
        <ChevronDown size={18} className={open ? 'rotated' : ''} />
      </button>
      {open && (
        <div className="technical-content">
          <TechnicalBlock title="Manifesto" data={caseData.locked_manifest} />
          <TechnicalBlock title="Rodadas de composição" data={caseData.conciliation_rounds} />
          <TechnicalBlock title="Organização estruturada" data={caseData.organized} />
          <TechnicalBlock title="Decisão estruturada" data={caseData.decision} />
          <TechnicalBlock title="Auditoria estruturada" data={caseData.review} />
          <TechnicalBlock title="Trilha de auditoria" data={caseData.audit_log} />
        </div>
      )}
    </section>
  )
}

function TechnicalBlock({ title, data }) {
  if (!data) return null
  return (
    <details>
      <summary>{title}</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  )
}

function Fact({ label, value, note }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  )
}

function Message({ type, text }) {
  return (
    <div className={`message ${type}`}>
      {type === 'error' ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
      <span>{text}</span>
    </div>
  )
}

function LoadingState() {
  return (
    <section className="surface loading-state">
      <RefreshCw size={22} />
      <span>Carregando seus casos...</span>
    </section>
  )
}

function outcomeLabel(outcome) {
  return {
    claimant: 'Favorável ao requerente',
    respondent: 'Favorável ao requerido',
    partial: 'Parcial',
    inconclusive: 'Inconclusivo'
  }[outcome] || 'Não informado'
}

function decisionDisplayText(decision = {}) {
  if (decision.outcome === 'inconclusive' && decision.execution?.mode === 'safe_fallback') {
    return 'O registro do caso foi preservado, mas a IA não analisou o mérito porque o serviço automático estava indisponível.'
  }
  return decision.decision
}

function conciliationPathLabel(path) {
  return {
    conciliation: 'Tentar conciliação com proposta objetiva',
    mediation: 'Tentar mediação para construção conjunta',
    adjudication: 'Seguir para julgamento',
    human_screening: 'Composição automática não concluída'
  }[path] || 'Não informado'
}

function partyLabel(party, caseData) {
  if (party === 'claimant') return `${caseData.claimant} (cliente)`
  if (party === 'respondent') return `${caseData.respondent} (empresa)`
  return 'parte não identificada'
}

function partyRoleLabel(role) {
  return {
    claimant: 'Cliente reclamante',
    respondent: 'Empresa reclamada'
  }[role] || role
}

function materialTypeLabel(type) {
  return type === 'argument' ? 'Alegação' : 'Prova'
}

function responseStatusLabel(status) {
  return {
    pending: 'Resposta pendente',
    answered: 'Respondido',
    challenged: 'Contestado',
    waived: 'Resposta dispensada',
    precluded: 'Prazo vencido sem resposta'
  }[status] || 'Resposta pendente'
}

function decisionDisplayReasoning(decision = {}) {
  if (decision.execution?.mode === 'safe_fallback') {
    return ['Não houve análise do mérito; o resultado exibido é apenas um bloqueio seguro do sistema.']
  }
  return decision.reasoning
}

function decisionDisplayLimitations(decision = {}) {
  if (decision.execution?.mode === 'safe_fallback') {
    return ['A API de IA não concluiu a chamada. Nenhuma decisão financeira foi produzida.']
  }
  return decision.limitations
}

function organizedDisplaySummary(organized = {}) {
  if (organized.execution?.mode === 'safe_fallback') {
    return 'Os documentos foram recebidos e preservados, mas não houve organização automática pela IA.'
  }
  return organized.summary
}

function hasUnavailableAI(caseData = {}) {
  return [caseData.conciliation, caseData.organized, caseData.decision, caseData.review]
    .some((stage) => stage?.execution?.mode === 'safe_fallback')
}

function truncateText(text = '', limit = 280) {
  if (text.length <= limit) return text
  return `${text.slice(0, limit).trim()}...`
}

function auditDisplayRisks(review = {}) {
  if (review.execution?.mode === 'safe_fallback') {
    return ['A decisão não foi validada como resultado final do sistema.']
  }
  return review.risks
}

function auditDisplayIssues(review = {}) {
  if (review.execution?.mode === 'safe_fallback') {
    return ['A auditoria independente por IA não foi executada.']
  }
  return review.issues
}
