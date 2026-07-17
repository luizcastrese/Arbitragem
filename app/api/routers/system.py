"""Rotas de status da plataforma: raiz informativa e health check."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import API_VERSION, get_db, settings

router = APIRouter(tags=["sistema"])


@router.get("/")
def root():
    return {
        "project": "Valinor",
        "version": API_VERSION,
        "status": "running",
        "docs": "/docs",
        "ui": "/ui/",
        "openai_enabled": settings.openai_enabled,
        "auth_required": settings.auth_required,
        "procedure_terms": {
            "version": "2026-07-12",
            "principles": [
                "participação voluntária e regras iguais para as partes",
                "conhecimento e oportunidade de resposta a todo material",
                "tentativas de composição dependem de aceitação das partes",
                "decisão por IA fundamentada apenas no registro admitido",
                "auditoria independente e indicação de revisão humana quando necessária",
            ],
        },
        "warnings": [
            warning
            for warning in [
                (
                    "OPENAI_API_KEY ausente: agentes usarão modo seguro inconclusivo."
                    if not settings.openai_enabled
                    else None
                ),
                (
                    "PLATFORM_SIGNING_SECRET usa valor de desenvolvimento."
                    if settings.using_development_signing_secret
                    else None
                ),
            ]
            if warning
        ],
    }


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "openai_enabled": settings.openai_enabled,
    }
