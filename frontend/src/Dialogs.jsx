import { ArrowRight, LogIn, Mail, UserPlus } from 'lucide-react'
import { CONTACT_EMAIL } from './shared.js'
import { CloseButton, LiveMessage, Modal, Spinner } from './ui.jsx'

// Formulário curto do piloto: grava o lead no backend, que avisa o time por e-mail.
export function LeadDialog({ onClose, onSubmit, pending, error, sent, onOpenPrivacy }) {
  return (
    <Modal onClose={onClose} labelledBy="lead-title" size="narrow">
      <section className="dialog-card">
        {sent ? (
          <div className="dialog-body" role="status">
            <span className="section-label">Recebemos seu contato</span>
            <h2 id="lead-title">Obrigado. Retornamos por e-mail.</h2>
            <CloseButton onClose={onClose} />
            <p>
              Se preferir, escreva direto para{' '}
              <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
            </p>
            <div className="dialog-actions">
              <button type="button" className="button primary" onClick={onClose}>Fechar</button>
            </div>
          </div>
        ) : (
          <form className="dialog-body" onSubmit={onSubmit}>
            <span className="section-label">Piloto para bancos e escritórios</span>
            <h2 id="lead-title">Quer testar com seus processos?</h2>
            <CloseButton onClose={onClose} />
            <p>Conte quem é você e quantos processos de revisional chegam por mês. Retornamos por e-mail.</p>
            <label className="mini-field">
              <span>Seu nome</span>
              <input name="name" required minLength="2" maxLength="120" autoComplete="name" />
            </label>
            <label className="mini-field">
              <span>Empresa ou escritório</span>
              <input name="company" required minLength="2" maxLength="160" autoComplete="organization" />
            </label>
            <label className="mini-field">
              <span>E-mail</span>
              <input name="email" type="email" required autoComplete="email" placeholder="voce@empresa.com" />
            </label>
            <label className="mini-field">
              <span>Processos por mês</span>
              <input name="monthly_volume" type="number" min="0" max="10000000" required inputMode="numeric" placeholder="Ex.: 300" />
            </label>
            {/* Campo-isca contra robôs: invisível e fora da ordem de tabulação. */}
            <input className="hp-field" name="website" tabIndex="-1" autoComplete="off" aria-hidden="true" />
            <LiveMessage type="error" text={error} />
            <p className="dialog-fine">
              Usamos estes dados só para responder ao seu contato.{' '}
              <button type="button" className="auth-switch" onClick={onOpenPrivacy}>Política de privacidade</button>
            </p>
            <div className="dialog-actions">
              <a className="dialog-alt" href={`mailto:${CONTACT_EMAIL}`}>
                <Mail size={15} /> Prefiro escrever: {CONTACT_EMAIL}
              </a>
              <button className="button primary" disabled={pending}>
                {pending ? <Spinner size={16} /> : <ArrowRight size={16} />} Enviar
              </button>
            </div>
          </form>
        )}
      </section>
    </Modal>
  )
}

// "Recebi um convite": explica o caminho antes de pedir o acesso.
export function InviteDialog({ onClose, onLogin, onRegister, hasToken }) {
  return (
    <Modal onClose={onClose} labelledBy="invite-title" size="narrow">
      <section className="dialog-card">
        <div className="dialog-body">
          <span className="section-label">Recebi um convite</span>
          <h2 id="invite-title">Entre com o e-mail que recebeu o convite</h2>
          <CloseButton onClose={onClose} />
          <p>
            O convite é pessoal: vale só para o endereço de e-mail que o recebeu. Entre, ou crie
            sua conta, com <strong>esse mesmo e-mail</strong>.
          </p>
          <ol className="dialog-steps">
            <li>Entre ou crie a conta com o e-mail do convite.</li>
            <li>
              {hasToken
                ? 'Aceite o convite no aviso que aparece no topo da página.'
                : 'Abra de novo o link que veio no e-mail; ele vincula o caso à sua conta.'}
            </li>
            <li>Leia os termos e responda no seu papel (reclamante ou reclamada).</li>
          </ol>
          <div className="dialog-actions">
            <button type="button" className="button ghost" onClick={onRegister}>
              <UserPlus size={16} /> Criar conta
            </button>
            <button type="button" className="button primary" onClick={onLogin}>
              <LogIn size={16} /> Entrar
            </button>
          </div>
        </div>
      </section>
    </Modal>
  )
}
