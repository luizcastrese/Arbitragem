import {
  AlertTriangle,
  ArrowRight,
  FileText,
  Gavel,
  Handshake,
  LockKeyhole,
  Search,
  ShieldCheck,
  Upload
} from 'lucide-react'

import { ConciliationActions } from './ConciliationActions'
import { ConsentPanel } from './ConsentPanel'

export function NextAction({
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
  setConciliationUpdate
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
      description: 'O agente julgador aplicará o framework Comercial Equilibrado às evidências do caso.'
    },
    decided: {
      icon: <ShieldCheck size={22} />,
      label: 'Último passo',
      title: 'Audite a decisão',
      description: 'Uma segunda IA verificará fundamentos, evidências, contradições e aderência às regras.'
    }
  }[caseData.status]

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
        />
      ) : caseData.status === 'draft' ? (
        <>
          <ConsentPanel
            caseData={caseData}
            busy={busy}
            run={run}
            request={request}
            actorHeaders={actorHeaders}
          />

          <div className="submission-context">
            <label className="mini-field">
              <span>Quem está apresentando?</span>
              <select
                value={documentParty}
                onChange={(event) => setDocumentParty(event.target.value)}
              >
                <option value="claimant">Cliente reclamante</option>
                <option value="respondent">Empresa reclamada</option>
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
              <input type="file" accept="application/pdf" onChange={uploadPdf} disabled={busy} />
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
                disabled={busy || !documentText.trim()}
                onClick={addTextDocument}
              >
                <FileText size={17} /> Adicionar texto ao caso
              </button>
            </div>
          </div>

          <div className="lock-explanation">
            <LockKeyhole size={20} />
            <div>
              <strong>Quando terminar de adicionar documentos</strong>
              <span>
                Fixe o conjunto documental. Depois disso, nenhum arquivo poderá ser
                incluído ou alterado, preservando a integridade do processo.
              </span>
            </div>
            <button
              className="button primary"
              disabled={
                busy
                || !caseData.documents.length
                || !caseData.consent?.complete
                || !caseData.contradictory?.complete
              }
              onClick={() => run(
                'Protegendo documentos e regras do processo...',
                () => request(`/cases/${caseData.id}/lock`, {
                  method: 'POST',
                  headers: actorHeaders(caseData.id, 'manager')
                })
              )}
            >
              Fixar documentos e continuar <ArrowRight size={17} />
            </button>
          </div>
          {(!caseData.consent?.complete || !caseData.contradictory?.complete) && (
            <div className="blocking-note">
              <AlertTriangle size={17} />
              <span>
                {!caseData.consent?.complete
                  ? 'A adesão das duas partes ainda está pendente. '
                  : ''}
                {!caseData.contradictory?.complete
                  ? 'Todos os materiais precisam de ciência, resposta ou renúncia e admissão antes da trava.'
                  : ''}
              </span>
            </div>
          )}
        </>
      ) : (
        <button
          className="button primary action-cta"
          disabled={busy}
          onClick={() => {
            if (caseData.status === 'locked') {
              return run(
                'Buscando interesses convergentes e possibilidades de composição...',
                () => request(`/cases/${caseData.id}/conciliation`, {
                  method: 'POST',
                  headers: actorHeaders(caseData.id, 'manager')
                })
              )
            }
            if (caseData.status === 'organized') {
              return run(
                'A IA está julgando o caso e fundamentando a decisão...',
                () => request(`/cases/${caseData.id}/decide`, {
                  method: 'POST',
                  headers: actorHeaders(caseData.id, 'manager')
                })
              )
            }
            return run(
              'A segunda IA está auditando a decisão...',
              () => request(`/cases/${caseData.id}/review`, {
                method: 'POST',
                headers: actorHeaders(caseData.id, 'manager')
              })
            )
          }}
        >
          {caseData.status === 'locked' && 'Avaliar conciliação ou mediação'}
          {caseData.status === 'organized' && 'Proferir decisão'}
          {caseData.status === 'decided' && 'Auditar decisão'}
          <ArrowRight size={18} />
        </button>
      )}
    </section>
  )
}
