import { Check, Circle } from 'lucide-react'

import { steps } from '../constants'

export function ProcessSteps({ currentStage, blockedByAI = false }) {
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
