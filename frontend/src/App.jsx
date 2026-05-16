import { ShieldCheck, FileText, Scale, SearchCheck } from 'lucide-react'

export default function App() {
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

          <div className="hero-actions">
            <button className="primary">Criar disputa</button>
            <button className="secondary">Ver manifesto</button>
          </div>
        </div>
      </header>

      <main className="content">
        <section className="grid">
          <Card
            icon={<FileText size={24} />}
            title="Documentos verificáveis"
            text="Todos os documentos recebem hashes SHA-256 e podem ser auditados pela contraparte."
          />

          <Card
            icon={<SearchCheck size={24} />}
            title="Retrieval contextual"
            text="A plataforma utiliza embeddings OpenAI e RAG para recuperar evidências semanticamente relevantes."
          />

          <Card
            icon={<Scale size={24} />}
            title="Framework explícito"
            text="As decisões seguem frameworks normativos transparentes e congelados antes do julgamento."
          />

          <Card
            icon={<ShieldCheck size={24} />}
            title="Manifesto criptográfico"
            text="A contraparte pode verificar que o procedimento não foi alterado ou enviesado após o lock."
          />
        </section>

        <section className="workflow">
          <h2>Fluxo do processo</h2>

          <div className="steps">
            <Step number="1" title="Abertura da disputa" />
            <Step number="2" title="Upload de documentos" />
            <Step number="3" title="Manifesto verificável" />
            <Step number="4" title="Lock procedural" />
            <Step number="5" title="Organização factual" />
            <Step number="6" title="Decisão multiagente" />
            <Step number="7" title="Revisão crítica" />
            <Step number="8" title="Relatório auditável" />
          </div>
        </section>
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

function Step({ number, title }) {
  return (
    <div className="step">
      <div className="step-number">{number}</div>
      <span>{title}</span>
    </div>
  )
}
