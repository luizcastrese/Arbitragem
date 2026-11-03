import { useEffect, useId, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, LoaderCircle, X } from 'lucide-react'
import { GLOSSARY } from './shared.js'

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

// Pilha de diálogos abertos: só o de cima prende o foco e responde ao Esc.
const trapStack = []

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
    trapStack.push(container)
    const items = () => Array.from(container?.querySelectorAll(FOCUSABLE) || [])
      .filter((node) => node.offsetParent !== null || node === document.activeElement)
    const target = container?.querySelector('input:not([disabled])') || items()[0] || container
    target?.focus()

    function onKey(event) {
      if (trapStack[trapStack.length - 1] !== container) return
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
      const position = trapStack.lastIndexOf(container)
      if (position >= 0) trapStack.splice(position, 1)
      if (previous && typeof previous.focus === 'function') previous.focus()
    }
  }, [active])

  return containerRef
}

// Diálogo modal: fundo escurecido, foco preso, Esc e clique fora fecham, e o
// rótulo vem do título (`labelledBy`) que o conteúdo renderiza.
export function Modal({ onClose, labelledBy, children, size = 'wide' }) {
  const dialogRef = useFocusTrap(true, onClose)
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div
        className={`dialog dialog-${size}`}
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  )
}

// Botão "×" dos diálogos. Fica DEPOIS do título no código (ordem de leitura e de
// Tab: o leitor de tela anuncia o diálogo, e só então a saída) e vai para o
// canto por CSS (`.dialog-close` é absoluto), então o visual não muda.
export function CloseButton({ onClose }) {
  return (
    <button type="button" className="dialog-close" onClick={onClose} aria-label="Fechar">
      <X size={18} aria-hidden="true" />
    </button>
  )
}

// Termo do procedimento com explicação curta. Abre ao passar o mouse, ao focar
// ou ao tocar; Esc fecha. O texto vem de GLOSSARY.
export function Term({ k, children }) {
  const id = useId()
  const wrapper = useRef(null)
  const [open, setOpen] = useState(false)
  const [alignRight, setAlignRight] = useState(false)
  const text = GLOSSARY[k]
  if (!text) return children

  function show() {
    const box = wrapper.current?.getBoundingClientRect()
    setAlignRight(Boolean(box) && box.left > window.innerWidth / 2)
    setOpen(true)
  }

  return (
    <span className="term" ref={wrapper} onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="term-button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : show())}
        onFocus={show}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false) }}
      >
        {children}
      </button>
      {open && (
        <span role="tooltip" id={id} className={`term-tip${alignRight ? ' right' : ''}`}>{text}</span>
      )}
    </span>
  )
}
