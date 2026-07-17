import { ArrowRight } from 'lucide-react'

export function CreateCase({ busy, onSubmit, onCancel }) {
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
