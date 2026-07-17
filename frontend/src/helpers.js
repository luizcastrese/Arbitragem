export function outcomeLabel(outcome) {
  return {
    claimant: 'Favorável ao requerente',
    respondent: 'Favorável ao requerido',
    partial: 'Parcial',
    inconclusive: 'Inconclusivo'
  }[outcome] || 'Não informado'
}

export function decisionDisplayText(decision = {}) {
  if (decision.outcome === 'inconclusive' && decision.execution?.mode === 'safe_fallback') {
    return 'O registro do caso foi preservado, mas a IA não analisou o mérito porque o serviço automático estava indisponível.'
  }
  return decision.decision
}

export function conciliationPathLabel(path) {
  return {
    conciliation: 'Tentar conciliação com proposta objetiva',
    mediation: 'Tentar mediação para construção conjunta',
    adjudication: 'Seguir para julgamento',
    human_screening: 'Composição automática não concluída'
  }[path] || 'Não informado'
}

export function partyLabel(party, caseData) {
  if (party === 'claimant') return `${caseData.claimant} (cliente)`
  if (party === 'respondent') return `${caseData.respondent} (empresa)`
  return 'parte não identificada'
}

export function materialTypeLabel(type) {
  return type === 'argument' ? 'Alegação' : 'Prova'
}

export function responseStatusLabel(status) {
  return {
    pending: 'Resposta pendente',
    answered: 'Respondido',
    challenged: 'Contestado',
    waived: 'Resposta dispensada'
  }[status] || 'Resposta pendente'
}

export function decisionDisplayReasoning(decision = {}) {
  if (decision.execution?.mode === 'safe_fallback') {
    return ['Não houve análise do mérito; o resultado exibido é apenas um bloqueio seguro do sistema.']
  }
  return decision.reasoning
}

export function decisionDisplayLimitations(decision = {}) {
  if (decision.execution?.mode === 'safe_fallback') {
    return ['A API de IA não concluiu a chamada. Nenhuma decisão financeira foi produzida.']
  }
  return decision.limitations
}

export function organizedDisplaySummary(organized = {}) {
  if (organized.execution?.mode === 'safe_fallback') {
    return 'Os documentos foram recebidos e preservados, mas não houve organização automática pela IA.'
  }
  return organized.summary
}

export function hasUnavailableAI(caseData = {}) {
  return [caseData.conciliation, caseData.organized, caseData.decision, caseData.review]
    .some((stage) => stage?.execution?.mode === 'safe_fallback')
}

export function truncateText(text = '', limit = 280) {
  if (text.length <= limit) return text
  return `${text.slice(0, limit).trim()}...`
}

export function auditDisplayRisks(review = {}) {
  if (review.execution?.mode === 'safe_fallback') {
    return ['A decisão não foi validada como resultado final do sistema.']
  }
  return review.risks
}

export function auditDisplayIssues(review = {}) {
  if (review.execution?.mode === 'safe_fallback') {
    return ['A auditoria independente por IA não foi executada.']
  }
  return review.issues
}
