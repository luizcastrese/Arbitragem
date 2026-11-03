import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  Gavel,
  Handshake,
  Info,
  LockKeyhole,
  Mail,
  Scale,
  Search,
  ShieldCheck,
  Upload,
  Eye,
  FolderOpen,
  RefreshCw,
  Sparkles
} from 'lucide-react'
import {
  API_BASE,
  EARLY_CLOSE,
  MATTERS,
  formatApiDetail,
  invitationDeliveryMessage,
  matterLabel,
  oppositeRole,
  roleLabel,
  stageIndexFor,
  statusLabels,
  steps,
  userHasRole
} from './shared.js'
import CalculationCard, { CALCULATION_MATTERS, MemoryTable, ProposalPanel } from './Calculation.jsx'
import { AttachChecklist, BatchContradictory, RefuseProposal } from './Pilot.jsx'
import Markdown from './Markdown.jsx'
import { LiveMessage, LoadingState, Term } from './ui.jsx'

// Casca do workspace: lista de casos à esquerda e, à direita, a abertura de um
// caso novo ou o caso selecionado. Carregada sob demanda (React.lazy) só depois
// do login, para que a landing não pague pelo peso destas telas.
export default function Workspace({
  cases,
  caseData,
  showCreate,
  setShowCreate,
  loadCase,
  loadCases,
  createCase,
  creating,
  createError,
  workspaceRef,
  ...caseProps
}) {
  return (
    <div className="workspace" ref={workspaceRef}>
      <aside className="case-sidebar">
        <div className="sidebar-heading">
          <div>
            <span className="section-label">Seus casos</span>
            <strong>{cases.length} {cases.length === 1 ? 'disputa' : 'disputas'}</strong>
          </div>
          <button type="button" className="icon-button" onClick={() => loadCases()} title="Atualizar casos" aria-label="Atualizar casos">
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
          <CreateCase busy={creating} error={createError} onSubmit={createCase} unverifiedEmail={caseProps.user?.email_verified === false ? caseProps.user.email : ''} onCancel={
            cases.length ? () => setShowCreate(false) : null
          } />
        ) : caseData ? (
          <CaseWorkspace caseData={caseData} {...caseProps} />
        ) : (
          <LoadingState />
        )}
      </div>
    </div>
  )
}

function CreateCase({ busy, error, onSubmit, onCancel, unverifiedEmail = '' }) {
  const [matterId, setMatterId] = useState(MATTERS[0].id)
  const [entryPoint, setEntryPoint] = useState('pre_litigation')
  const [creatorRole, setCreatorRole] = useState('claimant')
  const [actingAsCounsel, setActingAsCounsel] = useState(false)
  const matter = MATTERS.find((item) => item.id === matterId)
  return (
    <section className="surface create-surface">
      <div className="surface-header">
        <span className="number-badge">1</span>
        <div>
          <span className="section-label">Comece por aqui</span>
          <h2>Qual conflito será resolvido?</h2>
          <p>Identifique as partes, a matéria e se já existe processo na Justiça.</p>
        </div>
      </div>

      <form onSubmit={onSubmit} className="guided-form">
        <label className="field full">
          <span>Nome do caso</span>
          <small>Use um título curto que ajude você a encontrá-lo depois.</small>
          <input
            name="title"
            placeholder="Ex.: Desconto de consignado não reconhecido"
            required
            minLength="3"
          />
        </label>
        <label className="field">
          <span>Reclamante</span>
          <small>Quem abre o caso.</small>
          <input name="claimant" placeholder="Ex.: Maria da Silva" required minLength="2" />
        </label>
        <label className="field">
          <span>Reclamada</span>
          <small>A outra parte, que responderá ao caso.</small>
          <input name="respondent" placeholder="Ex.: Banco Exemplo S.A." required minLength="2" />
        </label>
        <label className="field">
          <span>Você atua como</span>
          <small>O convidado recebe o papel oposto.</small>
          <select name="creator_role" value={creatorRole} onChange={(event) => setCreatorRole(event.target.value)}>
            <option value="claimant">Reclamante (quem abre a reclamação)</option>
            <option value="respondent">Reclamada (a outra parte)</option>
          </select>
        </label>
        <div className="field counsel-field">
          <label className="check-line">
            <input
              type="checkbox"
              name="acting_as_counsel"
              checked={actingAsCounsel}
              onChange={(event) => setActingAsCounsel(event.target.checked)}
            />
            <span>Atuo como advogado(a) desta parte</span>
          </label>
          {actingAsCounsel && (
            <>
              <small>Informe a OAB. Ela fica registrada no caso; você segue como {creatorRole === 'claimant' ? 'reclamante' : 'reclamada'} no procedimento.</small>
              <input name="counsel_bar_number" placeholder="OAB/SP 123456" required maxLength="30" autoComplete="off" />
            </>
          )}
        </div>
        <label className="field">
          <span>Matéria</span>
          <small>Define as regras aplicadas, as exclusões e o limite de valor.</small>
          <select name="matter_framework_id" value={matterId} onChange={(event) => setMatterId(event.target.value)}>
            {MATTERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
        {matter?.consumer && (
          <label className="field">
            <span>Quem é o consumidor?</span>
            <small>Em consumo, a arbitragem só vale se o consumidor a escolher.</small>
            <select name="consumer_party" defaultValue="claimant">
              <option value="claimant">A reclamante</option>
              <option value="respondent">A reclamada</option>
            </select>
          </label>
        )}
        <label className="field">
          <span>Já existe processo?</span>
          <small>A Valinor atua antes do processo ou no lugar de um processo já ajuizado.</small>
          <select name="entry_point" value={entryPoint} onChange={(event) => setEntryPoint(event.target.value)}>
            <option value="pre_litigation">Não, ainda não há processo</option>
            <option value="pending_lawsuit">Sim, o processo já foi ajuizado</option>
          </select>
        </label>
        {entryPoint === 'pending_lawsuit' && (
          <>
            <label className="field">
              <span>Número do processo</span>
              <small>Padrão CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO.</small>
              <input name="lawsuit_number" placeholder="0001234-71.2024.8.26.0100" required maxLength="30" />
            </label>
            <label className="field">
              <span>Juízo</span>
              <small>Vara ou juizado onde o processo tramita.</small>
              <input name="court" placeholder="Ex.: 1ª Vara Cível de São Paulo" required minLength="3" />
            </label>
          </>
        )}

        {unverifiedEmail && (
          <div className="full-row auth-callout" role="note">
            <Info size={16} aria-hidden="true" />
            <span>
              Confirme seu e-mail antes de abrir o caso. Enviamos um link para {unverifiedEmail};
              use "Reenviar link" no aviso acima se ele não chegou.
            </span>
          </div>
        )}
        <div className="full-row"><LiveMessage type="error" text={error} /></div>

        <div className="form-actions">
          {onCancel && (
            <button type="button" className="button ghost" onClick={onCancel}>Cancelar</button>
          )}
          <button className="button primary" disabled={busy || Boolean(unverifiedEmail)}>
            Criar caso e adicionar documentos <ArrowRight size={17} />
          </button>
        </div>
      </form>
    </section>
  )
}

function CaseWorkspace({
  caseData,
  busy,
  isPending,
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
  conciliationUpdate,
  setClaimantResponse,
  setRespondentResponse,
  setConciliationUpdate,
  terms,
  privacy,
  showTechnical,
  setShowTechnical,
  user
}) {
  // Modo piloto "acordo rápido": disputa bancária de consumo, acordo primeiro,
  // sem agenda processual nem detalhes técnicos no caminho principal.
  const quick = CALCULATION_MATTERS.has(caseData.pathway?.matter_framework_id)
  const unavailable = hasUnavailableAI(caseData)
  const displayedStage = unavailable ? 2 : stageIndexFor(caseData)
  const endedEarly = EARLY_CLOSE.has(caseData.status) || caseData.procedure_conclusion === 'withdrawn'
  const roles = {
    claimant: userHasRole(caseData, user, 'claimant'),
    respondent: userHasRole(caseData, user, 'respondent')
  }

  return (
    <>
      <section className="case-heading">
        <div>
          <div className="case-meta">
            <span>Caso {caseData.id.slice(0, 8).toUpperCase()}</span>
            <span className={`case-status ${unavailable ? 'unavailable' : caseData.status}`}>
              {unavailable ? 'Análise automática indisponível' : procedureLabel(caseData)}
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

      <ProcessSteps
        currentStage={displayedStage}
        blockedByAI={unavailable}
        endedLabel={endedEarly ? statusLabels[caseData.status] || statusLabels.withdrawn : null}
      />

      {caseData.status !== 'reviewed'
        && caseData.status !== 'attested'
        && caseData.status !== 'contested'
        && caseData.status !== 'agreement'
        && !String(caseData.status || '').startsWith('processing') && (
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
          conciliationUpdate={conciliationUpdate}
          setClaimantResponse={setClaimantResponse}
          setRespondentResponse={setRespondentResponse}
          setConciliationUpdate={setConciliationUpdate}
          roles={roles}
          terms={terms}
          privacy={privacy}
        />
      )}

      {CALCULATION_MATTERS.has(caseData.pathway?.matter_framework_id)
        && (caseData.documents.length > 0 || caseData.calculation) && (
        <CalculationCard
          caseData={caseData}
          roles={roles}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
        />
      )}

      <LiveMessage type="success" text={status} />
      <LiveMessage type="error" text={error} />

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
        quick={quick}
        caseData={caseData}
        busy={busy}
        isPending={isPending}
        run={run}
        request={request}
        actorHeaders={actorHeaders}
        user={user}
      />

      {!caseData.decision_record && (roles.claimant || roles.respondent) && (
        <WithdrawToCourtCard
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          roles={roles}
        />
      )}

      {caseData.pathway && (
        <ArbitratorCard
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          roles={roles}
          isArbitrator={userHasRole(caseData, user, 'arbitrator')}
        />
      )}

      {caseData.decision_record?.outcome?.kind === 'decision'
        && !caseData.arbitral_award?.adopted
        && (roles.claimant || roles.respondent) && (
        <AcceptDecisionCard
          caseData={caseData}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          roles={roles}
        />
      )}

      {caseData.decision_record && (
        <DecisionRecordCard caseData={caseData} isPending={isPending} run={run} />
      )}

      {(caseData.decision?.calculation || caseData.decision_record?.agreement?.calculation) && (
        <section className="calc-card-ui">
          <span className="section-label">Memória de cálculo</span>
          <h3>{caseData.decision?.calculation ? 'Números da decisão' : 'Números do acordo'}</h3>
          <MemoryTable
            lines={(caseData.decision?.calculation || caseData.decision_record.agreement.calculation).lines}
            sha256={(caseData.decision?.calculation || caseData.decision_record.agreement.calculation).sha256}
            source={(caseData.decision?.calculation || caseData.decision_record.agreement.calculation).average_rate_source}
          />
          {caseData.decision?.calculation?.remedy_matches_calculation === false && (
            <small className="consent-note">O valor escrito pela IA divergiu da memória; vale a memória.</small>
          )}
        </section>
      )}

      {['reviewed', 'attested', 'contested', 'inconclusive', 'inadmissible', 'invalidated', 'system_failure'].includes(caseData.status) && (
        <Conclusion caseData={caseData} />
      )}

      {(caseData.conciliation || caseData.organized || caseData.decision || caseData.review) && (
        <AnalysisDetails caseData={caseData} />
      )}

      {quick && !showTechnical ? (
        <button type="button" className="technical-link" onClick={() => setShowTechnical(true)}>
          Mostrar detalhes técnicos (hashes, modelos e cadeia de auditoria)
        </button>
      ) : (
        <TechnicalDetails
          caseData={caseData}
          open={showTechnical}
          setOpen={setShowTechnical}
        />
      )}
    </>
  )
}

// Papel da parte com a explicação em tooltip (Reclamante, Reclamada).
const ROLE_TERM = { claimant: 'reclamante', respondent: 'reclamada' }

function RoleTerm({ role }) {
  return ROLE_TERM[role] ? <Term k={ROLE_TERM[role]}>{roleLabel(role)}</Term> : roleLabel(role)
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function ArbitratorCard({ caseData, busy, run, request, actorHeaders, roles, isArbitrator }) {
  const pathway = caseData.pathway || {}
  const arbitrator = pathway.arbitrator
  const elections = pathway.arbitration_elections || {}
  const anyElection = Object.values(elections).some((item) => item?.elected)
  const locked = caseData.manifest_locked
  const award = caseData.arbitral_award
  const recordKind = caseData.decision_record?.outcome?.kind
  const [form, setForm] = useState({ tax_id: '', qualification: '', independent: false, disclosure: '' })
  const [place, setPlace] = useState('')
  const [statement, setStatement] = useState('')
  if (!anyElection && !arbitrator && !isArbitrator) return null

  function post(label, path, body, party) {
    return run(label, () => request(`/cases/${caseData.id}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(party ? actorHeaders(caseData.id, party) : {}) },
      body: JSON.stringify(body)
    }))
  }

  const confirmations = arbitrator?.confirmations || {}
  const currentIdentity = arbitrator?.identity_sha256
  const confirmedBy = (party) => confirmations[party]?.identity_sha256 === currentIdentity && Boolean(currentIdentity)

  return (
    <section className="record-card arbitrator-card">
      <div className="record-heading">
        <span className="action-icon"><Scale size={22} /></span>
        <div>
          <span className="section-label">Árbitro pessoa física</span>
          <h3>
            {award
              ? (award.adopted ? 'Sentença arbitral assinada' : 'O árbitro não adotou a decisão')
              : pathway.arbitrator_designated
                ? `Árbitro designado: ${arbitrator.display_name}`
                : 'Designação do árbitro'}
          </h3>
          <p>
            A lei exige árbitro pessoa física, com a confiança das duas partes, que assine a sentença
            (Lei 9.307/96, arts. 13 e 26). A IA elabora a decisão; o árbitro a adota e assina, ou recusa.
            A designação fecha quando o caso é travado.
          </p>
        </div>
      </div>

      {arbitrator ? (
        <div className="arbitrator-facts">
          <span><strong>{arbitrator.display_name}</strong> · {arbitrator.qualification}</span>
          <span>Revelação: {arbitrator.disclosure || 'nada a revelar'}</span>
          <span>
            Confirmado pela reclamante: {confirmedBy('claimant') ? 'sim' : 'não'} ·
            pela reclamada: {confirmedBy('respondent') ? 'sim' : 'não'}
          </span>
        </div>
      ) : (
        <p className="consent-note">
          Nenhum árbitro aceitou a nomeação. Uma parte convida o árbitro em “Participantes e prazos”, com o papel Árbitro.
        </p>
      )}

      {!locked && arbitrator && ['claimant', 'respondent'].filter((party) => roles[party] && !confirmedBy(party)).map((party) => (
        <div className="record-actions" key={party}>
          <button
            className="button secondary"
            disabled={busy || !elections[party]?.elected}
            title={elections[party]?.elected ? undefined : 'Escolha a arbitragem no seu aceite antes'}
            onClick={() => post('Confirmando o árbitro...', '/arbitrator/confirm', { party }, party)}
          >
            Confirmar {arbitrator.display_name} como árbitro
          </button>
        </div>
      ))}

      {isArbitrator && !locked && (
        <form
          className="arbitrator-form"
          onSubmit={(event) => {
            event.preventDefault()
            post('Registrando o aceite da nomeação...', '/arbitrator/accept', form)
          }}
        >
          <input className="tax-id-input" placeholder="Seu CPF" value={form.tax_id}
            onChange={(e) => setForm({ ...form, tax_id: e.target.value })} required />
          <input placeholder="Profissão e domicílio" value={form.qualification}
            onChange={(e) => setForm({ ...form, qualification: e.target.value })} required minLength={5} />
          <textarea placeholder="Revele qualquer fato que possa gerar dúvida sobre sua imparcialidade (art. 14, §1º). Deixe em branco se não houver."
            value={form.disclosure} onChange={(e) => setForm({ ...form, disclosure: e.target.value })} />
          <label className="election-choice">
            <input type="checkbox" checked={form.independent}
              onChange={(e) => setForm({ ...form, independent: e.target.checked })} />
            <span>Declaro que sou independente e imparcial em relação às partes e à disputa.</span>
          </label>
          <button className="button primary" disabled={busy || !form.independent}>Aceitar a nomeação</button>
        </form>
      )}

      {isArbitrator && locked && !award && recordKind === 'decision' && (
        <div className="arbitrator-form">
          <input placeholder="Lugar em que a sentença é proferida (ex.: São Paulo/SP)" value={place}
            onChange={(e) => setPlace(e.target.value)} />
          <textarea placeholder="Manifestação do árbitro (opcional)" value={statement}
            onChange={(e) => setStatement(e.target.value)} />
          <div className="record-actions">
            <button className="button primary" disabled={busy || place.trim().length < 2}
              onClick={() => window.confirm('Adotar a decisão e assiná-la como sentença arbitral? A assinatura obriga as partes.')
                && post('Assinando a sentença arbitral...', '/arbitral-award', { adopt: true, place, statement })}>
              Adotar e assinar a sentença
            </button>
            <button className="button secondary" disabled={busy || place.trim().length < 2}
              onClick={() => window.confirm('Recusar adotar a decisão? Não haverá sentença arbitral na plataforma.')
                && post('Registrando a recusa...', '/arbitral-award', { adopt: false, place, statement })}>
              Recusar a decisão
            </button>
          </div>
        </div>
      )}

      {award && (
        <div className="blocking-note">
          <Scale size={17} />
          <span>
            {award.adopted ? 'Adotada e assinada' : 'Recusada'} por {award.arbitrator_name} em {award.place}.
            {' '}Documento adotado: {String(award.adopted_record_hash || '').slice(0, 16)}…
          </span>
        </div>
      )}
    </section>
  )
}

function AcceptDecisionCard({ caseData, busy, run, request, actorHeaders, roles }) {
  const [state, setState] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  const caseId = caseData.id
  const version = caseData.updated_at

  useEffect(() => {
    let cancelled = false
    request(`/cases/${caseId}/decision-acceptance`)
      .then((data) => { if (!cancelled) setState(data) })
      .catch(() => { if (!cancelled) setState(null) })
    return () => { cancelled = true }
  }, [caseId, version])

  if (!state) return null
  const parties = ['claimant', 'respondent'].filter((party) => roles[party])
  const label = { claimant: 'reclamante', respondent: 'reclamada' }
  const both = state.complete
  const reflectionEnds = state.reflection_ends_utc ? new Date(state.reflection_ends_utc) : null

  function accept(party) {
    return run('Registrando o acatamento da decisão...', () => request(`/cases/${caseId}/accept-decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...actorHeaders(caseId, party) },
      body: JSON.stringify({ party, confirm: true })
    }))
  }

  return (
    <section className="record-card accept-decision-card">
      <div className="record-heading">
        <span className="action-icon"><ShieldCheck size={22} /></span>
        <div>
          <span className="section-label">Acatar a decisão</span>
          <h3>{both ? 'Decisão acatada: vale como acordo entre as partes' : 'Adotar a decisão da IA como acordo'}</h3>
          <p>
            Não precisa de árbitro. Se as duas partes acatarem, a decisão passa a valer como acordo
            (Código Civil, art. 840), nos termos do dispositivo, e o pagamento pode ser feito sem esperar
            o prazo de recurso. O ato é irrevogável e afasta o recurso de quem acatou.
          </p>
        </div>
      </div>

      <div className="arbitrator-facts">
        {['claimant', 'respondent'].map((party) => (
          <span key={party}>
            Parte {label[party]}: {state.parties[party]
              ? `acatou em ${new Date(state.parties[party].accepted_at).toLocaleString('pt-BR')}`
              : 'ainda não acatou'}
          </span>
        ))}
      </div>

      {!both && state.can_accept && parties.some((party) => !state.parties[party]) && (
        <>
          <p className="muted">{state.statement.text}</p>
          <label className="election-choice">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            <span>Li a decisão e a declaração acima e quero acatar a decisão, ciente de que não poderei voltar atrás nem recorrer.</span>
          </label>
          <div className="record-actions">
            {parties.filter((party) => !state.parties[party]).map((party) => (
              <button key={party} className="button primary" disabled={busy || !confirmed}
                onClick={() => accept(party)}>
                Acatar como parte {label[party]}
              </button>
            ))}
          </div>
        </>
      )}

      {!both && !state.can_accept && state.blocked_code === 'reflection_period' && reflectionEnds && (
        <div className="blocking-note">
          <ShieldCheck size={17} />
          <span>
            Prazo de reflexão: o acatamento abre em {reflectionEnds.toLocaleString('pt-BR')}.
            Até lá, leia a decisão com calma.
          </span>
        </div>
      )}
    </section>
  )
}

function WithdrawToCourtCard({ caseData, busy, run, request, actorHeaders, roles }) {
  const [reason, setReason] = useState('')
  const party = roles.claimant ? 'claimant' : 'respondent'
  if (String(caseData.status || '').startsWith('processing')) return null

  function withdraw() {
    const confirmed = window.confirm(
      'Optar pela via judicial encerra o caso na Valinor para as duas partes. '
      + 'Não haverá acordo nem decisão aqui. As duas partes recebem o auto com '
      + 'todo o histórico até agora. Deseja continuar?'
    )
    if (!confirmed) return
    run('Encerrando o caso e emitindo o auto com o histórico...', () =>
      request(`/cases/${caseData.id}/withdraw-to-court`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, party) },
        body: JSON.stringify({ party, reason })
      })
    )
  }

  return (
    <section className="record-card withdraw-card">
      <div className="record-heading">
        <span className="action-icon"><Scale size={22} /></span>
        <div>
          <span className="section-label">Adesão voluntária</span>
          <h3>Prefere levar o conflito à Justiça?</h3>
          <p>
            Você pode sair a qualquer momento antes do desfecho, sem depender da outra parte.
            O caso encerra e as duas partes recebem o auto com todo o histórico até aqui:
            documentos, respostas, rodadas de acordo e a trilha de auditoria, para conferir
            e, se quiserem, juntar ao processo.
          </p>
        </div>
      </div>
      <div className="record-actions">
        <input
          className="tax-id-input withdraw-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Motivo (opcional)"
          aria-label="Motivo da opção pela via judicial"
          maxLength={2000}
        />
        <button className="button secondary" onClick={withdraw} disabled={busy}>
          Optar pela via judicial
        </button>
      </div>
    </section>
  )
}

function DecisionRecordCard({ caseData, isPending, run }) {
  const record = caseData.decision_record
  const kind = record.outcome?.kind
  const title = kind === 'agreement'
    ? 'Termo de acordo'
    : kind === 'decision'
      ? 'Decisão proferida'
      : kind === 'withdrawn'
        ? 'Encerrado por opção pela via judicial'
        : 'Encerrado sem decisão de mérito'
  const baseName = `auto-valinor-${caseData.id.slice(0, 8)}-${record.record_number}`

  async function downloadDocx() {
    await run('Gerando o auto em Word...', async () => {
      const response = await fetch(`${API_BASE}/cases/${caseData.id}/decision-record.docx`, {
        credentials: 'include'
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(formatApiDetail(data.detail, 'Não foi possível gerar o auto'))
      }
      saveBlob(await response.blob(), `${baseName}.docx`)
    }, { key: 'download:record', exclusive: false })
  }

  function downloadJson() {
    const blob = new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' })
    saveBlob(blob, `${baseName}.json`)
  }

  return (
    <section className="record-card">
      <div className="record-heading">
        <span className="action-icon"><FileCheck2 size={22} /></span>
        <div>
          <span className="section-label">Documento final · Auto nº {record.record_number}</span>
          <h3>Auto da decisão: {title}</h3>
          <p>{record.outcome?.summary}</p>
        </div>
      </div>
      <div className="record-actions">
        <button className="button primary" onClick={downloadDocx} disabled={isPending('download:record')}>
          <Download size={16} /> Baixar o auto (Word)
        </button>
        <button className="button secondary" onClick={downloadJson}>
          <FileText size={16} /> Baixar o auto assinado (JSON)
        </button>
      </div>
      <div className="blocking-note">
        <Scale size={17} />
        <span>
          {record.legal_effect
            ? <>{record.legal_effect.instrument_label}. {record.legal_effect.next_steps?.join(' ')} {record.legal_effect.pending?.join(' ')} </>
            : <>A decisão não obriga as partes. Este auto registra o procedimento, o
              desfecho e a fundamentação, e pode servir de base para uma ação
              judicial ou reclamação. </>}
          Hash {String(record.record_hash || '').slice(0, 16)}… ·
          assinatura {record.signature_algorithm}. A versão JSON é a que se confere
          em <code>/decision-records/verify</code>.
        </span>
      </div>
    </section>
  )
}

function OperationsCard({ caseData, busy, isPending, run, request, actorHeaders, user, quick = false }) {
  const [inviteLink, setInviteLink] = useState('')
  const [inviteNotice, setInviteNotice] = useState('')
  const deadlines = caseData.deadlines || []
  const participants = caseData.participants || []
  const pendingInvites = (caseData.invitations || []).filter((item) => item.status === 'pending')
  const canConduct = userHasRole(caseData, user, 'claimant') || userHasRole(caseData, user, 'respondent')
  // O convidado recebe, por padrão, o papel oposto ao de quem convida.
  const myRole = userHasRole(caseData, user, 'respondent') ? 'respondent' : 'claimant'
  const counsel = caseData.pathway?.counsel || {}

  async function invite(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await run('Criando convite protegido...', async () => {
      const data = await request(`/cases/${caseData.id}/invitations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, 'manager') },
        body: JSON.stringify({ email: form.get('email'), role: form.get('role') })
      })
      setInviteLink(data.acceptance_token
        ? `${window.location.origin}/ui/?invite=${data.acceptance_token}`
        : '')
      setInviteNotice(invitationDeliveryMessage(data))
      event.currentTarget?.reset?.()
      return data
    })
  }

  async function resendInvite(invitation) {
    await run('Reenviando convite...', async () => {
      const data = await request(`/cases/${caseData.id}/invitations/${invitation.id}/resend`, {
        method: 'POST',
        headers: actorHeaders(caseData.id, 'manager')
      })
      setInviteLink(data.acceptance_token
        ? `${window.location.origin}/ui/?invite=${data.acceptance_token}`
        : '')
      setInviteNotice(invitationDeliveryMessage(data))
      return data
    })
  }

  async function addDeadline(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await run('Registrando prazo e notificações...', () => request(`/cases/${caseData.id}/deadlines`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, 'manager') },
      body: JSON.stringify({
        label: form.get('label'),
        assigned_to: form.get('assigned_to'),
        kind: 'procedural',
        due_at: new Date(form.get('due_at')).toISOString()
      })
    }))
  }

  async function downloadReport() {
    await run('Gerando o relatório Word...', async () => {
      const response = await fetch(`${API_BASE}/cases/${caseData.id}/report.docx`, {
        credentials: 'include'
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(formatApiDetail(data.detail, 'Não foi possível gerar o relatório'))
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `relatorio-valinor-${caseData.id.slice(0, 8)}.docx`
      anchor.click()
      URL.revokeObjectURL(url)
    }, { key: 'download:report', exclusive: false })
  }

  return (
    <section className={`operations-card${quick ? ' quick' : ''}`}>
      <div className="card-title-row">
        <div>
          <span className="section-label">{quick ? 'Convite' : 'Acesso, agenda e entrega'}</span>
          <h3>{quick ? 'Convide a outra parte' : 'Condução pelas partes'}</h3>
        </div>
        {!quick && (
          <button className="button secondary" onClick={downloadReport} disabled={isPending('download:report')}>
            <Download size={16} /> Baixar relatório Word
          </button>
        )}
      </div>

      <div className="operations-grid">
        <div className="operation-block">
          <div className="operation-title"><Mail size={18} /><strong>Participantes</strong></div>
          <p>Convide cada pessoa pelo e-mail que será usado na conta. O papel limita as ações disponíveis.</p>
          {participants.map((participant) => (
            <span className="participant-row" key={`${participant.email}-${participant.role}`}>
              <strong>{participant.display_name}</strong> <RoleTerm role={participant.role} /> · {participant.email}
              {counsel[participant.role]?.bar_number && (
                <small> · advogado(a) da parte, {counsel[participant.role].bar_number}</small>
              )}
            </span>
          ))}
          {pendingInvites.map((invitation) => (
            <span className="participant-row pending-invite" key={invitation.id}>
              <span>
                <strong>{invitation.email}</strong>
                <small>{roleLabel(invitation.role)} · convite pendente</small>
              </span>
              {canConduct && (
                <button
                  type="button"
                  className="button ghost compact"
                  disabled={busy}
                  onClick={() => resendInvite(invitation)}
                >
                  Reenviar
                </button>
              )}
            </span>
          ))}
          {canConduct && <form className="compact-form" onSubmit={invite}>
            <input name="email" type="email" required placeholder="E-mail da parte" />
            <select name="role" defaultValue={oppositeRole(myRole)} key={myRole}>
              <option value="claimant">Reclamante</option>
              <option value="respondent">Reclamada</option>
              <option value="arbitrator">Árbitro</option>
            </select>
            <button className="button primary" disabled={busy}>Gerar convite</button>
          </form>}
          {inviteNotice && <small className="invite-notice">{inviteNotice}</small>}
          {inviteLink && (
            <label className="invite-link">
              <span>Link protegido para envio</span>
              <input value={inviteLink} readOnly onFocus={(event) => event.target.select()} />
            </label>
          )}
          {!canConduct && <small>Somente as partes podem criar novos convites.</small>}
        </div>

        {!quick && (
          <div className="operation-block">
            <div className="operation-title"><Clock3 size={18} /><strong>Agenda processual</strong></div>
            <p>Defina datas claras para manifestação, documentos ou negociação. A situação é calculada automaticamente.</p>
            <div className="deadline-list">
              {deadlines.map((deadline) => (
                <span className={`deadline-row ${deadline.status}`} key={deadline.id}>
                  <strong>{deadline.label}</strong>
                  <small>{deadline.assigned_to} · {new Date(deadline.due_at).toLocaleString('pt-BR')} · {deadline.status}</small>
                </span>
              ))}
              {!deadlines.length && <span className="empty-inline">Nenhum prazo registrado.</span>}
            </div>
            {canConduct && <form className="compact-form deadline-form" onSubmit={addDeadline}>
              <input name="label" required minLength="3" placeholder="Ex.: resposta aos documentos" />
              <select name="assigned_to" defaultValue="all">
                <option value="all">Todas as pessoas</option>
                <option value="claimant">Reclamante</option>
                <option value="respondent">Reclamada</option>
              </select>
              <input name="due_at" type="datetime-local" required />
              <button className="button secondary" disabled={busy}>Adicionar prazo</button>
            </form>}
          </div>
        )}
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
            || 'A posição da reclamante ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label={`Posição de ${caseData.respondent}`}
          text={[...companyResponses, ...respondentPurposes][0]
            || 'A posição da reclamada ainda não foi resumida nos materiais.'}
        />
        <BriefPoint
          label="Questão central"
          text={
            caseData.organized?.disputed_facts?.[0]
            || 'Comparar o pedido da reclamante e a defesa da reclamada usando apenas os materiais admitidos.'
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

function ProcessSteps({ currentStage, blockedByAI = false, endedLabel = null }) {
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
            : endedLabel || `${Math.round(((currentStage + 1) / steps.length) * 100)}% concluído`}
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
                <strong>{step.glossary ? <Term k={step.glossary}>{step.title}</Term> : step.title}</strong>
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
  conciliationUpdate,
  setClaimantResponse,
  setRespondentResponse,
  setConciliationUpdate,
  roles,
  terms,
  privacy
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
      label: 'Próximo passo',
      title: 'Verifique se existe espaço para acordo',
      description: 'A IA buscará interesses convergentes e indicará conciliação, mediação ou continuidade do julgamento.'
    },
    conciliation: {
      icon: <Search size={22} />,
      label: 'Sem acordo ou após a tentativa',
      title: 'Prepare o caso para julgamento',
      description: 'Se a composição não encerrar a disputa, o sistema organiza fatos, pedidos e evidências.'
    },
    organized: {
      icon: <Gavel size={22} />,
      label: 'Próximo passo',
      title: 'Solicite a decisão da IA',
      description: `O agente julgador aplicará às evidências do caso as regras fixadas para a matéria: ${matterLabel(caseData)}.`
    },
    decided: {
      icon: <ShieldCheck size={22} />,
      label: 'Último passo',
      title: 'Audite a decisão',
      description: 'Uma segunda IA verificará fundamentos, evidências, contradições e aderência às regras.'
    }
  }[caseData.status]

  // Estado sem próxima ação de parte (ex.: desfecho): só a nota do gestor.
  if (!actionContent) return <StewardNote caseData={caseData} />

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
          conciliationUpdate={conciliationUpdate}
          setClaimantResponse={setClaimantResponse}
          setRespondentResponse={setRespondentResponse}
          setConciliationUpdate={setConciliationUpdate}
          roles={roles}
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
            terms={terms}
            privacy={privacy}
          />

          <div className="submission-context">
            <label className="mini-field">
              <span>Quem está apresentando?</span>
              <select
                value={documentParty}
                onChange={(event) => setDocumentParty(event.target.value)}
              >
                {roles.claimant && <option value="claimant">Reclamante</option>}
                {roles.respondent && <option value="respondent">Reclamada</option>}
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

          {CALCULATION_MATTERS.has(caseData.pathway?.matter_framework_id) && (
            <AttachChecklist documents={caseData.documents || []} />
          )}

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

          <div className="lock-explanation">
            <LockKeyhole size={20} />
            <div>
              <strong>Quando a sua parte não tiver mais nada a apresentar</strong>
              <span>
                O gestor é uma IA. Ele trava o conjunto quando as duas partes
                declaram a apresentação encerrada e o contraditório fecha.
                Nenhuma das partes aperta esse botão pela outra.
              </span>
            </div>
            {['claimant', 'respondent'].filter((party) => roles[party]).map((party) => {
              const ready = Boolean(caseData.submission?.[party]?.ready)
              return (
                <button
                  key={party}
                  className="button primary"
                  disabled={busy}
                  onClick={() => run(
                    ready
                      ? 'Reabrindo a sua apresentação...'
                      : 'Registrando que a sua apresentação encerrou...',
                    () => request(`/cases/${caseData.id}/submission-ready`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json', ...actorHeaders() },
                      body: JSON.stringify({ party, ready: !ready })
                    })
                  )}
                >
                  {ready ? 'Ainda vou incluir material' : 'Concluí minha apresentação'}
                  <ArrowRight size={17} />
                </button>
              )
            })}
          </div>
          <div className="blocking-note">
            <AlertTriangle size={17} />
            <span>
              Reclamante: {caseData.submission?.claimant?.ready ? 'apresentação encerrada' : 'ainda pode incluir material'}.
              {' '}Reclamada: {caseData.submission?.respondent?.ready ? 'apresentação encerrada' : 'ainda pode incluir material'}.
              {' '}{!caseData.consent?.complete ? 'A adesão das duas partes ainda está pendente. ' : ''}
              {!caseData.contradictory?.complete
                ? 'Cada material precisa de ciência e resposta antes de o gestor travar.'
                : 'O gestor admite o material sozinho, depois da resposta.'}
            </span>
          </div>
        </>
      ) : (
        <StewardNote caseData={caseData} />
      )}
    </section>
  )
}

function ConsentPanel({ caseData, busy, run, request, actorHeaders, roles, terms, privacy }) {
  const [showTerms, setShowTerms] = useState(false)
  const [showPrivacy, setShowPrivacy] = useState(false)
  const [taxIds, setTaxIds] = useState({ claimant: '', respondent: '' })
  const [elections, setElections] = useState({ claimant: false, respondent: false })
  const pathway = caseData.pathway
  const consumerParty = pathway?.consumer_relation ? pathway.consumer_party : null
  const entries = [
    {
      party: 'claimant',
      label: 'Reclamante',
      name: caseData.claimant,
      consent: caseData.consent?.claimant
    },
    {
      party: 'respondent',
      label: 'Reclamada',
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
              <em>
                <Check size={14} /> Aceitou
                {pathway?.arbitration_elections?.[entry.party]?.elected ? ' · escolheu arbitragem' : ''}
              </em>
            ) : roles[entry.party] ? (
              <span className="consent-action">
              <input
                className="tax-id-input"
                value={taxIds[entry.party]}
                onChange={(event) => setTaxIds({ ...taxIds, [entry.party]: event.target.value })}
                placeholder="CPF ou CNPJ da parte"
                aria-label={`CPF ou CNPJ de ${entry.name}`}
                maxLength={20}
              />
              {pathway && (
                <label className="election-choice">
                  <input
                    type="checkbox"
                    checked={elections[entry.party]}
                    onChange={(event) => setElections({ ...elections, [entry.party]: event.target.checked })}
                  />
                  <span>
                    Se não houver acordo, escolho a arbitragem (opcional).
                    {consumerParty === entry.party ? ' Como consumidor, só você pode fazer esta escolha, e ela não altera nada no procedimento se você não a fizer.' : ''}
                  </span>
                </label>
              )}
              <button
                className="button secondary compact"
                // Sem o texto carregado não há o que aceitar: o aceite grava o
                // hash do que foi exibido, não uma versão suposta. O CPF/CNPJ
                // qualifica a parte no auto da decisão.
                disabled={busy || !terms || !taxIds[entry.party].trim()}
                title={terms ? undefined : 'Carregando os termos...'}
                onClick={() => run(
                  `Registrando a adesão de ${entry.name}...`,
                  () => request(`/cases/${caseData.id}/consent`, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      ...actorHeaders(caseData.id, entry.party)
                    },
                    body: JSON.stringify({
                      party: entry.party,
                      accepted: true,
                      // Aceita-se a versão que esta tela exibiu, não a que o
                      // servidor considerar vigente no momento do clique.
                      terms_version: terms.version,
                      tax_id: taxIds[entry.party],
                      ...(pathway ? { elects_arbitration: elections[entry.party] } : {})
                    })
                  })
                )}
              >
                Registrar aceite
              </button>
              </span>
            ) : (
              <em><Clock3 size={14} /> Aguardando a parte</em>
            )}
          </div>
        ))}
      </div>
      <div className="terms-summary">
        <strong>Ao aceitar, cada parte confirma que compreendeu:</strong>
        <span>adesão voluntária, antes do processo ou com processo ajuizado; acesso a todo material e oportunidade de resposta; acordo primeiro, só com o aceite das duas partes; sem acordo, decisão da IA com raciocínio e cálculos visíveis, que só é arbitragem se as duas partes a escolherem (em consumo, por escolha do consumidor depois do conflito) e vira sentença arbitral com a assinatura do árbitro pessoa física; sem essa escolha, a decisão não obriga; auditoria e recurso automáticos; na dúvida, o sistema se abstém; ao final, um auto assinado que diz o efeito jurídico do resultado.</span>
        {pathway && (
          <span className="pathway-line">
            {pathway.entry_label}
            {pathway.lawsuit ? ` · processo ${pathway.lawsuit.number} (${pathway.lawsuit.court})` : ''}
            {' · sem acordo: '}{pathway.resolution_track_label}
          </span>
        )}
        <button className="link-button" onClick={() => setShowTerms(!showTerms)}>
          {showTerms ? 'Ocultar o texto integral' : 'Ler o texto integral dos termos'}
        </button>
        {showTerms && (
          <div className="terms-scroll" tabIndex={0}>
            {terms?.text ? <Markdown source={terms.text} /> : <p>Carregando os termos...</p>}
          </div>
        )}
        <button className="link-button" onClick={() => setShowPrivacy(!showPrivacy)}>
          {showPrivacy ? 'Ocultar a política de privacidade' : 'Ler a política de privacidade'}
        </button>
        {showPrivacy && (
          <div className="terms-scroll" tabIndex={0}>
            {privacy?.text ? <Markdown source={privacy.text} /> : <p>Carregando a política de privacidade...</p>}
          </div>
        )}
      </div>
      <small>
        {terms
          ? <>Versão dos termos: {terms.version} · SHA-256 {terms.sha256.slice(0, 16)}…</>
          : 'Carregando a versão vigente dos termos...'}
        {' '}O aceite grava a versão e o hash deste texto na cadeia de auditoria, junto ao papel e ao momento.
        {privacy && (
          <> Política de privacidade: versão {privacy.version} · SHA-256 {privacy.sha256.slice(0, 16)}…</>
        )}
      </small>
    </div>
  )
}

function StewardNote({ caseData }) {
  const steward = caseData.steward
  if (!steward?.reason) return null
  return (
    <div className="blocking-note">
      <ShieldCheck size={17} />
      <span>
        <Term k="gestor">Gestor</Term>: {steward.reason}
        {steward.state === 'processing' ? ' A etapa está em andamento.' : ''}
        {steward.state === 'waiting' ? ' A próxima palavra é de uma parte.' : ''}
      </span>
    </div>
  )
}

function PartyPosition({
  party,
  caseData,
  latest,
  busy,
  run,
  request,
  actorHeaders,
  draft,
  setDraft
}) {
  const recorded = latest.party_positions?.[party]
  const label = party === 'claimant' ? 'parte reclamante' : 'parte reclamada'
  if (recorded) {
    return (
      <p className="consent-note">
        Posição da {label} registrada
        {recorded.waived ? ' (nada a acrescentar).' : '.'}
      </p>
    )
  }
  return (
    <div className="evidence-response">
      <label className="mini-field">
        <span>Posição da {label} nesta rodada</span>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="O que aceita, recusa ou o fato novo que o gestor deve considerar."
        />
      </label>
      <div>
        <button
          className="button secondary compact"
          disabled={busy || !draft.trim()}
          onClick={() => run(
            'Enviando a sua posição ao gestor...',
            () => request(
              `/cases/${caseData.id}/conciliation/${latest.round_number || 1}/position`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...actorHeaders() },
                body: JSON.stringify({ party, text: draft, waived: false })
              }
            )
          )}
        >
          Enviar minha posição
        </button>
        <button
          className="button ghost compact"
          disabled={busy}
          onClick={() => run(
            'Registrando que você não tem nada a acrescentar...',
            () => request(
              `/cases/${caseData.id}/conciliation/${latest.round_number || 1}/position`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...actorHeaders() },
                body: JSON.stringify({ party, text: '', waived: true })
              }
            )
          )}
        >
          Nada a acrescentar
        </button>
      </div>
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
  roles
}) {
  const rounds = caseData.conciliation_rounds || []
  const latest = rounds[rounds.length - 1] || caseData.conciliation || {}
  const agreement = latest.agreement || { responses: {} }

  function answerAgreement(party, accepted, reason = '') {
    return run(
      accepted ? 'Registrando seu aceite da proposta...' : 'Registrando sua recusa da proposta...',
      () => request(`/cases/${caseData.id}/conciliation/${latest.round_number || rounds.length}/agreement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, party) },
        body: JSON.stringify({ party, accepted, ...(accepted ? {} : { reason }) })
      })
    )
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

      {['claimant', 'respondent'].map((party) => roles[party] && (
        <PartyPosition
          key={party}
          party={party}
          caseData={caseData}
          latest={latest}
          busy={busy}
          run={run}
          request={request}
          actorHeaders={actorHeaders}
          draft={party === 'claimant' ? claimantResponse : respondentResponse}
          setDraft={party === 'claimant' ? setClaimantResponse : setRespondentResponse}
        />
      ))}

      <ProposalPanel round={latest} />

      <div className="conciliation-buttons">
        {['claimant', 'respondent'].map((party) => roles[party] && (
          <button
            key={`accept-${party}`}
            className="button primary"
            disabled={busy || agreement.complete || !latest.possible_terms?.length}
            onClick={() => answerAgreement(party, true)}
          >
            <Handshake size={17} />
            {(agreement.responses?.[party]?.accepted)
              ? 'Aceite registrado — aguardando a outra parte'
              : 'Aceitar esta proposta'}
          </button>
        ))}
      </div>
      {['claimant', 'respondent'].map((party) => roles[party] && latest.possible_terms?.length > 0 && !agreement.complete && (
        <RefuseProposal
          key={`refuse-${party}`}
          party={party}
          refused={agreement.responses?.[party]?.accepted === false}
          disabled={busy || agreement.responses?.[party]?.accepted === true}
          onRefuse={(who, reason) => answerAgreement(who, false, reason)}
        />
      ))}
      <StewardNote caseData={caseData} />
      <small className="consent-note">
        {agreement.complete
          ? 'Acordo formado: as duas partes aceitaram a mesma proposta.'
          : 'O acordo só se forma com o aceite separado das duas partes. O gestor, não uma delas, decide se abre outra rodada ou segue ao julgamento.'}
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
      <BatchContradictory
        caseData={caseData}
        roles={roles}
        busy={busy}
        run={run}
        request={request}
        actorHeaders={actorHeaders}
      />
      <div className="document-list">
        {documents.map((document) => (
          <DocumentEvidenceItem
            key={document.id}
            document={document}
            caseData={caseData}
            locked={locked}
            busy={busy}
            run={run}
            request={request}
            actorHeaders={actorHeaders}
            evidenceResponses={evidenceResponses}
            setEvidenceResponses={setEvidenceResponses}
            roles={roles}
          />
        ))}
      </div>
    </section>
  )
}

function DocumentEvidenceItem({
  document,
  caseData,
  locked,
  busy,
  run,
  request,
  actorHeaders,
  evidenceResponses,
  setEvidenceResponses,
  roles
}) {
  const [open, setOpen] = useState(false)
  const [content, setContent] = useState(null)
  const [readError, setReadError] = useState('')
  const purged = Boolean(document.content_purged_at)

  async function toggleContent() {
    if (purged || content !== null) {
      setOpen((value) => !value)
      return
    }
    setReadError('')
    try {
      const data = await request(`/cases/${caseData.id}/documents/${document.id}/content`)
      setContent(data.content || '')
      setOpen(true)
    } catch (err) {
      setReadError(err.message)
    }
  }

  async function downloadOriginal() {
    setReadError('')
    try {
      const response = await fetch(
        `${API_BASE}/cases/${caseData.id}/documents/${document.id}/original`,
        { credentials: 'include' }
      )
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(formatApiDetail(data.detail, 'Não foi possível baixar o original'))
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = document.name
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setReadError(err.message)
    }
  }

  function respondToEvidence(responseStatus) {
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

  return (
          <article className="evidence-item">
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

            <div className="evidence-actions">
              <button type="button" className="button ghost compact" onClick={toggleContent} disabled={busy}>
                <Eye size={14} /> {open ? 'Ocultar teor' : 'Ler teor'}
              </button>
              {document.has_original && !purged && (
                <button type="button" className="button ghost compact" onClick={downloadOriginal} disabled={busy}>
                  <Download size={14} /> Baixar original
                </button>
              )}
            </div>

            {open && (
              <div className="document-body">
                {purged
                  ? <p>O conteúdo foi expurgado pela política de retenção. Metadados e hash permanecem.</p>
                  : <pre>{content || 'Este documento não tem texto extraído.'}</pre>}
              </div>
            )}
            {readError && <p className="document-read-error">{readError}</p>}

            <div className="evidence-timeline">
              <EvidenceState done={Boolean(document.disclosed_at)} label="Disponibilizado" />
              <EvidenceState done={Boolean(document.acknowledged_at)} label="Ciência confirmada" />
              <EvidenceState
                done={document.response_status !== 'pending'}
                label={responseStatusLabel(document.response_status)}
              />
              <EvidenceState done={document.admitted} label="Admitido para decisão" />
            </div>

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
                    onClick={() => respondToEvidence('answered')}
                  >
                    Registrar resposta
                  </button>
                  <button
                    className="button ghost compact"
                    disabled={busy || !(evidenceResponses[document.id] || '').trim()}
                    onClick={() => respondToEvidence('challenged')}
                  >
                    Contestar
                  </button>
                  <button
                    className="button ghost compact"
                    disabled={busy}
                    onClick={() => respondToEvidence('waived')}
                  >
                    Renunciar à resposta
                  </button>
                </div>
              </div>
            )}

            {!locked && document.response_status !== 'pending' && !document.admitted && (
              <p className="consent-note">O gestor admite este material. Nenhuma parte faz isso pela outra.</p>
            )}

            {document.response_text && (
              <div className="recorded-response">
                <strong>Resposta da contraparte</strong>
                <p>{document.response_text}</p>
              </div>
            )}
          </article>
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
  const verification = caseData.verification || {}
  const stability = caseData.stability
  const inconclusive = decision.outcome === 'inconclusive' || ['inconclusive', 'inadmissible', 'invalidated', 'system_failure'].includes(caseData.procedure_conclusion)
  const unavailable = decision.execution?.mode === 'safe_fallback'
  const decisionText = decisionDisplayText(decision)
  const approvedFinal = Boolean(
    verification.valid
    && review.approved
    && (!stability || stability.stable !== false)
    && caseData.attestation
    && caseData.attestation.signature
    && !inconclusive
  )

  return (
    <section className={`conclusion ${inconclusive || !approvedFinal ? 'attention' : 'approved'}`}>
      <div className="conclusion-icon">
        {inconclusive || !approvedFinal ? <AlertTriangle size={28} /> : <CheckCircle2 size={28} />}
      </div>
      <div className="conclusion-copy">
        <span className="section-label">Decisão do procedimento autônomo</span>
        <h2>
          {unavailable
            ? 'A análise automática não foi concluída'
            : caseData.procedure_conclusion === 'inadmissible'
              ? 'O caso é inadmissível neste procedimento'
              : caseData.procedure_conclusion === 'invalidated'
                ? 'A decisão foi invalidada'
                : inconclusive
                  ? 'A IA se absteve de decidir o mérito'
                  : approvedFinal
                    ? 'Decisão aprovada'
                    : 'A decisão ainda não está aprovada'}
        </h2>
        <p>{decisionText}</p>
      </div>
      <div className="conclusion-facts">
        <Fact
          label="Confiança"
          value={`${Math.round((decision.confidence || 0) * 100)}%`}
          note={unavailable ? 'O modelo não chegou a analisar o caso' : inconclusive ? 'Evidência insuficiente ou abstenção' : 'Nível informado pelo modelo'}
        />
        <Fact
          label="Verificação"
          value={verification.valid ? 'Válida' : verification.valid === false ? 'Reprovada' : 'Pendente'}
          note="Verificador determinístico do manifesto"
        />
        <Fact
          label="Auditoria"
          value={unavailable ? 'Não executada' : review.approved ? 'Aprovada' : (review.outcome || 'Com ressalvas')}
          note={unavailable ? 'Não havia decisão para auditar' : 'Auditoria automática independente'}
        />
        <Fact
          label="Resultado"
          value={outcomeLabel(decision.outcome)}
          note={`Matéria: ${matterLabel(caseData)}${(decision.execution || {}).model ? ` · modelo ${decision.execution.model}` : ''}`}
        />
      </div>
      {decision.material_findings?.length > 0 && (
        <div className="findings-block">
          <strong>Findings</strong>
          {decision.material_findings.map((finding) => (
            <article key={finding.finding_id} className="finding-item">
              <span>{finding.status}</span>
              <p>{finding.proposition}</p>
              {(finding.evidence || []).map((ref, index) => (
                <small key={`${finding.finding_id}-${index}`}>
                  {ref.document_id} · {ref.page_number ? `p. ${ref.page_number} · ` : ''}
                  “{truncateText(ref.quoted_text, 140)}” · {(ref.quoted_text_sha256 || '').slice(0, 12)}…
                </small>
              ))}
            </article>
          ))}
        </div>
      )}
      {decision.rule_applications?.length > 0 && (
        <ListBlock title="Regras aplicadas" items={decision.rule_applications.map((item) => `${item.rule_id}: ${item.conclusion}`)} />
      )}
      {decision.remedy_calculation && (
        <p>
          Cálculo {decision.remedy_calculation.formula}: {decision.remedy_calculation.result_minor_units} {decision.remedy_calculation.currency}
        </p>
      )}
      {inconclusive && (
        <div className="human-review-note">
          <Info size={18} />
          <span>
            <strong>{unavailable ? 'Pendência técnica:' : 'Abstenção autônoma:'}</strong>
            {' '}{unavailable
              ? 'configure um provedor de modelo e processe um novo caso. Não há encaminhamento para julgador humano interno.'
              : 'o procedimento encerrou-se sem declarar vencedor. Direitos externos permanecem conforme a legislação e o contrato aplicáveis.'}
          </span>
        </div>
      )}
      {caseData.model_independence_satisfied === false && (
        <div className="human-review-note">
          <AlertTriangle size={18} />
          <span>Julgador e revisor não estão com políticas independentes nesta instância. O modo de demonstração não emite attestation de mérito.</span>
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
            {decision.execution?.model && (
              <p>Modelo efetivo: {decision.execution.provider || ''} {decision.execution.model}</p>
            )}
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
        <p>As propostas só formam acordo quando as duas partes manifestam concordância.</p>
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

function procedureLabel(caseData) {
  const conclusion = caseData.procedure_conclusion
  const verification = caseData.verification || {}
  const review = caseData.review || {}
  const stability = caseData.stability
  const attestation = caseData.attestation
  if (caseData.status?.startsWith('processing')) {
    return statusLabels[caseData.status] || 'Em processamento'
  }
  if (conclusion === 'withdrawn') return statusLabels.withdrawn
  if (conclusion === 'inadmissible') return 'Caso inadmissível'
  if (conclusion === 'invalidated') return 'Decisão invalidada'
  if (conclusion === 'system_failure') return 'Falha do sistema'
  if (conclusion === 'inconclusive') return 'Decisão inconclusiva'
  if (caseData.appeals?.length) {
    const latest = caseData.appeals[caseData.appeals.length - 1]
    const map = {
      upheld: 'Decisão mantida',
      corrected: 'Decisão corrigida',
      annulled: 'Decisão anulada',
      inconclusive: 'Recurso inconclusivo',
      inadmissible: 'Recurso inadmissível'
    }
    if (latest?.status && map[latest.status]) return map[latest.status]
    return 'Recurso automático'
  }
  if (attestation && attestation.signature && verification.valid && review.approved && (!stability || stability.stable !== false)) {
    return 'Decisão aprovada'
  }
  if (review && !review.approved) return 'Auditoria automática'
  if (verification && verification.valid === false) return 'Verificação determinística'
  return statusLabels[caseData.status] || caseData.status
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
  if (party === 'claimant') return `${caseData.claimant} (reclamante)`
  if (party === 'respondent') return `${caseData.respondent} (reclamada)`
  return 'parte não identificada'
}

function materialTypeLabel(type) {
  return type === 'argument' ? 'Alegação' : 'Prova'
}

function responseStatusLabel(status) {
  return {
    pending: 'Resposta pendente',
    answered: 'Respondido',
    challenged: 'Contestado',
    waived: 'Resposta dispensada'
  }[status] || 'Resposta pendente'
}

function decisionDisplayReasoning(decision = {}) {
  if (decision.execution?.mode === 'safe_fallback') {
    return ['Não houve análise do mérito; o resultado exibido é apenas um bloqueio seguro do sistema.']
  }
  if (decision.material_findings?.length) {
    return decision.material_findings.map((item) => `${item.status}: ${item.proposition}`)
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
  return (review.issues || []).map((item) => (
    typeof item === 'string' ? item : (item?.message || item?.code || '')
  )).filter(Boolean)
}
