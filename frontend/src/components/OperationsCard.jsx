import { useState } from 'react'
import { Clock3, Download, Mail } from 'lucide-react'

import { API_BASE } from '../constants'

export function OperationsCard({ caseData, busy, run, request, actorHeaders, user, sessionToken }) {
  const [inviteLink, setInviteLink] = useState('')
  const deadlines = caseData.deadlines || []
  const participants = caseData.participants || []

  async function invite(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await run('Criando convite protegido...', async () => {
      const data = await request(`/cases/${caseData.id}/invitations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...actorHeaders(caseData.id, 'manager') },
        body: JSON.stringify({ email: form.get('email'), role: form.get('role') })
      })
      setInviteLink(`${window.location.origin}/ui/?invite=${data.acceptance_token}`)
      event.currentTarget?.reset?.()
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
        headers: sessionToken ? { 'X-Session-Token': sessionToken } : {}
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
          <span className="section-label">Acesso, agenda e entrega</span>
          <h3>Administração do procedimento</h3>
        </div>
        <button className="button secondary" onClick={downloadReport} disabled={busy}>
          <Download size={16} /> Baixar relatório Word
        </button>
      </div>

      <div className="operations-grid">
        <div className="operation-block">
          <div className="operation-title"><Mail size={18} /><strong>Participantes</strong></div>
          <p>Convide cada pessoa pelo e-mail que será usado na conta. O papel limita as ações disponíveis.</p>
          {participants.map((participant) => (
            <span className="participant-row" key={`${participant.email}-${participant.role}`}>
              <strong>{participant.display_name}</strong> {participant.role} · {participant.email}
            </span>
          ))}
          <form className="compact-form" onSubmit={invite}>
            <input name="email" type="email" required placeholder="E-mail da parte" />
            <select name="role" defaultValue="claimant">
              <option value="claimant">Cliente reclamante</option>
              <option value="respondent">Empresa reclamada</option>
              <option value="manager">Gestor</option>
            </select>
            <button className="button primary" disabled={busy}>Gerar convite</button>
          </form>
          {inviteLink && (
            <label className="invite-link">
              <span>Link protegido para envio</span>
              <input value={inviteLink} readOnly onFocus={(event) => event.target.select()} />
            </label>
          )}
          {!user && <small>O modo local continua disponível; para convites nominativos, crie uma conta de gestor.</small>}
        </div>

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
          <form className="compact-form deadline-form" onSubmit={addDeadline}>
            <input name="label" required minLength="3" placeholder="Ex.: resposta aos documentos" />
            <select name="assigned_to" defaultValue="all">
              <option value="all">Todas as pessoas</option>
              <option value="claimant">Cliente</option>
              <option value="respondent">Empresa</option>
              <option value="manager">Gestor</option>
            </select>
            <input name="due_at" type="datetime-local" required />
            <button className="button secondary" disabled={busy}>Adicionar prazo</button>
          </form>
        </div>
      </div>
    </section>
  )
}
