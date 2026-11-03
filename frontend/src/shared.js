// Constantes e utilitários compartilhados entre a casca (App) e o workspace.

export const API_BASE = import.meta.env.VITE_API_BASE
  || (window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin)

export function formatApiDetail(detail, fallback = 'Erro inesperado') {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.detail || (typeof item === 'string' ? item : JSON.stringify(item)))
      .filter(Boolean)
      .join('; ') || fallback
  }
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (typeof detail.detail === 'string') return detail.detail
    return JSON.stringify(detail)
  }
  return fallback
}

export function invitationDeliveryMessage(data) {
  const delivery = data?.email_delivery || {}
  if (delivery.delivered) return `Convite enviado para ${data.email}.`
  if (delivery.error) {
    return `O e-mail não saiu (${delivery.error}). Use Reenviar quando o SMTP estiver ok.`
  }
  if (data?.acceptance_token) {
    return 'SMTP não configurado: copie o link abaixo para o convidado.'
  }
  return `Convite registrado para ${data.email}. Em produção o link só chega por e-mail.`
}

export const steps = [
  {
    key: 'draft',
    title: 'Documentos',
    short: 'Reúna o material',
    description: 'Adicione contratos, mensagens, comprovantes e alegações.'
  },
  {
    key: 'locked',
    title: 'Regras fixadas',
    short: 'Proteja o processo',
    description: 'O sistema registra os documentos e impede alterações posteriores.'
  },
  {
    key: 'conciliation',
    title: 'Composição',
    short: 'Negocie em rodadas',
    description: 'A IA conduz novas tentativas enquanto houver espaço útil para acordo.'
  },
  {
    key: 'organized',
    title: 'Fatos organizados',
    short: 'Separe fatos e alegações',
    description: 'O conteúdo é estruturado para facilitar a análise.'
  },
  {
    key: 'decided',
    title: 'Decisão da IA',
    short: 'Julgue o conflito',
    description: 'A IA aplica as regras fixadas e profere uma decisão fundamentada.'
  },
  {
    key: 'reviewed',
    title: 'Auditoria',
    short: 'Valide a decisão',
    description: 'Uma segunda IA procura falhas, contradições e desvios das regras.'
  }
]

export function userHasRole(caseData, user, role) {
  if (!user) return false
  return (caseData.participants || []).some(
    (participant) => participant.email === user.email && participant.role === role
  )
}

export const statusLabels = {
  withdrawn: 'Encerrado: opção pela via judicial',
  draft: 'Recebendo documentos',
  locked: 'Documentos protegidos',
  locking: 'Travando o manifesto',
  conciliation: 'Composição avaliada',
  organized: 'Fatos organizados',
  processing_organize: 'Organizando o registro',
  processing_decision: 'Decisão em processamento',
  decided: 'Decisão proferida',
  processing_review: 'Auditoria automática',
  reviewed: 'Auditoria automática concluída',
  agreement: 'Encerrado por acordo bilateral',
  processing_attestation: 'Emitindo attestation',
  attested: 'Attestation emitida',
  processing_appeal: 'Recurso automático',
  contested: 'Recurso automático apresentado',
  inconclusive: 'Decisão inconclusiva',
  inadmissible: 'Caso inadmissível',
  invalidated: 'Decisão invalidada',
  system_failure: 'Falha do sistema'
}

// Matérias que o painel oferece na abertura do caso. O núcleo é genérico:
// um setor novo entra como outro framework de matéria no backend.
export const MATTERS = [
  { id: 'consumer_banking_v1', label: 'Disputa bancária (consumidor × banco)', consumer: true },
  { id: 'digital_services_b2b_v1', label: 'Serviços digitais entre empresas', consumer: false }
]

// Cada status do caso aponta para a etapa da barra de andamento (índice em
// `steps`). Os status intermediários (locking, processing_*) e os de
// encerramento (agreement, attested, contested) não são chaves de `steps`, e
// sem este mapa a barra caía de volta em "1 de 6".
const STATUS_STAGE = {
  draft: 0,
  locking: 1,
  locked: 1,
  conciliation: 2,
  agreement: 2,
  processing_organize: 3,
  organized: 3,
  processing_decision: 4,
  decided: 4,
  processing_review: 5,
  reviewed: 5,
  processing_attestation: 5,
  attested: 5,
  processing_appeal: 5,
  contested: 5
}

export function stageIndexFor(caseData) {
  const mapped = STATUS_STAGE[caseData?.status]
  if (mapped !== undefined) return mapped
  // withdrawn, inconclusive, inadmissible, invalidated, system_failure: o caso
  // parou onde estava, então a etapa vem do que já foi produzido.
  if (caseData?.review) return 5
  if (caseData?.decision) return 4
  if (caseData?.organized) return 3
  if (caseData?.conciliation) return 2
  if (caseData?.manifest_locked) return 1
  return 0
}

// Status que encerram o caso antes da última etapa: a barra mostra onde parou,
// mas não deve prometer "% concluído".
export const EARLY_CLOSE = new Set(['agreement', 'withdrawn'])

// Etapa assíncrona (resposta 202) → status `processing_*` que ela ocupa.
export const STAGE_PROCESSING_STATUS = {
  organize: 'processing_organize',
  decide: 'processing_decision',
  review: 'processing_review',
  attestation: 'processing_attestation',
  appeal: 'processing_appeal'
}
