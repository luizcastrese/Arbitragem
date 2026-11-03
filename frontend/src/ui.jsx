import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, LoaderCircle } from 'lucide-react'

// Ícone de loading: gira por CSS (.spin). Com prefers-reduced-motion o giro
// para, e o texto ao lado continua dizendo que algo está em andamento.
export function Spinner({ size = 20, className = '' }) {
  return <LoaderCircle size={size} className={`spin ${className}`.trim()} aria-hidden="true" />
}

export function Message({ type, text }) {
  return (
    <div className={`message ${type}`}>
      {type === 'error' ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
      <span>{text}</span>
    </div>
  )
}

// Leitores de tela só anunciam mudanças em regiões que já estavam na página.
// Por isso o contêiner fica sempre montado e só o conteúdo entra e sai.
export function LiveMessage({ type, text }) {
  return (
    <div
      className="live-region"
      role={type === 'error' ? 'alert' : 'status'}
      aria-live={type === 'error' ? 'assertive' : 'polite'}
      aria-atomic="true"
    >
      {text ? <Message type={type} text={text} /> : null}
    </div>
  )
}

export function LoadingState() {
  return (
    <section className="surface loading-state" role="status" aria-live="polite">
      <Spinner size={22} />
      <span>Carregando seus casos...</span>
    </section>
  )
}

export function formatElapsed(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

function useElapsed(startedAt) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [startedAt])
  return (now - startedAt) / 1000
}

// Card fixo enquanto uma etapa de IA roda em segundo plano. O título é a única
// parte anunciada (aria-live); o relógio fica de fora para não falar a cada segundo.
export function ProcessingCard({ title, detail, startedAt }) {
  const elapsed = useElapsed(startedAt)
  return (
    <aside className="processing-card" aria-label="Etapa em andamento">
      <Spinner size={26} className="processing-spinner" />
      <div className="processing-text">
        <strong role="status" aria-live="polite" aria-atomic="true">{title}</strong>
        <span>{detail}</span>
      </div>
      <div className="processing-time">
        <span>Tempo decorrido</span>
        <time>{formatElapsed(elapsed)}</time>
      </div>
    </aside>
  )
}

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])', 'select:not([disabled])',
  'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])'
].join(',')

// Prende o foco dentro de um diálogo modal: Tab e Shift+Tab circulam, Esc
// fecha, o foco inicial vai para o primeiro campo e volta ao elemento que
// abriu o diálogo quando ele fecha.
export function useFocusTrap(active, onEscape) {
  const containerRef = useRef(null)
  const escapeRef = useRef(onEscape)
  escapeRef.current = onEscape

  useEffect(() => {
    if (!active) return undefined
    const container = containerRef.current
    const previous = document.activeElement
    const items = () => Array.from(container?.querySelectorAll(FOCUSABLE) || [])
      .filter((node) => node.offsetParent !== null || node === document.activeElement)
    const target = container?.querySelector('input:not([disabled])') || items()[0] || container
    target?.focus()

    function onKey(event) {
      if (event.key === 'Escape') {
        escapeRef.current?.()
        return
      }
      if (event.key !== 'Tab' || !container) return
      const nodes = items()
      if (!nodes.length) {
        event.preventDefault()
        return
      }
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (event.shiftKey && (document.activeElement === first || !container.contains(document.activeElement))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (document.activeElement === last || !container.contains(document.activeElement))) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (previous && typeof previous.focus === 'function') previous.focus()
    }
  }, [active])

  return containerRef
}
