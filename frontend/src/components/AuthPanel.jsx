export function AuthPanel({ mode, setMode, busy, onSubmit, onClose }) {
  return (
    <section className="auth-panel">
      <div>
        <span className="section-label">Acesso protegido</span>
        <h2>{mode === 'register' ? 'Crie sua conta' : 'Entre na plataforma'}</h2>
        <p>Uma conta permite receber convites, acessar apenas os casos vinculados e atuar com o papel correto.</p>
      </div>
      <form onSubmit={onSubmit} className="auth-form">
        {mode === 'register' && (
          <label className="mini-field">
            <span>Seu nome</span>
            <input name="display_name" minLength="2" required placeholder="Nome completo" />
          </label>
        )}
        <label className="mini-field">
          <span>E-mail</span>
          <input name="email" type="email" required placeholder="voce@empresa.com" />
        </label>
        <label className="mini-field">
          <span>Senha</span>
          <input name="password" type="password" minLength={mode === 'register' ? 10 : 1} required placeholder="Mínimo de 10 caracteres" />
        </label>
        <div className="auth-actions">
          <button type="button" className="button ghost" onClick={onClose}>Agora não</button>
          <button className="button primary" disabled={busy}>{mode === 'register' ? 'Criar conta' : 'Entrar'}</button>
        </div>
      </form>
      <button className="auth-switch" onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>
        {mode === 'register' ? 'Já tenho uma conta' : 'Quero criar uma conta'}
      </button>
    </section>
  )
}
