import { statusLabels, steps } from '../constants'
import { hasUnavailableAI } from '../helpers'
import { AnalysisDetails } from './AnalysisDetails'
import { CaseBrief } from './CaseBrief'
import { Conclusion } from './Conclusion'
import { DocumentsCard } from './DocumentsCard'
import { Message } from './common'
import { NextAction } from './NextAction'
import { OperationsCard } from './OperationsCard'
import { ProcessSteps } from './ProcessSteps'
import { TechnicalDetails } from './TechnicalDetails'

export function CaseWorkspace({
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
  conciliationUpdate,
  setClaimantResponse,
  setRespondentResponse,
  setConciliationUpdate,
  showTechnical,
  setShowTechnical,
  user,
  sessionToken
}) {
  const unavailable = hasUnavailableAI(caseData)
  const displayedStage = unavailable ? 2 : currentStage

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

      {caseData.status !== 'reviewed' && (
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
        />
      )}

      <OperationsCard
        caseData={caseData}
        busy={busy}
        run={run}
        request={request}
        actorHeaders={actorHeaders}
        user={user}
        sessionToken={sessionToken}
      />

      {caseData.status === 'reviewed' && (
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
