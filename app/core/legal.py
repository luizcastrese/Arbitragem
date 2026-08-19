"""Documentos legais: termos de uso e política de privacidade.

A versão dos termos é definida aqui, no servidor, e não pelo cliente. Antes ela
chegava no corpo da requisição de aceite com um valor padrão — o que significa
que a cadeia de auditoria registrava a versão que o cliente dissesse ter
aceitado, e não a que ele de fato viu. Num procedimento cujo valor está no
registro, isso é a diferença entre um aceite provável e um aceite comprovado.
"""

from functools import lru_cache
from pathlib import Path
from typing import Dict

# Bater com a data no cabeçalho dos arquivos em `docs/legal/`.
TERMS_VERSION = "2026-08-19"

DOCUMENTS = {
    "terms": ("termos-de-uso.md", "Termos de Uso"),
    "privacy": ("politica-de-privacidade.md", "Política de Privacidade"),
}

_LEGAL_DIR = Path(__file__).resolve().parents[2] / "docs" / "legal"

# Marca deixada nas minutas enquanto elas não passam por advogado. Enquanto
# estiver presente, a API diz isso de forma explícita, em vez de deixar a
# interface apresentar como vinculante um texto que ainda não é.
_DRAFT_MARKER = "pendente de revisão jurídica"


@lru_cache
def load_document(kind: str) -> Dict[str, object]:
    if kind not in DOCUMENTS:
        raise KeyError(kind)
    filename, title = DOCUMENTS[kind]
    content = (_LEGAL_DIR / filename).read_text(encoding="utf-8")
    return {
        "kind": kind,
        "title": title,
        "version": TERMS_VERSION,
        "content": content,
        "draft": _DRAFT_MARKER in content,
    }


def documents_summary() -> Dict[str, object]:
    """Versão vigente e situação de cada documento, sem o texto integral."""
    return {
        "version": TERMS_VERSION,
        "documents": [
            {
                "kind": kind,
                "title": item["title"],
                "draft": item["draft"],
                "url": f"/legal/{kind}",
            }
            for kind in DOCUMENTS
            for item in [load_document(kind)]
        ],
    }
