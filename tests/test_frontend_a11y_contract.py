"""Contrato de acessibilidade dos diálogos e do rodapé, lido do código do front.

Não há runner de testes de componentes no front; o que dá para garantir no CI é
a forma do código: todo diálogo usa o `Modal` compartilhado (Esc e clique fora),
tem o botão "×" e o põe depois do título, e o rodapé tem links reais.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"


def sources():
    return {path.name: path.read_text(encoding="utf-8") for path in SRC.glob("*.jsx")}


def test_modal_closes_with_escape_and_outside_click():
    ui = sources()["ui.jsx"]
    assert "useFocusTrap(true, onClose)" in ui
    assert "event.key === 'Escape'" in ui or "e.key === 'Escape'" in ui
    assert "onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}" in ui


def test_close_button_is_labelled_and_shared():
    ui = sources()["ui.jsx"]
    match = re.search(r"export function CloseButton.*?\n\}\n", ui, re.S)
    assert match and 'aria-label="Fechar"' in match.group(0)


def test_every_dialog_has_a_close_button_after_its_title():
    for name, code in sources().items():
        if name == "ui.jsx" or "<Modal" not in code:
            continue
        assert "<CloseButton" in code, f"{name}: diálogo sem botão ×"
        # O × nunca abre o contêiner do diálogo: o título vem antes.
        assert not re.search(r"<(section|form|header|div)[^>]*>\s*<CloseButton", code), (
            f"{name}: botão × antes do título na ordem de leitura"
        )
        # Nenhum botão "×" improvisado fora do componente compartilhado.
        assert 'className="dialog-close"' not in code, f"{name}: use <CloseButton />"


def test_every_modal_title_precedes_a_close_button():
    """Para cada diálogo, o título (id usado em labelledBy) vem antes do ×."""
    for name, code in sources().items():
        if name == "ui.jsx":
            continue
        for label in re.findall(r'labelledBy="([a-z-]+)"', code):
            title = code.find(f'id="{label}"')
            assert title != -1, f"{name}: título {label} não encontrado"
            assert "<CloseButton" in code[title:], f"{name}: sem × depois do título {label}"


def test_footer_legal_links_are_real_links():
    app = sources()["App.jsx"]
    link = re.search(r"function LegalLink.*?\n\}\n", app, re.S).group(0)
    assert "<a\n" in link or "<a " in link
    assert "href={`${import.meta.env.BASE_URL}${LEGAL_SLUGS[kind]}`}" in link
    assert "event.preventDefault()" in link
    # Ctrl/Cmd/Shift e botão do meio seguem o endereço (nova aba).
    for guard in ("event.metaKey", "event.ctrlKey", "event.shiftKey", "event.button !== 0"):
        assert guard in link
    assert '<LegalLink kind="terms"' in app and '<LegalLink kind="privacy"' in app
    assert "LEGAL_SLUGS = { terms: 'termos', privacy: 'privacidade' }" in app


def test_server_serves_the_legal_routes_for_new_tab_and_reload():
    from app.main import FRONTEND_CLIENT_ROUTES

    assert {"termos", "privacidade"} <= set(FRONTEND_CLIENT_ROUTES)
