import { useState } from 'react'
import { ShieldCheck, FileText, Scale, SearchCheck, Lock, Gavel } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export default function App() {
  const [caseData, setCaseData] = useState(null)
  const [documentText, setDocumentText] = useState('')
  const [documentName, setDocumentName] = useState('contrato.txt')
  const [manifest, setManifest] = useState(null)
  const [organized, setOrganized] = useState(null)
  const [decision, setDecision] = useState(null)
  const [review, setReview] = useState(null)
  const [report, setReport] = useState(null)
  const [status, setStatus] = useState('')

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, options)
    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || 'Erro na requisição')
    }

    return data
  }

  async function createCase(event) {
    event.preventDefault()
    setStatus('Criando disputa...')

    const form = new FormData(event.currentTarget)
    const payload = {
      title: form.get('title'),
      claimant: form.get('claimant'),
      respondent: form.get('respondent')
    }

    const data = await request('/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    setCaseData(data)
    setStatus('Disputa criada.')
  }

  async function addTextDocument() {
    if (!caseData) return
    setStatus('Adicionando documento...')

    await request(`/cases/${caseData.id}/documents/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: documentName, content: documentText })
    })

    setStatus('Documento adicionado e processado.')
  }

  async function uploadPdf(event) {
    if (!caseData) return
    const file = event.target.files[0]
    if (!file) return

    setStatus('Enviando PDF...')
    const form = new FormData()
    form.append('file', file)

    await request(`/cases/${caseData.id}/documents/pdf`, {
      method: 'POST',
      body: form
    })

    setStatus('PDF processado.')
  }

  async function lockProcess() {
    setStatus('Gerando manifesto...')
    const data = await request(`/cases/${caseData.id}/lock`, { method: 'POST' })
    setManifest(data.manifest)
    setStatus('Manifesto travado.')
  }

  async function organize() {
    setStatus('Organizando fatos...')
    const data = await request(`/cases/${caseData.id}/organize`, { method: 'POST' })
    setOrganized(data)
    setStatus('Fatos organizados.')
  }

  async function decide() {
    setStatus('Gerando decisão...')
    const data = await request(`/cases/${caseData.id}/decide`, { method: 'POST' })
    setDecision(data)
    setStatus('Decisão gerada.')
  }

  async function runReview() {
    setStatus('Revisando decisão...')
    const data = await request(`/cases/${caseData.id}/review`, { method: 'POST' })
    setReview(data)
    setStatus('Revisão concluída.')
  }

  async function loadReport() {
    setStatus('Carregando relatório...')
    const data = await request(`/cases/${caseData.id}/report`)
    setReport(data)
    setStatus('Relatório carregado.')
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-content">
          <span className="badge">Arbitragem Computacional</span>
          <h1>Infraestrutura de arbitragem assistida por IA</h1>
          <p>
            Plataforma experimental de resolução de disputas documentais baseada em
            IA multiagente, retrieval/RAG e verificabilidade criptográfica.
          </p>
        </div>
      </header>

      <main className="content">
        <section className="grid">
          <Card icon={<FileText size={24} />} title="Documentos verificáveis" text="Documentos recebem hashes SHA-256 e podem ser auditados pela contraparte." />
          <Card icon={<SearchCheck size={24} />} title="Retrieval contextual" text="Embeddings e RAG recuperam evidências semanticamente relevantes." />
          <Card icon={<Scale size={24} />} title="Framework explícito" text="O procedimento usa um framework normativo travado antes da decisão." />
          <Card icon={<ShieldCheck size={24} />} title="Manifesto criptográfico" text="A contraparte verifica que as regras não foram alteradas após o lock." />
        </section>

        <section className="panel">
          <h2>Criar disputa</h2>
          <form onSubmit={createCase} className="form">
            <input name="title" placeholder="Título da disputa" required />
            <input name="claimant" placeholder="Parte A / requerente" required />
            <input name="respondent" placeholder="Parte B / contraparte" required />
            <button className="primary">Criar disputa</button>
          </form>
        </section>

        {caseData && (
          <section className="panel">
            <h2>Disputa #{caseData.id}</h2>
            <p className="muted">{caseData.title} — {caseData.claimant} vs. {caseData.respondent}</p>

            <div className="form two-columns">
              <div>
                <h3>Adicionar texto</h3>
                <input value={documentName} onChange={(e) => setDocumentName(e.target.value)} />
                <textarea value={documentText} onChange={(e) => setDocumentText(e.target.value)} placeholder="Cole contrato, mensagens ou alegações..." />
                <button className="secondary" onClick={addTextDocument}>Adicionar documento</button>
              </div>

              <div>
                <h3>Adicionar PDF</h3>
                <input type="file" accept="application/pdf" onChange={uploadPdf} />
                <p className="muted">O PDF será extraído, hasheado, dividido em chunks e indexado por embeddings.</p>
              </div>
            </div>

            <div className="actions-row">
              <button onClick={lockProcess}><Lock size={16} /> Travar manifesto</button>
              <button onClick={organize}>Organizar fatos</button>
              <button onClick={decide}><Gavel size={16} /> Decidir</button>
              <button onClick={runReview}>Revisar</button>
              <button onClick={loadReport}>Relatório</button>
            </div>

            {status && <p className="status">{status}</p>}
          </section>
        )}

        <Result title="Manifesto" data={manifest} />
        <Result title="Organização factual" data={organized} />
        <Result title="Decisão" data={decision} />
        <Result title="Revisão" data={review} />
        <Result title="Relatório final" data={report} />
      </main>
    </div>
  )
}

function Card({ icon, title, text }) {
  return (
    <div className="card">
      <div className="card-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  )
}

function Result({ title, data }) {
  if (!data) return null

  return (
    <section className="panel result">
      <h2>{title}</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </section>
  )
}
