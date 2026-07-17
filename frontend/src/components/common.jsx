import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'

export function Fact({ label, value, note }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  )
}

export function Message({ type, text }) {
  return (
    <div className={`message ${type}`}>
      {type === 'error' ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
      <span>{text}</span>
    </div>
  )
}

export function LoadingState() {
  return (
    <section className="surface loading-state">
      <RefreshCw size={22} />
      <span>Carregando seus casos...</span>
    </section>
  )
}
