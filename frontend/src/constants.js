export const API_BASE = import.meta.env.VITE_API_BASE
  || (window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin)

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

export const statusLabels = {
  draft: 'Recebendo documentos',
  locked: 'Documentos protegidos',
  conciliation: 'Composição avaliada',
  organized: 'Fatos organizados',
  decided: 'Decisão proferida',
  reviewed: 'Decisão auditada'
}
