import { ChevronDown } from 'lucide-react'

export function TechnicalDetails({ caseData, open, setOpen }) {
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
